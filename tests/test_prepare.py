import sqlite3

from fixture.profiles import load_profile, register_profile
from intake.batches import admit, load_batch
from layout.drafts import arrange, load_draft
from layout.edit_log import list_draft_edits
from layout.freeze import freeze
from layout.moves import SegmentMove
from layout.revisions import load_revision
from tests.support import ArchiveCase, initialize_source, rows


class PrepareTests(ArchiveCase):
    def test_full_fixture(self):
        revision = self.frozen_batch(rows(('A', '甲', 4), ('B', '甲', 6), ('C', '甲', 3)))
        self.assertEqual(revision.original_order, ('A', 'B', 'C'))
        self.assertEqual(revision.receipt.source, 'sample-slip/LOT')
        self.assertEqual([(load.members, load.total_um) for load in revision.plan.loads],
                         [(('A', 'B'), 10), (('C',), 3)])
        self.assertEqual(revision.plan.load_count, 2)
        self.assertEqual(revision.plan.changeover_count, 0)
        self.assertEqual(load_revision(self.source, revision.revision_id), revision)

    def test_duplicate_specimen(self):
        with self.assertRaisesRegex(ValueError, 'duplicate specimen'):
            admit(self.source, 'LOT', 'slip', rows(('A', '甲', 4), ('A', '甲', 6)))
        self.assertEqual(self.intake_counts(), (0, 0, 0))
        with self.assertRaises(KeyError):
            arrange(self.source, 'LOT')

    def test_invalid_thickness(self):
        for invalid in (0, None, True, 1.5, '4', -1):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    admit(self.source, 'LOT', 'slip', [
                        {'specimen_id': 'A', 'group': '甲', 'thickness_um': 4},
                        {'specimen_id': 'B', 'group': '甲', 'thickness_um': invalid},
                    ])
                self.assertEqual(self.intake_counts(), (0, 0, 0))
                with self.assertRaises(KeyError):
                    arrange(self.source, 'LOT')

    def test_reorder_keeps_frozen_revision(self):
        old = self.frozen_batch(rows(('A', '甲', 4), ('B', '乙', 2), ('C', '甲', 6)))
        draft = arrange(self.source, 'LOT', SegmentMove(2, 3, 1))
        new = freeze(self.source, draft.draft_id, 'J')
        self.assertEqual(draft.original_order, ('A', 'B', 'C'))
        self.assertEqual(old.order, ('A', 'B', 'C'))
        self.assertEqual(new.order, ('A', 'C', 'B'))
        self.assertEqual((old.plan.changeover_count, new.plan.changeover_count), (2, 1))
        self.assertEqual([load.members for load in new.plan.loads], [('A', 'C'), ('B',)])
        self.assertEqual(load_revision(self.source, old.revision_id), old)
        self.assertEqual(load_revision(self.source, new.revision_id), new)

    def test_forward_destination(self):
        admit(self.source, 'LOT', 'slip', rows(*((name, '甲', 1) for name in 'ABCDE')))
        initial = arrange(self.source, 'LOT')
        move = SegmentMove(1, 3, 4)
        draft = arrange(self.source, 'LOT', move)
        self.assertEqual(draft.order, tuple('ADBCE'))
        self.assertEqual(draft.original_order, tuple('ABCDE'))
        self.assertEqual(load_draft(self.source, initial.draft_id), draft)
        edits = list_draft_edits(self.source, initial.draft_id)
        self.assertEqual([(edit.sequence, edit.move) for edit in edits], [(1, move)])

    def test_invalid_destination(self):
        admit(self.source, 'LOT', 'slip', rows(*((name, '甲', 1) for name in 'ABCDE')))
        arrange(self.source, 'LOT')
        draft = arrange(self.source, 'LOT', SegmentMove(1, 3, 4))
        edits = list_draft_edits(self.source, draft.draft_id)
        for move in (SegmentMove(1, 3, 2), SegmentMove(1, 3, 6), SegmentMove(1, 3, -1),
                     SegmentMove(2, 2, 0), SegmentMove(1, 6, 0), SegmentMove(True, 3, 0)):
            with self.subTest(move=move), self.assertRaises(ValueError):
                arrange(self.source, 'LOT', move)
        for destination in (1, 3):
            self.assertEqual(arrange(self.source, 'LOT', SegmentMove(1, 3, destination)), draft)
        self.assertEqual(load_draft(self.source, draft.draft_id), draft)
        self.assertEqual(list_draft_edits(self.source, draft.draft_id), edits)

    def test_draft_and_edit_share_transaction(self):
        admit(self.source, 'LOT', 'slip', rows(('A', '甲', 1), ('B', '甲', 1)))
        initial = arrange(self.source, 'LOT')
        self.source.execute('''
            CREATE TRIGGER reject_edit BEFORE INSERT ON layout_draft_edits
            BEGIN SELECT RAISE(ABORT, 'edit write failed'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'edit write failed'):
            arrange(self.source, 'LOT', SegmentMove(1, 2, 0))
        self.assertEqual(load_draft(self.source, initial.draft_id), initial)
        self.assertEqual(list_draft_edits(self.source, initial.draft_id), ())

    def test_reinitialize(self):
        old = self.frozen_batch(rows(('A', '甲', 4), ('B', '乙', 2), ('C', '甲', 6)))
        move = SegmentMove(2, 3, 1)
        draft = arrange(self.source, 'LOT', move)
        current_profile = register_profile(self.source, 'J', 12, ('甲', '乙'))
        new = freeze(self.source, draft.draft_id, 'J')
        self.source.close()
        self.source = self.connect(self.source_path, initialize_source)
        initialize_source(self.source)
        self.assertEqual(load_batch(self.source, 'LOT').receipt, old.receipt)
        self.assertEqual(load_draft(self.source, draft.draft_id), draft)
        self.assertEqual([edit.move for edit in list_draft_edits(self.source, draft.draft_id)], [move])
        self.assertEqual(load_revision(self.source, old.revision_id), old)
        self.assertEqual(load_revision(self.source, new.revision_id), new)
        self.assertEqual(load_profile(self.source, 'J'), current_profile)

    def test_oversize_rejects_freeze(self):
        admit(self.source, 'LOT', 'slip', rows(('A', '甲', 11)))
        draft = arrange(self.source, 'LOT')
        register_profile(self.source, 'J', 10, ('甲',))
        with self.assertRaisesRegex(ValueError, 'capacity'):
            freeze(self.source, draft.draft_id, 'J')
        self.assertEqual(self.source.execute('SELECT count(*) FROM layout_revisions').fetchone()[0], 0)
        self.assertEqual(arrange(self.source, 'LOT', SegmentMove(0, 1, 1)), draft)
        register_profile(self.source, 'J', 11, ('甲',))
        fixed = freeze(self.source, draft.draft_id, 'J')
        self.assertEqual(fixed.plan.loads[0].total_um, 11)

    def test_profile_rejections(self):
        admit(self.source, 'LOT', 'slip', rows(('A', '甲', 4)))
        draft = arrange(self.source, 'LOT')
        with self.assertRaises(ValueError):
            register_profile(self.source, 'bad', True, ('甲',))
        with self.assertRaises(KeyError):
            freeze(self.source, draft.draft_id, 'bad')
        with self.assertRaises(KeyError):
            freeze(self.source, draft.draft_id, 'missing')
        register_profile(self.source, 'J', 10, ('乙',))
        with self.assertRaisesRegex(ValueError, 'not allowed'):
            freeze(self.source, draft.draft_id, 'J')
        self.assertEqual(self.source.execute('SELECT count(*) FROM layout_revisions').fetchone()[0], 0)
        self.assertEqual(load_draft(self.source, draft.draft_id), draft)
        correct = register_profile(self.source, 'J', 10, ('甲',))
        with self.assertRaises(ValueError):
            register_profile(self.source, 'J', 0, ('乙',))
        self.assertEqual(load_profile(self.source, 'J'), correct)
        self.assertEqual(freeze(self.source, draft.draft_id, 'J').plan.loads[0].members, ('A',))
