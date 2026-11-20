from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class IntakeReceipt:
    receipt_id: int
    batch_id: str
    source: str


def init_intake_receipts(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS intake_receipts (
            receipt_id INTEGER PRIMARY KEY,
            batch_id TEXT NOT NULL UNIQUE REFERENCES intake_batches(batch_id),
            source TEXT NOT NULL
        )
    ''')


def write_intake_receipt(db: sqlite3.Connection, batch_id: str, source: str) -> IntakeReceipt:
    cursor = db.execute(
        'INSERT INTO intake_receipts (batch_id, source) VALUES (?, ?)',
        (batch_id, source),
    )
    return IntakeReceipt(cursor.lastrowid, batch_id, source)


def load_intake_receipt(db: sqlite3.Connection, batch_id: str) -> IntakeReceipt:
    row = db.execute(
        'SELECT receipt_id, batch_id, source FROM intake_receipts WHERE batch_id = ?',
        (batch_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f'no intake receipt for batch {batch_id!r}')
    return IntakeReceipt(*row)
