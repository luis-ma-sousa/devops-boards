"""Home: what matters to the person using the app right now."""

from datetime import date, datetime, timedelta

import streamlit as st

from boards import analytics as an
from boards import config, ui
from boards import repository as repo

MAX_PER_COLUMN = 8


def ago(ts: str) -> str:
    delta = datetime.now() - datetime.fromisoformat(ts)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 60 * 24:
        return f"{minutes // 60} h ago"
    return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"


def greeting() -> str:
    hour = datetime.now().hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"


def item_list(rows, key: str, empty: str) -> None:
    if rows.empty:
        st.caption(empty)
        return
    for row in rows.head(MAX_PER_COLUMN).to_dict("records"):
        details = [row["state"]]
        if not ui.blank(row.get("iteration_name")):
            details.append(row["iteration_name"])
        if not ui.blank(row.get("parent_title")):
            details.append(f"{ui.icon(row['parent_type'])} {row['parent_title']}")
        with st.container(gap=None):
            st.button(f"{ui.icon(row['type'])} {row['id']} · {ui.md_escape(row['title'])}", key=f"{key}_{row['id']}",
                      type="tertiary", on_click=ui.open_item, args=(row["id"],))
            st.caption(" · ".join(ui.md_escape(d) for d in details))
    if len(rows) > MAX_PER_COLUMN:
        st.caption(f"+{len(rows) - MAX_PER_COLUMN} more in Work items → Assigned to me")


me = ui.uid()
users = repo.list_users().set_index("id")
my_name = users.loc[me, "name"] if me in users.index else ""
items = repo.load_work_items()

st.title(f"{greeting()}, {my_name.split()[0] if my_name else 'there'} 👋")
st.caption(f"{repo.get_setting('project_name')} · {date.today():%A, %d %B}")
ui.live_updates("dashboard")

with st.container(horizontal=True, gap="small"):
    st.button("New work item", icon=":material/add:", type="primary", on_click=ui.open_new)
    st.page_link("views/board.py", label="Board", icon=":material/view_kanban:")
    st.page_link("views/backlog.py", label="Backlog", icon=":material/format_list_bulleted:")
    st.page_link("views/sprints.py", label="Sprint", icon=":material/directions_run:")

if items.empty:
    st.info("There are no work items yet. Start by creating an Epic or a User Story.", icon="🌱")
    st.stop()

# --- My work ---------------------------------------------------------------------------------------------
st.subheader("My work")
mine = items[(items["assigned_to"] == me).fillna(False).astype(bool)]
week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
todo = mine[mine["state"] == "New"]
doing = mine[mine["state"].isin(["Active", "Resolved"])]
done = mine[(mine["state"] == "Closed") & (mine["closed_at"].fillna("") >= week_ago)].sort_values(
    "closed_at", ascending=False)

if mine.empty:
    st.info("Nothing is assigned to you yet. Pick something from the backlog or the board.", icon="🙌")
else:
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1, st.container(border=True):
        st.markdown(f"**In progress** · {len(doing)}")
        item_list(doing, "doing", "Nothing in progress.")
    with c2, st.container(border=True):
        st.markdown(f"**Up next** · {len(todo)}")
        item_list(todo, "todo", "Nothing waiting for you.")
    with c3, st.container(border=True):
        st.markdown(f"**Done this week** · {len(done)}")
        item_list(done, "done", "Nothing closed this week yet.")

# --- Sprint and updates -------------------------------------------------------------------------------------
left, right = st.columns([1, 1], gap="medium")

with left:
    st.subheader("This sprint")
    current = repo.current_iteration()
    if not current:
        st.caption("No sprint planned yet. Create one in Settings → Iterations.")
    else:
        sprint = items[(items["iteration_id"] == current["id"]) & items["type"].isin(an.REQUIREMENT_TYPES)
                       & (items["state"] != "Removed")]
        closed = int((sprint["state"] == "Closed").sum())
        days = an.working_days(current["start_date"], current["end_date"])
        left_days = len([d for d in days if d >= date.today()])
        with st.container(border=True):
            st.markdown(f"**{ui.md_escape(current['name'])}** · {current['start_date']:%d %b} – "
                        f"{current['end_date']:%d %b} · {left_days} working day{'s' if left_days != 1 else ''} left")
            if current.get("goal"):
                st.markdown(f"🎯 {ui.md_escape(current['goal'])}")
            st.progress(closed / len(sprint) if len(sprint) else 0.0,
                        text=f"{closed} of {len(sprint)} stories and bugs done")
            my_sprint = sprint[(sprint["assigned_to"] == me).fillna(False).astype(bool)]
            if not my_sprint.empty:
                st.caption(f"Yours: {int((my_sprint['state'] == 'Closed').sum())} of {len(my_sprint)} done")
            st.page_link("views/sprints.py", label="Open the taskboard", icon=":material/arrow_forward:")

    st.subheader("Project progress")
    progress = an.rollup_progress(items, "Epic")
    if progress.empty:
        st.caption("No epics yet.")
    else:
        with st.container(border=True):
            for row in progress.to_dict("records"):
                st.button(f"👑 {ui.md_escape(row['title'])}", key=f"epic_{row['id']}", type="tertiary",
                          on_click=ui.open_item, args=(row["id"],))
                st.progress(float(row["progress"]), text=f"{row['done_items']} of {row['items']} done")

with right:
    st.subheader("Updates on your items")
    updates = repo.updates_for_user(me, limit=15) if me else None
    with st.container(border=True, height=520):
        if updates is None or updates.empty:
            st.caption("When teammates change or comment on your items, you will see it here.")
        for row in (updates.to_dict("records") if updates is not None else []):
            who = ui.md_escape(row["who"] or "Someone")
            what = f"{ui.icon(row['type'])} {row['item_id']} {ui.md_escape(row['title'])}"
            if row["kind"] == "comment":
                body = row["body"] if len(row["body"]) <= 140 else row["body"][:137] + "…"
                text = f"💬 **{who}** commented on {what}  \n> {ui.md_escape(body)}"
            elif row["field"] == "state":
                text = f"**{who}** moved {what} to **{row['new_value']}**"
            elif row["field"] == "created":
                text = f"**{who}** created {what}"
            elif row["field"] == "links":
                text = f"**{who}** {'linked' if row['new_value'] else 'unlinked'} {what}"
            elif row["field"] in ("deleted", "restored"):
                text = f"**{who}** {row['field']} {what}"
            else:
                text = f"**{who}** changed *{config.FIELD_LABELS.get(row['field'], row['field'])}* on {what}"
            st.markdown(f"{text}  \n:gray[{ago(row['at'])}]")
