"""Several people using the app at the same time must not lose or corrupt each other's work."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from boards import db, repository as repo
from boards.errors import ConflictError, ValidationError


def run_parallel(fn, args, workers=8):
    errors, results = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in [pool.submit(fn, *a) for a in args]:
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - collected and asserted on
                errors.append(exc)
    return results, errors


# --- optimistic concurrency (two people editing the same ticket) -------------------------------------------


def test_editing_the_same_field_raises_a_conflict(user, other_user, make_item):
    item_id = make_item(title="Original")
    base = repo.get_work_item(item_id)
    repo.update_work_item(item_id, {"title": "Alice's title"}, user, base={"title": base["title"]})
    with pytest.raises(ConflictError) as info:
        repo.update_work_item(item_id, {"title": "Bob's title"}, other_user, base={"title": base["title"]})
    assert info.value.fields == ["title"]
    assert repo.get_work_item(item_id)["title"] == "Alice's title"


def test_edits_to_different_fields_are_merged(user, other_user, make_item):
    item_id = make_item(title="Original", priority=2)
    base = repo.get_work_item(item_id)
    repo.update_work_item(item_id, {"title": "New title"}, user, base={"title": base["title"]})
    repo.update_work_item(item_id, {"priority": 1}, other_user, base={"priority": base["priority"]})
    item = repo.get_work_item(item_id)
    assert item["title"] == "New title" and item["priority"] == 1


def test_making_the_same_change_twice_is_not_a_conflict(user, other_user, make_item):
    item_id = make_item()
    repo.update_work_item(item_id, {"state": "Active"}, user, base={"state": "New"})
    assert repo.update_work_item(item_id, {"state": "Active"}, other_user, base={"state": "New"}) == []


def test_tag_conflicts_are_detected(user, other_user, make_item):
    item_id = make_item(tags=["a"])
    repo.update_work_item(item_id, {}, user, tags=["a", "b"], base_tags=["a"])
    with pytest.raises(ConflictError):
        repo.update_work_item(item_id, {}, other_user, tags=["a", "c"], base_tags=["a"])


def test_board_move_detects_stale_cards(user, other_user, make_item):
    item_id = make_item()
    repo.change_state(item_id, "Active", user, expected_state="New")
    with pytest.raises(ConflictError):
        repo.change_state(item_id, "Resolved", other_user, expected_state="New")
    assert repo.get_work_item(item_id)["state"] == "Active"


# --- real parallel writes ----------------------------------------------------------------------------------


def test_parallel_creates_all_succeed(user):
    def create(i):
        return repo.create_work_item({"type": "Task", "title": f"Task {i}"}, user, tags=["shared", f"t{i % 3}"])

    ids, errors = run_parallel(create, [(i,) for i in range(80)])
    assert errors == []
    assert len(set(ids)) == 80
    assert len(repo.load_work_items()) == 80
    assert set(repo.list_tags()["name"]) == {"shared", "t0", "t1", "t2"}
    assert db.integrity_report() == []


def test_parallel_moves_of_the_same_card_have_one_winner(user, make_item):
    item_id = make_item()
    targets = ["Active", "Resolved", "Closed", "Removed"] * 3

    def move(state):
        repo.change_state(item_id, state, user, expected_state="New")
        return state

    winners, errors = run_parallel(move, [(s,) for s in targets])
    final = repo.get_work_item(item_id)["state"]
    # Only moves to the winning state can succeed (repeating the same move is harmless).
    assert set(winners) == {final}
    assert len(errors) == len(targets) - targets.count(final)
    assert all(isinstance(e, ConflictError) for e in errors)


def test_parallel_signups_with_the_same_email(user):
    _, errors = run_parallel(lambda i: repo.create_user(f"Person {i}", "same@example.com"), [(i,) for i in range(10)])
    assert len(errors) == 9
    assert all(isinstance(e, ValidationError) for e in errors)
    assert (repo.list_users()["email"] == "same@example.com").sum() == 1


def test_parallel_tag_creation_with_different_case(make_item, user):
    items = [make_item(title=f"Item {i}") for i in range(12)]
    _, errors = run_parallel(lambda i, name: repo.update_work_item(i, {}, user, tags=[name]),
                             [(item, name) for item, name in zip(items, ["Urgent", "urgent", "URGENT"] * 4)])
    assert errors == []
    assert len(repo.list_tags()) == 1


def test_parallel_comments_and_edits_keep_every_write(user, make_item):
    item_id = make_item()

    def work(i):
        if i % 2:
            repo.add_comment(item_id, user, f"comment {i}")
        else:
            repo.update_work_item(item_id, {"story_points": float(i)}, user)

    _, errors = run_parallel(work, [(i,) for i in range(30)])
    assert errors == []
    assert len(repo.list_comments(item_id)) == 15
    history = repo.list_history(item_id)
    assert (history["field"] == "story_points").sum() >= 1
    assert db.integrity_report() == []
