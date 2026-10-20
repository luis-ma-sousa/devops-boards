"""Data access and business rules.

Every public function validates its input and runs in a single transaction, so a failure never
leaves partial writes behind. Errors meant for the user are raised as ``ValidationError``,
``NotFoundError`` or ``ConflictError`` (see ``errors.py``).
"""

import json
import math
import re
from datetime import date, datetime

import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError

from . import config, db
from .db import now
from .errors import ConflictError, NotFoundError, ValidationError

# Fields that can be set when creating or updating a work item.
EDITABLE_FIELDS = [
    "title", "description", "acceptance_criteria", "state", "reason", "priority", "severity",
    "value_area", "story_points", "effort", "business_value", "original_estimate",
    "remaining_work", "completed_work", "assigned_to", "iteration_id", "area_id", "parent_id",
    "backlog_rank", "start_date", "target_date",
]
NUMBER_FIELDS = ["story_points", "effort", "original_estimate", "remaining_work", "completed_work"]
NO_HISTORY_FIELDS = {"reason", "backlog_rank"}
_UNSET = object()

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- helpers --------------------------------------------------------------------------------------


def _sql(sql: str, *expanding: str):
    stmt = text(sql)
    return stmt.bindparams(*(bindparam(name, expanding=True) for name in expanding)) if expanding else stmt


def _df(conn, sql: str, params: dict | None = None, expanding=()) -> pd.DataFrame:
    return pd.read_sql_query(_sql(sql, *expanding), conn, params=params or {})


def _clean(value):
    """Convert pandas/numpy/widget values into plain Python values."""
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()  # numpy scalar
    if value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _same(a, b) -> bool:
    a, b = _clean(a), _clean(b)
    if isinstance(a, str):
        a = a.strip()
    if isinstance(b, str):
        b = b.strip()
    if a in ("", None) and b in ("", None):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return float(a) == float(b)
    return a == b


def _text(value, label: str, *, max_len: int, required: bool = False, single_line: bool = True) -> str:
    value = _clean(value)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be text.")
    value = _CONTROL.sub("", value)
    value = " ".join(value.split()) if single_line else value.strip()
    if required and not value:
        raise ValidationError(f"{label} is required.")
    if len(value) > max_len:
        raise ValidationError(f"{label} is too long (maximum {max_len} characters).")
    return value


def _number(value, label: str, *, integer: bool = False, max_value: float = config.MAX_ESTIMATE):
    value = _clean(value)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} must be a number.")
    if math.isnan(value) or math.isinf(value):
        raise ValidationError(f"{label} must be a finite number.")
    if value < 0:
        raise ValidationError(f"{label} cannot be negative.")
    if value > max_value:
        raise ValidationError(f"{label} is too large (maximum {max_value:g}).")
    if integer:
        if float(value) != int(value):
            raise ValidationError(f"{label} must be a whole number.")
        return int(value)
    return float(value)


def _date(value, label: str):
    value = _clean(value)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        raise ValidationError(f"{label} must be a date (YYYY-MM-DD).")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{label} is not a valid date.") from None
    return value


def _id(value, label: str):
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != int(value):
        raise ValidationError(f"{label} must be an id.")
    return int(value)


def _upsert(conn, table, values: dict, keys: list[str]):
    dialect = postgresql if conn.dialect.name == "postgresql" else sqlite
    stmt = dialect.insert(table).values(**values)
    stmt = stmt.on_conflict_do_update(index_elements=keys, set_={k: v for k, v in values.items() if k not in keys})
    conn.execute(stmt)


def _insert_ignore(conn, table, values: dict):
    dialect = postgresql if conn.dialect.name == "postgresql" else sqlite
    conn.execute(dialect.insert(table).values(**values).on_conflict_do_nothing())


def _int_cols(df: pd.DataFrame, cols) -> pd.DataFrame:
    for col in cols:
        if col in df.columns:
            df[col] = df[col].astype("Int64")
    return df


# --- settings ---------------------------------------------------------------------------------------


def _get_setting(conn, key):
    row = conn.execute(text("SELECT value FROM settings WHERE key = :k"), {"k": key}).first()
    return json.loads(row[0]) if row else config.DEFAULT_SETTINGS.get(key)


def get_setting(key):
    with db.read() as conn:
        return _get_setting(conn, key)


def set_setting(key: str, value) -> None:
    if key not in config.DEFAULT_SETTINGS:
        raise ValidationError(f"Unknown setting: {key}")
    if key == "project_name":
        value = _text(value, "Project name", max_len=80, required=True)
    elif key == "wip_limits":
        if not isinstance(value, dict):
            raise ValidationError("WIP limits must be a mapping.")
        clean = {}
        for level, limits in value.items():
            if level not in config.BACKLOG_LEVELS or not isinstance(limits, dict):
                raise ValidationError(f"Unknown backlog level: {level}")
            clean[level] = {}
            for state, limit in limits.items():
                if state not in config.BOARD_COLUMNS:
                    raise ValidationError(f"Unknown board column: {state}")
                limit = _number(limit, "WIP limit", integer=True, max_value=999)
                if limit:
                    clean[level][state] = limit
        value = clean
    elif not isinstance(value, bool):
        raise ValidationError(f"{key} must be true or false.")
    with db.write() as conn:
        _upsert(conn, db.settings, {"key": key, "value": json.dumps(value)}, ["key"])


# --- users --------------------------------------------------------------------------------------------


def list_users(active_only: bool = False) -> pd.DataFrame:
    sql = "SELECT * FROM users" + (" WHERE active = 1" if active_only else "") + " ORDER BY lower(name), id"
    with db.read() as conn:
        return _df(conn, sql)


def user_count() -> int:
    with db.read() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM users")).scalar()


def list_teams() -> list[str]:
    with db.read() as conn:
        rows = conn.execute(text("SELECT DISTINCT team FROM users WHERE team <> '' ORDER BY team")).all()
    return [r[0] for r in rows]


def _validate_user(conn, name, email, team, user_id=None):
    name = _text(name, "Name", max_len=config.MAX_NAME, required=True)
    email = _text(email, "Email", max_len=254, required=True).lower()
    if not _EMAIL.match(email):
        raise ValidationError("Enter a valid email address, e.g. name@company.com.")
    team = _text(team, "Team", max_len=config.MAX_NAME)
    clash = conn.execute(text("SELECT id FROM users WHERE email = :e AND id <> :id"),
                         {"e": email, "id": user_id or -1}).first()
    if clash:
        raise ValidationError(f"A user with the email {email} already exists.")
    return name, email, team


def create_user(name: str, email: str, team: str = "") -> int:
    try:
        with db.write() as conn:
            name, email, team = _validate_user(conn, name, email, team)
            result = conn.execute(db.users.insert().values(
                name=name, email=email, team=team, active=1, created_at=now()))
            return result.inserted_primary_key[0]
    except IntegrityError:
        raise ValidationError(f"A user with the email {email} already exists.") from None


def update_user(user_id: int, **fields) -> None:
    unknown = set(fields) - {"name", "email", "team", "active"}
    if unknown:
        raise ValidationError(f"Unknown user field: {', '.join(sorted(unknown))}")
    try:
        with db.write() as conn:
            cur = conn.execute(text("SELECT * FROM users WHERE id = :id"), {"id": user_id}).mappings().first()
            if cur is None:
                raise NotFoundError(f"User {user_id} does not exist.")
            merged = {**cur, **{k: _clean(v) for k, v in fields.items()}}
            name, email, team = _validate_user(conn, merged["name"], merged["email"], merged["team"], user_id)
            active = merged["active"]
            if active not in (0, 1, True, False):
                raise ValidationError("Active must be true or false.")
            active = int(bool(active))
            if not active and cur["active"]:
                others = conn.execute(text("SELECT COUNT(*) FROM users WHERE active = 1 AND id <> :id"),
                                      {"id": user_id}).scalar()
                if not others:
                    raise ValidationError("At least one user must stay active.")
            conn.execute(db.users.update().where(db.users.c.id == user_id).values(
                name=name, email=email, team=team, active=active))
    except IntegrityError:
        raise ValidationError("A user with that email already exists.") from None


def delete_user(user_id: int) -> None:
    with db.write() as conn:
        if conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id}).first() is None:
            raise NotFoundError(f"User {user_id} does not exist.")
        if conn.execute(text("SELECT COUNT(*) FROM users")).scalar() <= 1:
            raise ValidationError("You cannot delete the last user.")
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def user_workload() -> pd.DataFrame:
    with db.read() as conn:
        return _df(conn, """
            SELECT u.id, u.name, u.email, u.team, u.active,
                   COUNT(w.id) AS open_items,
                   COALESCE(SUM(CASE WHEN w.type IN ('User Story', 'Bug') THEN w.story_points END), 0) AS open_points,
                   COALESCE(SUM(CASE WHEN w.type = 'Task' THEN w.remaining_work END), 0) AS remaining_work
            FROM users u
            LEFT JOIN work_items w
                   ON w.assigned_to = u.id AND w.deleted_at IS NULL AND w.state NOT IN ('Closed', 'Removed')
            GROUP BY u.id, u.name, u.email, u.team, u.active
            ORDER BY lower(u.name), u.id
        """)


# --- iterations -----------------------------------------------------------------------------------------


def list_iterations() -> pd.DataFrame:
    with db.read() as conn:
        df = _df(conn, "SELECT * FROM iterations ORDER BY start_date IS NULL, start_date, name")
    for col in ("start_date", "end_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date
    return df


def current_iteration(iterations: pd.DataFrame | None = None, today: date | None = None):
    """Iteration containing today; otherwise the next one; otherwise the last one."""
    df = list_iterations() if iterations is None else iterations
    df = df.dropna(subset=["start_date", "end_date"])
    if df.empty:
        return None
    today = today or date.today()
    current = df[(df.start_date <= today) & (df.end_date >= today)]
    if not current.empty:
        return current.iloc[0].to_dict()
    future = df[df.start_date > today]
    if not future.empty:
        return future.iloc[0].to_dict()
    return df.iloc[-1].to_dict()


def _validate_iteration(conn, name, start, end, goal, iteration_id=None):
    name = _text(name, "Iteration name", max_len=config.MAX_NAME, required=True)
    start, end = _date(start, "Start date"), _date(end, "End date")
    if start and end and end < start:
        raise ValidationError("The end date must be on or after the start date.")
    goal = _text(goal, "Sprint goal", max_len=500)
    clash = conn.execute(text("SELECT id FROM iterations WHERE lower(name) = lower(:n) AND id <> :id"),
                         {"n": name, "id": iteration_id or -1}).first()
    if clash:
        raise ValidationError(f"An iteration called {name} already exists.")
    return name, start, end, goal


def create_iteration(name, start_date=None, end_date=None, goal="") -> int:
    try:
        with db.write() as conn:
            name, start, end, goal = _validate_iteration(conn, name, start_date, end_date, goal)
            return conn.execute(db.iterations.insert().values(
                name=name, start_date=start, end_date=end, goal=goal)).inserted_primary_key[0]
    except IntegrityError:
        raise ValidationError(f"An iteration called {name} already exists.") from None


def update_iteration(iteration_id: int, **fields) -> None:
    unknown = set(fields) - {"name", "start_date", "end_date", "goal"}
    if unknown:
        raise ValidationError(f"Unknown iteration field: {', '.join(sorted(unknown))}")
    try:
        with db.write() as conn:
            cur = conn.execute(text("SELECT * FROM iterations WHERE id = :id"), {"id": iteration_id}).mappings().first()
            if cur is None:
                raise NotFoundError(f"Iteration {iteration_id} does not exist.")
            merged = {**cur, **fields}
            name, start, end, goal = _validate_iteration(conn, merged["name"], merged["start_date"],
                                                         merged["end_date"], merged["goal"], iteration_id)
            conn.execute(db.iterations.update().where(db.iterations.c.id == iteration_id).values(
                name=name, start_date=start, end_date=end, goal=goal))
    except IntegrityError:
        raise ValidationError("An iteration with that name already exists.") from None


def delete_iteration(iteration_id: int) -> None:
    with db.write() as conn:
        conn.execute(text("DELETE FROM iterations WHERE id = :id"), {"id": iteration_id})


def get_capacity(iteration_id: int) -> pd.DataFrame:
    with db.read() as conn:
        return _df(conn, """
            SELECT u.id AS user_id, u.name, u.team,
                   COALESCE(c.hours_per_day, 6) AS hours_per_day,
                   COALESCE(c.days_off, 0) AS days_off
            FROM users u
            LEFT JOIN capacity c ON c.user_id = u.id AND c.iteration_id = :it
            WHERE u.active = 1
            ORDER BY lower(u.name), u.id
        """, {"it": iteration_id})


def save_capacity(iteration_id: int, rows: pd.DataFrame) -> None:
    with db.write() as conn:
        if conn.execute(text("SELECT 1 FROM iterations WHERE id = :id"), {"id": iteration_id}).first() is None:
            raise NotFoundError(f"Iteration {iteration_id} does not exist.")
        for row in rows.to_dict("records"):
            hours = _number(row.get("hours_per_day"), "Hours per day", max_value=24) or 0.0
            days_off = _number(row.get("days_off"), "Days off", integer=True, max_value=366) or 0
            _upsert(conn, db.capacity, {"iteration_id": iteration_id, "user_id": _id(row["user_id"], "User"),
                                        "hours_per_day": hours, "days_off": days_off},
                    ["iteration_id", "user_id"])


# --- areas and tags -----------------------------------------------------------------------------------------


def list_areas() -> pd.DataFrame:
    with db.read() as conn:
        return _df(conn, """
            SELECT a.id, a.name,
                   (SELECT COUNT(*) FROM work_items w WHERE w.area_id = a.id AND w.deleted_at IS NULL) AS items
            FROM areas a ORDER BY lower(a.name)
        """)


def _area_name(conn, name, area_id=None) -> str:
    name = _text(name, "Area name", max_len=config.MAX_NAME, required=True)
    clash = conn.execute(text("SELECT id FROM areas WHERE lower(name) = lower(:n) AND id <> :id"),
                         {"n": name, "id": area_id or -1}).first()
    if clash:
        raise ValidationError(f"The area {name} already exists.")
    return name


def create_area(name: str) -> int:
    try:
        with db.write() as conn:
            return conn.execute(db.areas.insert().values(name=_area_name(conn, name))).inserted_primary_key[0]
    except IntegrityError:
        raise ValidationError(f"The area {name} already exists.") from None


def rename_area(area_id: int, name: str) -> None:
    try:
        with db.write() as conn:
            conn.execute(db.areas.update().where(db.areas.c.id == area_id).values(name=_area_name(conn, name, area_id)))
    except IntegrityError:
        raise ValidationError(f"The area {name} already exists.") from None


def delete_area(area_id: int) -> None:
    with db.write() as conn:
        conn.execute(text("DELETE FROM areas WHERE id = :id"), {"id": area_id})


def list_tags() -> pd.DataFrame:
    with db.read() as conn:
        return _df(conn, """
            SELECT t.id, t.name, COUNT(w.id) AS items
            FROM tags t
            LEFT JOIN work_item_tags wt ON wt.tag_id = t.id
            LEFT JOIN work_items w ON w.id = wt.work_item_id AND w.deleted_at IS NULL
            GROUP BY t.id, t.name ORDER BY lower(t.name)
        """)


def _tag_name(value) -> str:
    name = _text(value, "Tag", max_len=config.MAX_TAG, required=True)
    if "," in name:
        raise ValidationError("Tags cannot contain commas.")
    return name


def rename_tag(tag_id: int, name: str) -> None:
    name = _tag_name(name)
    with db.write() as conn:
        clash = conn.execute(text("SELECT id FROM tags WHERE name_key = :k AND id <> :id"),
                             {"k": name.lower(), "id": tag_id}).first()
        if clash:
            raise ValidationError(f"The tag {name} already exists.")
        conn.execute(db.tags.update().where(db.tags.c.id == tag_id).values(name=name, name_key=name.lower()))


def delete_tag(tag_id: int) -> None:
    with db.write() as conn:
        conn.execute(text("DELETE FROM tags WHERE id = :id"), {"id": tag_id})


def _normalise_tags(names) -> list[str]:
    seen, out = set(), []
    for raw in names or []:
        if raw is None or not str(raw).strip():
            continue
        name = _tag_name(raw)
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return sorted(out, key=str.lower)


def _current_tags(conn, item_id) -> list[str]:
    rows = conn.execute(text("""
        SELECT t.name FROM work_item_tags wt JOIN tags t ON t.id = wt.tag_id WHERE wt.work_item_id = :id
    """), {"id": item_id}).all()
    return sorted((r[0] for r in rows), key=str.lower)


def _set_tags(conn, item_id: int, names: list[str]) -> None:
    conn.execute(text("DELETE FROM work_item_tags WHERE work_item_id = :id"), {"id": item_id})
    for name in names:
        _insert_ignore(conn, db.tags, {"name": name, "name_key": name.lower()})
        tag_id = conn.execute(text("SELECT id FROM tags WHERE name_key = :k"), {"k": name.lower()}).scalar()
        _insert_ignore(conn, db.work_item_tags, {"work_item_id": item_id, "tag_id": tag_id})


# --- work items: reading --------------------------------------------------------------------------------------

_BASE_SELECT = """
    SELECT w.*,
           u.name  AS assigned_name,
           u.team  AS assigned_team,
           cb.name AS created_by_name,
           i.name  AS iteration_name,
           a.name  AS area_name,
           p.title AS parent_title,
           p.type  AS parent_type,
           (SELECT COUNT(*) FROM work_items c
             WHERE c.parent_id = w.id AND c.deleted_at IS NULL AND c.state <> 'Removed') AS child_count,
           (SELECT COUNT(*) FROM work_items c
             WHERE c.parent_id = w.id AND c.deleted_at IS NULL AND c.state = 'Closed') AS child_done
    FROM work_items w
    LEFT JOIN users u       ON u.id = w.assigned_to
    LEFT JOIN users cb      ON cb.id = w.created_by
    LEFT JOIN iterations i  ON i.id = w.iteration_id
    LEFT JOIN areas a       ON a.id = w.area_id
    LEFT JOIN work_items p  ON p.id = w.parent_id AND p.deleted_at IS NULL
"""
_INT_COLUMNS = ["assigned_to", "created_by", "iteration_id", "area_id", "parent_id", "business_value"]


def _query_items(conn, where: str = "w.deleted_at IS NULL", params: dict | None = None) -> pd.DataFrame:
    df = _df(conn, f"{_BASE_SELECT} WHERE {where} ORDER BY w.backlog_rank, w.id", params)
    if df.empty:
        df["tags"] = pd.Series(dtype=str)
        return _int_cols(df, _INT_COLUMNS)
    tag_rows = _df(conn, """
        SELECT wt.work_item_id, t.name FROM work_item_tags wt JOIN tags t ON t.id = wt.tag_id
        WHERE wt.work_item_id IN :ids
    """, {"ids": [int(i) for i in df["id"]]}, expanding=("ids",))
    tag_map = tag_rows.groupby("work_item_id")["name"].agg(lambda s: ", ".join(sorted(s, key=str.lower)))
    df["tags"] = df["id"].map(tag_map).fillna("").astype(str)
    df = _int_cols(df, _INT_COLUMNS)
    # A parent in the recycle bin counts as no parent.
    df.loc[df["parent_title"].isna(), "parent_id"] = pd.NA
    return df


def load_work_items() -> pd.DataFrame:
    with db.read() as conn:
        return _query_items(conn)


def list_deleted() -> pd.DataFrame:
    with db.read() as conn:
        return _query_items(conn, "w.deleted_at IS NOT NULL")


def get_work_item(item_id: int) -> dict | None:
    with db.read() as conn:
        df = _query_items(conn, "w.id = :id", {"id": int(item_id)})
    if df.empty:
        return None
    item = {k: None if not isinstance(v, (list, dict)) and pd.isna(v) else v
            for k, v in df.iloc[0].to_dict().items()}
    item["tag_list"] = [t for t in (item.get("tags") or "").split(", ") if t]
    return item


def get_children(item_id: int) -> pd.DataFrame:
    with db.read() as conn:
        return _query_items(conn, "w.deleted_at IS NULL AND w.parent_id = :id", {"id": int(item_id)})


def get_same_parent(item_id: int) -> pd.DataFrame:
    """Items that share this item's parent (derived siblings)."""
    with db.read() as conn:
        parent = conn.execute(text("SELECT parent_id FROM work_items WHERE id = :id"), {"id": item_id}).scalar()
        if parent is None:
            return _query_items(conn, "1 = 0")
        return _query_items(conn, "w.deleted_at IS NULL AND w.parent_id = :p AND w.id <> :id",
                            {"p": parent, "id": item_id})


def get_ancestors(item_id: int) -> list[dict]:
    """Chain of parents from the top (e.g. Epic) down to the direct parent."""
    chain = []
    with db.read() as conn:
        current = conn.execute(text("SELECT parent_id FROM work_items WHERE id = :id"), {"id": item_id}).mappings().first()
        seen = {item_id}
        while current and current["parent_id"] and current["parent_id"] not in seen:
            row = conn.execute(text("""
                SELECT id, type, title, state, parent_id FROM work_items WHERE id = :id AND deleted_at IS NULL
            """), {"id": current["parent_id"]}).mappings().first()
            if not row:
                break
            chain.append(dict(row))
            seen.add(row["id"])
            current = row
    return list(reversed(chain))


def parent_candidates(item_type: str, exclude_id: int | None = None) -> pd.DataFrame:
    """Items that may become the parent of an item of this type (respects strict hierarchy)."""
    with db.read() as conn:
        strict = _get_setting(conn, "strict_hierarchy")
        types = config.AGILE_PARENTS.get(item_type, []) if strict else config.WORK_ITEM_TYPES
        if not types:
            return pd.DataFrame(columns=["id", "type", "title", "state"])
        df = _df(conn, """
            SELECT id, type, title, state FROM work_items
            WHERE deleted_at IS NULL AND state <> 'Removed' AND type IN :types AND id <> :ex
            ORDER BY backlog_rank, id
        """, {"types": list(types), "ex": exclude_id or -1}, expanding=("types",))
    if exclude_id:
        df = df[~df["id"].isin(_descendant_ids(exclude_id))]
    order = {t: i for i, t in enumerate(config.WORK_ITEM_TYPES)}
    return df.sort_values("type", key=lambda s: s.map(order), kind="stable")


def _descendant_ids(item_id: int) -> set[int]:
    with db.read() as conn:
        rows = conn.execute(text("SELECT id, parent_id FROM work_items WHERE parent_id IS NOT NULL")).all()
    children = {}
    for child, parent in rows:
        children.setdefault(parent, []).append(child)
    out, stack = set(), [item_id]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def list_comments(item_id: int) -> pd.DataFrame:
    with db.read() as conn:
        return _df(conn, """
            SELECT c.*, u.name AS user_name FROM comments c
            LEFT JOIN users u ON u.id = c.user_id
            WHERE c.work_item_id = :id ORDER BY c.created_at DESC, c.id DESC
        """, {"id": item_id})


def add_comment(item_id: int, user_id: int | None, body: str) -> int:
    body = _text(body, "Comment", max_len=config.MAX_COMMENT, required=True, single_line=False)
    with db.write() as conn:
        _lock_item(conn, item_id)
        ts = now()
        new_id = conn.execute(db.comments.insert().values(
            work_item_id=item_id, user_id=_existing_user(conn, user_id), body=body, created_at=ts,
        )).inserted_primary_key[0]
        conn.execute(text("UPDATE work_items SET updated_at = :ts, rev = rev + 1 WHERE id = :id"), {"ts": ts, "id": item_id})
        return new_id


def list_history(item_id: int) -> pd.DataFrame:
    with db.read() as conn:
        return _df(conn, """
            SELECT h.*, u.name AS user_name FROM history h
            LEFT JOIN users u ON u.id = h.user_id
            WHERE h.work_item_id = :id ORDER BY h.changed_at DESC, h.id DESC
        """, {"id": item_id})


def load_history(fields=None) -> pd.DataFrame:
    """History of items that are not in the recycle bin (for analytics)."""
    sql = """
        SELECT h.work_item_id, h.field, h.old_value, h.new_value, h.changed_at
        FROM history h JOIN work_items w ON w.id = h.work_item_id
        WHERE w.deleted_at IS NULL
    """
    with db.read() as conn:
        if fields:
            return _df(conn, sql + " AND h.field IN :fields ORDER BY h.changed_at, h.id",
                       {"fields": list(fields)}, expanding=("fields",))
        return _df(conn, sql + " ORDER BY h.changed_at, h.id")


def recent_activity(limit: int = 15) -> pd.DataFrame:
    with db.read() as conn:
        return _df(conn, """
            SELECT h.changed_at, h.field, h.old_value, h.new_value, u.name AS user_name,
                   w.id AS item_id, w.type, w.title
            FROM history h
            JOIN work_items w ON w.id = h.work_item_id AND w.deleted_at IS NULL
            LEFT JOIN users u ON u.id = h.user_id
            ORDER BY h.changed_at DESC, h.id DESC LIMIT :limit
        """, {"limit": int(limit)})


def updates_for_user(user_id: int, limit: int = 20) -> pd.DataFrame:
    """Changes and comments made by *other people* on items assigned to or created by this user."""
    params = {"u": user_id, "limit": int(limit)}
    with db.read() as conn:
        changes = _df(conn, """
            SELECT h.changed_at AS at, u.name AS who, 'change' AS kind, h.field, h.old_value, h.new_value,
                   w.id AS item_id, w.type, w.title, NULL AS body
            FROM history h
            JOIN work_items w ON w.id = h.work_item_id AND w.deleted_at IS NULL
            LEFT JOIN users u ON u.id = h.user_id
            WHERE (w.assigned_to = :u OR w.created_by = :u) AND (h.user_id IS NULL OR h.user_id <> :u)
            ORDER BY h.changed_at DESC, h.id DESC LIMIT :limit
        """, params)
        notes = _df(conn, """
            SELECT c.created_at AS at, u.name AS who, 'comment' AS kind, NULL AS field, NULL AS old_value,
                   NULL AS new_value, w.id AS item_id, w.type, w.title, c.body
            FROM comments c
            JOIN work_items w ON w.id = c.work_item_id AND w.deleted_at IS NULL
            LEFT JOIN users u ON u.id = c.user_id
            WHERE (w.assigned_to = :u OR w.created_by = :u) AND (c.user_id IS NULL OR c.user_id <> :u)
            ORDER BY c.created_at DESC, c.id DESC LIMIT :limit
        """, params)
    frames = [f for f in (changes, notes) if not f.empty]
    if not frames:
        return changes
    return pd.concat(frames, ignore_index=True).sort_values("at", ascending=False).head(limit)


def data_version() -> str:
    """Cheap fingerprint that changes whenever work items, links or comments change."""
    with db.read() as conn:
        a = conn.execute(text(
            "SELECT COUNT(*), COALESCE(SUM(rev), 0), COALESCE(MAX(updated_at), '') FROM work_items")).first()
        b = conn.execute(text("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM work_item_links")).first()
        c = conn.execute(text("SELECT COALESCE(MAX(id), 0) FROM comments")).scalar()
    return f"{tuple(a)}|{tuple(b)}|{c}"


# --- work items: validation ----------------------------------------------------------------------------------


def _lock_item(conn, item_id, include_deleted: bool = False):
    row = conn.execute(text(f"SELECT * FROM work_items WHERE id = :id{db.lock_clause()}"),
                       {"id": int(item_id)}).mappings().first()
    if row is None or (row["deleted_at"] and not include_deleted):
        raise NotFoundError(f"Work item {item_id} does not exist.")
    return dict(row)


def _existing_user(conn, user_id):
    user_id = _id(user_id, "User")
    if user_id is None:
        return None
    return user_id if conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id}).first() else None


def _validate_values(conn, item_type: str, values: dict, current: dict | None = None) -> dict:
    """Validate and normalise work item fields. Raises ValidationError on the first problem."""
    unknown = set(values) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationError(f"Unknown field: {', '.join(sorted(unknown))}")
    out = {}
    for field, raw in values.items():
        label = config.FIELD_LABELS.get(field, field)
        if field == "title":
            out[field] = _text(raw, label, max_len=config.MAX_TITLE, required=True)
        elif field in ("description", "acceptance_criteria"):
            out[field] = _text(raw, label, max_len=config.MAX_TEXT, single_line=False)
        elif field == "reason":
            out[field] = _text(raw, label, max_len=200)
        elif field == "state":
            state = _clean(raw)
            if state not in config.STATES[item_type]:
                raise ValidationError(f"{state!r} is not a valid state for a {item_type}.")
            out[field] = state
        elif field == "priority":
            priority = _clean(raw)
            if isinstance(priority, bool) or priority not in config.PRIORITIES:
                raise ValidationError("Priority must be 1, 2, 3 or 4.")
            out[field] = int(priority)
        elif field == "severity":
            severity = _clean(raw) or None
            if severity is not None and severity not in config.SEVERITIES:
                raise ValidationError(f"{severity!r} is not a valid severity.")
            out[field] = severity
        elif field == "value_area":
            value_area = _clean(raw) or "Business"
            if value_area not in config.VALUE_AREAS:
                raise ValidationError(f"{value_area!r} is not a valid value area.")
            out[field] = value_area
        elif field in NUMBER_FIELDS:
            out[field] = _number(raw, label)
        elif field == "business_value":
            out[field] = _number(raw, label, integer=True)
        elif field == "backlog_rank":
            rank = _clean(raw)
            if isinstance(rank, bool) or not isinstance(rank, (int, float)) or not math.isfinite(rank):
                raise ValidationError("Backlog rank must be a number.")
            out[field] = float(rank)
        elif field in ("start_date", "target_date"):
            out[field] = _date(raw, label)
        elif field == "assigned_to":
            user_id = _id(raw, label)
            if user_id is not None:
                row = conn.execute(text("SELECT active, name FROM users WHERE id = :id"), {"id": user_id}).first()
                if row is None:
                    raise ValidationError(f"User {user_id} does not exist.")
                if not row[0] and (current is None or current.get("assigned_to") != user_id):
                    raise ValidationError(f"{row[1]} is inactive and cannot be assigned new work.")
            out[field] = user_id
        elif field == "iteration_id":
            iteration_id = _id(raw, label)
            if iteration_id is not None and conn.execute(
                    text("SELECT 1 FROM iterations WHERE id = :id"), {"id": iteration_id}).first() is None:
                raise ValidationError(f"Iteration {iteration_id} does not exist.")
            out[field] = iteration_id
        elif field == "area_id":
            area_id = _id(raw, label)
            if area_id is not None and conn.execute(
                    text("SELECT 1 FROM areas WHERE id = :id"), {"id": area_id}).first() is None:
                raise ValidationError(f"Area {area_id} does not exist.")
            out[field] = area_id
        elif field == "parent_id":
            out[field] = _id(raw, label)
    start = out.get("start_date", (current or {}).get("start_date"))
    target = out.get("target_date", (current or {}).get("target_date"))
    if start and target and target < start:
        raise ValidationError("The target date must be on or after the start date.")
    return out


def _validate_parent(conn, item_id, item_type: str, parent_id) -> None:
    if parent_id is None:
        return
    if item_id is not None and parent_id == item_id:
        raise ValidationError("An item cannot be its own parent.")
    parent = conn.execute(text("SELECT id, type, parent_id, deleted_at FROM work_items WHERE id = :id"),
                          {"id": parent_id}).mappings().first()
    if parent is None or parent["deleted_at"]:
        raise ValidationError(f"The parent item {parent_id} does not exist.")
    if _get_setting(conn, "strict_hierarchy") and parent["type"] not in config.AGILE_PARENTS[item_type]:
        allowed = ", ".join(config.AGILE_PARENTS[item_type]) or "no parent"
        raise ValidationError(
            f"With the strict Agile hierarchy a {item_type} cannot have a {parent['type']} as parent "
            f"(allowed: {allowed}).")
    if item_id is not None:
        seen, current = set(), parent
        while current is not None and current["parent_id"] is not None:
            if current["parent_id"] == item_id:
                raise ValidationError("That parent would create a cycle (an item cannot be under its own child).")
            if current["parent_id"] in seen:
                break
            seen.add(current["parent_id"])
            current = conn.execute(text("SELECT id, parent_id FROM work_items WHERE id = :id"),
                                   {"id": current["parent_id"]}).mappings().first()


def _display_value(conn, field, value):
    """Human-readable value stored in the history."""
    if value is None:
        return None
    lookups = {"assigned_to": "users", "iteration_id": "iterations", "area_id": "areas"}
    if field in lookups:
        row = conn.execute(text(f"SELECT name FROM {lookups[field]} WHERE id = :id"), {"id": value}).first()
        return row[0] if row else str(value)
    if field == "parent_id":
        return _item_ref(conn, value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _item_ref(conn, item_id) -> str:
    row = conn.execute(text("SELECT type, title FROM work_items WHERE id = :id"), {"id": item_id}).first()
    return f"{row[0]} {item_id}: {row[1]}" if row else f"#{item_id}"


def _log(conn, item_id, user_id, field, old, new, ts):
    conn.execute(db.history.insert().values(
        work_item_id=item_id, user_id=user_id, field=field, old_value=old, new_value=new, changed_at=ts))


# --- work items: writing -------------------------------------------------------------------------------------


def create_work_item(data: dict, user_id: int | None, tags=None) -> int:
    with db.write() as conn:
        return _create(conn, data, user_id, tags)


def _create(conn, data: dict, user_id, tags=None, ts=None) -> int:
    data = dict(data)
    item_type = data.pop("type", None)
    if item_type not in config.WORK_ITEM_TYPES:
        raise ValidationError(f"Invalid work item type: {item_type!r}")
    if "title" not in data:
        raise ValidationError("Title is required.")
    values = _validate_values(conn, item_type, data)
    state = values.get("state") or "New"
    values["state"] = state
    if not values.get("reason"):
        values["reason"] = config.STATE_REASONS[state]
    _validate_parent(conn, None, item_type, values.get("parent_id"))
    tag_names = _normalise_tags(tags)
    user_id = _existing_user(conn, user_id)
    values.setdefault("priority", 2)
    values["value_area"] = values.get("value_area") or "Business"
    for field in ("description", "acceptance_criteria"):
        values[field] = values.get(field) or ""
    if item_type == "Task" and values.get("remaining_work") is None and values.get("original_estimate") is not None:
        values["remaining_work"] = values["original_estimate"]
    if item_type == "Task" and state == "Closed" and values.get("remaining_work") is not None:
        values["remaining_work"] = 0.0
    if values.get("backlog_rank") is None:
        max_rank = conn.execute(text("SELECT COALESCE(MAX(backlog_rank), 0) FROM work_items")).scalar()
        values["backlog_rank"] = float(max_rank) + 1000

    ts = ts or now()
    values.update(type=item_type, created_by=user_id, created_at=ts, updated_at=ts, rev=1)
    if state in ("Active", "Resolved", "Closed"):
        values["activated_at"] = ts
    if state in ("Resolved", "Closed"):
        values["resolved_at"] = ts
    if state == "Closed":
        values["closed_at"] = ts

    item_id = conn.execute(db.work_items.insert().values(**values)).inserted_primary_key[0]
    _log(conn, item_id, user_id, "created", None, item_type, ts)
    if tag_names:
        _set_tags(conn, item_id, tag_names)
    if state != "New":
        _apply_parent_rules(conn, item_id, user_id)
    return item_id


def update_work_item(item_id: int, changes: dict, user_id: int | None, tags=None,
                     base: dict | None = None, base_tags=None) -> list[str]:
    """Apply changes, record history and run the automation rules. Returns the changed fields.

    ``base`` holds the values the user started from. If someone else changed one of the same
    fields in the meantime, a ``ConflictError`` is raised instead of silently overwriting it.
    Fields the user did not touch are never written, so concurrent edits to *different*
    fields are merged.
    """
    with db.write() as conn:
        return _update(conn, item_id, changes, user_id, tags=tags, base=base, base_tags=base_tags)


def _update(conn, item_id, changes, user_id, tags=None, base=None, base_tags=None, ts=None) -> list[str]:
    cur = _lock_item(conn, item_id)
    item_type = cur["type"]
    ts = ts or now()
    user_id = _existing_user(conn, user_id)
    values = _validate_values(conn, item_type, changes, current=cur)

    diff = {f: v for f, v in values.items() if not _same(cur[f], v)}
    new_tags = _normalise_tags(tags) if tags is not None else None
    current_tags = _current_tags(conn, item_id) if new_tags is not None else None

    if base is not None:
        clashes = [f for f in diff if f in base and not _same(cur[f], base[f])]
        if clashes:
            labels = ", ".join(config.FIELD_LABELS.get(f, f) for f in clashes)
            raise ConflictError(f"Someone else changed {labels} on #{item_id} after you opened it. "
                                "Reload to see their version.", clashes)
    if new_tags is not None and base_tags is not None:
        def lower(names):
            return sorted(n.lower() for n in names)
        if lower(current_tags) != lower(base_tags) and lower(current_tags) != lower(new_tags):
            raise ConflictError(f"Someone else changed the tags on #{item_id} after you opened it. "
                                "Reload to see their version.", ["tags"])

    if "parent_id" in diff:
        _validate_parent(conn, item_id, item_type, diff["parent_id"])

    if "state" in diff:
        new_state, old_state = diff["state"], cur["state"]
        order = config.ALL_STATES
        backwards = order.index(new_state) < order.index(old_state) and new_state not in ("Removed", "New")
        if "reason" not in values or _same(values.get("reason"), cur["reason"]):
            diff["reason"] = "Reactivated" if backwards else config.STATE_REASONS[new_state]
        if new_state in ("Active", "Resolved", "Closed") and not cur["activated_at"]:
            diff["activated_at"] = ts
        if new_state in ("Resolved", "Closed") and not cur["resolved_at"]:
            diff["resolved_at"] = ts
        diff["closed_at"] = ts if new_state == "Closed" else None
        if new_state in ("New", "Active"):
            diff["resolved_at"] = None
        if new_state == "New":
            diff["activated_at"] = None
        remaining = diff.get("remaining_work", cur["remaining_work"])
        if item_type == "Task" and new_state == "Closed" and (remaining or 0) > 0:
            diff["remaining_work"] = 0.0

    changed = []
    if diff:
        conn.execute(db.work_items.update().where(db.work_items.c.id == item_id).values(
            **diff, updated_at=ts, rev=db.work_items.c.rev + 1))
        for field, value in diff.items():
            if field in NO_HISTORY_FIELDS or field.endswith("_at"):
                continue
            _log(conn, item_id, user_id, field,
                 _display_value(conn, field, cur[field]), _display_value(conn, field, value), ts)
            changed.append(field)

    if new_tags is not None and [t.lower() for t in current_tags] != [t.lower() for t in new_tags]:
        _set_tags(conn, item_id, new_tags)
        if not diff:
            conn.execute(text("UPDATE work_items SET updated_at = :ts, rev = rev + 1 WHERE id = :id"),
                         {"ts": ts, "id": item_id})
        _log(conn, item_id, user_id, "tags", ", ".join(current_tags) or None, ", ".join(new_tags) or None, ts)
        changed.append("tags")

    if "state" in diff:
        _apply_parent_rules(conn, item_id, user_id)
    return changed


def _apply_parent_rules(conn, item_id, user_id):
    """Azure Boards team rules: activate the parent / close the parent when all children are done."""
    child = conn.execute(text("SELECT parent_id, state FROM work_items WHERE id = :id"), {"id": item_id}).first()
    if not child or not child[0]:
        return
    parent = conn.execute(text("SELECT id, type, state FROM work_items WHERE id = :id AND deleted_at IS NULL"),
                          {"id": child[0]}).mappings().first()
    if not parent:
        return
    if (_get_setting(conn, "auto_activate_parent") and child[1] in ("Active", "Resolved", "Closed")
            and parent["state"] == "New"):
        _update(conn, parent["id"], {"state": "Active", "reason": "Child in progress"}, user_id)
        return
    if _get_setting(conn, "auto_close_parent") and child[1] in ("Closed", "Removed"):
        states = [r[0] for r in conn.execute(
            text("SELECT state FROM work_items WHERE parent_id = :id AND deleted_at IS NULL"), {"id": parent["id"]})]
        if (states and all(s in ("Closed", "Removed") for s in states) and "Closed" in states
                and parent["state"] not in ("Closed", "Removed")):
            _update(conn, parent["id"], {"state": "Closed", "reason": "All children are done"}, user_id)


def change_state(item_id: int, state: str, user_id: int | None, expected_state: str | None = None) -> None:
    base = {"state": expected_state} if expected_state else None
    update_work_item(item_id, {"state": state}, user_id, base=base)


def move_item(item_id: int, user_id: int | None, *, state=None, expected_state=None,
              parent_id=_UNSET, expected_parent=_UNSET, order_ids=None) -> None:
    """Board drag and drop: change state and/or parent and reorder, in one transaction."""
    changes, base = {}, {}
    if state is not None:
        changes["state"] = state
        if expected_state is not None:
            base["state"] = expected_state
    if parent_id is not _UNSET:
        changes["parent_id"] = parent_id
        if expected_parent is not _UNSET:
            base["parent_id"] = expected_parent
    with db.write() as conn:
        if changes:
            _update(conn, item_id, changes, user_id, base=base or None)
        else:
            _lock_item(conn, item_id)
        if order_ids:
            _reorder(conn, order_ids)


def bulk_update(item_ids, changes: dict, user_id: int | None) -> tuple[int, list[str]]:
    """Apply the same change to many items. Each item is its own transaction."""
    ok, errors = 0, []
    for item_id in item_ids:
        try:
            with db.write() as conn:
                _update(conn, int(item_id), changes, user_id)
            ok += 1
        except (ValidationError, NotFoundError, ConflictError) as exc:
            errors.append(f"#{item_id}: {exc}")
    return ok, errors


def _reorder(conn, ids) -> None:
    ids = [int(i) for i in ids]
    if len(ids) < 2 or len(set(ids)) != len(ids):
        return
    rows = conn.execute(_sql(f"SELECT id, backlog_rank FROM work_items WHERE id IN :ids{db.lock_clause()}", "ids"),
                        {"ids": ids}).all()
    if len(rows) != len(ids):
        raise NotFoundError("Some of the items to reorder no longer exist.")
    ranks = sorted(r[1] for r in rows)
    for i in range(1, len(ranks)):
        if ranks[i] <= ranks[i - 1]:
            ranks[i] = ranks[i - 1] + 0.001
    current = {r[0]: r[1] for r in rows}
    for item_id, rank in zip(ids, ranks):
        if current[item_id] != rank:
            conn.execute(text("UPDATE work_items SET backlog_rank = :r, rev = rev + 1 WHERE id = :id"),
                         {"r": rank, "id": item_id})


def reorder(ids_in_new_order) -> None:
    """Reorder a subset of the backlog by swapping their existing ranks."""
    with db.write() as conn:
        _reorder(conn, ids_in_new_order)


def move_in_list(item_id: int, ordered_ids, direction: int) -> None:
    """Move an item one position up (-1) or down (+1) within an ordered list."""
    ids = [int(i) for i in ordered_ids]
    if item_id not in ids:
        return
    pos = ids.index(item_id)
    new_pos = pos + direction
    if 0 <= new_pos < len(ids):
        ids[pos], ids[new_pos] = ids[new_pos], ids[pos]
        reorder(ids)


def delete_work_item(item_id: int, user_id: int | None) -> None:
    """Move to the recycle bin."""
    ts = now()
    with db.write() as conn:
        _lock_item(conn, item_id)
        conn.execute(text("UPDATE work_items SET deleted_at = :ts, updated_at = :ts, rev = rev + 1 WHERE id = :id"),
                     {"ts": ts, "id": item_id})
        _log(conn, item_id, _existing_user(conn, user_id), "deleted", None, None, ts)


def restore_work_item(item_id: int, user_id: int | None) -> None:
    ts = now()
    with db.write() as conn:
        row = _lock_item(conn, item_id, include_deleted=True)
        if not row["deleted_at"]:
            raise ValidationError(f"Work item {item_id} is not in the recycle bin.")
        conn.execute(text("UPDATE work_items SET deleted_at = NULL, updated_at = :ts, rev = rev + 1 WHERE id = :id"),
                     {"ts": ts, "id": item_id})
        _log(conn, item_id, _existing_user(conn, user_id), "restored", None, None, ts)


def purge_work_item(item_id: int) -> None:
    """Delete permanently. Only items already in the recycle bin can be purged."""
    with db.write() as conn:
        row = _lock_item(conn, item_id, include_deleted=True)
        if not row["deleted_at"]:
            raise ValidationError("Move the item to the recycle bin before deleting it permanently.")
        conn.execute(text("DELETE FROM work_items WHERE id = :id"), {"id": item_id})


# --- links -------------------------------------------------------------------------------------------------


def _stored_link(kind: str, item_id: int, other_id: int) -> tuple[str, int, int]:
    """Map a link kind seen from ``item_id`` to (stored type, source, target)."""
    if kind in ("related", "sibling"):
        a, b = sorted((item_id, other_id))
        return kind, a, b
    return {
        "successor": ("predecessor", item_id, other_id),
        "predecessor": ("predecessor", other_id, item_id),
        "duplicate_of": ("duplicate", item_id, other_id),
        "duplicate": ("duplicate", other_id, item_id),
    }[kind]


def _kind_from(link_type: str, source: int, item_id: int) -> str:
    if link_type in ("related", "sibling"):
        return link_type
    if link_type == "predecessor":
        return "successor" if source == item_id else "predecessor"
    return "duplicate_of" if source == item_id else "duplicate"


def _reaches(conn, start: int, goal: int, link_type: str) -> bool:
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(r[0] for r in conn.execute(
            text("SELECT target_id FROM work_item_links WHERE source_id = :n AND link_type = :t"),
            {"n": node, "t": link_type}))
    return False


def add_link(item_id: int, kind: str, other_id: int, user_id: int | None) -> None:
    """Link two work items. ``kind`` is one of ``config.LINK_KINDS``, seen from ``item_id``."""
    if kind not in config.LINK_KINDS:
        raise ValidationError(f"Unknown link type: {kind!r}")
    item_id, other_id = _id(item_id, "Work item"), _id(other_id, "Linked item")
    if other_id is None:
        raise ValidationError("Choose the item to link to.")
    if item_id == other_id:
        raise ValidationError("An item cannot be linked to itself.")
    with db.write() as conn:
        for locked in sorted((item_id, other_id)):  # consistent lock order avoids deadlocks
            _lock_item(conn, locked)
        user_id = _existing_user(conn, user_id)
        if kind == "parent":
            _update(conn, item_id, {"parent_id": other_id}, user_id)
            return
        if kind == "child":
            current_parent = conn.execute(text("SELECT parent_id FROM work_items WHERE id = :id"),
                                          {"id": other_id}).scalar()
            if current_parent not in (None, item_id):
                raise ValidationError(f"#{other_id} already has a parent (#{current_parent}). "
                                      "Change its parent instead.")
            _update(conn, other_id, {"parent_id": item_id}, user_id)
            return

        link_type, source, target = _stored_link(kind, item_id, other_id)
        exists = conn.execute(text("""
            SELECT 1 FROM work_item_links WHERE link_type = :t
               AND ((source_id = :a AND target_id = :b) OR (source_id = :b AND target_id = :a))
        """), {"t": link_type, "a": source, "b": target}).first()
        if exists:
            raise ValidationError(f"These items are already linked ({link_type}).")
        if link_type in ("predecessor", "duplicate") and _reaches(conn, target, source, link_type):
            raise ValidationError("That link would create a circular chain.")
        if link_type == "duplicate" and conn.execute(text(
                "SELECT 1 FROM work_item_links WHERE source_id = :s AND link_type = 'duplicate'"),
                {"s": source}).first():
            raise ValidationError(f"#{source} is already marked as a duplicate of another item.")
        ts = now()
        conn.execute(db.work_item_links.insert().values(
            source_id=source, target_id=target, link_type=link_type, created_by=user_id, created_at=ts))
        label = config.LINK_KINDS[kind]
        reverse = config.LINK_KINDS[_kind_from(link_type, source, other_id)]
        _log(conn, item_id, user_id, "links", None, f"{label}: {_item_ref(conn, other_id)}", ts)
        _log(conn, other_id, user_id, "links", None, f"{reverse}: {_item_ref(conn, item_id)}", ts)
        conn.execute(_sql("UPDATE work_items SET updated_at = :ts, rev = rev + 1 WHERE id IN :ids", "ids"),
                     {"ts": ts, "ids": [item_id, other_id]})


def remove_link(link_id: int, user_id: int | None) -> None:
    with db.write() as conn:
        row = conn.execute(text("SELECT * FROM work_item_links WHERE id = :id"), {"id": link_id}).mappings().first()
        if row is None:
            raise NotFoundError("That link no longer exists.")
        user_id = _existing_user(conn, user_id)
        conn.execute(text("DELETE FROM work_item_links WHERE id = :id"), {"id": link_id})
        ts = now()
        for me, other in ((row["source_id"], row["target_id"]), (row["target_id"], row["source_id"])):
            label = config.LINK_KINDS[_kind_from(row["link_type"], row["source_id"], me)]
            _log(conn, me, user_id, "links", f"{label}: {_item_ref(conn, other)}", None, ts)
        conn.execute(_sql("UPDATE work_items SET updated_at = :ts, rev = rev + 1 WHERE id IN :ids", "ids"),
                     {"ts": ts, "ids": [row["source_id"], row["target_id"]]})


def get_links(item_id: int) -> pd.DataFrame:
    """Every link of an item (parent, children and stored links), seen from the item."""
    rows = []
    with db.read() as conn:
        parent = conn.execute(text("""
            SELECT p.id, p.type, p.title, p.state, u.name AS assigned_name
            FROM work_items w JOIN work_items p ON p.id = w.parent_id AND p.deleted_at IS NULL
            LEFT JOIN users u ON u.id = p.assigned_to WHERE w.id = :id
        """), {"id": item_id}).mappings().first()
        if parent:
            rows.append({"kind": "parent", "link_id": None, **parent})
        for child in conn.execute(text("""
            SELECT c.id, c.type, c.title, c.state, u.name AS assigned_name
            FROM work_items c LEFT JOIN users u ON u.id = c.assigned_to
            WHERE c.parent_id = :id AND c.deleted_at IS NULL ORDER BY c.backlog_rank, c.id
        """), {"id": item_id}).mappings():
            rows.append({"kind": "child", "link_id": None, **child})
        for link in conn.execute(text("""
            SELECT l.id AS link_id, l.link_type, l.source_id, o.id, o.type, o.title, o.state,
                   u.name AS assigned_name
            FROM work_item_links l
            JOIN work_items o ON o.id = CASE WHEN l.source_id = :id THEN l.target_id ELSE l.source_id END
            LEFT JOIN users u ON u.id = o.assigned_to
            WHERE (l.source_id = :id OR l.target_id = :id) AND o.deleted_at IS NULL
            ORDER BY l.id
        """), {"id": item_id}).mappings():
            rows.append({"kind": _kind_from(link["link_type"], link["source_id"], item_id),
                         "link_id": link["link_id"], "id": link["id"], "type": link["type"],
                         "title": link["title"], "state": link["state"], "assigned_name": link["assigned_name"]})
    df = pd.DataFrame(rows, columns=["kind", "link_id", "id", "type", "title", "state", "assigned_name"])
    df["label"] = df["kind"].map(config.LINK_KINDS)
    return df
