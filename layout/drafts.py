from dataclasses import dataclass, replace
import json
import sqlite3

from intake.batches import load_batch
from intake.specimens import require_text
from .edit_log import append_draft_edit, init_edit_log
from .moves import SegmentMove, move_segment
from .permutations import require_permutation
from .revisions import init_revisions
from .sections import init_sections


@dataclass(frozen=True)
class Draft:
    draft_id: str
    batch_id: str
    original_order: tuple[str, ...]
    order: tuple[str, ...]


def init_layout(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    with db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS layout_drafts (
                draft_number INTEGER PRIMARY KEY,
                batch_id TEXT NOT NULL UNIQUE REFERENCES intake_batches(batch_id),
                original_order TEXT NOT NULL,
                current_order TEXT NOT NULL
            )
        ''')
        init_edit_log(db)
        init_revisions(db)
        init_sections(db)


def _decode_draft(row: tuple) -> Draft:
    number, batch_id, original, current = row
    original_order = tuple(json.loads(original))
    return Draft(f'draft:{number}', batch_id, original_order, require_permutation(original_order, json.loads(current)))


def load_draft(db: sqlite3.Connection, draft_id: str) -> Draft:
    require_text(draft_id, 'draft_id')
    row = db.execute('''
        SELECT draft_number, batch_id, original_order, current_order FROM layout_drafts
        WHERE 'draft:' || draft_number = ?
    ''', (draft_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown draft {draft_id!r}')
    return _decode_draft(row)


def arrange(db: sqlite3.Connection, batch_id: str, move: SegmentMove | None = None) -> Draft:
    require_text(batch_id, 'batch_id')
    db.execute('BEGIN IMMEDIATE')
    with db:
        original = load_batch(db, batch_id).original_order
        row = db.execute('''
            SELECT draft_number, batch_id, original_order, current_order FROM layout_drafts WHERE batch_id = ?
        ''', (batch_id,)).fetchone()
        if row is None:
            if move is not None:
                raise KeyError(f'no open draft for batch {batch_id!r}')
            recorded = json.dumps(original)
            cursor = db.execute('''
                INSERT INTO layout_drafts (batch_id, original_order, current_order) VALUES (?, ?, ?)
            ''', (batch_id, recorded, recorded))
            return Draft(f'draft:{cursor.lastrowid}', batch_id, original, original)
        draft = _decode_draft(row)
        if draft.original_order != original:
            raise ValueError('draft original order does not match the admitted batch')
        if move is None:
            return draft
        order = require_permutation(original, move_segment(draft.order, move))
        if order == draft.order:
            return draft
        db.execute('UPDATE layout_drafts SET current_order = ? WHERE batch_id = ?', (json.dumps(order), batch_id))
        append_draft_edit(db, draft.draft_id, move)
        return replace(draft, order=order)
