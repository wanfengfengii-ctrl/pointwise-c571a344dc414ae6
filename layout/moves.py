from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentMove:
    start: int
    stop: int
    destination: int


def move_segment(order: tuple[str, ...], move: SegmentMove) -> tuple[str, ...]:
    if not isinstance(move, SegmentMove):
        raise ValueError('a SegmentMove is required')
    start, stop, destination = move.start, move.stop, move.destination
    if any(type(coordinate) is not int for coordinate in (start, stop, destination)):
        raise ValueError('segment and cut coordinates must be integers')
    if not 0 <= start < stop <= len(order):
        raise ValueError('segment must be nonempty and inside the order')
    if not 0 <= destination <= len(order) or start < destination < stop:
        raise ValueError('destination must be a legal cut outside the segment interior')
    if destination in (start, stop):
        return order
    segment = order[start:stop]
    remaining = order[:start] + order[stop:]
    insertion = destination - (stop - start) if destination > stop else destination
    return remaining[:insertion] + segment + remaining[insertion:]
