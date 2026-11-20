from dataclasses import asdict, dataclass
import json
import sqlite3

from fixture.loading import LoadPlan
from fixture.profiles import FixtureProfile, make_profile
from intake.batches import Batch
from intake.receipts import IntakeReceipt
from intake.specimens import Specimen, build_specimens, require_text


@dataclass(frozen=True)
class FrozenRevision:
    revision_id: str
    draft_id: str
    batch_id: str
    receipt: IntakeReceipt
    specimens: tuple[Specimen, ...]
    order: tuple[str, ...]
    profile: FixtureProfile
    plan: LoadPlan

    @property
    def original_order(self) -> tuple[str, ...]:
        return tuple(specimen.specimen_id for specimen in self.specimens)


def init_revisions(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS layout_revisions (
            revision_number INTEGER PRIMARY KEY,
            draft_id TEXT NOT NULL,
            batch_id TEXT NOT NULL REFERENCES intake_batches(batch_id),
            snapshot TEXT NOT NULL
        )
    ''')


def store_revision(
    db: sqlite3.Connection, draft_id: str, batch: Batch, order: tuple[str, ...],
    profile: FixtureProfile, plan: LoadPlan,
) -> FrozenRevision:
    snapshot = {
        'receipt': asdict(batch.receipt),
        'specimens': [asdict(specimen) for specimen in batch.specimens],
        'order': order,
        'profile': asdict(profile),
        'plan': asdict(plan),
    }
    cursor = db.execute('''
        INSERT INTO layout_revisions (draft_id, batch_id, snapshot) VALUES (?, ?, ?)
    ''', (draft_id, batch.batch_id, json.dumps(snapshot)))
    return FrozenRevision(
        f'revision:{cursor.lastrowid}', draft_id, batch.batch_id,
        batch.receipt, batch.specimens, order, profile, plan,
    )


def load_revision(db: sqlite3.Connection, revision_id: str) -> FrozenRevision:
    require_text(revision_id, 'revision_id')
    row = db.execute('''
        SELECT draft_id, batch_id, snapshot FROM layout_revisions WHERE 'revision:' || revision_number = ?
    ''', (revision_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown frozen revision {revision_id!r}')
    draft_id, batch_id, encoded = row
    snapshot = json.loads(encoded)
    return FrozenRevision(
        revision_id, draft_id, batch_id, IntakeReceipt(**snapshot['receipt']),
        build_specimens(snapshot['specimens']), tuple(snapshot['order']),
        make_profile(**snapshot['profile']), LoadPlan.from_record(snapshot['plan']),
    )
