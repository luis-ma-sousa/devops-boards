"""The database protects itself: constraints, atomic transactions, schema management and backups."""

import json
import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from boards import db, repository as repo
from boards.errors import ValidationError

NOW = "2026-01-01 00:00:00"


def raw_item(**overrides):
    values = {"type": "Task", "title": "raw", "state": "New", "priority": 2, "created_at": NOW, "updated_at": NOW}
    values.update(overrides)
    with db.write() as conn:
        conn.execute(db.work_items.insert().values(**values))


@pytest.mark.parametrize("overrides", [
    {"type": "Story"},
    {"state": "Resolved"},             # not a Task state
    {"type": "Bug", "state": "Removed"},
    {"priority": 0},
    {"priority": 9},
    {"title": "   "},
    {"story_points": -1},
    {"remaining_work": -0.5},
    {"severity": "Huge"},
    {"value_area": "Fun"},
    {"rev": 0},
])
def test_check_constraints_reject_bad_rows_written_directly(overrides):
    with pytest.raises(IntegrityError):
        raw_item(**overrides)
    assert repo.load_work_items().empty


def test_foreign_keys_are_enforced():
    with pytest.raises(IntegrityError):
        raw_item(assigned_to=999)
    with pytest.raises(IntegrityError):
        raw_item(parent_id=999)


@pytest.mark.parametrize("email", ["UPPER@example.com", "no-at-sign"])
def test_user_constraints_hold_at_database_level(email):
    with pytest.raises(IntegrityError):
        with db.write() as conn:
            conn.execute(db.users.insert().values(name="X", email=email, team="", created_at=NOW))


def test_a_failure_mid_transaction_leaves_nothing_behind(user, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(repo, "_set_tags", boom)
    with pytest.raises(RuntimeError):
        repo.create_work_item({"type": "Task", "title": "half written"}, user, tags=["x"])
    with db.read() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM work_items")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM history")).scalar() == 0


def test_update_failure_rolls_back_state_and_history(user, make_item, monkeypatch):
    item_id = make_item()
    monkeypatch.setattr(repo, "_apply_parent_rules", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        repo.change_state(item_id, "Active", user)
    item = repo.get_work_item(item_id)
    assert item["state"] == "New" and item["rev"] == 1
    assert repo.list_history(item_id)["field"].tolist() == ["created"]


def test_init_db_is_idempotent_and_versioned(database, user):
    db.init_db(database)
    db.init_db(database)
    assert repo.user_count() == 1
    with db.read() as conn:
        assert conn.execute(text("SELECT value FROM schema_info WHERE key = 'version'")).scalar() == str(db.SCHEMA_VERSION)


def test_newer_schema_is_refused(database):
    with db.write() as conn:
        conn.execute(text("UPDATE schema_info SET value = '999' WHERE key = 'version'"))
    with pytest.raises(RuntimeError, match="newer"):
        db.init_db(database)


def test_reset_db_empties_everything(user, make_item):
    make_item()
    db.reset_db()
    assert repo.user_count() == 0
    assert repo.load_work_items().empty


def test_integrity_report_is_clean_after_normal_use(user, make_item):
    parent = make_item("Feature")
    child = make_item(parent_id=parent)
    repo.add_link(parent, "related", make_item(), user)
    repo.delete_work_item(child, user)
    repo.purge_work_item(child)
    assert db.integrity_report() == []


def test_export_json_contains_every_table(user, make_item):
    make_item(tags=["x"])
    data = json.loads(db.export_json())
    assert set(data["tables"]) == {t.name for t in db.metadata.sorted_tables}
    assert len(data["tables"]["work_items"]) == 1
    assert data["tables"]["users"][0]["email"] == "alice@example.com"


def test_settings_are_validated():
    with pytest.raises(ValidationError, match="Unknown setting"):
        repo.set_setting("theme", "dark")
    with pytest.raises(ValidationError):
        repo.set_setting("auto_close_parent", "yes")
    with pytest.raises(ValidationError):
        repo.set_setting("project_name", "   ")
    with pytest.raises(ValidationError):
        repo.set_setting("wip_limits", {"Stories": {"Doing": 3}})
    with pytest.raises(ValidationError):
        repo.set_setting("wip_limits", {"Stories": {"Active": -1}})
    repo.set_setting("wip_limits", {"Stories": {"Active": 3, "Resolved": 0}})
    assert repo.get_setting("wip_limits") == {"Stories": {"Active": 3}}


def test_iterations_are_validated(iteration):
    with pytest.raises(ValidationError, match="already exists"):
        repo.create_iteration("sprint 1")
    with pytest.raises(ValidationError, match="end date"):
        repo.create_iteration("Sprint 2", "2026-02-10", "2026-02-01")
    with pytest.raises(ValidationError):
        repo.create_iteration("   ")
    with pytest.raises(ValidationError):
        repo.update_iteration(iteration, end_date="2025-12-01")


def test_deleting_an_iteration_returns_its_items_to_the_backlog(make_item, iteration):
    item_id = make_item(iteration_id=iteration)
    repo.delete_iteration(iteration)
    assert repo.get_work_item(item_id)["iteration_id"] is None


def test_capacity_is_validated(user, iteration):
    import pandas as pd
    with pytest.raises(ValidationError):
        repo.save_capacity(iteration, pd.DataFrame([{"user_id": user, "hours_per_day": 30, "days_off": 0}]))
    with pytest.raises(ValidationError):
        repo.save_capacity(iteration, pd.DataFrame([{"user_id": user, "hours_per_day": 6, "days_off": -2}]))
    repo.save_capacity(iteration, pd.DataFrame([{"user_id": user, "hours_per_day": 5.5, "days_off": 1}]))
    assert repo.get_capacity(iteration).iloc[0]["hours_per_day"] == 5.5


# --- SQLite specifics ---------------------------------------------------------------------------------------


def test_sqlite_runs_in_wal_mode_with_foreign_keys(backend):
    if backend != "sqlite":
        pytest.skip("SQLite only")
    with db.read() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_sqlite_backup_is_a_consistent_copy(backend, user, make_item, tmp_path):
    if backend != "sqlite":
        pytest.skip("SQLite only")
    for i in range(5):
        make_item(title=f"Item {i}")
    backup = tmp_path / "backup.db"
    backup.write_bytes(db.sqlite_backup_bytes())
    conn = sqlite3.connect(backup)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 5
    finally:
        conn.close()


def test_legacy_prototype_database_is_moved_aside(backend, tmp_path):
    if backend != "sqlite":
        pytest.skip("SQLite only")
    legacy = tmp_path / "legacy.db"
    conn = sqlite3.connect(legacy)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, role TEXT)")
    conn.execute("INSERT INTO users (name, role) VALUES ('Old', 'Developer')")
    conn.commit()
    conn.close()
    engine = db.configure(f"sqlite:///{legacy}")
    db.init_db(engine)
    assert db.legacy_backup is not None and db.legacy_backup.exists()
    assert repo.user_count() == 0
    old = sqlite3.connect(db.legacy_backup)
    assert old.execute("SELECT name FROM users").fetchone()[0] == "Old"
    old.close()
    db.legacy_backup = None
