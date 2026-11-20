from dataclasses import dataclass
import sqlite3

from intake.specimens import require_text
from .moves import SegmentMove


@dataclass(frozen=True)
class DraftEdit:
    draft_id: str
    sequence: int
    move: SegmentMove


def init_edit_log(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS layout_draft_edits (
            draft_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            start_cut INTEGER NOT NULL,
            stop_cut INTEGER NOT NULL,
            destination INTEGER NOT NULL,
            PRIMARY KEY (draft_id, sequence)
        )
    ''')


def append_draft_edit(db: sqlite3.Connection, draft_id: str, move: SegmentMove) -> DraftEdit:
    sequence = db.execute('''
        SELECT COALESCE(MAX(sequence), 0) + 1 FROM layout_draft_edits WHERE draft_id = ?
    ''', (draft_id,)).fetchone()[0]
    db.execute('''
        INSERT INTO layout_draft_edits (draft_id, sequence, start_cut, stop_cut, destination)
        VALUES (?, ?, ?, ?, ?)
    ''', (draft_id, sequence, move.start, move.stop, move.destination))
    return DraftEdit(draft_id, sequence, move)


def list_draft_edits(db: sqlite3.Connection, draft_id: str) -> tuple[DraftEdit, ...]:
    require_text(draft_id, 'draft_id')
    rows = db.execute('''
        SELECT sequence, start_cut, stop_cut, destination FROM layout_draft_edits
        WHERE draft_id = ? ORDER BY sequence
    ''', (draft_id,))
    return tuple(DraftEdit(draft_id, sequence, SegmentMove(start, stop, cut))
                 for sequence, start, stop, cut in rows)
