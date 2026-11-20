import sqlite3

from layout.revisions import load_revision
from .format import V1Payload, encode_v1


def issue(db: sqlite3.Connection, revision_id: str) -> bytes:
    revision = load_revision(db, revision_id)
    payload = V1Payload(
        revision.batch_id, revision.revision_id, revision.receipt.receipt_id,
        revision.receipt.source, revision.specimens, revision.order, revision.profile,
    )
    return encode_v1(payload)
