from collections.abc import Callable
import sqlite3

from exchange.format import V2Payload, decode_item
from exchange.receipts import load_received_item
from .audit import audit_payload_v1, audit_payload_v2
from .entries import Daybook, SignReceipt, insert_daybook, insert_sign_receipt


def sign(
    db: sqlite3.Connection, receipt_id: int, *, notes: object = None,
    before_commit: Callable[[], None] | None = None,
) -> tuple[Daybook, SignReceipt]:
    db.execute('BEGIN IMMEDIATE')
    with db:
        received = load_received_item(db, receipt_id)
        payload = decode_item(received.item)
        if isinstance(payload, V2Payload):
            if notes is None:
                raise ValueError('V2 items require an explicit notes list')
            result = audit_payload_v2(received, payload, notes)
        else:
            if notes is not None:
                raise ValueError('V1 items do not accept layout notes')
            result = audit_payload_v1(received, payload)
        book = insert_daybook(db, result)
        receipt = insert_sign_receipt(db, book)
        if before_commit is not None:
            before_commit()
    return book, receipt
