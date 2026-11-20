import hashlib
import json
import sqlite3
from contextlib import closing

from clip_cases import BATCH, build_history
from exchange.intake import accept
from exchange.issue import issue, issue_layout
from exchange.receipts import load_received_item
from fixture.profiles import register_profile
from intake.batches import admit
from layout.drafts import arrange
from layout.freeze import freeze
from layout.moves import SegmentMove
from settlement.audit import review_notes
from settlement.publish import sign
from settlement.readback import read
from tests.support import ArchiveCase, fail_before_commit, initialize_night, initialize_source, rows


def rebind(document):
    payload = json.dumps(document['payload'], sort_keys=True, separators=(',', ':')).encode('utf-8')
    document['directory'] = {
        'batch_id': document['payload']['terminal']['batch_id'],
        'revision_id': document['payload']['terminal']['revision_id'],
        'payload_sha256': hashlib.sha256(payload).hexdigest(),
    }
    return json.dumps(document).encode('utf-8')


class LayoutNoteTests(ArchiveCase):
    def _package(self, history):
        revisions = build_history(self.source, history)
        ids = tuple(revision.revision_id for revision in revisions)
        return ids, issue_layout(self.source, BATCH, ids[0], ids[-1])

    def test_together_flow(self):
        (r0, r1), package = self._package('together')
        self.source.close()
        receipt_id = accept(self.night, package)
        self.assertEqual(accept(self.night, package), receipt_id)
        received = load_received_item(self.night, receipt_id)
        self.assertEqual(received.item, package)
        self.assertEqual(received.receipt.batch_id, BATCH)
        self.assertEqual(received.receipt.revision_id, r1)
        notes = [
            dict(batch_id=BATCH, revision_id=r0, left='B', right='C', text='段内夹位'),
            dict(batch_id=BATCH, revision_id=r0, left='A', right='B', text='拆开的夹位'),
            dict(batch_id=BATCH, revision_id=r0, left='B', right='C', text='段内夹位'),
        ]
        with self.assertRaisesRegex(sqlite3.OperationalError, 'injected before commit'):
            sign(self.night, receipt_id, notes=notes, before_commit=fail_before_commit)
        self.assertEqual(self.settlement_counts(), (0, 0))
        book, signed = sign(self.night, receipt_id, notes=notes)
        self.assertEqual(self.settlement_counts(), (1, 1))
        self.reopen_night()
        claimed = read(self.night, book.book_id)
        self.assertEqual((claimed.book, claimed.receipt), (book, signed))
        review = claimed.detail['layout_review']
        self.assertEqual((review['start_revision'], review['end_revision']), (r0, r1))
        self.assertEqual([entry['note'] for entry in review['results']], notes)
        self.assertEqual(
            [(entry['status'], entry['final_cut']) for entry in review['results']],
            [('placed', 1), ('review', None), ('placed', 1)],
        )
        self.assertEqual(claimed.detail['loads'], [
            {'group': 'G', 'members': ['B', 'C', 'A'], 'total_um': 3},
            {'group': 'G', 'members': ['D'], 'total_um': 1},
        ])
        self.assertEqual(read(self.night, book.book_id), claimed)
        self.assertEqual(
            self.night.execute('SELECT book_id FROM settlement_claims ORDER BY claim_id').fetchall(),
            [(book.book_id,), (book.book_id,)],
        )

    def test_three_observations_example(self):
        (r0, r1, r2), package = self._package('three_observations')
        old = dict(batch_id=BATCH, revision_id=r0, left='B', right='C', text='旧夹位')
        new = dict(batch_id=BATCH, revision_id=r2, left='B', right='C', text='终版夹位')
        expected = [
            dict(note=old, status='review', final_cut=None),
            dict(note=new, status='placed', final_cut=2),
            dict(note=old, status='review', final_cut=None),
        ]
        self.assertEqual(review_notes(package, [old, new, old]), expected)
        first = dict(batch_id=BATCH, revision_id=r0, left=None, right='A', text='首缝')
        last = dict(batch_id=BATCH, revision_id=r0, left='D', right=None, text='尾缝')
        self.assertEqual(
            [(entry['status'], entry['final_cut']) for entry in review_notes(package, [first, last])],
            [('placed', 0), ('review', None)],
        )
        with self.assertRaises(ValueError):
            review_notes(package, [dict(old, revision_id=r1)])
        swapped = review_notes(package, [new, old])
        self.assertEqual([entry['status'] for entry in swapped], ['placed', 'review'])
        self.source.close()
        receipt_id = accept(self.night, package)
        book, _ = sign(self.night, receipt_id, notes=[old, new, old])
        self.reopen_night()
        detail = read(self.night, book.book_id).detail
        self.assertEqual(detail['layout_review']['results'], expected)
        self.assertEqual(detail['processing_order'], ['A', 'B', 'C', 'D'])
        self.assertEqual(detail['loads'], [
            {'group': 'G', 'members': ['A', 'B', 'C'], 'total_um': 3},
            {'group': 'G', 'members': ['D'], 'total_um': 1},
        ])

    def test_detours_distinguish_occurrences(self):
        packages = {}
        for history in ('detour_between_freezes', 'detour_before_freezes'):
            with closing(sqlite3.connect(':memory:')) as day:
                revisions = build_history(day, history)
                ids = tuple(revision.revision_id for revision in revisions)
                packages[history] = (ids, issue_layout(day, BATCH, ids[0], ids[-1]))
        (between_ids, between), (before_ids, before) = packages.values()
        self.assertNotEqual(between, before)
        note_between = dict(batch_id=BATCH, revision_id=between_ids[0], left='B', right='C', text='初版夹位')
        note_before = dict(batch_id=BATCH, revision_id=before_ids[0], left='B', right='C', text='初版夹位')
        self.assertEqual(review_notes(between, [note_between])[0]['status'], 'review')
        result = review_notes(before, [note_before])[0]
        self.assertEqual((result['status'], result['final_cut']), ('placed', 2))

    def test_issue_layout_deterministic(self):
        built = []
        for _ in range(2):
            with closing(sqlite3.connect(':memory:')) as day:
                revisions = build_history(day, 'three_observations')
                built.append(issue_layout(day, BATCH, revisions[0].revision_id, revisions[-1].revision_id))
        self.assertEqual(built[0], built[1])

    def test_reissue_ignores_later_history(self):
        (r0, _, r2), package = self._package('three_observations')
        arrange(self.source, BATCH, SegmentMove(0, 1, 3))
        draft = arrange(self.source, BATCH)
        register_profile(self.source, 'J', 2, ('G',))
        freeze(self.source, draft.draft_id, 'J')
        self.assertEqual(issue_layout(self.source, BATCH, r0, r2), package)

    def test_issue_layout_errors(self):
        (r0, _, r2), _ = self._package('three_observations')
        with self.assertRaises(KeyError):
            issue_layout(self.source, BATCH, 'revision:999', r2)
        with self.assertRaises(KeyError):
            issue_layout(self.source, BATCH, r0, 'revision:999')
        with self.assertRaises(ValueError):
            issue_layout(self.source, 'OTHER', r0, r2)
        with self.assertRaises(ValueError):
            issue_layout(self.source, BATCH, r2, r0)
        self.source.execute('DELETE FROM layout_revision_sections')
        self.source.commit()
        with self.assertRaises(ValueError):
            issue_layout(self.source, BATCH, r0, r2)
        item = issue(self.source, r2)
        self.source.close()
        receipt_id = accept(self.night, item)
        book, _ = sign(self.night, receipt_id)
        self.assertNotIn('layout_review', read(self.night, book.book_id).detail)

    def test_same_section_freezes(self):
        admit(self.source, BATCH, 'sample-slip/LOT', rows(('A', 'G', 1), ('B', 'G', 1)))
        draft = arrange(self.source, BATCH)
        register_profile(self.source, 'J', 3, ('G',))
        first = freeze(self.source, draft.draft_id, 'J')
        second = freeze(self.source, draft.draft_id, 'J')
        package = issue_layout(self.source, BATCH, first.revision_id, second.revision_id)
        note = dict(batch_id=BATCH, revision_id=first.revision_id, left='A', right='B', text='同截面')
        other = dict(note, revision_id=second.revision_id)
        results = review_notes(package, [note, other])
        self.assertEqual(
            [(entry['status'], entry['final_cut']) for entry in results],
            [('placed', 1), ('placed', 1)],
        )

    def test_accept_v2_validation(self):
        _, package = self._package('together')
        self.source.close()
        receipt_id = accept(self.night, package)
        self.assertEqual(accept(self.night, package), receipt_id)
        self.assertEqual(self.exchange_counts(), (1, 1))
        bad_terminal = json.loads(package)
        bad_terminal['payload']['terminal']['order'] = ['D', 'C', 'B', 'A']
        bad_observation = json.loads(package)
        bad_observation['payload']['evidence']['observations'][0]['order'] = ['D', 'C', 'B', 'A']
        bad_move = json.loads(package)
        bad_move['payload']['evidence']['moves'] = [[1, 2, 2]]
        tampered_directory = json.loads(package)
        tampered_directory['directory']['revision_id'] = 'revision:99'
        for candidate in (rebind(bad_terminal), rebind(bad_observation), rebind(bad_move),
                          json.dumps(tampered_directory).encode('utf-8'), package[:-1],
                          package.replace(b'"version":2', b'"version":3', 1), b'{}'):
            with self.subTest(candidate=candidate[:60]), self.assertRaises(ValueError):
                accept(self.night, candidate)
        self.assertEqual(self.exchange_counts(), (1, 1))

    def test_review_notes_rejections(self):
        (r0, _, r2), package = self._package('three_observations')
        base = dict(batch_id=BATCH, revision_id=r0, left='A', right='B', text='x')
        self.assertEqual(review_notes(package, []), [])
        bad_notes = [
            'not-a-note',
            dict(base, extra='field'),
            {key: value for key, value in base.items() if key != 'text'},
            dict(base, batch_id=''),
            dict(base, batch_id='OTHER'),
            dict(base, revision_id='revision:999'),
            dict(base, revision_id='junk'),
            dict(base, left=5),
            dict(base, right=True),
            dict(base, text=None),
            dict(base, left=None, right=None),
            dict(base, left='A', right='C'),
            dict(base, left='ZZZ', right='A'),
        ]
        for note in bad_notes:
            with self.subTest(note=note), self.assertRaises(ValueError):
                review_notes(package, [note])
        with self.assertRaises(ValueError):
            review_notes(package, 'not-a-list')
        with self.assertRaises(ValueError):
            review_notes(issue(self.source, r2), [])

    def test_sign_note_rules(self):
        (_, r1), package = self._package('together')
        v1_item = issue(self.source, r1)
        self.source.close()
        v2_receipt = accept(self.night, package)
        v1_receipt = accept(self.night, v1_item)
        with self.assertRaises(ValueError):
            sign(self.night, v2_receipt)
        with self.assertRaises(ValueError):
            sign(self.night, v1_receipt, notes=[])
        self.assertEqual(self.settlement_counts(), (0, 0))
        book, _ = sign(self.night, v2_receipt, notes=[])
        self.assertEqual(read(self.night, book.book_id).detail['layout_review']['results'], [])
        with self.assertRaises(KeyError):
            sign(self.night, 999, notes=[])

    def test_v2_sign_failure_preserves_old_books(self):
        old_revision = self.frozen_batch(rows(('A', '甲', 4)), batch_id='OLD')
        old_item = issue(self.source, old_revision.revision_id)
        (r0, _), package = self._package('together')
        self.source.close()
        old_receipt = accept(self.night, old_item)
        new_receipt = accept(self.night, package)
        old_book, _ = sign(self.night, old_receipt)
        before = read(self.night, old_book.book_id)
        notes = [dict(batch_id=BATCH, revision_id=r0, left='B', right='C', text='段内夹位')]
        with self.assertRaisesRegex(sqlite3.OperationalError, 'injected before commit'):
            sign(self.night, new_receipt, notes=notes, before_commit=fail_before_commit)
        self.reopen_night()
        initialize_night(self.night)
        self.assertEqual(self.settlement_counts(), (1, 1))
        self.assertEqual(read(self.night, old_book.book_id), before)
        new_book, _ = sign(self.night, new_receipt, notes=notes)
        self.reopen_night()
        initialize_night(self.night)
        self.assertEqual(read(self.night, old_book.book_id), before)
        claimed = read(self.night, new_book.book_id)
        self.assertEqual(claimed.detail['layout_review']['results'],
                         [{'note': notes[0], 'status': 'placed', 'final_cut': 1}])
        self.assertNotIn('layout_review', before.detail)

    def test_legacy_database_without_sections(self):
        revision = self.frozen_batch(rows(('A', '甲', 1)))
        self.source.execute('DROP TABLE layout_revision_sections')
        self.source.commit()
        self.source.close()
        self.source = self.connect(self.source_path, initialize_source)
        with self.assertRaises(ValueError):
            issue_layout(self.source, BATCH, revision.revision_id, revision.revision_id)
        item = issue(self.source, revision.revision_id)
        self.source.close()
        receipt_id = accept(self.night, item)
        book, _ = sign(self.night, receipt_id)
        self.reopen_night()
        detail = read(self.night, book.book_id).detail
        self.assertNotIn('layout_review', detail)
        self.assertEqual(detail['processing_order'], ['A'])

    def test_empty_batch_layout(self):
        admit(self.source, BATCH, 'sample-slip/LOT', rows())
        draft = arrange(self.source, BATCH)
        register_profile(self.source, 'J', 3, ('G',))
        revision = freeze(self.source, draft.draft_id, 'J')
        package = issue_layout(self.source, BATCH, revision.revision_id, revision.revision_id)
        self.source.close()
        receipt_id = accept(self.night, package)
        note = dict(batch_id=BATCH, revision_id=revision.revision_id, left=None, right=None, text='')
        book, _ = sign(self.night, receipt_id, notes=[note])
        detail = read(self.night, book.book_id).detail
        self.assertEqual(detail['layout_review']['results'],
                         [{'note': note, 'status': 'placed', 'final_cut': 0}])
        self.assertEqual(detail['loads'], [])
