import sqlite3

from fixture.loading import plan_loads
from fixture.profiles import load_profile
from intake.batches import load_batch
from .drafts import load_draft
from .permutations import require_permutation
from .revisions import FrozenRevision, store_revision


def freeze(db: sqlite3.Connection, draft_id: str, profile_name: str) -> FrozenRevision:
    db.execute('BEGIN IMMEDIATE')
    with db:
        draft = load_draft(db, draft_id)
        batch = load_batch(db, draft.batch_id)
        order = require_permutation(batch.original_order, draft.order)
        profile = load_profile(db, profile_name)
        by_id = {specimen.specimen_id: specimen for specimen in batch.specimens}
        plan = plan_loads((by_id[identity] for identity in order), profile)
        return store_revision(db, draft_id, batch, order, profile, plan)
