import pandas as pd
import streamlit as st

from boards import config, ui
from boards import repository as repo
from boards.errors import BoardsError

ESTIMATE_FIELD = {"Epic": "effort", "Feature": "effort", "User Story": "story_points", "Bug": "story_points",
                  "Task": "remaining_work"}
INDENT = " "  # em space

st.title("Backlogs")
ui.live_updates("backlog")

items = repo.load_work_items()
lk = ui.lookups()

with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
    level = st.segmented_control("Level", list(config.BACKLOG_LEVELS), default="Stories", required=True,
                                 key="backlog_level", label_visibility="collapsed")
    show_children = st.toggle("Show children", key="backlog_children", help="Include the hierarchy below each item")
    show_done = st.toggle("Show completed", key="backlog_done")
    edit_mode = st.toggle("Grid editing", key="backlog_edit",
                          help="Edit state, person, iteration, estimate and order directly in the table")

types = config.BACKLOG_LEVELS[level]

with st.form(f"backlog_add_{level}", clear_on_submit=True, border=False):
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        new_type = st.selectbox("Type", types, format_func=lambda t: f"{ui.icon(t)} {t}", width=170,
                                label_visibility="collapsed") if len(types) > 1 else types[0]
        new_title = st.text_input("Title", placeholder=f"Add a {types[0]} to the bottom of the backlog…",
                                  label_visibility="collapsed", max_chars=config.MAX_TITLE)
        if st.form_submit_button("Add", icon=":material/add:"):
            try:
                new_id = repo.create_work_item({"type": new_type, "title": new_title}, ui.uid())
                ui.flash(f"{new_type} {new_id} added to the backlog.")
                st.rerun()
            except BoardsError as exc:
                st.error(str(exc))

roots = items[items["type"].isin(types)]
if not show_done:
    roots = roots[~roots["state"].isin(config.INACTIVE_STATES)]
roots = ui.filter_bar(roots, "backlog", types=types if len(types) > 1 else None)

# --- build the tree ---------------------------------------------------------------------------------------
children_of = {int(pid): grp for pid, grp in items.groupby("parent_id")}


def walk(row, depth, out, order=None, seen=None):
    seen = seen if seen is not None else set()
    if int(row["id"]) in seen:
        return
    seen.add(int(row["id"]))
    out.append({**row, "depth": depth, "order": order})
    if not show_children:
        return
    kids = children_of.get(int(row["id"]))
    if kids is None:
        return
    if not show_done:
        kids = kids[~kids["state"].isin(config.INACTIVE_STATES)]
    for kid in kids.sort_values(["backlog_rank", "id"]).to_dict("records"):
        walk(kid, depth + 1, out, seen=seen)


tree = []
for pos, row in enumerate(roots.sort_values(["backlog_rank", "id"]).to_dict("records"), start=1):
    walk(row, 0, tree, pos)
rows = pd.DataFrame(tree)

if rows.empty:
    st.info("Nothing to show with these filters.")
    st.stop()


def estimate(r):
    value = r.get(ESTIMATE_FIELD[r["type"]])
    return None if ui.blank(value) else float(value)


def progress(r):
    total = int(r.get("child_count") or 0)
    return (int(r.get("child_done") or 0) / total) if total and r["type"] != "Task" else None


grid = pd.DataFrame({
    "Order": rows["order"].astype("Int64"),
    "ID": rows["id"].astype(int),
    "Type": [(INDENT * d) + f"{ui.icon(t)} {t}" for d, t in zip(rows["depth"], rows["type"])],
    "Item": [(INDENT * d) + f"{ui.icon(t)} {title}" for d, t, title in zip(rows["depth"], rows["type"], rows["title"])],
    "Title": rows["title"],
    "State": rows["state"],
    "Assigned to": rows["assigned_name"].fillna(""),
    "Iteration": rows["iteration_name"].fillna(""),
    "Estimate": [estimate(r) for r in tree],
    "Priority": rows["priority"].astype(int),
    "Tags": rows["tags"],
    "Progress": [progress(r) for r in tree],
})

total_est = grid.loc[rows["depth"] == 0, "Estimate"].sum()
unit = {"Epics": "effort", "Features": "effort", "Stories": "Story Points"}[level]
st.caption(f"{int((rows['depth'] == 0).sum())} items · {total_est:.0f} {unit} in total")

if not edit_mode:
    # --- read mode: multi-select + bulk actions --------------------------------------------------------------
    counter = st.session_state.setdefault("backlog_sel_n", 0)
    keep = st.session_state.pop("backlog_keep", None)  # keep the moved item selected
    default_sel = None
    if keep is not None and keep in grid["ID"].values:
        counter += 1
        st.session_state["backlog_sel_n"] = counter
        default_sel = {"selection": {"rows": [int(grid.index[grid["ID"] == keep][0])]}}
    event = st.dataframe(
        grid, hide_index=True, placeholder="", selection_default=default_sel, width="stretch",
        height=min(640, 38 + 35 * len(grid)), on_select="rerun", selection_mode="multi-row",
        key=f"backlog_grid_{counter}",
        column_order=["Order", "ID", "Item", "State", "Assigned to", "Iteration", "Estimate", "Priority",
                      "Tags", "Progress"],
        column_config={
            "Order": st.column_config.NumberColumn(width=60),
            "ID": st.column_config.NumberColumn(width=60, format="%d"),
            "Item": st.column_config.TextColumn("Title", width="large"),
            "Estimate": st.column_config.NumberColumn(format="%.1f", width=90),
            "Priority": st.column_config.NumberColumn(width=80),
            "Progress": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent", width=110),
        },
    )
    selected = grid.iloc[event.selection.rows]
    if selected.empty:
        st.caption("Select rows to open, reorder or bulk edit them.")
        st.stop()

    def done_action():
        st.session_state["backlog_sel_n"] = counter + 1

    ids = selected["ID"].tolist()
    with st.container(border=True):
        st.markdown(f"**{len(ids)} selected**")
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            if len(ids) == 1:
                if st.button("Open", icon=":material/open_in_new:"):
                    ui.open_item(ids[0])
                    done_action()
                    st.rerun()
                sel = selected.iloc[0]
                if not pd.isna(sel["Order"]):
                    order_ids = grid.loc[grid["Order"].notna(), "ID"].tolist()
                    if st.button("Up", icon=":material/arrow_upward:"):
                        repo.move_in_list(int(sel["ID"]), order_ids, -1)
                        st.session_state["backlog_keep"] = int(sel["ID"])
                        st.rerun()
                    if st.button("Down", icon=":material/arrow_downward:"):
                        repo.move_in_list(int(sel["ID"]), order_ids, +1)
                        st.session_state["backlog_keep"] = int(sel["ID"])
                        st.rerun()
                    if st.button("To top", icon=":material/vertical_align_top:"):
                        repo.reorder([int(sel["ID"])] + [i for i in order_ids if i != int(sel["ID"])])
                        st.session_state["backlog_keep"] = int(sel["ID"])
                        st.rerun()

            it_opts = [None] + list(lk["iterations"])
            target_it = st.selectbox("Iteration", it_opts, format_func=lambda i: "No iteration" if i is None
                                     else lk["iterations"][i], width=180, key="bl_bulk_it")
            if st.button("Move to iteration", icon=":material/event:"):
                ok, errors = repo.bulk_update(ids, {"iteration_id": target_it}, ui.uid())
                for err in errors:
                    ui.flash(err, "⚠️")
                ui.flash(f"{ok} item(s) moved to {lk['iterations'].get(target_it, 'no iteration')}.")
                done_action()
                st.rerun()
            target_state = st.selectbox("State", config.ALL_STATES, width=130, key="bl_bulk_state")
            if st.button("Change state", icon=":material/swap_horiz:"):
                ok, errors = repo.bulk_update(ids, {"state": target_state}, ui.uid())
                for err in errors:
                    ui.flash(err, "⚠️")
                ui.flash(f"{ok} item(s) moved to {target_state}.")
                done_action()
                st.rerun()
            user_opts = [None] + lk["active_users"]
            target_user = st.selectbox("Assign to", user_opts, format_func=lambda u: "Unassigned" if u is None
                                       else lk["users"][u], width=180, key="bl_bulk_user")
            if st.button("Assign", icon=":material/person:"):
                ok, errors = repo.bulk_update(ids, {"assigned_to": target_user}, ui.uid())
                for err in errors:
                    ui.flash(err, "⚠️")
                ui.flash(f"{ok} item(s) assigned.")
                done_action()
                st.rerun()
else:
    # --- grid editing ----------------------------------------------------------------------------------------
    user_by_name = {name: user_id for user_id, name in lk["users"].items()}
    it_by_name = {name: iteration_id for iteration_id, name in lk["iterations"].items()}
    # The key changes when the data changes, so edits are never applied to the wrong rows.
    data_hash = int(pd.util.hash_pandas_object(grid.drop(columns=["Progress"]).astype(str), index=False).sum())
    editor_key = f"backlog_editor_{level}_{data_hash}"
    edited = st.data_editor(
        grid, hide_index=True, width="stretch", height=min(640, 38 + 35 * len(grid)), key=editor_key,
        placeholder="",
        column_order=["Order", "ID", "Type", "Title", "State", "Assigned to", "Iteration", "Estimate",
                      "Priority", "Tags"],
        disabled=["ID", "Type", "Item", "Tags", "Progress"],
        column_config={
            "Order": st.column_config.NumberColumn(width=60, min_value=1, step=1,
                                                   help="Change the numbers to reorder the backlog"),
            "ID": st.column_config.NumberColumn(width=60, format="%d"),
            "Title": st.column_config.TextColumn(width="large", required=True, max_chars=config.MAX_TITLE),
            "State": st.column_config.SelectboxColumn(options=config.ALL_STATES, required=True),
            "Assigned to": st.column_config.SelectboxColumn(options=[""] + [lk["users"][u] for u in lk["active_users"]]),
            "Iteration": st.column_config.SelectboxColumn(options=[""] + list(lk["iterations"].values())),
            "Estimate": st.column_config.NumberColumn(min_value=0, format="%.1f", width=90),
            "Priority": st.column_config.SelectboxColumn(options=config.PRIORITIES, required=True, width=80),
        },
    )
    if st.button("Save changes", type="primary", icon=":material/save:"):
        changed_items, errors = 0, []
        for i in range(len(grid)):
            before, after = grid.iloc[i], edited.iloc[i]
            row = tree[i]
            changes, base = {}, {}
            for col, field, mapper in (
                ("Title", "title", None),
                ("State", "state", None),
                ("Assigned to", "assigned_to", lambda v: user_by_name.get(v)),
                ("Iteration", "iteration_id", lambda v: it_by_name.get(v)),
                ("Priority", "priority", int),
                ("Estimate", ESTIMATE_FIELD[row["type"]], None),
            ):
                if not (ui.blank(before[col]) and ui.blank(after[col])) and before[col] != after[col]:
                    changes[field] = mapper(after[col]) if mapper else after[col]
                    base[field] = row.get(field)
            if changes:
                try:
                    repo.update_work_item(int(before["ID"]), changes, ui.uid(), base=base)
                    changed_items += 1
                except BoardsError as exc:
                    errors.append(f"#{before['ID']}: {exc}")
        roots_mask = grid["Order"].notna()
        new_order = edited.loc[roots_mask, "Order"].astype("Float64")
        if (new_order != grid.loc[roots_mask, "Order"].astype("Float64")).fillna(True).any():
            order = pd.DataFrame({"id": grid.loc[roots_mask, "ID"], "new": new_order.fillna(10**6),
                                  "old": grid.loc[roots_mask, "Order"]}).sort_values(["new", "old"])
            repo.reorder(order["id"].tolist())
            changed_items += 1
        for err in errors:
            ui.flash(err, "⚠️")
        ui.flash(f"{changed_items} change(s) saved." if changed_items else "Nothing to save.",
                 "✅" if changed_items else "ℹ️")
        st.session_state.pop(editor_key, None)
        st.rerun()
