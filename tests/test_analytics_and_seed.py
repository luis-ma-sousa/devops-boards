"""Metrics are computed correctly, and the demo data obeys every rule."""

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import text

from boards import analytics as an, config, db, seed, repository as repo


def test_working_days_skip_weekends():
    days = an.working_days(date(2026, 1, 2), date(2026, 1, 12))  # Fri .. Mon
    assert [d.isoformat() for d in days] == ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
                                             "2026-01-08", "2026-01-09", "2026-01-12"]


def test_field_as_of_rebuilds_past_values():
    items = pd.DataFrame({"id": [1, 2], "state": ["Closed", "Active"],
                          "created_at": ["2026-01-01 09:00:00", "2026-01-03 09:00:00"]})
    history = pd.DataFrame({
        "work_item_id": [1, 1], "field": ["state", "state"],
        "old_value": ["New", "Active"], "new_value": ["Active", "Closed"],
        "changed_at": ["2026-01-02 10:00:00", "2026-01-04 10:00:00"],
    })
    assert an.field_as_of(items, history, "state", "2026-01-01 23:59:59").to_dict() == {1: "New"}
    assert an.field_as_of(items, history, "state", "2026-01-03 23:59:59").to_dict() == {1: "Active", 2: "Active"}
    assert an.field_as_of(items, history, "state", "2026-01-05 23:59:59").to_dict() == {1: "Closed", 2: "Active"}


def test_burndown_and_velocity(user, make_item, iteration):
    a = make_item(story_points=5, iteration_id=iteration)
    make_item(story_points=3, iteration_id=iteration)
    repo.change_state(a, "Closed", user)
    sprint = repo.list_iterations().iloc[0].to_dict()
    items, history = repo.load_work_items(), repo.load_history()
    burn = an.burndown(items, history, sprint, "points", today=date(2026, 1, 20))
    ideal = burn[burn["series"] == "Ideal"]["value"].tolist()
    assert ideal[0] >= ideal[-1] == 0
    vel = an.velocity(items, repo.list_iterations(), today=date(2026, 1, 20)).set_index("status")["points"]
    assert vel["Completed"] == 5 and vel["Incomplete"] == 3


def test_rollup_progress_uses_descendants(user, make_item):
    epic = make_item("Epic")
    feature = make_item("Feature", parent_id=epic)
    done = make_item(story_points=8, parent_id=feature)
    make_item(story_points=2, parent_id=feature)
    repo.change_state(done, "Closed", user)
    row = an.rollup_progress(repo.load_work_items(), "Epic").iloc[0]
    assert row["items"] == 2 and row["done_items"] == 1
    assert row["progress"] == pytest.approx(0.8)


def test_demo_data_is_valid():
    seed.load_demo()
    assert db.integrity_report() == []
    items = repo.load_work_items()
    assert len(items) > 100
    for row in items.itertuples():
        assert row.state in config.STATES[row.type], row
        assert row.title.strip() == row.title and row.title
        if row.type == "Task" and row.state == "Closed":
            assert (row.remaining_work or 0) == 0
    with db.read() as conn:
        links = conn.execute(text("SELECT COUNT(*) FROM work_item_links")).scalar()
    assert links == len(seed.LINKS)
    # No item is its own ancestor.
    parents = dict(zip(items["id"], items["parent_id"]))
    for item_id in parents:
        seen, current = set(), parents[item_id]
        while not pd.isna(current):
            assert current not in seen and current != item_id
            seen.add(current)
            current = parents.get(current, pd.NA)
