from dataclasses import dataclass
import sqlite3

from .entries import Daybook, SignReceipt, load_signed_daybook, record_claim
from .export import render_daybook


@dataclass(frozen=True)
class Readback:
    book: Daybook
    receipt: SignReceipt
    detail: dict


def read(db: sqlite3.Connection, book_id: int) -> Readback:
    db.execute('BEGIN IMMEDIATE')
    with db:
        book, receipt = load_signed_daybook(db, book_id)
        detail = render_daybook(book, receipt)
        record_claim(db, book_id)
    return Readback(book, receipt, detail)
