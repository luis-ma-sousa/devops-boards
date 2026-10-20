"""Test fixtures.

Every test runs against a fresh SQLite database. Set ``TEST_DATABASE_URL`` to also run every test
against PostgreSQL (``TEST_DATABASE_URL=embedded`` starts a throwaway server with ``pgserver``).
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from boards import db  # noqa: E402
from boards import repository as repo  # noqa: E402

_PG_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
BACKENDS = ["sqlite"] + (["postgresql"] if _PG_URL else [])


@pytest.fixture(scope="session")
def postgres_url(tmp_path_factory):
    if _PG_URL != "embedded":
        return _PG_URL
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"), cleanup_mode="stop")
    return server.get_uri()


@pytest.fixture(params=BACKENDS, autouse=True)
def database(request, tmp_path):
    """A clean database for each test; the app's engine points at it."""
    if request.param == "sqlite":
        engine = db.configure(f"sqlite:///{tmp_path / 'boards-test.db'}")
    else:
        url = request.getfixturevalue("postgres_url")
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg://" + url[len(prefix):]
        engine = db.configure(url)
        db.metadata.drop_all(engine)
    db.init_db(engine)
    yield engine
    if request.param != "sqlite":
        db.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def backend(database) -> str:
    return database.dialect.name


@pytest.fixture
def user():
    return repo.create_user("Alice Example", "alice@example.com", "Platform")


@pytest.fixture
def other_user():
    return repo.create_user("Bob Example", "bob@example.com", "Mobile")


@pytest.fixture
def make_item(user):
    def _make(item_type="User Story", title=None, by=None, tags=None, **fields):
        data = {"type": item_type, "title": title or f"{item_type} item", **fields}
        return repo.create_work_item(data, by or user, tags=tags)
    return _make


@pytest.fixture
def iteration():
    return repo.create_iteration("Sprint 1", "2026-01-05", "2026-01-16", "First sprint")
