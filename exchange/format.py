from dataclasses import asdict, dataclass
import json

from fixture.loading import plan_loads
from fixture.profiles import FixtureProfile, make_profile
from intake.specimens import Specimen, build_specimens, require_text
from layout.moves import SegmentMove, move_segment
from layout.permutations import require_permutation
from layout.revisions import require_revision_identity
from .bindings import build_directory, verify_directory

V1_VERSION = 1
V2_VERSION = 2


@dataclass(frozen=True)
class V1Payload:
    batch_id: str
    revision_id: str
    intake_receipt_id: int
    source: str
    specimens: tuple[Specimen, ...]
    order: tuple[str, ...]
    profile: FixtureProfile

    @property
    def original_order(self) -> tuple[str, ...]:
        return tuple(specimen.specimen_id for specimen in self.specimens)


@dataclass(frozen=True)
class Observation:
    revision_id: str
    applied: int
    order: tuple[str, ...]


@dataclass(frozen=True)
class LayoutEvidence:
    initial_order: tuple[str, ...]
    moves: tuple[SegmentMove, ...]
    observations: tuple[Observation, ...]


@dataclass(frozen=True)
class V2Payload:
    start_revision: str
    end_revision: str
    terminal: V1Payload
    evidence: LayoutEvidence

    @property
    def batch_id(self) -> str:
        return self.terminal.batch_id

    @property
    def revision_id(self) -> str:
        return self.terminal.revision_id

    @property
    def specimens(self) -> tuple[Specimen, ...]:
        return self.terminal.specimens

    @property
    def profile(self) -> FixtureProfile:
        return self.terminal.profile


def _canonical(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _checked_payload(record: object) -> V1Payload:
    fields = {'batch_id', 'revision_id', 'intake_receipt_id', 'source', 'specimens', 'order', 'profile'}
    if not isinstance(record, dict) or record.keys() != fields:
        raise ValueError('invalid V1 payload fields')
    batch_id = require_text(record['batch_id'], 'batch_id')
    revision_id = require_revision_identity(record['revision_id'])
    receipt = record['intake_receipt_id']
    if type(receipt) is not int or receipt <= 0:
        raise ValueError('invalid intake receipt identity')
    source = require_text(record['source'], 'source')
    specimens = build_specimens(record['specimens'])
    original = tuple(specimen.specimen_id for specimen in specimens)
    order = require_permutation(original, record['order'])
    profile = record['profile']
    if not isinstance(profile, dict) or profile.keys() != {'name', 'capacity_um', 'allowed_groups'}:
        raise ValueError('invalid frozen fixture profile fields')
    return V1Payload(batch_id, revision_id, receipt, source, specimens, order, make_profile(**profile))


def encode_v1(payload: V1Payload) -> bytes:
    record = asdict(payload)
    _checked_payload(record)
    directory = build_directory(payload.batch_id, payload.revision_id, _canonical(record))
    return _canonical({'version': V1_VERSION, 'directory': directory, 'payload': record})


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f'invalid JSON constant {value}')


def _parse_envelope(item: bytes, version: int) -> dict:
    if not isinstance(item, bytes):
        raise ValueError('exchange item must be bytes')
    try:
        record = json.loads(item.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid UTF-8 exchange JSON') from error
    if not isinstance(record, dict) or record.keys() != {'version', 'directory', 'payload'}:
        raise ValueError('invalid exchange envelope fields')
    if type(record['version']) is not int or record['version'] != version:
        raise ValueError('unsupported exchange version')
    return record


def decode_v1(item: bytes) -> V1Payload:
    record = _parse_envelope(item, V1_VERSION)
    payload = _checked_payload(record['payload'])
    verify_directory(record['directory'], payload.batch_id, payload.revision_id, _canonical(record['payload']))
    return payload


def _checked_move(raw: object) -> SegmentMove:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3 or any(type(cut) is not int for cut in raw):
        raise ValueError('invalid evidence move coordinates')
    move = SegmentMove(*raw)
    if move.destination in (move.start, move.stop):
        raise ValueError('evidence moves must be effective')
    return move


def _checked_evidence(
    record: object, terminal: V1Payload, start_revision: str, end_revision: str,
) -> LayoutEvidence:
    fields = {'initial_order', 'moves', 'observations'}
    if not isinstance(record, dict) or record.keys() != fields:
        raise ValueError('invalid layout evidence fields')
    initial_order = require_permutation(terminal.original_order, record['initial_order'])
    raw_moves = record['moves']
    if not isinstance(raw_moves, (list, tuple)):
        raise ValueError('evidence moves must be a list')
    moves = tuple(_checked_move(raw) for raw in raw_moves)
    orders = [initial_order]
    for move in moves:
        orders.append(require_permutation(terminal.original_order, move_segment(orders[-1], move)))
    if orders[-1] != terminal.order:
        raise ValueError('evidence contradicts the terminal order')
    raw_observations = record['observations']
    if not isinstance(raw_observations, (list, tuple)) or not raw_observations:
        raise ValueError('evidence observations must be a nonempty list')
    observations = []
    seen = set()
    previous = -1
    for raw in raw_observations:
        if not isinstance(raw, dict) or raw.keys() != {'revision_id', 'applied', 'order'}:
            raise ValueError('invalid observation fields')
        revision_id = require_revision_identity(raw['revision_id'])
        applied = raw['applied']
        if type(applied) is not int or not 0 <= applied <= len(moves):
            raise ValueError('invalid observation section')
        if applied < previous:
            raise ValueError('observations must follow section order')
        previous = applied
        if revision_id in seen:
            raise ValueError('duplicate observation revision')
        seen.add(revision_id)
        order = require_permutation(terminal.original_order, raw['order'])
        if order != orders[applied]:
            raise ValueError('observation contradicts the section replay')
        observations.append(Observation(revision_id, applied, order))
    if observations[0].revision_id != start_revision or observations[0].applied != 0:
        raise ValueError('evidence does not open on the start revision')
    if observations[-1].revision_id != end_revision or observations[-1].applied != len(moves):
        raise ValueError('evidence does not close on the end revision')
    return LayoutEvidence(initial_order, moves, tuple(observations))


def _checked_v2_payload(record: object) -> V2Payload:
    fields = {'start_revision', 'end_revision', 'terminal', 'evidence'}
    if not isinstance(record, dict) or record.keys() != fields:
        raise ValueError('invalid V2 payload fields')
    start_revision = require_revision_identity(record['start_revision'])
    end_revision = require_revision_identity(record['end_revision'])
    terminal = _checked_payload(record['terminal'])
    if terminal.revision_id != end_revision:
        raise ValueError('terminal payload does not match the end revision')
    evidence = _checked_evidence(record['evidence'], terminal, start_revision, end_revision)
    by_id = {specimen.specimen_id: specimen for specimen in terminal.specimens}
    plan_loads((by_id[identity] for identity in terminal.order), terminal.profile)
    return V2Payload(start_revision, end_revision, terminal, evidence)


def _v2_record(payload: V2Payload) -> dict:
    return {
        'start_revision': payload.start_revision,
        'end_revision': payload.end_revision,
        'terminal': asdict(payload.terminal),
        'evidence': {
            'initial_order': list(payload.evidence.initial_order),
            'moves': [[move.start, move.stop, move.destination] for move in payload.evidence.moves],
            'observations': [
                {'revision_id': observation.revision_id, 'applied': observation.applied,
                 'order': list(observation.order)}
                for observation in payload.evidence.observations
            ],
        },
    }


def encode_v2(payload: V2Payload) -> bytes:
    record = _v2_record(payload)
    checked = _checked_v2_payload(record)
    directory = build_directory(checked.batch_id, checked.revision_id, _canonical(record))
    return _canonical({'version': V2_VERSION, 'directory': directory, 'payload': record})


def decode_v2(item: bytes) -> V2Payload:
    record = _parse_envelope(item, V2_VERSION)
    payload = _checked_v2_payload(record['payload'])
    verify_directory(record['directory'], payload.batch_id, payload.revision_id, _canonical(record['payload']))
    return payload


def decode_item(item: bytes) -> V1Payload | V2Payload:
    if not isinstance(item, bytes):
        raise ValueError('exchange item must be bytes')
    try:
        record = json.loads(item.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid UTF-8 exchange JSON') from error
    if not isinstance(record, dict) or type(record.get('version')) is not int:
        raise ValueError('invalid exchange envelope fields')
    if record['version'] == V1_VERSION:
        return decode_v1(item)
    if record['version'] == V2_VERSION:
        return decode_v2(item)
    raise ValueError('unsupported exchange version')
