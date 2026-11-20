from collections.abc import Callable
import sqlite3

from .audit import audit_received_item
from .entries import Daybook, SignReceipt, insert_daybook, insert_sign_receipt


def sign(
    db: sqlite3.Connection, receipt_id: int, *, before_commit: Callable[[], None] | None = None,
) -> tuple[Daybook, SignReceipt]:
    db.execute('BEGIN IMMEDIATE')
    with db:
        result = audit_received_item(db, receipt_id)
        book = insert_daybook(db, result)
        receipt = insert_sign_receipt(db, book)
        if before_commit is not None:
            before_commit()
    return book, receipt
