from dataclasses import dataclass
import json
import sqlite3

from intake.measurements import require_thickness_um
from intake.specimens import require_text


@dataclass(frozen=True)
class FixtureProfile:
    name: str
    capacity_um: int
    allowed_groups: tuple[str, ...]

    def __post_init__(self) -> None:
        require_text(self.name, 'profile name')
        require_thickness_um(self.capacity_um, 'capacity_um')
        if not isinstance(self.allowed_groups, tuple):
            raise ValueError('allowed_groups must be a tuple in a fixture profile')
        for group in self.allowed_groups:
            require_text(group, 'allowed group')
        if len(set(self.allowed_groups)) != len(self.allowed_groups):
            raise ValueError('allowed_groups contains duplicates')


def make_profile(name: str, capacity_um: int, allowed_groups: object) -> FixtureProfile:
    if not isinstance(allowed_groups, (list, tuple)):
        raise ValueError('allowed_groups must be a list or tuple')
    return FixtureProfile(name, capacity_um, tuple(allowed_groups))


def init_fixtures(db: sqlite3.Connection) -> None:
    db.execute('BEGIN IMMEDIATE')
    with db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS fixture_profiles (
                name TEXT PRIMARY KEY NOT NULL,
                capacity_um TEXT NOT NULL,
                allowed_groups TEXT NOT NULL
            )
        ''')


def register_profile(
    db: sqlite3.Connection, name: str, capacity_um: int, allowed_groups: object,
) -> FixtureProfile:
    profile = make_profile(name, capacity_um, allowed_groups)
    db.execute('BEGIN IMMEDIATE')
    with db:
        db.execute('''
            INSERT INTO fixture_profiles (name, capacity_um, allowed_groups) VALUES (?, ?, ?)
            ON CONFLICT (name) DO UPDATE SET
                capacity_um = excluded.capacity_um, allowed_groups = excluded.allowed_groups
        ''', (name, str(profile.capacity_um), json.dumps(profile.allowed_groups)))
    return profile


def load_profile(db: sqlite3.Connection, name: str) -> FixtureProfile:
    require_text(name, 'profile name')
    row = db.execute(
        'SELECT capacity_um, allowed_groups FROM fixture_profiles WHERE name = ?', (name,),
    ).fetchone()
    if row is None:
        raise KeyError(f'unknown fixture profile {name!r}')
    return make_profile(name, int(row[0]), json.loads(row[1]))
