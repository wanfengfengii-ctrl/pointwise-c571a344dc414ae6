from collections.abc import Iterable
from itertools import pairwise


def count_changeovers(groups: Iterable[str]) -> int:
    return sum(previous != current for previous, current in pairwise(groups))
