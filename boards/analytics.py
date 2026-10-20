"""Sprint metrics: burndown, velocity (for planning) and epic progress.

The value of a field on a past day is rebuilt from the ``history`` table: the value at time T
is the ``old_value`` of the first change after T, or the current value if nothing changed since.
"""

from datetime import date, timedelta

import pandas as pd

from . import config

REQUIREMENT_TYPES = ["User Story", "Bug"]


def _ts(day: date) -> str:
    return f"{day.isoformat()} 23:59:59"


def field_as_of(items: pd.DataFrame, history: pd.DataFrame, field: str, ts: str) -> pd.Series:
    """Value of ``field`` per item (index = id) at time ``ts``. Items created later are excluded."""
    existing = items[items["created_at"] <= ts]
    values = existing.set_index("id")[field].astype(object)
    later = history[(history["field"] == field) & (history["changed_at"] > ts)]
    if not later.empty and not values.empty:
        first_old = later.groupby("work_item_id")["old_value"].first()
        idx = first_old.index.intersection(values.index)
        values.loc[idx] = first_old.loc[idx]
    return values


def working_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def burndown(items: pd.DataFrame, history: pd.DataFrame, iteration: dict, metric: str,
             today: date | None = None) -> pd.DataFrame:
    """Daily (working days) remaining work in an iteration, plus the ideal line.

    metric: "points" (Story Points of User Stories/Bugs), "hours" (remaining work of Tasks)
            or "count" (number of open User Stories/Bugs).
    """
    today = today or date.today()
    start, end = iteration["start_date"], iteration["end_date"]
    if not start or not end:
        return pd.DataFrame(columns=["date", "series", "value"])
    sprint = items[items["iteration_id"] == iteration["id"]]
    if metric == "hours":
        scope, field = sprint[sprint["type"] == "Task"], "remaining_work"
    else:
        scope, field = sprint[sprint["type"].isin(REQUIREMENT_TYPES)], "story_points"

    days = working_days(start, end)
    rows = []
    for day in days:
        if day > today:
            break
        ts = _ts(day)
        states = field_as_of(scope, history, "state", ts)
        open_ids = states[~states.isin(config.INACTIVE_STATES)].index
        if metric == "count":
            value = float(len(open_ids))
        else:
            values = pd.to_numeric(field_as_of(scope, history, field, ts), errors="coerce").fillna(0)
            value = float(values.loc[values.index.intersection(open_ids)].sum())
        rows.append({"date": pd.Timestamp(day), "series": "Remaining", "value": value})

    if days:
        initial = rows[0]["value"] if rows else 0.0
        n = max(len(days) - 1, 1)
        for i, day in enumerate(days):
            rows.append({"date": pd.Timestamp(day), "series": "Ideal", "value": round(initial * (1 - i / n), 2)})
    return pd.DataFrame(rows)


def velocity(items: pd.DataFrame, iterations: pd.DataFrame, today: date | None = None,
             last: int = 6) -> pd.DataFrame:
    """Completed vs. incomplete Story Points in the most recent iterations that have started."""
    today = today or date.today()
    its = iterations.dropna(subset=["start_date"])
    its = its[its["start_date"] <= today].tail(last)
    reqs = items[items["type"].isin(REQUIREMENT_TYPES) & (items["state"] != "Removed")]
    rows = []
    for it in its.itertuples():
        scope = reqs[reqs["iteration_id"] == it.id]
        points = scope["story_points"].fillna(0)
        done = float(points[scope["state"] == "Closed"].sum())
        rows.append({"iteration": it.name, "order": it.start_date, "status": "Completed", "points": done})
        rows.append({"iteration": it.name, "order": it.start_date, "status": "Incomplete",
                     "points": float(points.sum()) - done})
    return pd.DataFrame(rows, columns=["iteration", "order", "status", "points"])


def rollup_progress(items: pd.DataFrame, parent_type: str) -> pd.DataFrame:
    """Progress of Epics/Features: share of requirement-level descendants that are closed (points or count)."""
    parents = items[(items["type"] == parent_type) & (items["state"] != "Removed")]
    by_parent = items.groupby("parent_id")
    children_of = {pid: grp for pid, grp in by_parent}

    def descendants(pid):
        out = []
        stack = [pid]
        while stack:
            current = stack.pop()
            kids = children_of.get(current)
            if kids is None:
                continue
            out.append(kids)
            stack.extend(kids["id"].tolist())
        return pd.concat(out) if out else items.iloc[0:0]

    rows = []
    for p in parents.itertuples():
        desc = descendants(p.id)
        reqs = desc[desc["type"].isin(REQUIREMENT_TYPES) & (desc["state"] != "Removed")]
        total_pts = float(reqs["story_points"].fillna(0).sum())
        done_pts = float(reqs.loc[reqs["state"] == "Closed", "story_points"].fillna(0).sum())
        rows.append({
            "id": p.id, "title": p.title, "state": p.state, "assigned_name": p.assigned_name,
            "items": len(reqs), "done_items": int((reqs["state"] == "Closed").sum()),
            "points": total_pts, "done_points": done_pts,
            "progress": (done_pts / total_pts) if total_pts else (
                (reqs["state"] == "Closed").mean() if len(reqs) else 0.0),
            "target_date": p.target_date,
        })
    return pd.DataFrame(rows)
