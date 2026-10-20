"""Smoke tests of the Streamlit app itself, plus escaping of user content in the UI."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from boards import config, seed, ui
from boards import repository as repo

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["views/dashboard.py", "views/board.py", "views/backlog.py", "views/sprints.py", "views/queries.py",
         "views/users.py", "views/settings.py"]


@pytest.fixture
def sqlite_only(backend):
    if backend != "sqlite":
        pytest.skip("UI smoke tests run once, on SQLite")


def test_onboarding_rejects_invalid_users_and_creates_valid_ones(sqlite_only):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.title[0].value.startswith("🗂️ Welcome")
    name, email, team = at.text_input[0], at.text_input[1], at.text_input[2]
    name.input("Valid Person")
    email.input("broken-email")
    at.button[0].click().run()
    assert any("valid email" in e.value for e in at.error)
    assert repo.user_count() == 0
    at.text_input[1].input("valid@example.com")
    at.text_input[2].input("Any team at all")
    at.button[0].click().run()
    assert not at.exception
    assert repo.list_users()["team"].tolist() == ["Any team at all"]


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_demo_data(sqlite_only, page):
    seed.load_demo()
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.switch_page(page).run()
    assert not at.exception, [e.message for e in at.exception]


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_with_an_empty_project(sqlite_only, user, page):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.switch_page(page).run()
    assert not at.exception, [e.message for e in at.exception]


def test_html_helpers_escape_user_content():
    evil = '<img src=x onerror="alert(1)">'
    for html in (ui.person(evil), ui.state_badge(evil), ui.avatar(evil), ui.esc(evil)):
        assert "<img" not in html
    assert ui.md_escape("*bold* $x$ [link](y)") == r"\*bold\* \$x\$ \[link\](y)"


def test_card_payload_is_plain_data(user, make_item):
    feature = make_item("Feature", title="<b>Parent</b>")
    story = make_item(title="<script>alert(1)</script>", parent_id=feature, story_points=3, tags=["a"])
    row = repo.load_work_items().set_index("id").loc[story].to_dict() | {"id": story}
    card = ui.card_payload(row, show_parent=True)
    # The component inserts text with textContent, so the payload keeps the raw text (no HTML building).
    assert card["title"] == "<script>alert(1)</script>"
    assert card["allowed"] == config.STATES["User Story"]
    assert card["meta"][0] == "SP 3" and "<b>Parent</b>" in card["meta"][-1]
    assert card["tags"] == ["a"]
