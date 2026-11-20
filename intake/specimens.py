from collections.abc import Mapping
from dataclasses import dataclass

from .measurements import require_thickness_um


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f'{field} must be nonempty text')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as error:
        raise ValueError(f'{field} must be valid Unicode text') from error
    return value


@dataclass(frozen=True)
class Specimen:
    specimen_id: str
    group: str
    thickness_um: int

    def __post_init__(self) -> None:
        require_text(self.specimen_id, 'specimen_id')
        require_text(self.group, 'group')
        require_thickness_um(self.thickness_um)


def build_specimens(rows: object) -> tuple[Specimen, ...]:
    if not isinstance(rows, (list, tuple)):
        raise ValueError('specimens must be an ordered list or tuple')
    specimens = []
    identities = set()
    fields = {'specimen_id', 'group', 'thickness_um'}
    for row in rows:
        if isinstance(row, Specimen):
            specimen = row
        elif isinstance(row, Mapping) and row.keys() == fields:
            specimen = Specimen(row['specimen_id'], row['group'], row['thickness_um'])
        else:
            raise ValueError('invalid specimen row')
        if specimen.specimen_id in identities:
            raise ValueError(f'duplicate specimen {specimen.specimen_id!r}')
        identities.add(specimen.specimen_id)
        specimens.append(specimen)
    return tuple(specimens)
