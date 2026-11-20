from .moves import SegmentMove, move_segment


def _pair_at(order: tuple[str, ...], cut: int) -> tuple[str | None, str | None]:
    left = order[cut - 1] if cut > 0 else None
    right = order[cut] if cut < len(order) else None
    return (left, right)


def cut_pairs(order: tuple[str, ...]) -> tuple[tuple[str | None, str | None], ...]:
    order = tuple(order)
    return tuple(_pair_at(order, cut) for cut in range(len(order) + 1))


def cut_index(order: tuple[str, ...], pair: tuple[str | None, str | None]) -> int:
    for index, current in enumerate(cut_pairs(order)):
        if current == pair:
            return index
    raise ValueError(f'clip {pair!r} is not present in the order')


def removed_pairs(order: tuple[str, ...], move: SegmentMove) -> frozenset:
    order = tuple(order)
    return frozenset(
        (_pair_at(order, move.start), _pair_at(order, move.stop), _pair_at(order, move.destination))
    )


def replay_orders(initial_order: tuple[str, ...], moves: tuple[SegmentMove, ...]) -> list[tuple[str, ...]]:
    orders = [tuple(initial_order)]
    for move in moves:
        orders.append(move_segment(orders[-1], move))
    return orders
