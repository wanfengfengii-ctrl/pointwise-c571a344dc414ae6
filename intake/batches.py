from dataclasses import dataclass
import sqlite3

from .receipts import IntakeReceipt, init_intake_receipts, load_intake_receipt, write_intake_receipt
from .specimens import Specimen, build_specimens, require_text


@dataclass(frozen=True)
class Batch:
    batch_id: str
    specimens: tuple[Specimen, ...]
    receipt: IntakeReceipt

    @property
    def original_order(self) -> tuple[str, ...]:
        return tuple(specimen.specimen_id for specimen in self.specimens)


def init_intake(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS intake_batches (batch_id TEXT PRIMARY KEY NOT NULL)')
        db.execute('''
            CREATE TABLE IF NOT EXISTS intake_specimens (
                batch_id TEXT NOT NULL REFERENCES intake_batches(batch_id),
                position INTEGER NOT NULL,
                specimen_id TEXT NOT NULL,
                group_name TEXT NOT NULL,
                thickness_um TEXT NOT NULL,
                PRIMARY KEY (batch_id, position),
                UNIQUE (batch_id, specimen_id)
            )
        ''')
        init_intake_receipts(db)


def admit(db: sqlite3.Connection, batch_id: str, source: str, rows: object) -> Batch:
    require_text(batch_id, 'batch_id')
    require_text(source, 'source')
    specimens = build_specimens(rows)
    db.execute('BEGIN IMMEDIATE')
    with db:
        exists = db.execute(
            'SELECT 1 FROM intake_batches WHERE batch_id = ?', (batch_id,),
        ).fetchone()
        if exists is not None:
            raise ValueError(f'batch already admitted: {batch_id!r}')
        db.execute('INSERT INTO intake_batches (batch_id) VALUES (?)', (batch_id,))
        db.executemany('''
            INSERT INTO intake_specimens (batch_id, position, specimen_id, group_name, thickness_um)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            (batch_id, position, specimen.specimen_id, specimen.group, str(specimen.thickness_um))
            for position, specimen in enumerate(specimens)
        ))
        receipt = write_intake_receipt(db, batch_id, source)
    return Batch(batch_id, specimens, receipt)


def load_batch(db: sqlite3.Connection, batch_id: str) -> Batch:
    require_text(batch_id, 'batch_id')
    receipt = load_intake_receipt(db, batch_id)
    rows = db.execute('''
        SELECT specimen_id, group_name, thickness_um
        FROM intake_specimens WHERE batch_id = ? ORDER BY position
    ''', (batch_id,))
    specimens = tuple(Specimen(identity, group, int(thickness)) for identity, group, thickness in rows)
    return Batch(batch_id, specimens, receipt)
