import hashlib
import json

from exchange.format import decode_v1
from exchange.intake import accept
from exchange.issue import issue
from exchange.receipts import load_received_item
from fixture.profiles import register_profile
from settlement.audit import audit_received_item
from tests.support import ArchiveCase, initialize_night, rows


def with_payload_digest(document):
    payload = json.dumps(document['payload'], sort_keys=True, separators=(',', ':')).encode('utf-8')
    document['directory']['payload_sha256'] = hashlib.sha256(payload).hexdigest()
    return json.dumps(document).encode('utf-8')


class ExchangeTests(ArchiveCase):
    def test_duplicate_delivery(self):
        revision = self.frozen_batch(rows(('A', '甲', 4), ('B', '乙', 6)))
        item = issue(self.source, revision.revision_id)
        self.assertEqual(issue(self.source, revision.revision_id), item)
        self.source.close()
        receipt_id = accept(self.night, item)
        self.assertEqual(accept(self.night, item), receipt_id)
        actual = load_received_item(self.night, receipt_id)
        self.assertEqual(actual.item, item)
        self.assertEqual(actual.receipt.revision_id, revision.revision_id)
        self.assertEqual(actual.receipt.item_sha256, hashlib.sha256(item).hexdigest())
        self.assertEqual(decode_v1(actual.item).profile, revision.profile)
        self.assertEqual(self.exchange_counts(), (1, 1))

    def test_profile_snapshot(self):
        old = self.frozen_batch(rows(('A', '甲', 6), ('B', '甲', 6)))
        register_profile(self.source, 'J', 12, ('甲',))
        item = issue(self.source, old.revision_id)
        self.source.close()
        receipt_id = accept(self.night, item)
        saved = load_received_item(self.night, receipt_id)
        payload = decode_v1(saved.item)
        self.assertEqual(payload.revision_id, old.revision_id)
        self.assertEqual(payload.profile.capacity_um, 10)
        self.assertEqual(payload.profile.allowed_groups, ('甲', '乙'))
        self.assertEqual([load.total_um for load in audit_received_item(self.night, receipt_id).plan.loads], [6, 6])

    def test_unfrozen_ref(self):
        revision = self.frozen_batch(rows())
        for bad in (revision.draft_id, 'revision:999'):
            with self.subTest(bad=bad), self.assertRaises(KeyError):
                issue(self.source, bad)
        self.assertEqual(self.exchange_counts(), (0, 0))

    def test_reopen_receipt(self):
        revision = self.frozen_batch(rows(('A', '甲', 4)))
        item = issue(self.source, revision.revision_id)
        self.source.close()
        first = accept(self.night, item)
        self.reopen_night()
        initialize_night(self.night)
        self.assertEqual(accept(self.night, item), first)
        self.assertEqual(load_received_item(self.night, first).item, item)
        self.assertEqual(self.exchange_counts(), (1, 1))
        other = accept(self.night, item + b'\n')
        self.assertNotEqual(other, first)
        self.assertEqual(load_received_item(self.night, other).item, item + b'\n')
        self.assertEqual(self.exchange_counts(), (2, 2))

    def test_bad_binding(self):
        revision = self.frozen_batch(rows(('A', '甲', 4)))
        item = issue(self.source, revision.revision_id)
        self.source.close()
        for field, value in (('batch_id', 'OTHER'), ('revision_id', 'revision:999'), ('payload_sha256', '0' * 64)):
            document = json.loads(item)
            document['directory'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'directory'):
                accept(self.night, json.dumps(document).encode('utf-8'))
            self.assertEqual(self.exchange_counts(), (0, 0))

    def test_bad_payload(self):
        revision = self.frozen_batch(rows(('A', '甲', 4), ('B', '甲', 6)))
        item = issue(self.source, revision.revision_id)
        self.source.close()
        duplicate = json.loads(item)
        duplicate['payload']['order'] = ['A', 'A']
        ineligible = json.loads(item)
        ineligible['payload']['profile']['allowed_groups'] = ['乙']
        oversized = json.loads(item)
        oversized['payload']['profile']['capacity_um'] = 5
        for bad_item in (item[:-1], with_payload_digest(duplicate), with_payload_digest(ineligible),
                         with_payload_digest(oversized), b'{"version":1,"version":1}'):
            with self.subTest(item=bad_item), self.assertRaises(ValueError):
                accept(self.night, bad_item)
            self.assertEqual(self.exchange_counts(), (0, 0))
