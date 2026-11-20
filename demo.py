from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from clip_cases import BATCH, build_history
from exchange.intake import accept
from exchange.issue import issue_layout
from exchange.receipts import init_exchange
from settlement.entries import init_settlement
from settlement.publish import sign
from settlement.readback import read


def demonstrate(directory: Path) -> dict:
    source_path = directory / 'day.sqlite'
    night_path = directory / 'night.sqlite'
    with closing(sqlite3.connect(source_path)) as day:
        r0, _, r2 = build_history(day, 'three_observations')
        package = issue_layout(day, BATCH, r0.revision_id, r2.revision_id)
    source_path.unlink()

    old = dict(batch_id=BATCH, revision_id=r0.revision_id, left='B', right='C', text='旧夹位')
    new = dict(batch_id=BATCH, revision_id=r2.revision_id, left='B', right='C', text='终版夹位')
    notes = [old, new, old]
    with closing(sqlite3.connect(night_path)) as night:
        init_exchange(night)
        init_settlement(night)
        receipt_id = accept(night, package)
        book, signed = sign(night, receipt_id, notes=notes)
    with closing(sqlite3.connect(night_path)) as night:
        init_exchange(night)
        init_settlement(night)
        claimed = read(night, book.book_id)

    expected_results = [
        {'note': old, 'status': 'review', 'final_cut': None},
        {'note': new, 'status': 'placed', 'final_cut': 2},
        {'note': old, 'status': 'review', 'final_cut': None},
    ]
    expected_loads = [
        {'group': 'G', 'members': ['A', 'B', 'C'], 'total_um': 3},
        {'group': 'G', 'members': ['D'], 'total_um': 1},
    ]
    detail = claimed.detail
    review = detail['layout_review']
    if (claimed.receipt != signed or claimed.book != book
            or (review['start_revision'], review['end_revision']) != (r0.revision_id, r2.revision_id)
            or review['results'] != expected_results
            or detail['incoming_order'] != ['A', 'B', 'C', 'D']
            or detail['processing_order'] != ['A', 'B', 'C', 'D']
            or detail['loads'] != expected_loads or detail['load_count'] != 2
            or detail['changeover_count'] != 0
            or detail['delivery']['receipt_id'] != receipt_id
            or detail['delivery']['revision_id'] != r2.revision_id):
        raise RuntimeError('reopened layout review differs from the worked sample')
    return detail


def main() -> None:
    with TemporaryDirectory(prefix='clip-note-handoff-') as directory:
        print(json.dumps(demonstrate(Path(directory)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
