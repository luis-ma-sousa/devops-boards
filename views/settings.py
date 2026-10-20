from datetime import date, timedelta

import pandas as pd
import streamlit as st

from boards import config, db, seed, ui
from boards import repository as repo
from boards.errors import BoardsError

st.title("Settings")

tab_project, tab_iterations, tab_areas, tab_tags, tab_board, tab_bin, tab_data = st.tabs(
    ["Project", "Iterations", "Areas", "Tags", "Board", "Recycle bin", "Data"], key="settings_tab"
)


def save_rows(before: pd.DataFrame, after: pd.DataFrame, columns: dict, update) -> None:
    """Compare two versions of a table and call update(id, **fields) for the rows that changed."""
    saved, errors = 0, []
    for b, a in zip(before.to_dict("records"), after.to_dict("records")):
        changes = {field: a[col] for col, field in columns.items()
                   if not (ui.blank(b[col]) and ui.blank(a[col])) and b[col] != a[col]}
        if changes:
            try:
                update(int(b["id"]), **changes)
                saved += 1
            except BoardsError as exc:
                errors.append(str(exc))
    for err in errors:
        ui.flash(err, "⚠️")
    ui.flash(f"{saved} row(s) saved." if saved else "Nothing to save.", "✅" if saved else "ℹ️")


# --- Project ----------------------------------------------------------------------------------------------
with tab_project:
    with st.form("project"):
        name = st.text_input("Project name", repo.get_setting("project_name"), max_chars=80)
        st.markdown("**Automation rules** (like the *team automation rules* in Azure Boards)")
        auto_activate = st.toggle("Activate the parent when a child becomes Active",
                                  repo.get_setting("auto_activate_parent"))
        auto_close = st.toggle("Close the parent when all its children are Closed",
                               repo.get_setting("auto_close_parent"))
        st.markdown("**Hierarchy**")
        strict = st.toggle("Strict Agile hierarchy", repo.get_setting("strict_hierarchy"),
                           help="When on, parents must follow Epic → Feature → User Story/Bug → Task. "
                                "When off, any item can be the parent of any other (cycles are always blocked).")
        if st.form_submit_button("Save", type="primary"):
            try:
                repo.set_setting("project_name", name)
                repo.set_setting("auto_activate_parent", auto_activate)
                repo.set_setting("auto_close_parent", auto_close)
                repo.set_setting("strict_hierarchy", strict)
                ui.flash("Settings saved.")
                st.rerun()
            except BoardsError as exc:
                st.error(str(exc))

    st.markdown("**Process** (Agile template)")
    process = pd.DataFrame([{
        "Type": f"{ui.icon(t)} {t}",
        "States": " → ".join(config.STATES[t]),
        "Recommended parent": ", ".join(config.AGILE_PARENTS[t]) or "—",
        "Recommended children": ", ".join(config.AGILE_CHILDREN[t]) or "—",
    } for t in config.WORK_ITEM_TYPES])
    st.dataframe(process, hide_index=True, width="stretch")
    st.caption("Link types available on every work item: " + ", ".join(config.LINK_KINDS.values()) + ".")

# --- Iterations ----------------------------------------------------------------------------------------------
with tab_iterations:
    iterations = repo.list_iterations()
    last_end = iterations["end_date"].dropna().max() if not iterations.empty else None
    start_default = (last_end + timedelta(days=3)) if isinstance(last_end, date) else date.today()
    c1, c2 = st.columns(2, gap="medium")
    with c1, st.form("new_iteration", clear_on_submit=True):
        st.markdown("**New iteration**")
        name = st.text_input("Name", f"Sprint {len(iterations) + 1}", max_chars=config.MAX_NAME)
        a, b = st.columns(2)
        start = a.date_input("Start", start_default, format="YYYY-MM-DD")
        end = b.date_input("End", start_default + timedelta(days=11), format="YYYY-MM-DD")
        goal = st.text_input("Sprint goal", max_chars=500)
        if st.form_submit_button("Create", type="primary", icon=":material/add:"):
            try:
                repo.create_iteration(name, start, end, goal)
                ui.flash(f"{name} created.")
                st.rerun()
            except BoardsError as exc:
                st.error(str(exc))
    with c2, st.form("gen_iterations"):
        st.markdown("**Generate several sprints**")
        a, b = st.columns(2)
        count = a.number_input("How many", 1, 26, 4)
        weeks = b.number_input("Weeks per sprint", 1, 6, 2)
        first = st.date_input("Start on (a Monday)", start_default, format="YYYY-MM-DD")
        prefix = st.text_input("Prefix", "Sprint", max_chars=40)
        if st.form_submit_button("Generate", icon=":material/auto_awesome:"):
            existing = {n.lower() for n in iterations["name"]}
            number, created, errors = len(iterations) + 1, 0, []
            for i in range(int(count)):
                s = first + timedelta(weeks=int(weeks) * i)
                e = s + timedelta(days=int(weeks) * 7 - 3)
                while f"{prefix} {number}".lower() in existing:
                    number += 1
                try:
                    repo.create_iteration(f"{prefix} {number}", s, e)
                    existing.add(f"{prefix} {number}".lower())
                    created += 1
                except BoardsError as exc:
                    errors.append(str(exc))
            for err in errors:
                ui.flash(err, "⚠️")
            ui.flash(f"{created} iterations created.")
            st.rerun()

    if not iterations.empty:
        st.markdown("**Existing iterations**")
        grid = iterations[["id", "name", "start_date", "end_date", "goal"]].copy()
        edited = st.data_editor(grid, hide_index=True, width="stretch", key="it_editor",
                                column_order=["name", "start_date", "end_date", "goal"],
                                column_config={
                                    "name": st.column_config.TextColumn("Name", required=True),
                                    "start_date": st.column_config.DateColumn("Start", format="YYYY-MM-DD"),
                                    "end_date": st.column_config.DateColumn("End", format="YYYY-MM-DD"),
                                    "goal": st.column_config.TextColumn("Goal", width="large"),
                                })
        c1, c2 = st.columns([1, 4])
        if c1.button("Save", key="it_save", icon=":material/save:"):
            save_rows(grid, edited, {"name": "name", "start_date": "start_date", "end_date": "end_date",
                                     "goal": "goal"}, repo.update_iteration)
            st.session_state.pop("it_editor", None)
            st.rerun()
        with c2.popover("Delete iteration", icon=":material/delete:"):
            names = dict(zip(iterations["id"].astype(int), iterations["name"]))
            victim = st.selectbox("Iteration", list(names), format_func=names.get, index=None, key="it_del")
            st.caption("Its work items go back to the backlog (no iteration).")
            if st.button("Delete", type="primary", disabled=victim is None, key="it_del_btn"):
                repo.delete_iteration(victim)
                ui.flash(f"{names[victim]} deleted.", "🗑️")
                st.rerun()

# --- Areas ------------------------------------------------------------------------------------------------------
with tab_areas:
    areas = repo.list_areas()
    with st.form("new_area", clear_on_submit=True, border=False):
        with st.container(horizontal=True, vertical_alignment="bottom"):
            area_name = st.text_input("New area", placeholder="e.g. Web, Mobile, API…", width=320,
                                      max_chars=config.MAX_NAME)
            if st.form_submit_button("Add", icon=":material/add:"):
                try:
                    repo.create_area(area_name)
                    st.rerun()
                except BoardsError as exc:
                    st.error(str(exc))
    if not areas.empty:
        grid = areas.copy()
        edited = st.data_editor(grid, hide_index=True, key="area_editor", width=520,
                                column_order=["name", "items"], disabled=["items"],
                                column_config={"name": st.column_config.TextColumn("Area", required=True),
                                               "items": st.column_config.NumberColumn("Work items")})
        c1, c2 = st.columns([1, 4])
        if c1.button("Save", key="area_save", icon=":material/save:"):
            save_rows(grid, edited, {"name": "name"}, lambda i, name: repo.rename_area(i, name))
            st.session_state.pop("area_editor", None)
            st.rerun()
        with c2.popover("Delete area", icon=":material/delete:"):
            names = dict(zip(areas["id"].astype(int), areas["name"]))
            victim = st.selectbox("Area", list(names), format_func=names.get, index=None, key="area_del")
            if st.button("Delete", type="primary", disabled=victim is None, key="area_del_btn"):
                repo.delete_area(victim)
                st.rerun()

# --- Tags ---------------------------------------------------------------------------------------------------------
with tab_tags:
    tags = repo.list_tags()
    st.caption("Tags are created by typing them on a work item. Rename or delete them here.")
    if tags.empty:
        st.info("There are no tags yet.")
    else:
        grid = tags.copy()
        edited = st.data_editor(grid, hide_index=True, key="tag_editor", width=520,
                                column_order=["name", "items"], disabled=["items"],
                                column_config={"name": st.column_config.TextColumn("Tag", required=True),
                                               "items": st.column_config.NumberColumn("Work items")})
        c1, c2 = st.columns([1, 4])
        if c1.button("Save", key="tag_save", icon=":material/save:"):
            save_rows(grid, edited, {"name": "name"}, lambda i, name: repo.rename_tag(i, name))
            st.session_state.pop("tag_editor", None)
            st.rerun()
        with c2.popover("Delete tags", icon=":material/delete:"):
            names = dict(zip(tags["id"].astype(int), tags["name"]))
            victims = st.multiselect("Tags", list(names), format_func=names.get, key="tag_del")
            if st.button("Delete", type="primary", disabled=not victims, key="tag_del_btn"):
                for v in victims:
                    repo.delete_tag(v)
                st.rerun()

# --- Board (WIP limits) ----------------------------------------------------------------------------------------------
with tab_board:
    st.caption("WIP limit per column (0 = no limit). The count turns red when the limit is exceeded.")
    limits = repo.get_setting("wip_limits") or {}
    with st.form("wip"):
        new_limits = {}
        for level in config.BACKLOG_LEVELS:
            st.markdown(f"**{level}**")
            cols = st.columns(len(config.BOARD_COLUMNS))
            new_limits[level] = {}
            for col, state in zip(cols, config.BOARD_COLUMNS):
                value = col.number_input(state, min_value=0, max_value=999, step=1,
                                         value=int(limits.get(level, {}).get(state, 0)), key=f"wip_{level}_{state}")
                if value:
                    new_limits[level][state] = int(value)
        if st.form_submit_button("Save", type="primary"):
            try:
                repo.set_setting("wip_limits", new_limits)
                ui.flash("WIP limits saved.")
                st.rerun()
            except BoardsError as exc:
                st.error(str(exc))

# --- Recycle bin ------------------------------------------------------------------------------------------------------
with tab_bin:
    deleted = repo.list_deleted()
    if deleted.empty:
        st.info("The recycle bin is empty.")
    else:
        table = pd.DataFrame({
            "ID": deleted["id"].astype(int),
            "Item": [f"{ui.icon(t)} {title}" for t, title in zip(deleted["type"], deleted["title"])],
            "State": deleted["state"],
            "Deleted at": deleted["deleted_at"].str[:16],
        })
        n = st.session_state.setdefault("bin_n", 0)
        ev = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                          key=f"bin_{n}")
        chosen = table.iloc[ev.selection.rows]["ID"].tolist()
        c1, c2, _ = st.columns([1, 1.2, 3])
        if c1.button("Restore", icon=":material/restore_from_trash:", disabled=not chosen):
            for item_id in chosen:
                repo.restore_work_item(item_id, ui.uid())
            ui.flash(f"{len(chosen)} item(s) restored.")
            st.session_state["bin_n"] = n + 1
            st.rerun()
        with c2.popover("Delete forever", icon=":material/delete_forever:", disabled=not chosen):
            st.warning(f"Permanently delete {len(chosen)} item(s), including comments, links and history?")
            if st.button("Confirm", type="primary", key="bin_purge"):
                for item_id in chosen:
                    repo.purge_work_item(item_id)
                ui.flash(f"{len(chosen)} item(s) permanently deleted.", "🗑️")
                st.session_state["bin_n"] = n + 1
                st.rerun()

# --- Data -------------------------------------------------------------------------------------------------------------
with tab_data:
    st.markdown(f"Database: `{db.safe_url()}`")
    problems = db.integrity_report()
    if problems:
        st.error("Integrity check found problems:\n\n" + "\n".join(f"- {p}" for p in problems))
    else:
        st.success("Integrity check passed.", icon="✅")
    c1, c2, c3 = st.columns(3)
    if db.is_sqlite():
        c1.download_button("Download database backup", db.sqlite_backup_bytes, "boards-backup.db",
                           "application/x-sqlite3", icon=":material/database:", on_click="ignore")
    c2.download_button("Export everything (JSON)", db.export_json, "boards-export.json", "application/json",
                       icon=":material/data_object:", on_click="ignore")
    c3.download_button("Export work items (CSV)", lambda: repo.load_work_items().to_csv(index=False).encode("utf-8"),
                       "work_items.csv", "text/csv", icon=":material/download:", on_click="ignore")

    st.divider()
    st.markdown("**Danger zone**")
    confirm = st.text_input("Type DELETE to confirm", key="reset_confirm")
    c1, c2, _ = st.columns([1.3, 1.3, 2])
    if c1.button("Reset with demo data", disabled=confirm != "DELETE"):
        db.reset_db()
        seed.load_demo()
        st.session_state.clear()
        st.rerun()
    if c2.button("Delete everything and start empty", type="primary", disabled=confirm != "DELETE"):
        db.reset_db()
        st.session_state.clear()
        st.rerun()
