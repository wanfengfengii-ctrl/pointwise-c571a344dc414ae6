from dataclasses import asdict, dataclass
import json
import sqlite3

from exchange.receipts import DeliveryReceipt
from fixture.loading import LoadPlan
from fixture.profiles import make_profile
from intake.specimens import build_specimens
from .audit import AuditResult, LayoutReview


@dataclass(frozen=True)
class Daybook:
    book_id: int
    result: AuditResult


@dataclass(frozen=True)
class SignReceipt:
    book_id: int
    receipt_id: int
    item_sha256: str


def init_settlement(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    with db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS settlement_books (
                book_id INTEGER PRIMARY KEY,
                result TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS settlement_sign_receipts (
                book_id INTEGER PRIMARY KEY REFERENCES settlement_books(book_id),
                receipt_id INTEGER NOT NULL REFERENCES exchange_receipts(receipt_id),
                item_sha256 TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS settlement_claims (
                claim_id INTEGER PRIMARY KEY,
                book_id INTEGER NOT NULL REFERENCES settlement_sign_receipts(book_id)
            )
        ''')


def _snapshot(result: AuditResult) -> dict:
    record = asdict(result)
    if record['layout_review'] is None:
        del record['layout_review']
    return record


def insert_daybook(db: sqlite3.Connection, result: AuditResult) -> Daybook:
    cursor = db.execute('INSERT INTO settlement_books (result) VALUES (?)', (json.dumps(_snapshot(result)),))
    return Daybook(cursor.lastrowid, result)


def insert_sign_receipt(db: sqlite3.Connection, book: Daybook) -> SignReceipt:
    delivery = book.result.delivery
    db.execute('''
        INSERT INTO settlement_sign_receipts (book_id, receipt_id, item_sha256) VALUES (?, ?, ?)
    ''', (book.book_id, delivery.receipt_id, delivery.item_sha256))
    return SignReceipt(book.book_id, delivery.receipt_id, delivery.item_sha256)


def load_signed_daybook(db: sqlite3.Connection, book_id: int) -> tuple[Daybook, SignReceipt]:
    if type(book_id) is not int:
        raise ValueError('book_id must be an integer')
    if not 1 <= book_id <= 2**63 - 1:
        raise KeyError(f'unknown signed daybook {book_id}')
    row = db.execute('''
        SELECT b.result, s.receipt_id, s.item_sha256
        FROM settlement_books AS b JOIN settlement_sign_receipts AS s USING (book_id)
        WHERE b.book_id = ?
    ''', (book_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown signed daybook {book_id}')
    encoded, receipt_id, digest = row
    snapshot = json.loads(encoded)
    review = snapshot.get('layout_review')
    if review is not None:
        review = LayoutReview(
            review['start_revision'], review['end_revision'],
            tuple(review['notes']), tuple(review['adjudications']),
        )
    result = AuditResult(
        DeliveryReceipt(**snapshot['delivery']), snapshot['intake_receipt_id'], snapshot['source'],
        build_specimens(snapshot['specimens']), tuple(snapshot['order']),
        make_profile(**snapshot['profile']), LoadPlan.from_record(snapshot['plan']), review,
    )
    return Daybook(book_id, result), SignReceipt(book_id, receipt_id, digest)


def record_claim(db: sqlite3.Connection, book_id: int) -> int:
    cursor = db.execute('INSERT INTO settlement_claims (book_id) VALUES (?)', (book_id,))
    return cursor.lastrowid
