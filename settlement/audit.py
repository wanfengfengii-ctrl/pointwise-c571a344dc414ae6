from collections.abc import Mapping
from dataclasses import dataclass
import sqlite3

from exchange.format import V1Payload, V2Payload, decode_v1, decode_v2
from exchange.receipts import DeliveryReceipt, ReceivedItem, load_received_item
from fixture.loading import LoadPlan, plan_loads
from fixture.profiles import FixtureProfile
from intake.specimens import Specimen, require_text
from layout.clips import cut_index, cut_pairs, removed_pairs, replay_orders


@dataclass(frozen=True)
class LayoutReview:
    start_revision: str
    end_revision: str
    notes: tuple[dict, ...]
    adjudications: tuple[dict, ...]


@dataclass(frozen=True)
class AuditResult:
    delivery: DeliveryReceipt
    intake_receipt_id: int
    source: str
    specimens: tuple[Specimen, ...]
    order: tuple[str, ...]
    profile: FixtureProfile
    plan: LoadPlan
    layout_review: LayoutReview | None = None

    @property
    def original_order(self) -> tuple[str, ...]:
        return tuple(specimen.specimen_id for specimen in self.specimens)


def _audit_payload(
    receipt: DeliveryReceipt, payload: V1Payload, layout_review: LayoutReview | None = None,
) -> AuditResult:
    by_id = {specimen.specimen_id: specimen for specimen in payload.specimens}
    plan = plan_loads((by_id[identity] for identity in payload.order), payload.profile)
    return AuditResult(
        receipt, payload.intake_receipt_id, payload.source, payload.specimens,
        payload.order, payload.profile, plan, layout_review,
    )


def audit_payload_v1(received: ReceivedItem, payload: V1Payload) -> AuditResult:
    receipt = received.receipt
    if (payload.batch_id, payload.revision_id) != (receipt.batch_id, receipt.revision_id):
        raise ValueError('delivery receipt disagrees with received payload')
    return _audit_payload(receipt, payload)


def audit_payload_v2(received: ReceivedItem, payload: V2Payload, notes: object) -> AuditResult:
    terminal = payload.terminal
    receipt = received.receipt
    if (terminal.batch_id, terminal.revision_id) != (receipt.batch_id, receipt.revision_id):
        raise ValueError('delivery receipt disagrees with received payload')
    results = review_notes(received.item, notes)
    review = LayoutReview(
        payload.start_revision,
        payload.end_revision,
        tuple(result['note'] for result in results),
        tuple({'status': result['status'], 'final_cut': result['final_cut']} for result in results),
    )
    return _audit_payload(receipt, terminal, review)


def audit_received_item(db: sqlite3.Connection, receipt_id: int) -> AuditResult:
    received = load_received_item(db, receipt_id)
    return audit_payload_v1(received, decode_v1(received.item))


NOTE_FIELDS = {'batch_id', 'revision_id', 'left', 'right', 'text'}


def _require_note_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError('note text must be a string')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError('note text must be valid Unicode text') from error
    return value


def _check_note(note: object) -> dict:
    if not isinstance(note, Mapping) or set(note.keys()) != NOTE_FIELDS:
        raise ValueError('invalid layout note fields')
    batch_id = require_text(note['batch_id'], 'batch_id')
    revision_id = require_text(note['revision_id'], 'revision_id')
    left, right = note['left'], note['right']
    if left is not None:
        left = require_text(left, 'left')
    if right is not None:
        right = require_text(right, 'right')
    return {
        'batch_id': batch_id,
        'revision_id': revision_id,
        'left': left,
        'right': right,
        'text': _require_note_text(note['text']),
    }


def review_notes(package: bytes, notes: object) -> list[dict]:
    payload = decode_v2(package)
    if not isinstance(notes, (list, tuple)):
        raise ValueError('layout notes must be a list')
    evidence = payload.evidence
    orders = replay_orders(evidence.initial_order, evidence.moves)
    demolished = [
        removed_pairs(orders[index], move) for index, move in enumerate(evidence.moves)
    ]
    observations = {observation.revision_id: observation for observation in evidence.observations}
    results = []
    for note in notes:
        checked = _check_note(note)
        if checked['batch_id'] != payload.terminal.batch_id:
            raise ValueError('note batch does not match the package')
        observation = observations.get(checked['revision_id'])
        if observation is None:
            raise ValueError('note revision is not observed by the package')
        pair = (checked['left'], checked['right'])
        if pair not in cut_pairs(orders[observation.applied]):
            raise ValueError('clip did not exist at the noted revision')
        status, final_cut = 'placed', None
        for index in range(observation.applied, len(evidence.moves)):
            if pair in demolished[index]:
                status = 'review'
                break
        if status == 'placed':
            final_cut = cut_index(payload.terminal.order, pair)
        results.append({'note': checked, 'status': status, 'final_cut': final_cut})
    return results
