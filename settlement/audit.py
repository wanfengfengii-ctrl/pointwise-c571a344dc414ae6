from dataclasses import dataclass
import sqlite3

from exchange.format import decode_v1
from exchange.receipts import DeliveryReceipt, load_received_item
from fixture.loading import LoadPlan, plan_loads
from fixture.profiles import FixtureProfile
from intake.specimens import Specimen


@dataclass(frozen=True)
class AuditResult:
    delivery: DeliveryReceipt
    intake_receipt_id: int
    source: str
    specimens: tuple[Specimen, ...]
    order: tuple[str, ...]
    profile: FixtureProfile
    plan: LoadPlan

    @property
    def original_order(self) -> tuple[str, ...]:
        return tuple(specimen.specimen_id for specimen in self.specimens)


def audit_received_item(db: sqlite3.Connection, receipt_id: int) -> AuditResult:
    received = load_received_item(db, receipt_id)
    payload = decode_v1(received.item)
    receipt = received.receipt
    if (payload.batch_id, payload.revision_id) != (receipt.batch_id, receipt.revision_id):
        raise ValueError('delivery receipt disagrees with received payload')
    by_id = {specimen.specimen_id: specimen for specimen in payload.specimens}
    plan = plan_loads((by_id[identity] for identity in payload.order), payload.profile)
    return AuditResult(
        receipt, payload.intake_receipt_id, payload.source, payload.specimens,
        payload.order, payload.profile, plan,
    )
