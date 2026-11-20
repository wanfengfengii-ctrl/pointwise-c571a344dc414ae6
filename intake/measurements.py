def require_thickness_um(value: object, field: str = 'thickness_um') -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f'{field} must be a positive integer in micrometres')
    return value
