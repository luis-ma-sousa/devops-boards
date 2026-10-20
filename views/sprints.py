from datetime import date

import pandas as pd
import streamlit as st

from boards import analytics as an
from boards import charts, config, ui
from boards import repository as repo
from boards.errors import BoardsError, ConflictError
from boards.kanban import event, kanban

ORPHANS = "orphans"
KEY = "taskboard_kanban"

st.title("Sprints")
ui.live_updates("sprints")

iterations = repo.list_iterations()
if iterations.empty:
    st.info("There are no iterations yet. Create the first one:")
    with st.form("first_iteration"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name", "Sprint 1")
        start = c2.date_input("Start", format="YYYY-MM-DD")
        end = c3.date_input("End", format="YYYY-MM-DD")
        if st.form_submit_button("Create iteration", type="primary"):
            try:
                repo.create_iteration(name, start, end)
                st.rerun()
            except BoardsError as exc:
                st.error(str(exc))
    st.stop()

today = date.today()
current = repo.current_iteration(iterations)
it_ids = iterations["id"].astype(int).tolist()


def it_label(iid):
    row = iterations[iterations["id"] == iid].iloc[0]
    dates = (f" · {row.start_date:%d %b} – {row.end_date:%d %b}"
             if not ui.blank(row.start_date) and not ui.blank(row.end_date) else "")
    tag = " (current)" if current and iid == current["id"] else ""
    return f"{row['name']}{dates}{tag}"


default_idx = it_ids.index(current["id"]) if current else 0
iid = st.selectbox("Iteration", it_ids, index=default_idx, format_func=it_label, key="sprint_sel", width=380)
it = iterations[iterations["id"] == iid].iloc[0].to_dict()

items = repo.load_work_items()
sprint = items[(items["iteration_id"] == iid) & (items["state"] != "Removed")]
reqs = sprint[sprint["type"].isin(an.REQUIREMENT_TYPES)]
tasks = sprint[sprint["type"] == "Task"]

has_dates = not ui.blank(it["start_date"]) and not ui.blank(it["end_date"])
work_days = an.working_days(it["start_date"], it["end_date"]) if has_dates else []
remaining_days = [d for d in work_days if d >= today]
capacity = repo.get_capacity(iid)
capacity["total"] = capacity["hours_per_day"] * (len(work_days) - capacity["days_off"]).clip(lower=0)
share_left = len(remaining_days) / len(work_days) if work_days else 0
capacity["left"] = capacity["hours_per_day"] * (len(remaining_days) - capacity["days_off"] * share_left).clip(lower=0)

if it.get("goal"):
    st.markdown(f"🎯 **Goal:** {ui.md_escape(it['goal'])}")
total_pts = float(reqs["story_points"].fillna(0).sum())
done_pts = float(reqs.loc[reqs["state"] == "Closed", "story_points"].fillna(0).sum())
m = st.columns(3)
m[0].metric("Working days left", f"{len(remaining_days)} of {len(work_days)}" if work_days else "—", border=True)
m[1].metric("Stories and bugs done", f"{int((reqs['state'] == 'Closed').sum())} of {len(reqs)}", border=True)
m[2].metric("Story Points done", f"{done_pts:.0f} of {total_pts:.0f}", border=True)

tab_board, tab_backlog, tab_capacity, tab_burndown, tab_plan = st.tabs(
    ["Taskboard", "Sprint backlog", "Capacity", "Burndown", "Planning"], key="sprint_tab"
)

# --- Taskboard --------------------------------------------------------------------------------------------


def on_moved() -> None:
    move = event(KEY, "moved")
    if not move:
        return
    fresh = repo.load_work_items()
    sprint_tasks = fresh[(fresh["iteration_id"] == iid) & (fresh["type"] == "Task") & (fresh["state"] != "Removed")]
    new_parent = None if move["toLane"] == ORPHANS else int(move["toLane"])
    old_parent = None if move["fromLane"] == ORPHANS else int(move["fromLane"])
    lane_tasks = sprint_tasks[(sprint_tasks["state"] == move["to"]) & (sprint_tasks["id"] != move["id"])]
    lane_tasks = lane_tasks[lane_tasks["parent_id"].isna()] if new_parent is None else \
        lane_tasks[lane_tasks["parent_id"] == new_parent]
    order = lane_tasks.sort_values(["backlog_rank", "id"])["id"].astype(int).tolist()
    position = order.index(move["before"]) if move.get("before") in order else len(order)
    order.insert(position, int(move["id"]))
    kwargs = {}
    if new_parent != old_parent:
        kwargs = {"parent_id": new_parent, "expected_parent": old_parent}
    try:
        repo.move_item(int(move["id"]), ui.uid(), state=move["to"] if move["to"] != move["from"] else None,
                       expected_state=move["from"], order_ids=order, **kwargs)
        if move["to"] != move["from"]:
            ui.flash(f"Task {move['id']} moved to {move['to']}", "↪️")
        if kwargs:
            ui.flash(f"Task {move['id']} moved to another parent", "↪️")
    except ConflictError:
        ui.flash(f"Task {move['id']} was just changed by someone else. The board has been refreshed.", "⚠️")
    except BoardsError as exc:
        ui.flash(str(exc), "⚠️")


def on_opened() -> None:
    opened = event(KEY, "opened")
    if opened:
        ui.open_item(opened["id"])


def on_add() -> None:
    add = event(KEY, "add")
    if add and add.get("lane") not in (None, ORPHANS):
        ui.open_new("Task", parent_id=int(add["lane"]), iteration_id=iid)
    elif add:
        ui.open_new("Task", iteration_id=iid)


with tab_board:
    people = sorted({n for n in tasks["assigned_name"].dropna()} | {n for n in reqs["assigned_name"].dropna()})
    who = st.pills("Person", ["Everyone"] + people + ["Unassigned"], default="Everyone", key="tb_person",
                   label_visibility="collapsed")
    view_tasks = tasks
    if who and who != "Everyone":
        view_tasks = tasks[tasks["assigned_name"].isna()] if who == "Unassigned" else tasks[tasks["assigned_name"] == who]

    columns = [ui.column_payload(s, int((view_tasks["state"] == s).sum())) for s in config.TASKBOARD_COLUMNS]
    lanes, cards = [], []
    req_ids = set(reqs["id"].astype(int))
    for req in reqs.sort_values(["backlog_rank", "id"]).to_dict("records"):
        own = view_tasks[view_tasks["parent_id"] == req["id"]]
        if who not in (None, "Everyone") and own.empty and req.get("assigned_name") != who:
            continue
        lane_id = str(int(req["id"]))
        lanes.append({"id": lane_id, "card": ui.card_payload(req, lane=lane_id, show_state=True), "addLabel": "Task"})
        cards += [ui.card_payload(t, lane=lane_id, allowed=config.TASKBOARD_COLUMNS) for t in own.to_dict("records")]
    orphans = view_tasks[~view_tasks["parent_id"].isin(req_ids).fillna(False).astype(bool)]
    if not orphans.empty or not lanes:
        lanes.append({"id": ORPHANS, "title": "Tasks without a parent in this sprint", "addLabel": "Task"})
        cards += [ui.card_payload(t, lane=ORPHANS, allowed=config.TASKBOARD_COLUMNS)
                  for t in orphans.to_dict("records")]

    st.caption("Drag tasks between columns to change their state, or to another row to move them to that story. "
               "Click a card to open it.")
    kanban(key=KEY, columns=columns, cards=cards, lanes=lanes, lane_move=True, lane_title="Item",
           on_moved=on_moved, on_opened=on_opened, on_add=on_add)
    if reqs.empty and tasks.empty:
        st.info("This sprint has no work yet. Use the **Planning** tab to add items.")

# --- Sprint backlog -----------------------------------------------------------------------------------------
with tab_backlog:
    if reqs.empty:
        st.caption("No user stories or bugs in this sprint.")
    else:
        task_stats = tasks.groupby("parent_id").agg(
            total=("id", "size"), done=("state", lambda s: int((s == "Closed").sum())),
            hours=("remaining_work", "sum"))
        ordered = reqs.sort_values(["backlog_rank", "id"])
        stats = task_stats.reindex(ordered["id"].tolist())
        table = pd.DataFrame({
            "ID": ordered["id"].astype(int).values,
            "Item": [f"{ui.icon(t)} {title}" for t, title in zip(ordered["type"], ordered["title"])],
            "State": ordered["state"].values,
            "Assigned to": ordered["assigned_name"].fillna("").values,
            "Story Points": ordered["story_points"].values,
            "Tasks": [f"{int(d)}/{int(t)}" if not pd.isna(t) else "0/0" for d, t in zip(stats["done"], stats["total"])],
            "Remaining hours": stats["hours"].fillna(0).values,
            "Tags": ordered["tags"].values,
        })
        ui.item_table(table, "sprint_backlog", column_config={
            "ID": st.column_config.NumberColumn(width=60, format="%d"),
            "Item": st.column_config.TextColumn(width="large"),
            "Story Points": st.column_config.NumberColumn(format="%.0f"),
            "Remaining hours": st.column_config.NumberColumn(format="%.1f h"),
        })
        st.caption("Select a row to open the item.")

# --- Capacity ------------------------------------------------------------------------------------------------
with tab_capacity:
    if not work_days:
        st.caption("Set start and end dates on the iteration to calculate capacity.")
    st.caption(f"{len(work_days)} working days in the sprint · {len(remaining_days)} left. "
               "Set each person's hours per day and days off.")
    edited = st.data_editor(
        capacity[["user_id", "name", "team", "hours_per_day", "days_off"]], hide_index=True, width="stretch",
        key=f"cap_editor_{iid}", disabled=["name", "team"],
        column_order=["name", "team", "hours_per_day", "days_off"],
        column_config={
            "name": "Person", "team": "Team",
            "hours_per_day": st.column_config.NumberColumn("Hours per day", min_value=0, max_value=24, step=0.5),
            "days_off": st.column_config.NumberColumn("Days off", min_value=0, max_value=len(work_days) or 30, step=1),
        },
    )
    if st.button("Save capacity", icon=":material/save:"):
        try:
            repo.save_capacity(iid, edited)
            ui.flash("Capacity saved.")
        except BoardsError as exc:
            ui.flash(str(exc), "⚠️")
        st.session_state.pop(f"cap_editor_{iid}", None)
        st.rerun()

    assigned = tasks.groupby("assigned_to")["remaining_work"].sum()
    cap_view = pd.DataFrame({
        "name": capacity["name"],
        "Capacity": capacity["left"].round(1),
        "Assigned": capacity["user_id"].map(assigned).fillna(0).round(1),
    })
    unassigned_h = float(tasks.loc[tasks["assigned_to"].isna(), "remaining_work"].fillna(0).sum())
    over = cap_view[cap_view["Assigned"] > cap_view["Capacity"]]
    st.altair_chart(charts.capacity_chart(cap_view), width="stretch")
    if not over.empty:
        st.warning("Over capacity: " + ", ".join(
            f"{r.name} (+{r.Assigned - r.Capacity:.0f} h)" for r in over.itertuples()), icon="⚠️")
    if unassigned_h:
        st.caption(f"{unassigned_h:.0f} h of remaining work is not assigned to anyone.")

# --- Burndown --------------------------------------------------------------------------------------------------
with tab_burndown:
    if not has_dates:
        st.caption("Set dates on the iteration to see the burndown.")
    else:
        metric = st.segmented_control("Metric", ["Story Points", "Remaining hours", "Items"], default="Remaining hours",
                                      key="sprint_bd_metric", required=True, label_visibility="collapsed")
        key = {"Story Points": "points", "Remaining hours": "hours", "Items": "count"}[metric]
        bd = an.burndown(items, repo.load_history(["state", "story_points", "remaining_work"]), it, key)
        if bd.empty or not (bd["series"] == "Remaining").any():
            st.caption("The sprint has not started yet.")
        else:
            st.altair_chart(charts.burndown_chart(bd, metric, height=340), width="stretch")
            with st.expander("Show data", icon=":material/table:"):
                st.dataframe(bd.pivot_table(index="date", columns="series", values="value").reset_index(),
                             hide_index=True, column_config={"date": st.column_config.DateColumn("Day",
                                                                                                  format="YYYY-MM-DD")})

# --- Planning ----------------------------------------------------------------------------------------------------
with tab_plan:
    vel = an.velocity(items, iterations)
    past = vel[(vel["status"] == "Completed") & (vel["iteration"] != it["name"])]
    avg_velocity = past["points"].mean() if not past.empty else None
    st.caption(f"Planned in this sprint: **{total_pts:.0f}** Story Points"
               + (f" · average velocity: **{avg_velocity:.0f}**" if avg_velocity else ""))
    if avg_velocity and total_pts > avg_velocity * 1.15:
        st.warning("This sprint has more points than the team's average velocity.", icon="⚠️")

    left, right = st.columns(2, gap="medium")
    candidates = items[items["type"].isin(an.REQUIREMENT_TYPES) & ~items["state"].isin(config.INACTIVE_STATES)
                       & (items["iteration_id"] != iid).fillna(True).astype(bool)].sort_values(["backlog_rank", "id"])
    with left:
        st.markdown("**Backlog (outside this sprint)**")
        only_unplanned = st.toggle("Only items without an iteration", value=True, key="plan_unplanned")
        if only_unplanned:
            candidates = candidates[candidates["iteration_id"].isna()]
        cand_table = pd.DataFrame({
            "ID": candidates["id"].astype(int).values,
            "Item": [f"{ui.icon(t)} {title}" for t, title in zip(candidates["type"], candidates["title"])],
            "SP": candidates["story_points"].values,
            "Iteration": candidates["iteration_name"].fillna("—").values,
        })
        n = st.session_state.setdefault("plan_n", 0)
        ev = st.dataframe(cand_table, hide_index=True, width="stretch", on_select="rerun", placeholder="",
                          selection_mode="multi-row", key=f"plan_cand_{n}", height=360,
                          column_config={"ID": st.column_config.NumberColumn(width=60, format="%d"),
                                         "SP": st.column_config.NumberColumn(format="%.0f", width=60)})
        chosen = cand_table.iloc[ev.selection.rows]["ID"].tolist()
        if st.button(f"Add {len(chosen)} to the sprint", icon=":material/arrow_forward:", disabled=not chosen,
                     type="primary"):
            ok, errors = repo.bulk_update(chosen, {"iteration_id": iid}, ui.uid())
            # Child tasks follow their item.
            child_tasks = items[items["parent_id"].isin(chosen).fillna(False).astype(bool) & (items["type"] == "Task")
                                & ~items["state"].isin(config.INACTIVE_STATES)]["id"].tolist()
            if child_tasks:
                repo.bulk_update(child_tasks, {"iteration_id": iid}, ui.uid())
            for err in errors:
                ui.flash(err, "⚠️")
            ui.flash(f"{ok} item(s) added to {it['name']}.")
            st.session_state["plan_n"] = n + 1
            st.rerun()

    with right:
        st.markdown(f"**{it['name']}**")
        in_sprint = reqs.sort_values(["backlog_rank", "id"])
        sprint_table = pd.DataFrame({
            "ID": in_sprint["id"].astype(int).values,
            "Item": [f"{ui.icon(t)} {title}" for t, title in zip(in_sprint["type"], in_sprint["title"])],
            "SP": in_sprint["story_points"].values,
            "State": in_sprint["state"].values,
        })
        m2 = st.session_state.setdefault("plan_m", 0)
        ev2 = st.dataframe(sprint_table, hide_index=True, width="stretch", on_select="rerun", placeholder="",
                           selection_mode="multi-row", key=f"plan_sprint_{m2}", height=400,
                           column_config={"ID": st.column_config.NumberColumn(width=60, format="%d"),
                                          "SP": st.column_config.NumberColumn(format="%.0f", width=60)})
        removing = sprint_table.iloc[ev2.selection.rows]["ID"].tolist()
        if st.button(f"Return {len(removing)} to the backlog", icon=":material/arrow_back:", disabled=not removing):
            ok, errors = repo.bulk_update(removing, {"iteration_id": None}, ui.uid())
            for err in errors:
                ui.flash(err, "⚠️")
            ui.flash(f"{ok} item(s) returned to the backlog.")
            st.session_state["plan_m"] = m2 + 1
            st.rerun()
