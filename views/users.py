import pandas as pd
import streamlit as st

from boards import config, ui
from boards import repository as repo
from boards.errors import BoardsError

st.title("People")

with st.expander("Add person", icon=":material/person_add:"):
    with st.form("add_user", clear_on_submit=True, border=False):
        c1, c2, c3 = st.columns([2, 2, 1.5], vertical_alignment="bottom")
        name = c1.text_input("Name", max_chars=config.MAX_NAME)
        email = c2.text_input("Email", max_chars=254)
        team = c3.text_input("Team", max_chars=config.MAX_NAME, placeholder="Any team name")
        if st.form_submit_button("Add", type="primary", icon=":material/add:"):
            try:
                repo.create_user(name, email, team)
                ui.flash(f"{name.strip()} added.")
                st.rerun()
            except BoardsError as exc:
                st.error(str(exc))

workload = repo.user_workload()
st.caption("Edit directly in the table and press **Save**. Deactivate people who left instead of deleting them, "
           "so their history is kept.")
grid = pd.DataFrame({
    "id": workload["id"],
    "Initials": workload["name"].map(ui.initials),
    "Name": workload["name"],
    "Email": workload["email"],
    "Team": workload["team"],
    "Active": workload["active"].astype(bool),
    "Open items": workload["open_items"],
})
edited = st.data_editor(
    grid, hide_index=True, width="stretch", key="users_editor",
    column_order=["Initials", "Name", "Email", "Team", "Active", "Open items"],
    disabled=["Initials", "Open items"],
    column_config={
        "Initials": st.column_config.TextColumn(" ", width=50),
        "Name": st.column_config.TextColumn(required=True, max_chars=config.MAX_NAME),
        "Email": st.column_config.TextColumn(required=True, max_chars=254),
        "Team": st.column_config.TextColumn(max_chars=config.MAX_NAME),
        "Open items": st.column_config.NumberColumn(help="Work items assigned and not closed"),
    },
)

c1, c2 = st.columns([1, 4])
if c1.button("Save", type="primary", icon=":material/save:"):
    errors, saved = [], 0
    for before, after in zip(grid.to_dict("records"), edited.to_dict("records")):
        changes = {field: after[col] for col, field in (("Name", "name"), ("Email", "email"),
                                                          ("Team", "team"), ("Active", "active"))
                   if before[col] != after[col]}
        if changes:
            try:
                repo.update_user(int(before["id"]), **changes)
                saved += 1
            except BoardsError as exc:
                errors.append(f"{before['Name']}: {exc}")
    for err in errors:
        ui.flash(err, "⚠️")
    ui.flash(f"{saved} person(s) updated." if saved else "Nothing to save.", "✅" if saved else "ℹ️")
    st.session_state.pop("users_editor", None)
    st.rerun()

with c2.popover("Delete person", icon=":material/person_remove:"):
    names = dict(zip(workload["id"].astype(int), workload["name"]))
    victim = st.selectbox("Person", list(names), format_func=names.get, index=None, placeholder="Choose…")
    if victim is not None:
        st.warning("Their work items become unassigned and their history loses its author. Prefer deactivating.")
        if victim == ui.uid():
            st.caption("You cannot delete the user you are working as.")
        elif st.button("Delete permanently", type="primary"):
            try:
                repo.delete_user(victim)
                ui.flash(f"{names[victim]} deleted.", "🗑️")
            except BoardsError as exc:
                ui.flash(str(exc), "⚠️")
            st.rerun()

st.subheader("Teams")
members = workload[workload["active"] == 1]
teams = members.assign(team=members["team"].replace("", "No team")).groupby("team")["name"].agg(list)
if teams.empty:
    st.caption("Nobody has a team yet. Type one in the Team column above.")
for team, names in sorted(teams.items(), key=lambda kv: kv[0].lower()):
    with st.container(border=True):
        st.markdown(f"**{ui.md_escape(team)}** · {len(names)} {'person' if len(names) == 1 else 'people'}")
        st.html('<div class="wi-meta">' + "".join(f"<span>{ui.person(n)}</span>" for n in sorted(names)) + "</div>")
