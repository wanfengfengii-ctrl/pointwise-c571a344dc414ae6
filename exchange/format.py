from dataclasses import asdict, dataclass
import json

from fixture.profiles import FixtureProfile, make_profile
from intake.specimens import Specimen, build_specimens, require_text
from layout.permutations import require_permutation
from .bindings import build_directory, verify_directory

V1_VERSION = 1


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


def _canonical(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _checked_payload(record: object) -> V1Payload:
    fields = {'batch_id', 'revision_id', 'intake_receipt_id', 'source', 'specimens', 'order', 'profile'}
    if not isinstance(record, dict) or record.keys() != fields:
        raise ValueError('invalid V1 payload fields')
    batch_id = require_text(record['batch_id'], 'batch_id')
    revision_id = require_text(record['revision_id'], 'revision_id')
    prefix, separator, number = revision_id.partition(':')
    if (prefix != 'revision' or not separator or not number.isascii()
            or not number.isdecimal() or number.startswith('0')):
        raise ValueError('invalid frozen revision identity')
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


def decode_v1(item: bytes) -> V1Payload:
    if not isinstance(item, bytes):
        raise ValueError('V1 item must be bytes')
    try:
        record = json.loads(item.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid UTF-8 V1 JSON') from error
    if not isinstance(record, dict) or record.keys() != {'version', 'directory', 'payload'}:
        raise ValueError('invalid V1 envelope fields')
    if type(record['version']) is not int or record['version'] != V1_VERSION:
        raise ValueError('unsupported exchange version')
    payload = _checked_payload(record['payload'])
    verify_directory(record['directory'], payload.batch_id, payload.revision_id, _canonical(record['payload']))
    return payload
