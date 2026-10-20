from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from boards import analytics as an
from boards import charts, config, ui
from boards import repository as repo


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


items = repo.load_work_items()
st.title(f"{repo.get_setting('project_name')} · Overview")
ui.live_updates("dashboard")

if items.empty:
    st.info("There are no work items yet. Start by creating an Epic or a User Story.")
    st.button("Create work item", icon=":material/add:", type="primary", on_click=ui.open_new, args=("Epic",))
    st.stop()

history = repo.load_history(["state", "story_points", "remaining_work"])
iterations = repo.list_iterations()
current = repo.current_iteration(iterations)
today = date.today()

# --- KPIs ----------------------------------------------------------------------------------------------
reqs = items[items["type"].isin(an.REQUIREMENT_TYPES)]
open_reqs = reqs[~reqs["state"].isin(config.INACTIVE_STATES)]
in_progress = open_reqs[open_reqs["state"].isin(["Active", "Resolved"])]
open_bugs = items[(items["type"] == "Bug") & ~items["state"].isin(config.INACTIVE_STATES)]
week_ago = (today - timedelta(days=7)).isoformat()
new_bugs = int((items["type"].eq("Bug") & (items["created_at"] >= week_ago)).sum())
since = (today - timedelta(days=13)).isoformat()
closed_recent = int((reqs["state"].eq("Closed") & (reqs["closed_at"].fillna("") >= since)).sum())
flow = an.flow_times(items, days=30)

k = st.columns(6)
k[0].metric("Open", len(open_reqs), border=True, help="User Stories and Bugs not closed")
k[1].metric("In progress", len(in_progress), border=True, help="Active or Resolved")
k[2].metric("Open bugs", len(open_bugs), delta=f"{new_bugs} new (7 days)" if new_bugs else None,
            delta_color="inverse", border=True)
k[3].metric("Closed (14 days)", closed_recent, border=True, help="User Stories and Bugs closed")
k[4].metric("Lead time", f"{flow['lead_time'].mean():.1f} d" if not flow.empty else "—", border=True,
            help="Average from creation to close (items closed in the last 30 days)")
k[5].metric("Cycle time", f"{flow['cycle_time'].mean():.1f} d" if not flow.empty else "—", border=True,
            help="Average from activation to close (items closed in the last 30 days)")

# --- Current sprint -----------------------------------------------------------------------------------------
if current:
    sprint_items = items[items["iteration_id"] == current["id"]]
    sprint_reqs = sprint_items[sprint_items["type"].isin(an.REQUIREMENT_TYPES) & (sprint_items["state"] != "Removed")]
    total_pts = float(sprint_reqs["story_points"].fillna(0).sum())
    done_pts = float(sprint_reqs.loc[sprint_reqs["state"] == "Closed", "story_points"].fillna(0).sum())
    days = an.working_days(current["start_date"], current["end_date"])
    left = len([d for d in days if d >= today]) if current["start_date"] <= today else len(days)
    st.subheader(f"🗓 {current['name']}")
    st.caption(f"{current['start_date']:%d %b} – {current['end_date']:%d %b} · {left} working days left"
               + (f" · Goal: {current['goal']}" if current.get("goal") else ""))
    st.progress(done_pts / total_pts if total_pts else 0.0, text=f"{done_pts:.0f} of {total_pts:.0f} Story Points done")

c1, c2 = st.columns(2, gap="medium")
with c1, st.container(border=True):
    st.markdown("**Sprint burndown**")
    if current:
        metric = st.segmented_control("Metric", ["Story Points", "Remaining hours", "Items"], default="Story Points",
                                      key="dash_bd_metric", label_visibility="collapsed", required=True)
        key = {"Story Points": "points", "Remaining hours": "hours", "Items": "count"}[metric]
        bd = an.burndown(items, history, current, key)
        if bd.empty or not (bd["series"] == "Remaining").any():
            st.caption("The sprint has not started yet.")
        else:
            st.altair_chart(charts.burndown_chart(bd, metric), width="stretch")
    else:
        st.caption("Create an iteration with dates to see the burndown.")

with c2, st.container(border=True):
    st.markdown("**Velocity**")
    vel = an.velocity(items, iterations)
    if vel.empty:
        st.caption("No iteration has started yet.")
    else:
        st.altair_chart(charts.velocity_chart(vel), width="stretch")
        past = vel[(vel["status"] == "Completed") & (vel["iteration"] != (current or {}).get("name"))]
        if not past.empty:
            st.caption(f"Average of previous iterations: **{past['points'].mean():.1f}** points")

c1, c2 = st.columns(2, gap="medium")
with c1, st.container(border=True):
    st.markdown("**Cumulative flow (30 days)**")
    level = st.segmented_control("Level", list(config.BACKLOG_LEVELS), default="Stories", key="dash_cfd_level",
                                 label_visibility="collapsed", required=True)
    cfd = an.cumulative_flow(items, history, config.BACKLOG_LEVELS[level], days=30)
    st.altair_chart(charts.cfd_chart(cfd), width="stretch")

with c2, st.container(border=True):
    st.markdown("**Open work per person**")
    scope = items[~items["state"].isin(config.INACTIVE_STATES) & items["type"].isin(["User Story", "Bug", "Task"])]
    by_person = (scope.assign(person=scope["assigned_name"].fillna("Unassigned"))
                 .groupby(["person", "state"]).size().reset_index(name="count"))
    if by_person.empty:
        st.caption("Nothing open.")
    else:
        st.altair_chart(charts.stacked_by_state(by_person, "person", "Stories, bugs and tasks", height=300),
                        width="stretch")

c1, c2 = st.columns([3, 2], gap="medium")
with c1, st.container(border=True):
    st.markdown("**Epic progress**")
    progress = an.rollup_progress(items, "Epic")
    if progress.empty:
        st.caption("No epics.")
    else:
        table = pd.DataFrame({
            "ID": progress["id"],
            "Epic": "👑 " + progress["title"],
            "State": progress["state"],
            "Stories": progress["done_items"].astype(str) + "/" + progress["items"].astype(str),
            "Points": progress["done_points"].map("{:.0f}".format) + "/" + progress["points"].map("{:.0f}".format),
            "Progress": progress["progress"],
        })
        ui.item_table(table, "dash_epics", column_config={
            "ID": st.column_config.NumberColumn(width=50),
            "State": st.column_config.TextColumn(width=70),
            "Stories": st.column_config.TextColumn(width=60),
            "Points": st.column_config.TextColumn(width=60),
            "Progress": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
        })
        st.caption("Select a row to open the epic.")

with c2, st.container(border=True, height=420):
    st.markdown("**Recent activity**")
    activity = repo.recent_activity(25)
    for row in activity.itertuples():
        who = ui.md_escape(row.user_name or "Someone")
        what = f"{ui.icon(row.type)} {row.item_id} {ui.md_escape(row.title)}"
        if row.field == "created":
            text = f"**{who}** created {what}"
        elif row.field == "state":
            text = f"**{who}** moved {what}: {row.old_value} → **{row.new_value}**"
        elif row.field in ("deleted", "restored"):
            text = f"**{who}** {row.field} {what}"
        elif row.field == "links":
            change = row.new_value or row.old_value or ""
            text = f"**{who}** {'linked' if row.new_value else 'unlinked'} {what} ({ui.md_escape(change.split(':')[0])})"
        else:
            text = f"**{who}** changed *{config.FIELD_LABELS.get(row.field, row.field)}* on {what}"
        st.markdown(f"{text}  \n:gray[{ago(row.changed_at)}]")
