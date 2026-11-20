from contextlib import ExitStack, closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from exchange.receipts import init_exchange
from fixture.profiles import init_fixtures, register_profile
from intake.batches import admit, init_intake
from intake.specimens import Specimen
from layout.drafts import arrange, init_layout
from layout.freeze import freeze
from settlement.entries import init_settlement


def rows(*facts):
    return [Specimen(*fact) for fact in facts]


def initialize_source(db):
    init_intake(db)
    init_layout(db)
    init_fixtures(db)


def initialize_night(db):
    init_exchange(db)
    init_settlement(db)


def fail_before_commit():
    raise sqlite3.OperationalError('injected before commit')


class ArchiveCase(unittest.TestCase):
    def setUp(self):
        self.stack = self.addCleanupStack()
        directory = Path(self.stack.enter_context(TemporaryDirectory(prefix='schedule-test-')))
        self.source_path = directory / 'source.sqlite'
        self.night_path = directory / 'night.sqlite'
        self.source = self.connect(self.source_path, initialize_source)
        self.night = self.connect(self.night_path, initialize_night)

    def addCleanupStack(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        return stack

    def connect(self, path, initialize):
        connection = self.stack.enter_context(closing(sqlite3.connect(path)))
        initialize(connection)
        return connection

    def reopen_night(self):
        self.night.close()
        self.night = self.connect(self.night_path, initialize_night)
        return self.night

    def frozen_batch(self, specimens, *, batch_id='LOT', capacity=10, moves=()):
        admit(self.source, batch_id, f'sample-slip/{batch_id}', specimens)
        draft = arrange(self.source, batch_id)
        for move in moves:
            draft = arrange(self.source, batch_id, move)
        register_profile(self.source, 'J', capacity, ('甲', '乙'))
        return freeze(self.source, draft.draft_id, 'J')

    def intake_counts(self):
        return tuple(self.source.execute(query).fetchone()[0] for query in (
            'SELECT count(*) FROM intake_batches',
            'SELECT count(*) FROM intake_specimens',
            'SELECT count(*) FROM intake_receipts',
        ))

    def exchange_counts(self):
        return tuple(self.night.execute(query).fetchone()[0] for query in (
            'SELECT count(*) FROM exchange_items',
            'SELECT count(*) FROM exchange_receipts',
        ))

    def settlement_counts(self):
        return tuple(self.night.execute(query).fetchone()[0] for query in (
            'SELECT count(*) FROM settlement_books',
            'SELECT count(*) FROM settlement_sign_receipts',
        ))
