"""Users must always be valid: required name, valid unique email, free-text team."""

import pytest

from boards import repository as repo
from boards.errors import NotFoundError, ValidationError


def test_create_user_normalises_input():
    user_id = repo.create_user("  Ana   Ferreira ", "  Ana.Ferreira@Example.COM ", "  Data   & AI  ")
    row = repo.list_users().set_index("id").loc[user_id]
    assert row["name"] == "Ana Ferreira"
    assert row["email"] == "ana.ferreira@example.com"
    assert row["team"] == "Data & AI"
    assert row["active"] == 1


@pytest.mark.parametrize("team", ["", "Platform", "Équipe Données 🚀", "Team with a very specific name 42"])
def test_team_is_free_text(team):
    user_id = repo.create_user("Someone", f"someone{abs(hash(team))}@example.com", team)
    assert repo.list_users().set_index("id").loc[user_id, "team"] == team


def test_team_too_long_is_rejected():
    with pytest.raises(ValidationError, match="Team is too long"):
        repo.create_user("Someone", "someone@example.com", "x" * 121)


@pytest.mark.parametrize("name", ["", "   ", "\t\n", None, "x" * 121])
def test_invalid_names_are_rejected(name):
    with pytest.raises(ValidationError):
        repo.create_user(name, "valid@example.com")
    assert repo.user_count() == 0


@pytest.mark.parametrize("email", [
    "", "   ", "plainaddress", "a@", "@example.com", "a b@example.com", "a@example", "a@@example.com",
    "a@exa mple.com", None, "x" * 250 + "@example.com",
])
def test_invalid_emails_are_rejected(email):
    with pytest.raises(ValidationError):
        repo.create_user("Valid Name", email)
    assert repo.user_count() == 0


def test_duplicate_email_is_rejected_case_insensitively(user):
    with pytest.raises(ValidationError, match="already exists"):
        repo.create_user("Someone Else", "ALICE@example.com")
    assert repo.user_count() == 1


def test_non_text_values_are_rejected():
    with pytest.raises(ValidationError):
        repo.create_user(123, "valid@example.com")
    with pytest.raises(ValidationError):
        repo.create_user("Valid", "valid@example.com", team=["not", "text"])


def test_update_user_validates(user, other_user):
    repo.update_user(user, team="Data")
    assert repo.list_users().set_index("id").loc[user, "team"] == "Data"
    with pytest.raises(ValidationError, match="already exists"):
        repo.update_user(user, email="Bob@Example.com")
    with pytest.raises(ValidationError):
        repo.update_user(user, name="   ")
    with pytest.raises(ValidationError, match="Unknown user field"):
        repo.update_user(user, role="Admin")
    with pytest.raises(NotFoundError):
        repo.update_user(9999, name="Ghost")
    with pytest.raises(ValidationError):
        repo.update_user(user, active="maybe")


def test_last_active_user_cannot_be_deactivated_or_deleted(user):
    with pytest.raises(ValidationError, match="active"):
        repo.update_user(user, active=False)
    with pytest.raises(ValidationError, match="last user"):
        repo.delete_user(user)
    assert repo.user_count() == 1


def test_deleting_a_user_unassigns_their_work(user, other_user, make_item):
    item = make_item(assigned_to=other_user)
    repo.delete_user(other_user)
    assert repo.get_work_item(item)["assigned_to"] is None
    with pytest.raises(NotFoundError):
        repo.delete_user(other_user)


def test_inactive_user_cannot_get_new_work_but_keeps_existing(user, other_user, make_item):
    kept = make_item(assigned_to=other_user)
    fresh = make_item()
    repo.update_user(other_user, active=False)
    with pytest.raises(ValidationError, match="inactive"):
        repo.update_work_item(fresh, {"assigned_to": other_user}, user)
    # Editing another field of an item that is already theirs still works.
    repo.update_work_item(kept, {"assigned_to": other_user, "priority": 1}, user)
    assert repo.get_work_item(kept)["priority"] == 1


def test_list_teams_is_distinct_and_skips_empty(user, other_user):
    repo.create_user("Carol", "carol@example.com", "Platform")
    repo.create_user("Dan", "dan@example.com", "")
    assert repo.list_teams() == ["Mobile", "Platform"]
