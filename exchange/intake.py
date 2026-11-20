import sqlite3

from fixture.eligibility import require_eligible
from .format import decode_item
from .receipts import find_received_item, store_received_item


def accept(db: sqlite3.Connection, item: bytes) -> int:
    payload = decode_item(item)
    for specimen in payload.specimens:
        require_eligible(specimen, payload.profile)
    db.execute('BEGIN IMMEDIATE')
    with db:
        received = find_received_item(db, item)
        if received is None:
            received = store_received_item(db, item, payload.batch_id, payload.revision_id)
        return received.receipt.receipt_id
