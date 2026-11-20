from dataclasses import dataclass
import sqlite3

from intake.specimens import require_text
from .revisions import revision_number


@dataclass(frozen=True)
class BoundSection:
    revision_id: str
    draft_id: str
    applied_edits: int


def init_sections(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS layout_revision_sections (
            revision_number INTEGER PRIMARY KEY,
            draft_id TEXT NOT NULL,
            applied_edits INTEGER NOT NULL
        )
    ''')


def bind_section(db: sqlite3.Connection, revision_id: str, draft_id: str) -> BoundSection:
    number = revision_number(revision_id)
    require_text(draft_id, 'draft_id')
    applied = db.execute('''
        SELECT COALESCE(MAX(sequence), 0) FROM layout_draft_edits WHERE draft_id = ?
    ''', (draft_id,)).fetchone()[0]
    db.execute('''
        INSERT INTO layout_revision_sections (revision_number, draft_id, applied_edits)
        VALUES (?, ?, ?)
    ''', (number, draft_id, applied))
    return BoundSection(revision_id, draft_id, applied)


def load_section(db: sqlite3.Connection, revision_id: str) -> BoundSection | None:
    number = revision_number(revision_id)
    row = db.execute('''
        SELECT draft_id, applied_edits FROM layout_revision_sections WHERE revision_number = ?
    ''', (number,)).fetchone()
    if row is None:
        return None
    return BoundSection(revision_id, row[0], row[1])


def list_sections(
    db: sqlite3.Connection, draft_id: str, first_number: int, last_number: int,
) -> tuple[BoundSection, ...]:
    require_text(draft_id, 'draft_id')
    rows = db.execute('''
        SELECT revision_number, applied_edits FROM layout_revision_sections
        WHERE draft_id = ? AND revision_number >= ? AND revision_number <= ?
        ORDER BY revision_number
    ''', (draft_id, first_number, last_number))
    return tuple(
        BoundSection(f'revision:{number}', draft_id, applied) for number, applied in rows
    )
