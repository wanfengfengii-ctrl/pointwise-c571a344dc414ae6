import sqlite3

from intake.specimens import require_text
from layout.edit_log import list_draft_edits
from layout.revisions import load_revision, revision_number
from layout.sections import list_sections, load_section
from .format import LayoutEvidence, Observation, V1Payload, V2Payload, encode_v1, encode_v2


def issue(db: sqlite3.Connection, revision_id: str) -> bytes:
    revision = load_revision(db, revision_id)
    payload = V1Payload(
        revision.batch_id, revision.revision_id, revision.receipt.receipt_id,
        revision.receipt.source, revision.specimens, revision.order, revision.profile,
    )
    return encode_v1(payload)


def issue_layout(db: sqlite3.Connection, batch_id: str, start_revision: str, end_revision: str) -> bytes:
    require_text(batch_id, 'batch_id')
    start = load_revision(db, start_revision)
    end = load_revision(db, end_revision)
    if start.batch_id != batch_id or end.batch_id != batch_id:
        raise ValueError('revision batch does not match the requested batch')
    if start.draft_id != end.draft_id:
        raise ValueError('endpoint revisions belong to different drafts')
    start_section = load_section(db, start.revision_id)
    end_section = load_section(db, end.revision_id)
    if start_section is None or end_section is None:
        raise ValueError('endpoint revision lacks a bound edit section')
    first = revision_number(start.revision_id)
    last = revision_number(end.revision_id)
    if first > last:
        raise ValueError('start revision must not follow the end revision')
    edits = list_draft_edits(db, start.draft_id)
    moves = tuple(
        edit.move for edit in edits
        if start_section.applied_edits < edit.sequence <= end_section.applied_edits
    )
    observations = tuple(
        Observation(
            section.revision_id, section.applied_edits - start_section.applied_edits,
            load_revision(db, section.revision_id).order,
        )
        for section in list_sections(db, start.draft_id, first, last)
    )
    terminal = V1Payload(
        end.batch_id, end.revision_id, end.receipt.receipt_id, end.receipt.source,
        end.specimens, end.order, end.profile,
    )
    payload = V2Payload(
        start.revision_id, end.revision_id, terminal,
        LayoutEvidence(start.order, moves, observations),
    )
    return encode_v2(payload)
