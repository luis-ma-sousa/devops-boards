"""Boards: a simplified Azure DevOps Boards clone built with Streamlit.

Run with:  streamlit run app.py
"""

import streamlit as st

from boards import db, seed, ui
from boards import repository as repo
from boards.errors import BoardsError

st.set_page_config(page_title="Boards", page_icon="🗂️", layout="wide")


@st.cache_resource
def _init_db() -> bool:
    db.init_db()
    return True


_init_db()
ui.inject_css()
ui.show_flash()

if db.legacy_backup is not None and not st.session_state.get("_legacy_seen"):
    st.session_state["_legacy_seen"] = True
    st.warning(f"An older database from the first prototype was moved to `{db.legacy_backup.name}` "
               "and a new, empty database was created.", icon="🗄️")


def onboarding() -> None:
    st.title("🗂️ Welcome to Boards")
    st.write("There are no users yet. Create the first user, or load a demo project with epics, features, "
             "stories, tasks, bugs, sprints and history.")
    left, right = st.columns(2, gap="large")
    with left, st.form("first_user"):
        st.subheader("Start from scratch")
        name = st.text_input("Name", max_chars=120)
        email = st.text_input("Email", max_chars=254)
        team = st.text_input("Team", max_chars=120, placeholder="e.g. Platform, Mobile, Data…")
        project = st.text_input("Project name", "My Project", max_chars=80)
        if st.form_submit_button("Create and continue", type="primary"):
            try:
                st.session_state["user_id"] = repo.create_user(name, email, team)
                repo.set_setting("project_name", project.strip() or "My Project")
                st.rerun()
            except BoardsError as exc:
                st.error(str(exc))
    with right, st.container(border=True):
        st.subheader("Demo project")
        st.write("Online Store: 4 epics, 10 features, 25 user stories, 8 bugs, ~90 tasks, 6 sprints and 7 people.")
        if st.button("Load demo", icon=":material/rocket_launch:"):
            with st.spinner("Creating data…"):
                seed.load_demo()
            st.rerun()


def sidebar() -> None:
    users = repo.list_users(active_only=True)
    if users.empty:
        users = repo.list_users()
    names = {int(r.id): f"{r.name} · {r.team}" if r.team else r.name for r in users.itertuples()}
    # Remember who is using this browser tab in the address (?user=3), so reloads and bookmarks keep it.
    from_url = st.query_params.get("user", "")
    if "user_id" not in st.session_state and from_url.isdigit() and int(from_url) in names:
        st.session_state["user_id"] = int(from_url)
    if st.session_state.get("user_id") not in names:
        st.session_state["user_id"] = next(iter(names))
    with st.sidebar:
        st.markdown(f"#### 🗂️ {ui.md_escape(repo.get_setting('project_name'))}")
        st.selectbox("Working as", list(names), format_func=names.get, key="user_id")
        st.query_params["user"] = str(st.session_state["user_id"])
        st.button("New work item", icon=":material/add:", type="primary", width="stretch", on_click=ui.open_new)
        with st.form("goto", border=False, clear_on_submit=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
            target = c1.number_input("Open work item", min_value=1, step=1, value=None, placeholder="ID")
            if c2.form_submit_button("", icon=":material/arrow_forward:") and target:
                if repo.get_work_item(int(target)):
                    ui.open_item(int(target))
                else:
                    st.error(f"Work item {int(target)} does not exist.")


if repo.user_count() == 0:
    onboarding()
    st.stop()

pages = {
    "Project": [
        st.Page("views/dashboard.py", title="Home", icon=":material/home:", default=True),
    ],
    "Boards": [
        st.Page("views/board.py", title="Boards", icon=":material/view_kanban:"),
        st.Page("views/backlog.py", title="Backlogs", icon=":material/format_list_bulleted:"),
        st.Page("views/sprints.py", title="Sprints", icon=":material/directions_run:"),
        st.Page("views/queries.py", title="Work items", icon=":material/list_alt:"),
    ],
    "Organisation": [
        st.Page("views/users.py", title="People", icon=":material/group:"),
        st.Page("views/settings.py", title="Settings", icon=":material/settings:"),
    ],
}
page = st.navigation(pages)
sidebar()
page.run()
ui.render_pending_dialog()
