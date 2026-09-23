"""Give every test an isolated, initialized database.

Without this, a fresh clone fails `pytest` until `make seed` has run (the smoke tests hit a DB with no
tables). This autouse fixture points `DB_PATH` at a per-test temp file and creates the schema, so the suite
passes cold and no test depends on — or pollutes — a shared database. Tests that set their own `DB_PATH`
(e.g. the persistence tests) simply override it within the test.
"""
import pytest

from app import store


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    store.init_db()
    yield
