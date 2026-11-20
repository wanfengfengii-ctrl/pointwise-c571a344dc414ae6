from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from exchange.intake import accept
from exchange.issue import issue
from exchange.receipts import init_exchange
from fixture.profiles import init_fixtures, register_profile
from intake.batches import admit, init_intake
from layout.drafts import arrange, init_layout
from layout.freeze import freeze
from layout.moves import SegmentMove
from settlement.entries import init_settlement
from settlement.publish import sign
from settlement.readback import read


def demonstrate(directory: Path) -> dict:
    source_path = directory / 'day.sqlite'
    night_path = directory / 'night.sqlite'
    specimens = [
        {'specimen_id': 'A', 'group': '甲', 'thickness_um': 4},
        {'specimen_id': 'B', 'group': '甲', 'thickness_um': 6},
        {'specimen_id': 'C', 'group': '甲', 'thickness_um': 3},
        {'specimen_id': 'D', 'group': '乙', 'thickness_um': 2},
    ]
    with closing(sqlite3.connect(source_path)) as day:
        init_intake(day)
        init_layout(day)
        init_fixtures(day)
        admit(day, 'LOT-01', '送样单-01', specimens)
        arrange(day, 'LOT-01')
        draft = arrange(day, 'LOT-01', SegmentMove(0, 1, 2))
        register_profile(day, 'J10', 10, ('甲', '乙'))
        revision = freeze(day, draft.draft_id, 'J10')
        item = issue(day, revision.revision_id)
    source_path.unlink()

    with closing(sqlite3.connect(night_path)) as night:
        init_exchange(night)
        init_settlement(night)
        receipt_id = accept(night, item)
        book, signed = sign(night, receipt_id)
    with closing(sqlite3.connect(night_path)) as night:
        init_exchange(night)
        init_settlement(night)
        claimed = read(night, book.book_id)

    expected_loads = [
        {'group': '甲', 'members': ['B', 'A'], 'total_um': 10},
        {'group': '甲', 'members': ['C'], 'total_um': 3},
        {'group': '乙', 'members': ['D'], 'total_um': 2},
    ]
    detail = claimed.detail
    if (claimed.receipt != signed or claimed.book != book
            or detail['incoming_order'] != ['A', 'B', 'C', 'D']
            or detail['processing_order'] != ['B', 'A', 'C', 'D']
            or detail['loads'] != expected_loads or detail['load_count'] != 3
            or detail['changeover_count'] != 1 or detail['delivery']['receipt_id'] != receipt_id):
        raise RuntimeError('reopened daybook differs from the worked sample')
    return detail


def main() -> None:
    with TemporaryDirectory(prefix='specimen-handoff-') as directory:
        print(json.dumps(demonstrate(Path(directory)), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
