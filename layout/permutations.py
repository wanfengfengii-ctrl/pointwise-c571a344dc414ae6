def require_permutation(original: tuple[str, ...], order: object) -> tuple[str, ...]:
    if not isinstance(order, (list, tuple)) or any(not isinstance(value, str) for value in order):
        raise ValueError('processing order must be a sequence of specimen identities')
    if len(order) != len(original) or len(set(order)) != len(order) or set(order) != set(original):
        raise ValueError('processing order must contain each admitted specimen exactly once')
    return tuple(order)
