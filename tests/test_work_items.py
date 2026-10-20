"""Work items must never be created or edited into an invalid state."""

import math

import pandas as pd
import pytest

from boards import config, repository as repo
from boards.errors import NotFoundError, ValidationError


def count_items() -> int:
    return len(repo.load_work_items()) + len(repo.list_deleted())


# --- creation -------------------------------------------------------------------------------------


def test_create_sets_sensible_defaults(user):
    item_id = repo.create_work_item({"type": "User Story", "title": "  Pay   with card  "}, user)
    item = repo.get_work_item(item_id)
    assert item["title"] == "Pay with card"
    assert item["state"] == "New"
    assert item["reason"] == config.STATE_REASONS["New"]
    assert item["priority"] == 2
    assert item["value_area"] == "Business"
    assert item["created_by"] == user
    assert item["rev"] == 1
    assert repo.list_history(item_id)["field"].tolist() == ["created"]


def test_new_items_go_to_the_bottom_of_the_backlog(make_item):
    first, second = make_item(title="First"), make_item(title="Second")
    assert repo.get_work_item(second)["backlog_rank"] > repo.get_work_item(first)["backlog_rank"]


@pytest.mark.parametrize("item_type", [None, "", "Story", "epic", "Initiative", 5])
def test_invalid_type_is_rejected(user, item_type):
    with pytest.raises(ValidationError, match="type"):
        repo.create_work_item({"type": item_type, "title": "x"}, user)
    assert count_items() == 0


@pytest.mark.parametrize("title", [None, "", "   ", "\n\t", "x" * 256, 42])
def test_invalid_titles_are_rejected(user, title):
    with pytest.raises(ValidationError):
        repo.create_work_item({"type": "Task", "title": title}, user)
    assert count_items() == 0


def test_missing_title_is_rejected(user):
    with pytest.raises(ValidationError, match="Title is required"):
        repo.create_work_item({"type": "Task"}, user)


def test_title_control_characters_and_newlines_are_cleaned(make_item):
    item_id = make_item(title="Line one\nline\x00 two\x07")
    assert repo.get_work_item(item_id)["title"] == "Line one line two"


@pytest.mark.parametrize("item_type,state", [("Bug", "Removed"), ("Task", "Resolved"), ("Epic", "Done"),
                                             ("User Story", "active"), ("Feature", "")])
def test_state_must_be_valid_for_the_type(user, item_type, state):
    with pytest.raises(ValidationError, match="not a valid state"):
        repo.create_work_item({"type": item_type, "title": "x", "state": state}, user)


@pytest.mark.parametrize("priority", [0, 5, -1, "high", "2", True, 2.5, None])
def test_invalid_priority_is_rejected(user, priority):
    with pytest.raises(ValidationError, match="Priority"):
        repo.create_work_item({"type": "Task", "title": "x", "priority": priority}, user)


@pytest.mark.parametrize("field", ["story_points", "effort", "original_estimate", "remaining_work", "completed_work"])
@pytest.mark.parametrize("value", [-1, -0.5, math.inf, -math.inf, "abc", True, 10**9])
def test_invalid_numbers_are_rejected(user, field, value):
    with pytest.raises(ValidationError):
        repo.create_work_item({"type": "Task", "title": "x", field: value}, user)
    assert count_items() == 0


def test_nan_means_empty(user):
    # Empty cells in pandas/data_editor arrive as NaN: they clear the field instead of storing NaN.
    item_id = repo.create_work_item({"type": "Task", "title": "x", "story_points": math.nan}, user)
    assert repo.get_work_item(item_id)["story_points"] is None


def test_business_value_must_be_a_whole_number(user):
    with pytest.raises(ValidationError, match="whole number"):
        repo.create_work_item({"type": "Epic", "title": "x", "business_value": 2.5}, user)
    item_id = repo.create_work_item({"type": "Epic", "title": "x", "business_value": 30}, user)
    assert repo.get_work_item(item_id)["business_value"] == 30


@pytest.mark.parametrize("value", ["2026/01/01", "01-02-2026", "2026-02-30", "tomorrow", 20260101])
def test_invalid_dates_are_rejected(user, value):
    with pytest.raises(ValidationError):
        repo.create_work_item({"type": "Epic", "title": "x", "start_date": value}, user)


def test_target_date_cannot_be_before_start_date(user, make_item):
    with pytest.raises(ValidationError, match="target date"):
        repo.create_work_item({"type": "Epic", "title": "x", "start_date": "2026-05-10",
                               "target_date": "2026-05-01"}, user)
    epic = make_item("Epic", start_date="2026-05-01")
    with pytest.raises(ValidationError, match="target date"):
        repo.update_work_item(epic, {"target_date": "2026-04-01"}, user)


@pytest.mark.parametrize("field,value", [("assigned_to", 999), ("iteration_id", 999), ("area_id", 999),
                                         ("parent_id", 999), ("severity", "Huge"), ("value_area", "Fun")])
def test_references_and_choices_must_exist(user, field, value):
    with pytest.raises(ValidationError):
        repo.create_work_item({"type": "Bug", "title": "x", field: value}, user)
    assert count_items() == 0


def test_unknown_fields_are_rejected(user, make_item):
    with pytest.raises(ValidationError, match="Unknown field"):
        repo.create_work_item({"type": "Task", "title": "x", "owner": "me"}, user)
    item = make_item()
    with pytest.raises(ValidationError, match="Unknown field"):
        repo.update_work_item(item, {"rev": 99}, user)


def test_long_text_is_rejected(user):
    with pytest.raises(ValidationError, match="too long"):
        repo.create_work_item({"type": "Task", "title": "x", "description": "a" * (config.MAX_TEXT + 1)}, user)


def test_description_keeps_line_breaks(make_item):
    item_id = make_item(description="Step 1\nStep 2\n\n- bullet")
    assert repo.get_work_item(item_id)["description"] == "Step 1\nStep 2\n\n- bullet"


def test_task_remaining_work_defaults_to_the_estimate(make_item):
    task = make_item("Task", original_estimate=6)
    assert repo.get_work_item(task)["remaining_work"] == 6


# --- updates ------------------------------------------------------------------------------------------


def test_update_records_history_and_revision(user, other_user, make_item, iteration):
    item_id = make_item()
    changed = repo.update_work_item(item_id, {"title": "Renamed", "assigned_to": other_user,
                                              "iteration_id": iteration, "priority": 1}, user)
    assert set(changed) == {"title", "assigned_to", "iteration_id", "priority"}
    item = repo.get_work_item(item_id)
    assert item["rev"] == 2
    hist = repo.list_history(item_id).set_index("field")
    assert hist.loc["assigned_to", "new_value"] == "Bob Example"
    assert hist.loc["iteration_id", "new_value"] == "Sprint 1"
    assert hist.loc["title", "old_value"] == "User Story item"


def test_update_without_changes_is_a_no_op(user, make_item):
    item_id = make_item(story_points=3)
    assert repo.update_work_item(item_id, {"story_points": 3.0, "title": " User Story item "}, user) == []
    assert repo.get_work_item(item_id)["rev"] == 1


def test_failed_update_writes_nothing(user, make_item):
    item_id = make_item()
    with pytest.raises(ValidationError):
        repo.update_work_item(item_id, {"title": "New title", "priority": 7}, user)
    item = repo.get_work_item(item_id)
    assert item["title"] == "User Story item" and item["rev"] == 1


def test_state_changes_maintain_timestamps_and_reason(user, make_item):
    item_id = make_item()
    repo.change_state(item_id, "Active", user)
    item = repo.get_work_item(item_id)
    assert item["activated_at"] and not item["closed_at"]
    repo.change_state(item_id, "Closed", user)
    item = repo.get_work_item(item_id)
    assert item["closed_at"] and item["resolved_at"]
    assert item["reason"] == config.STATE_REASONS["Closed"]
    repo.change_state(item_id, "Active", user)
    item = repo.get_work_item(item_id)
    assert item["closed_at"] is None and item["resolved_at"] is None
    assert item["reason"] == "Reactivated"


def test_closing_a_task_zeroes_remaining_work(user, make_item):
    task = make_item("Task", original_estimate=8)
    repo.change_state(task, "Closed", user)
    assert repo.get_work_item(task)["remaining_work"] == 0


def test_operations_on_missing_items_fail_cleanly(user):
    with pytest.raises(NotFoundError):
        repo.update_work_item(12345, {"title": "x"}, user)
    with pytest.raises(NotFoundError):
        repo.add_comment(12345, user, "hello")
    with pytest.raises(NotFoundError):
        repo.delete_work_item(12345, user)


# --- tags -------------------------------------------------------------------------------------------------


def test_tags_are_trimmed_and_deduplicated(user):
    item_id = repo.create_work_item({"type": "Task", "title": "x"}, user,
                                    tags=[" Backend ", "backend", "UX", "", None, "ux  "])
    assert repo.get_work_item(item_id)["tag_list"] == ["Backend", "UX"]
    assert len(repo.list_tags()) == 2


@pytest.mark.parametrize("tag", ["a,b", "x" * 61])
def test_invalid_tags_are_rejected(user, tag):
    with pytest.raises(ValidationError):
        repo.create_work_item({"type": "Task", "title": "x"}, user, tags=[tag])
    assert count_items() == 0


def test_tag_changes_are_recorded(user, make_item):
    item_id = make_item(tags=["one"])
    assert repo.update_work_item(item_id, {}, user, tags=["one", "two"]) == ["tags"]
    assert repo.update_work_item(item_id, {}, user, tags=["TWO", "One"]) == []  # same tags, different case
    hist = repo.list_history(item_id)
    assert hist[hist["field"] == "tags"]["new_value"].tolist() == ["one, two"]


def test_tag_rename_cannot_clash(make_item):
    make_item(tags=["alpha", "beta"])
    tags = repo.list_tags().set_index("name")["id"]
    with pytest.raises(ValidationError, match="already exists"):
        repo.rename_tag(int(tags["alpha"]), "BETA")


# --- automation rules ------------------------------------------------------------------------------------


def test_parent_is_activated_when_a_child_starts(user, make_item):
    feature = make_item("Feature")
    story = make_item(parent_id=feature)
    repo.change_state(story, "Active", user)
    assert repo.get_work_item(feature)["state"] == "Active"


def test_parent_is_closed_when_all_children_are_done_if_enabled(user, make_item):
    repo.set_setting("auto_close_parent", True)
    story = make_item()
    tasks = [make_item("Task", parent_id=story) for _ in range(2)]
    repo.change_state(tasks[0], "Closed", user)
    assert repo.get_work_item(story)["state"] == "Active"
    repo.change_state(tasks[1], "Removed", user)
    assert repo.get_work_item(story)["state"] == "Closed"


def test_automation_can_be_turned_off(user, make_item):
    repo.set_setting("auto_activate_parent", False)
    feature = make_item("Feature")
    story = make_item(parent_id=feature)
    repo.change_state(story, "Active", user)
    assert repo.get_work_item(feature)["state"] == "New"


# --- recycle bin -----------------------------------------------------------------------------------------


def test_soft_delete_restore_and_purge(user, make_item):
    parent = make_item("Feature")
    child = make_item(parent_id=parent)
    repo.add_comment(parent, user, "note")
    with pytest.raises(ValidationError, match="recycle bin"):
        repo.purge_work_item(parent)
    repo.delete_work_item(parent, user)
    assert parent not in repo.load_work_items()["id"].tolist()
    assert pd.isna(repo.load_work_items().set_index("id").loc[child, "parent_id"])
    with pytest.raises(NotFoundError):
        repo.update_work_item(parent, {"title": "x"}, user)
    repo.restore_work_item(parent, user)
    assert repo.get_work_item(child)["parent_id"] == parent
    with pytest.raises(ValidationError, match="not in the recycle bin"):
        repo.restore_work_item(parent, user)
    repo.delete_work_item(parent, user)
    repo.purge_work_item(parent)
    assert repo.get_work_item(parent) is None
    assert repo.list_comments(parent).empty and repo.list_history(parent).empty
    assert repo.get_work_item(child)["parent_id"] is None


# --- comments ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", ["", "   ", None, "x" * (config.MAX_COMMENT + 1)])
def test_invalid_comments_are_rejected(user, make_item, body):
    item_id = make_item()
    with pytest.raises(ValidationError):
        repo.add_comment(item_id, user, body)
    assert repo.list_comments(item_id).empty


def test_comment_bumps_revision(user, make_item):
    item_id = make_item()
    repo.add_comment(item_id, user, "Looks good\n\n- yes")
    assert repo.get_work_item(item_id)["rev"] == 2
    assert repo.list_comments(item_id)["body"].tolist() == ["Looks good\n\n- yes"]


# --- ordering and bulk -----------------------------------------------------------------------------------


def test_reorder_and_move_in_list(make_item):
    a, b, c = make_item(title="A"), make_item(title="B"), make_item(title="C")
    repo.reorder([c, a, b])
    order = repo.load_work_items().sort_values("backlog_rank")["id"].tolist()
    assert order == [c, a, b]
    repo.move_in_list(b, order, -1)
    assert repo.load_work_items().sort_values("backlog_rank")["id"].tolist() == [c, b, a]


def test_reorder_rejects_missing_items(make_item):
    a = make_item()
    with pytest.raises(NotFoundError):
        repo.reorder([a, 999])


def test_bulk_update_reports_items_that_fail(user, make_item):
    story = make_item()
    task = make_item("Task")
    ok, errors = repo.bulk_update([story, task, 999], {"state": "Resolved"}, user)
    assert ok == 1
    assert len(errors) == 2
    assert repo.get_work_item(story)["state"] == "Resolved"
    assert repo.get_work_item(task)["state"] == "New"


def test_move_item_changes_state_and_order_atomically(user, make_item):
    a, b = make_item(title="A"), make_item(title="B")
    repo.change_state(b, "Active", user)
    repo.move_item(a, user, state="Active", expected_state="New", order_ids=[b, a])
    items = repo.load_work_items().set_index("id")
    assert items.loc[a, "state"] == "Active"
    assert items.loc[b, "backlog_rank"] < items.loc[a, "backlog_rank"]


# --- home page ------------------------------------------------------------------------------------------


def test_updates_for_user_shows_other_peoples_changes_only(user, other_user, make_item):
    mine = make_item(assigned_to=user)
    theirs = make_item(by=other_user, assigned_to=other_user)
    repo.update_work_item(mine, {"priority": 1}, user)                 # my own change: hidden
    repo.change_state(mine, "Active", other_user)                      # someone else's change: shown
    repo.add_comment(mine, other_user, "Picked this up with you")      # someone else's comment: shown
    repo.change_state(theirs, "Active", other_user)                    # not my item: hidden
    updates = repo.updates_for_user(user)
    assert set(updates["item_id"]) == {mine}
    assert set(updates["kind"]) == {"change", "comment"}
    assert "priority" not in set(updates["field"].dropna())
    assert repo.updates_for_user(user, limit=1).shape[0] == 1
