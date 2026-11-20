"""V1 source histories and hand-checked observations for the clip-note task."""
from contextlib import closing
import json
import sqlite3

from exchange.intake import accept
from exchange.issue import issue, issue_layout
from exchange.receipts import init_exchange
from fixture.profiles import init_fixtures, register_profile
from intake.batches import admit, init_intake
from layout.drafts import arrange, init_layout
from layout.freeze import freeze
from layout.moves import SegmentMove
from settlement.audit import review_notes
from settlement.entries import init_settlement
from settlement.publish import sign
from settlement.readback import read

BATCH = "LOT"
OUT = SegmentMove(1, 2, 4)
BACK = SegmentMove(3, 4, 1)
TOGETHER = SegmentMove(1, 3, 0)
# None records a frozen observation. Moves have the original V1 coordinates.
HISTORIES = {
    "together": (None, TOGETHER, None),
    "three_observations": (None, OUT, None, BACK, None),
    "detour_between_freezes": (None, OUT, BACK, None),
    "detour_before_freezes": (OUT, BACK, None, None),
}
ORDERS = {
    "together": ("ABCD", "BCAD"),
    "three_observations": ("ABCD", "ACDB", "ABCD"),
    "detour_between_freezes": ("ABCD", "ABCD"),
    "detour_before_freezes": ("ABCD", "ABCD"),
}
# (revision index, left, right, text, expected status, expected final cut)
V2_CHECKS = {
    "together": [
        (0, "B", "C", "段内夹位", "placed", 1),
        (0, "A", "B", "拆开的夹位", "review", None),
    ],
    "three_observations": [
        (0, "B", "C", "旧夹位", "review", None),
        (2, "B", "C", "终版夹位", "placed", 2),
        (0, "B", "C", "旧夹位", "review", None),
        (0, None, "A", "首缝", "placed", 0),
        (0, "D", None, "尾缝", "review", None),
    ],
    "detour_between_freezes": [
        (0, "B", "C", "初版夹位", "review", None),
    ],
    "detour_before_freezes": [
        (0, "B", "C", "初版夹位", "placed", 2),
    ],
}


def build_history(db, history):
    init_intake(db)
    init_layout(db)
    init_fixtures(db)
    admit(db, BATCH, "sample-slip/LOT", [
        {"specimen_id": name, "group": "G", "thickness_um": 1} for name in "ABCD"
    ])
    draft = arrange(db, BATCH)
    register_profile(db, "J", 3, ("G",))
    revisions = []
    for event in HISTORIES[history]:
        if event is None:
            revisions.append(freeze(db, draft.draft_id, "J"))
        else:
            arrange(db, BATCH, event)
    return tuple(revisions)


def inspect_v1(history):
    with closing(sqlite3.connect(":memory:")) as day:
        revisions = build_history(day, history)
        orders = tuple("".join(revision.order) for revision in revisions)
        if orders != ORDERS[history]:
            raise AssertionError((history, orders, ORDERS[history]))
        items = tuple(issue(day, revision.revision_id) for revision in revisions)
    with closing(sqlite3.connect(":memory:")) as night:
        init_exchange(night)
        init_settlement(night)
        receipt_id = accept(night, items[-1])
        book, _ = sign(night, receipt_id)
        detail = read(night, book.book_id).detail
    expected = ((orders[-1][:3], 3), (orders[-1][3:], 1))
    actual = tuple(("".join(load["members"]), load["total_um"]) for load in detail["loads"])
    if actual != expected or detail["changeover_count"] != 0:
        raise AssertionError((history, actual, expected, detail["changeover_count"]))
    return items, {"observed_orders": orders, "terminal_loads": actual}


def inspect_v2(history):
    with closing(sqlite3.connect(":memory:")) as day:
        revisions = build_history(day, history)
        ids = tuple(revision.revision_id for revision in revisions)
        package = issue_layout(day, BATCH, ids[0], ids[-1])
    return ids, package


def check_outcomes(ids, package, checks):
    notes = [
        dict(batch_id=BATCH, revision_id=ids[index], left=left, right=right, text=text)
        for index, left, right, text, _, _ in checks
    ]
    results = review_notes(package, notes)
    expected = [
        {"note": item, "status": status, "final_cut": cut}
        for item, (_, _, _, _, status, cut) in zip(notes, checks)
    ]
    if results != expected:
        raise AssertionError((results, expected))
    return results


def main():
    inspected = {history: inspect_v1(history) for history in HISTORIES}
    if inspected["detour_between_freezes"] != inspected["detour_before_freezes"]:
        raise AssertionError("V1 should have identical handoffs in the two detour cases")
    packages = {}
    reviewed = {}
    for history in HISTORIES:
        ids, package = inspect_v2(history)
        packages[history] = package
        reviewed[history] = check_outcomes(ids, package, V2_CHECKS[history])
    if packages["detour_between_freezes"] == packages["detour_before_freezes"]:
        raise AssertionError("V2 evidence should distinguish the two detour cases")
    three_ids, three_package = inspect_v2("three_observations")
    try:
        review_notes(three_package, [
            dict(batch_id=BATCH, revision_id=three_ids[1], left="B", right="C", text="中途引用"),
        ])
    except ValueError:
        pass
    else:
        raise AssertionError("a clip absent at the noted revision must reject the whole list")
    print(json.dumps({
        "v1": {name: detail for name, (_, detail) in inspected.items()},
        "v2": reviewed,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
