from dataclasses import dataclass
import sqlite3

from .bindings import item_identity


@dataclass(frozen=True)
class DeliveryReceipt:
    receipt_id: int
    batch_id: str
    revision_id: str
    item_sha256: str


@dataclass(frozen=True)
class ReceivedItem:
    receipt: DeliveryReceipt
    item: bytes


def init_exchange(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    with db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS exchange_items (
                receipt_id INTEGER PRIMARY KEY,
                item_sha256 TEXT NOT NULL,
                item BLOB NOT NULL
            )
        ''')
        db.execute('CREATE INDEX IF NOT EXISTS exchange_item_digest ON exchange_items (item_sha256)')
        db.execute('''
            CREATE TABLE IF NOT EXISTS exchange_receipts (
                receipt_id INTEGER PRIMARY KEY REFERENCES exchange_items(receipt_id),
                batch_id TEXT NOT NULL,
                revision_id TEXT NOT NULL
            )
        ''')


def _received(row: tuple) -> ReceivedItem:
    receipt_id, batch_id, revision_id, item_sha256, item = row
    return ReceivedItem(DeliveryReceipt(receipt_id, batch_id, revision_id, item_sha256), item)


def find_received_item(db: sqlite3.Connection, item: bytes) -> ReceivedItem | None:
    row = db.execute('''
        SELECT i.receipt_id, r.batch_id, r.revision_id, i.item_sha256, i.item
        FROM exchange_items AS i JOIN exchange_receipts AS r USING (receipt_id)
        WHERE i.item_sha256 = ? AND i.item = ? ORDER BY i.receipt_id LIMIT 1
    ''', (item_identity(item), item)).fetchone()
    return None if row is None else _received(row)


def store_received_item(db: sqlite3.Connection, item: bytes, batch_id: str, revision_id: str) -> ReceivedItem:
    digest = item_identity(item)
    cursor = db.execute('INSERT INTO exchange_items (item_sha256, item) VALUES (?, ?)', (digest, item))
    receipt_id = cursor.lastrowid
    db.execute('''
        INSERT INTO exchange_receipts (receipt_id, batch_id, revision_id) VALUES (?, ?, ?)
    ''', (receipt_id, batch_id, revision_id))
    return ReceivedItem(DeliveryReceipt(receipt_id, batch_id, revision_id, digest), item)


def load_received_item(db: sqlite3.Connection, receipt_id: int) -> ReceivedItem:
    if type(receipt_id) is not int:
        raise ValueError('receipt_id must be an integer')
    if not 1 <= receipt_id <= 2**63 - 1:
        raise KeyError(f'unknown delivery receipt {receipt_id}')
    row = db.execute('''
        SELECT i.receipt_id, r.batch_id, r.revision_id, i.item_sha256, i.item
        FROM exchange_items AS i JOIN exchange_receipts AS r USING (receipt_id)
        WHERE i.receipt_id = ?
    ''', (receipt_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown delivery receipt {receipt_id}')
    return _received(row)
