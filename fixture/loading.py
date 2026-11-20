from collections.abc import Iterable
from dataclasses import dataclass

from intake.specimens import Specimen
from .changeovers import count_changeovers
from .eligibility import require_eligible
from .profiles import FixtureProfile


@dataclass(frozen=True)
class LoadGroup:
    group: str
    members: tuple[str, ...]
    total_um: int


@dataclass(frozen=True)
class LoadPlan:
    loads: tuple[LoadGroup, ...]
    changeover_count: int

    @property
    def load_count(self) -> int:
        return len(self.loads)

    @classmethod
    def from_record(cls, record: dict) -> 'LoadPlan':
        loads = tuple(
            LoadGroup(row['group'], tuple(row['members']), row['total_um'])
            for row in record['loads']
        )
        return cls(loads, record['changeover_count'])


def plan_loads(specimens: Iterable[Specimen], profile: FixtureProfile) -> LoadPlan:
    loads = []
    members = []
    group = ''
    total = 0
    for specimen in specimens:
        require_eligible(specimen, profile)
        if members and (specimen.group != group or total + specimen.thickness_um > profile.capacity_um):
            loads.append(LoadGroup(group, tuple(members), total))
            members = []
            total = 0
        group = specimen.group
        members.append(specimen.specimen_id)
        total += specimen.thickness_um
    if members:
        loads.append(LoadGroup(group, tuple(members), total))
    return LoadPlan(tuple(loads), count_changeovers(load.group for load in loads))
