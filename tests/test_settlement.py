import json
import sqlite3

from exchange.intake import accept
from exchange.issue import issue
from exchange.receipts import load_received_item
from layout.moves import SegmentMove
from settlement.publish import sign
from settlement.readback import read
from tests.support import ArchiveCase, fail_before_commit, initialize_night, rows


class SettlementTests(ArchiveCase):
    def _deliver(self, revision):
        item = issue(self.source, revision.revision_id)
        self.source.close()
        return accept(self.night, item)

    def _retry_and_reopen(self, receipt_id):
        earlier = self.settlement_counts()
        with self.assertRaisesRegex(sqlite3.OperationalError, 'injected before commit'):
            sign(self.night, receipt_id, before_commit=fail_before_commit)
        self.reopen_night()
        self.assertEqual(self.settlement_counts(), earlier)
        fixed = sign(self.night, receipt_id)
        self.assertEqual(self.settlement_counts(), (earlier[0] + 1, earlier[1] + 1))
        self.reopen_night()
        claimed = read(self.night, fixed[0].book_id)
        self.assertEqual((claimed.book, claimed.receipt), fixed)
        actual = load_received_item(self.night, receipt_id).receipt
        self.assertEqual(claimed.book.result.delivery, actual)
        self.assertEqual((claimed.receipt.receipt_id, claimed.receipt.item_sha256),
                         (actual.receipt_id, actual.item_sha256))
        return claimed

    def test_empty_run_readback(self):
        revision = self.frozen_batch(rows())
        receipt_id = self._deliver(revision)
        book, signed = sign(self.night, receipt_id)
        self.assertEqual(book.result.plan.loads, ())
        self.assertEqual(book.result.plan.load_count, 0)
        self.assertEqual(book.result.plan.changeover_count, 0)
        self.reopen_night()
        first = read(self.night, book.book_id)
        second = read(self.night, book.book_id)
        self.assertEqual(first, second)
        self.assertEqual((first.book, first.receipt), (book, signed))
        self.assertEqual(first.detail['loads'], [])
        self.assertEqual(first.detail['processing_order'], [])
        self.assertEqual(first.detail['delivery']['revision_id'], revision.revision_id)
        self.assertEqual(self.night.execute('SELECT book_id FROM settlement_claims ORDER BY claim_id').fetchall(),
                         [(book.book_id,), (book.book_id,)])

    def test_unknown_book(self):
        receipt_id = self._deliver(self.frozen_batch(rows()))
        book, _ = sign(self.night, receipt_id)
        self.reopen_night()
        read(self.night, book.book_id)
        with self.assertRaises(KeyError):
            read(self.night, book.book_id + 1)
        self.assertEqual(self.night.execute('SELECT book_id FROM settlement_claims').fetchall(), [(book.book_id,)])

    def test_failed_sign_can_retry(self):
        revision = self.frozen_batch(rows(('A', '甲', 6), ('B', '乙', 4)))
        receipt_id = self._deliver(revision)
        claimed = self._retry_and_reopen(receipt_id)
        self.assertEqual(claimed.detail['processing_order'], ['A', 'B'])
        self.assertEqual(claimed.detail['loads'], [
            {'group': '甲', 'members': ['A'], 'total_um': 6},
            {'group': '乙', 'members': ['B'], 'total_um': 4},
        ])
        self.assertEqual(claimed.detail['changeover_count'], 1)
        self.assertEqual(claimed.detail['delivery']['revision_id'], revision.revision_id)
        self.assertEqual(claimed.detail['source'], 'sample-slip/LOT')

    def test_changeover_by_group(self):
        specimens = rows(('A', '甲', 4), ('B', '甲', 6), ('C', '甲', 3), ('D', '乙', 2))
        revision = self.frozen_batch(specimens)
        receipt_id = self._deliver(revision)
        claimed = self._retry_and_reopen(receipt_id)
        expected = {
            'loads': [{'group': '甲', 'members': ['A', 'B'], 'total_um': 10},
                      {'group': '甲', 'members': ['C'], 'total_um': 3},
                      {'group': '乙', 'members': ['D'], 'total_um': 2}],
            'load_count': 3,
            'changeover_count': 1,
        }
        actual = {
            'loads': [{'group': load.group, 'members': list(load.members), 'total_um': load.total_um}
                      for load in revision.plan.loads],
            'load_count': revision.plan.load_count,
            'changeover_count': revision.plan.changeover_count,
        }
        downstream = {field: claimed.detail[field] for field in expected}
        self.assertEqual(actual, expected)
        self.assertEqual(downstream, expected)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 't8.changeover_by_group',
            'input': {'capacity_um': revision.profile.capacity_um,
                      'specimens': [[row.specimen_id, row.group, row.thickness_um] for row in specimens]},
            'expected': expected,
            'actual': actual,
            'downstream_expected': expected,
            'downstream_actual': downstream,
            'code_paths': ['layout/freeze.py', 'fixture/loading.py', 'fixture/changeovers.py',
                           'exchange/issue.py', 'exchange/intake.py', 'settlement/audit.py',
                           'settlement/publish.py', 'settlement/readback.py'],
            'oracle': '手算 4+6 恰满，甲组 3 单独装夹，随后乙组 2 触发唯一一次换型',
        }, ensure_ascii=False, sort_keys=True))

    def test_ordered_readback(self):
        revision = self.frozen_batch(rows(('A', '甲', 4), ('B', '甲', 6), ('C', '甲', 6), ('D', '甲', 4)),
                                     moves=(SegmentMove(3, 4, 0), SegmentMove(1, 2, 4)))
        claimed = self._retry_and_reopen(self._deliver(revision))
        self.assertEqual(claimed.detail['incoming_order'], ['A', 'B', 'C', 'D'])
        self.assertEqual(claimed.detail['processing_order'], ['D', 'B', 'C', 'A'])
        self.assertEqual(claimed.detail['loads'], [
            {'group': '甲', 'members': ['D', 'B'], 'total_um': 10},
            {'group': '甲', 'members': ['C', 'A'], 'total_um': 10},
        ])
        self.assertEqual(claimed.detail['changeover_count'], 0)

    def test_reinitialize_preserves_old_ledger(self):
        old = self.frozen_batch(rows(('A', '甲', 4)), batch_id='OLD')
        new = self.frozen_batch(rows(('A', '乙', 7)), batch_id='NEW')
        old_item = issue(self.source, old.revision_id)
        new_item = issue(self.source, new.revision_id)
        self.source.close()
        first_id = accept(self.night, old_item)
        second_id = accept(self.night, new_item)
        initial = sign(self.night, first_id)
        before = read(self.night, initial[0].book_id)
        with self.assertRaisesRegex(sqlite3.OperationalError, 'injected before commit'):
            sign(self.night, second_id, before_commit=fail_before_commit)
        self.reopen_night()
        initialize_night(self.night)
        self.assertEqual(self.settlement_counts(), (1, 1))
        self.assertEqual(read(self.night, initial[0].book_id), before)
        second = sign(self.night, second_id)
        self.reopen_night()
        initialize_night(self.night)
        self.assertEqual(self.settlement_counts(), (2, 2))
        self.assertEqual(read(self.night, initial[0].book_id), before)
        after = read(self.night, second[0].book_id)
        self.assertEqual((after.book, after.receipt), second)
        self.assertEqual(after.detail['delivery']['batch_id'], 'NEW')
        self.assertEqual(after.detail['loads'], [{'group': '乙', 'members': ['A'], 'total_um': 7}])

    def test_missing_receipt(self):
        with self.assertRaises(KeyError):
            sign(self.night, 999)
        self.assertEqual(self.settlement_counts(), (0, 0))
