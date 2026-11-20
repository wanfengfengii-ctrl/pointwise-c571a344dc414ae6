from intake.specimens import Specimen
from .profiles import FixtureProfile


def require_eligible(specimen: Specimen, profile: FixtureProfile) -> None:
    if specimen.group not in profile.allowed_groups:
        raise ValueError(f'group {specimen.group!r} is not allowed by {profile.name!r}')
    if specimen.thickness_um > profile.capacity_um:
        raise ValueError(f'specimen {specimen.specimen_id!r} exceeds fixture capacity')
