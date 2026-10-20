"""Database engine, schema and transactions.

SQLite is used by default (``data/boards.db``). Set ``DATABASE_URL`` to a PostgreSQL URL
(e.g. ``postgresql://user:pass@host/db``) for deployments where many people use the app at
the same time.

Safety measures against corruption and lost updates:

* SQLite runs in WAL mode with foreign keys on, a 30 s busy timeout and ``synchronous=NORMAL``.
* Every write runs in a transaction; on SQLite it starts with ``BEGIN IMMEDIATE`` so that
  read-modify-write sequences are serialised, on PostgreSQL rows are locked with ``FOR UPDATE``.
* The schema has CHECK, UNIQUE and FOREIGN KEY constraints as a second line of defence behind
  the validation done in ``repository.py``.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import make_url

from . import config

SCHEMA_VERSION = 1
DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "boards.db"


def _quoted(values) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


_STATE_RULE = " OR ".join(
    f"(type = '{t}' AND state IN ({_quoted(states)}))" for t, states in config.STATES.items()
)

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(config.MAX_NAME), nullable=False),
    Column("email", String(254), nullable=False, unique=True),
    Column("team", String(config.MAX_NAME), nullable=False, server_default=""),
    Column("active", Integer, nullable=False, server_default="1"),
    Column("created_at", String(19), nullable=False),
    CheckConstraint("length(trim(name)) > 0", name="ck_users_name"),
    CheckConstraint("email = lower(email) AND email LIKE '%_@_%'", name="ck_users_email"),
    CheckConstraint("active IN (0, 1)", name="ck_users_active"),
)

iterations = Table(
    "iterations", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(config.MAX_NAME), nullable=False, unique=True),
    Column("start_date", String(10)),
    Column("end_date", String(10)),
    Column("goal", Text, nullable=False, server_default=""),
    CheckConstraint("length(trim(name)) > 0", name="ck_iterations_name"),
    CheckConstraint("start_date IS NULL OR end_date IS NULL OR end_date >= start_date", name="ck_iterations_dates"),
)

areas = Table(
    "areas", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(config.MAX_NAME), nullable=False, unique=True),
    CheckConstraint("length(trim(name)) > 0", name="ck_areas_name"),
)

tags = Table(
    "tags", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(config.MAX_TAG), nullable=False),
    Column("name_key", String(config.MAX_TAG), nullable=False, unique=True),
    CheckConstraint("length(trim(name)) > 0 AND name_key = lower(name)", name="ck_tags_name"),
)

work_items = Table(
    "work_items", metadata,
    Column("id", Integer, primary_key=True),
    Column("type", String(20), nullable=False),
    Column("title", String(config.MAX_TITLE), nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("acceptance_criteria", Text, nullable=False, server_default=""),
    Column("state", String(20), nullable=False, server_default="New"),
    Column("reason", String(200), nullable=False, server_default=""),
    Column("priority", Integer, nullable=False, server_default="2"),
    Column("severity", String(20)),
    Column("value_area", String(20), nullable=False, server_default="Business"),
    Column("story_points", Float),
    Column("effort", Float),
    Column("business_value", Integer),
    Column("original_estimate", Float),
    Column("remaining_work", Float),
    Column("completed_work", Float),
    Column("assigned_to", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("iteration_id", Integer, ForeignKey("iterations.id", ondelete="SET NULL")),
    Column("area_id", Integer, ForeignKey("areas.id", ondelete="SET NULL")),
    Column("parent_id", Integer, ForeignKey("work_items.id", ondelete="SET NULL")),
    Column("backlog_rank", Float, nullable=False, server_default="0"),
    Column("start_date", String(10)),
    Column("target_date", String(10)),
    Column("rev", Integer, nullable=False, server_default="1"),
    Column("created_at", String(19), nullable=False),
    Column("updated_at", String(19), nullable=False),
    Column("activated_at", String(19)),
    Column("resolved_at", String(19)),
    Column("closed_at", String(19)),
    Column("deleted_at", String(19)),
    CheckConstraint(f"type IN ({_quoted(config.WORK_ITEM_TYPES)})", name="ck_wi_type"),
    CheckConstraint(_STATE_RULE, name="ck_wi_state"),
    CheckConstraint("length(trim(title)) > 0", name="ck_wi_title"),
    CheckConstraint("priority BETWEEN 1 AND 4", name="ck_wi_priority"),
    CheckConstraint(f"severity IS NULL OR severity IN ({_quoted(config.SEVERITIES)})", name="ck_wi_severity"),
    CheckConstraint(f"value_area IN ({_quoted(config.VALUE_AREAS)})", name="ck_wi_value_area"),
    CheckConstraint(
        "(story_points IS NULL OR story_points >= 0) AND (effort IS NULL OR effort >= 0)"
        " AND (business_value IS NULL OR business_value >= 0)"
        " AND (original_estimate IS NULL OR original_estimate >= 0)"
        " AND (remaining_work IS NULL OR remaining_work >= 0)"
        " AND (completed_work IS NULL OR completed_work >= 0)",
        name="ck_wi_numbers",
    ),
    CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_wi_parent"),
    CheckConstraint("rev >= 1", name="ck_wi_rev"),
)
Index("ix_wi_parent", work_items.c.parent_id)
Index("ix_wi_iteration", work_items.c.iteration_id)
Index("ix_wi_assigned", work_items.c.assigned_to)
Index("ix_wi_type_state", work_items.c.type, work_items.c.state)

work_item_tags = Table(
    "work_item_tags", metadata,
    Column("work_item_id", Integer, ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

work_item_links = Table(
    "work_item_links", metadata,
    Column("id", Integer, primary_key=True),
    Column("source_id", Integer, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
    Column("target_id", Integer, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
    Column("link_type", String(20), nullable=False),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", String(19), nullable=False),
    UniqueConstraint("source_id", "target_id", "link_type", name="uq_links"),
    CheckConstraint("source_id <> target_id", name="ck_links_self"),
    CheckConstraint(f"link_type IN ({_quoted(config.STORED_LINK_TYPES)})", name="ck_links_type"),
)
Index("ix_links_source", work_item_links.c.source_id)
Index("ix_links_target", work_item_links.c.target_id)

comments = Table(
    "comments", metadata,
    Column("id", Integer, primary_key=True),
    Column("work_item_id", Integer, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("body", Text, nullable=False),
    Column("created_at", String(19), nullable=False),
    CheckConstraint("length(trim(body)) > 0", name="ck_comments_body"),
)
Index("ix_comments_item", comments.c.work_item_id)

# Field-by-field audit trail. Also used to rebuild burndown and cumulative flow.
history = Table(
    "history", metadata,
    Column("id", Integer, primary_key=True),
    Column("work_item_id", Integer, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("field", String(40), nullable=False),
    Column("old_value", Text),
    Column("new_value", Text),
    Column("changed_at", String(19), nullable=False),
)
Index("ix_history_item", history.c.work_item_id, history.c.changed_at)

capacity = Table(
    "capacity", metadata,
    Column("iteration_id", Integer, ForeignKey("iterations.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("hours_per_day", Float, nullable=False, server_default="6"),
    Column("days_off", Integer, nullable=False, server_default="0"),
    CheckConstraint("hours_per_day >= 0 AND hours_per_day <= 24", name="ck_capacity_hours"),
    CheckConstraint("days_off >= 0", name="ck_capacity_days"),
)

settings = Table(
    "settings", metadata,
    Column("key", String(60), primary_key=True),
    Column("value", Text, nullable=False),
)

schema_info = Table(
    "schema_info", metadata,
    Column("key", String(40), primary_key=True),
    Column("value", String(200), nullable=False),
)


# --- engine -----------------------------------------------------------------------------------------

_engine = None
_engine_lock = threading.Lock()
legacy_backup: Path | None = None  # set when an old prototype database was moved aside


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    return f"sqlite:///{os.environ.get('BOARDS_DB', DEFAULT_SQLITE_PATH)}"


def safe_url(url: str | None = None) -> str:
    """Database URL with the password hidden, for display."""
    return make_url(url or database_url()).render_as_string(hide_password=True)


def is_sqlite(engine=None) -> bool:
    return (engine or get_engine()).dialect.name == "sqlite"


def sqlite_path(engine=None) -> Path | None:
    engine = engine or get_engine()
    if engine.dialect.name != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        return None
    return Path(engine.url.database)


def make_engine(url: str):
    if url.startswith("sqlite"):
        database = make_url(url).database
        if database and database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"timeout": 30, "check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, _record):
            dbapi_conn.isolation_level = None  # let SQLAlchemy emit BEGIN itself
            cur = dbapi_conn.cursor()
            for pragma in ("foreign_keys = ON", "journal_mode = WAL", "synchronous = NORMAL",
                           "busy_timeout = 30000"):
                cur.execute(f"PRAGMA {pragma}")
            cur.close()

        @event.listens_for(engine, "begin")
        def _on_begin(conn):
            conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.info.get("write") else "BEGIN")
    else:
        engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)
    return engine


def get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = make_engine(database_url())
    return _engine


def configure(url: str):
    """Point the app at another database (used by the tests). Returns the new engine."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = make_engine(url)
    return _engine


@contextmanager
def read():
    with get_engine().connect() as conn:
        yield conn


@contextmanager
def write():
    """A single atomic transaction. Rolled back entirely if anything raises."""
    with get_engine().connect() as conn:
        conn.info["write"] = True
        try:
            with conn.begin():
                yield conn
        finally:
            conn.info.pop("write", None)


def lock_clause() -> str:
    """Row lock suffix for read-modify-write queries (SQLite is already serialised by BEGIN IMMEDIATE)."""
    return "" if is_sqlite() else " FOR UPDATE"


# --- schema management -------------------------------------------------------------------------------


def _move_legacy_sqlite(engine) -> Path | None:
    path = sqlite_path(engine)
    if path is None or not path.exists():
        return None
    engine.dispose()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.legacy-{stamp}{path.suffix}")
    shutil.move(path, backup)
    for suffix in ("-wal", "-shm"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            shutil.move(extra, Path(str(backup) + suffix))
    return backup


def init_db(engine=None) -> None:
    """Create the schema if needed. Safe to call any number of times."""
    global legacy_backup
    engine = engine or get_engine()
    existing = set(inspect(engine).get_table_names())
    if existing and "schema_info" not in existing:
        # Database from the first prototype (different schema): keep it aside, start fresh.
        if engine.dialect.name != "sqlite":
            raise RuntimeError("The database contains tables from an unknown schema. Use an empty database.")
        legacy_backup = _move_legacy_sqlite(engine)
    metadata.create_all(engine)
    with write() as conn:
        row = conn.execute(text("SELECT value FROM schema_info WHERE key = 'version'")).first()
        if row is None:
            conn.execute(schema_info.insert().values(key="version", value=str(SCHEMA_VERSION)))
        elif int(row[0]) > SCHEMA_VERSION:
            raise RuntimeError(f"Database schema v{row[0]} is newer than this app (v{SCHEMA_VERSION}).")


def reset_db() -> None:
    """Drop every table and recreate an empty schema."""
    engine = get_engine()
    metadata.drop_all(engine)
    init_db(engine)


def integrity_report() -> list[str]:
    """Problems found by the database's own integrity checks (empty list = healthy)."""
    problems = []
    with read() as conn:
        if is_sqlite():
            result = conn.exec_driver_sql("PRAGMA integrity_check").scalar()
            if result != "ok":
                problems.append(f"integrity_check: {result}")
            for row in conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                problems.append(f"foreign key violation: {tuple(row)}")
        orphans = conn.execute(text("""
            SELECT COUNT(*) FROM work_items w
            WHERE w.parent_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM work_items p WHERE p.id = w.parent_id)
        """)).scalar()
        if orphans:
            problems.append(f"{orphans} work items point to a parent that does not exist")
    return problems


def sqlite_backup_bytes() -> bytes:
    """Consistent snapshot of the SQLite database (safe while other people are writing)."""
    path = sqlite_path()
    if path is None:
        raise RuntimeError("Backups as a file are only available for SQLite.")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "backup.db"
        src = sqlite3.connect(path)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return target.read_bytes()


def export_json() -> bytes:
    """Every table as JSON. Works on any database."""
    out = {"schema_version": SCHEMA_VERSION, "exported_at": now(), "tables": {}}
    with read() as conn:
        for table in metadata.sorted_tables:
            rows = conn.execute(table.select()).mappings().all()
            out["tables"][table.name] = [dict(r) for r in rows]
    return json.dumps(out, ensure_ascii=False, indent=1, default=str).encode("utf-8")
