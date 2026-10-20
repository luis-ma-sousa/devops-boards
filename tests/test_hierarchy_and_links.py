"""Parent/child hierarchy and the other link types (related, sibling, predecessor, duplicate)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from boards import db, repository as repo
from boards.errors import NotFoundError, ValidationError


def kinds(item_id) -> dict:
    links = repo.get_links(item_id)
    return {(row.kind, int(row.id)) for row in links.itertuples()}


# --- hierarchy -----------------------------------------------------------------------------------------


def test_item_cannot_be_its_own_parent(user, make_item):
    story = make_item()
    with pytest.raises(ValidationError, match="own parent"):
        repo.update_work_item(story, {"parent_id": story}, user)


def test_parent_must_exist_and_not_be_deleted(user, make_item):
    feature = make_item("Feature")
    repo.delete_work_item(feature, user)
    with pytest.raises(ValidationError, match="does not exist"):
        make_item(parent_id=feature)
    with pytest.raises(ValidationError, match="does not exist"):
        make_item(parent_id=4242)


@pytest.mark.parametrize("depth", [2, 3, 6])
def test_cycles_are_rejected_at_any_depth(user, make_item, depth):
    chain = [make_item("Epic", title="root")]
    for i in range(depth - 1):
        chain.append(make_item("Feature", title=f"level {i}", parent_id=chain[-1]))
    with pytest.raises(ValidationError, match="cycle"):
        repo.update_work_item(chain[0], {"parent_id": chain[-1]}, user)
    assert repo.get_work_item(chain[0])["parent_id"] is None


def test_flexible_hierarchy_allows_any_parent_type(user, make_item):
    task = make_item("Task")
    epic = make_item("Epic", parent_id=task)          # unusual, but allowed when not strict
    story = make_item("User Story", parent_id=epic)
    assert repo.get_work_item(story)["parent_id"] == epic


def test_strict_hierarchy_enforces_agile_rules(user, make_item):
    repo.set_setting("strict_hierarchy", True)
    epic, feature = make_item("Epic"), make_item("Feature")
    story = make_item("User Story", parent_id=feature)
    with pytest.raises(ValidationError, match="strict"):
        make_item("User Story", parent_id=epic)
    with pytest.raises(ValidationError, match="strict"):
        repo.update_work_item(feature, {"parent_id": story}, user)
    make_item("Bug", parent_id=story)
    make_item("Task", parent_id=story)


def test_parent_candidates_exclude_self_and_descendants(make_item):
    epic = make_item("Epic")
    feature = make_item("Feature", parent_id=epic)
    story = make_item(parent_id=feature)
    other = make_item("Feature", title="Other")
    candidates = set(repo.parent_candidates("Epic", exclude_id=epic)["id"])
    assert epic not in candidates and feature not in candidates and story not in candidates
    assert other in candidates
    repo.set_setting("strict_hierarchy", True)
    assert set(repo.parent_candidates("User Story")["id"]) == {feature, other}
    assert repo.parent_candidates("Epic").empty


def test_ancestors_are_listed_top_down(make_item):
    epic = make_item("Epic")
    feature = make_item("Feature", parent_id=epic)
    story = make_item(parent_id=feature)
    assert [a["id"] for a in repo.get_ancestors(story)] == [epic, feature]


# --- links -----------------------------------------------------------------------------------------------


def test_related_link_is_visible_from_both_sides(user, make_item):
    a, b = make_item(title="A"), make_item(title="B")
    repo.add_link(a, "related", b, user)
    assert kinds(a) == {("related", b)}
    assert kinds(b) == {("related", a)}
    assert repo.list_history(a)["field"].tolist()[0] == "links"
    assert repo.list_history(b)["field"].tolist()[0] == "links"


@pytest.mark.parametrize("kind", ["related", "sibling"])
def test_symmetric_links_cannot_be_duplicated_in_either_direction(user, make_item, kind):
    a, b = make_item(), make_item()
    repo.add_link(a, kind, b, user)
    with pytest.raises(ValidationError, match="already linked"):
        repo.add_link(b, kind, a, user)
    with pytest.raises(ValidationError, match="already linked"):
        repo.add_link(a, kind, b, user)


def test_predecessor_and_successor_are_two_views_of_one_link(user, make_item):
    design, build = make_item(title="Design"), make_item(title="Build")
    repo.add_link(build, "predecessor", design, user)
    assert kinds(build) == {("predecessor", design)}
    assert kinds(design) == {("successor", build)}
    with pytest.raises(ValidationError):
        repo.add_link(design, "predecessor", build, user)  # reverse would be a 2-step cycle


def test_circular_dependencies_are_rejected(user, make_item):
    a, b, c = make_item(title="A"), make_item(title="B"), make_item(title="C")
    repo.add_link(a, "successor", b, user)   # a before b
    repo.add_link(b, "successor", c, user)   # b before c
    with pytest.raises(ValidationError, match="circular"):
        repo.add_link(c, "successor", a, user)


def test_duplicate_rules(user, make_item):
    original, copy, other = make_item(title="Original"), make_item(title="Copy"), make_item(title="Other")
    repo.add_link(copy, "duplicate_of", original, user)
    assert kinds(original) == {("duplicate", copy)}
    with pytest.raises(ValidationError, match="already marked as a duplicate"):
        repo.add_link(copy, "duplicate_of", other, user)
    with pytest.raises(ValidationError):
        repo.add_link(original, "duplicate_of", copy, user)


@pytest.mark.parametrize("kind", ["related", "parent", "child", "successor"])
def test_items_cannot_link_to_themselves(user, make_item, kind):
    a = make_item()
    with pytest.raises(ValidationError, match="itself"):
        repo.add_link(a, kind, a, user)


def test_invalid_link_requests(user, make_item):
    a, b = make_item(), make_item()
    with pytest.raises(ValidationError, match="Unknown link type"):
        repo.add_link(a, "blocks", b, user)
    with pytest.raises(ValidationError, match="Choose"):
        repo.add_link(a, "related", None, user)
    with pytest.raises(NotFoundError):
        repo.add_link(a, "related", 9999, user)
    repo.delete_work_item(b, user)
    with pytest.raises(NotFoundError):
        repo.add_link(a, "related", b, user)


def test_parent_and_child_links(user, make_item):
    feature, story, other_feature = make_item("Feature"), make_item(), make_item("Feature", title="Other")
    repo.add_link(feature, "child", story, user)
    assert ("parent", feature) in kinds(story)
    assert ("child", story) in kinds(feature)
    with pytest.raises(ValidationError, match="already has a parent"):
        repo.add_link(other_feature, "child", story, user)
    repo.add_link(story, "parent", other_feature, user)  # changing your own parent is allowed
    assert repo.get_work_item(story)["parent_id"] == other_feature


def test_remove_link(user, make_item):
    a, b = make_item(), make_item()
    repo.add_link(a, "sibling", b, user)
    link_id = int(repo.get_links(a)["link_id"].iloc[0])
    repo.remove_link(link_id, user)
    assert repo.get_links(a).empty and repo.get_links(b).empty
    with pytest.raises(NotFoundError):
        repo.remove_link(link_id, user)


def test_links_to_deleted_items_are_hidden_and_purged(user, make_item):
    a, b = make_item(), make_item()
    repo.add_link(a, "related", b, user)
    repo.delete_work_item(b, user)
    assert repo.get_links(a).empty
    repo.restore_work_item(b, user)
    assert kinds(a) == {("related", b)}
    repo.delete_work_item(b, user)
    repo.purge_work_item(b)
    with db.read() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM work_item_links")).scalar() == 0


def test_database_rejects_invalid_links_directly(make_item):
    a, b = make_item(), make_item()
    with pytest.raises(IntegrityError):
        with db.write() as conn:
            conn.execute(db.work_item_links.insert().values(source_id=a, target_id=a, link_type="related",
                                                            created_at="2026-01-01 00:00:00"))
    with pytest.raises(IntegrityError):
        with db.write() as conn:
            conn.execute(db.work_item_links.insert().values(source_id=a, target_id=b, link_type="blocks",
                                                            created_at="2026-01-01 00:00:00"))
