"""Shared UI: styles, formatting, filters, board cards and the work item dialogs."""

import html
import re
from datetime import date

import pandas as pd
import streamlit as st

from . import config
from . import repository as repo
from .errors import BoardsError, ConflictError

CSS = """
<style>
.block-container { padding-top: 2.4rem; }
button[data-testid="stBaseButton-tertiary"] { justify-content: flex-start; text-align: left; min-height: 0; }
button[data-testid="stBaseButton-tertiary"] p { text-align: left; }
.wi-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; font-size: 0.82rem; }
.wi-muted { opacity: 0.72; }
.wi-avatar { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px;
             border-radius: 50%; color: #fff; font-size: 0.6rem; font-weight: 700; flex-shrink: 0; }
.wi-avatar.empty { background: rgba(128,128,128,0.35); }
.wi-person { display: inline-flex; align-items: center; gap: 5px; }
.wi-state { display: inline-flex; align-items: center; gap: 5px; }
.wi-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.wi-tag { display: inline-block; padding: 0 7px; border-radius: 10px; background: rgba(128,128,128,0.16);
          font-size: 0.72rem; line-height: 1.5; margin: 1px 3px 1px 0; }
</style>
"""

AVATAR_COLORS = ["#0078D4", "#8764B8", "#038387", "#CA5010", "#498205", "#C239B3", "#986F0B", "#4F6BED"]


def inject_css() -> None:
    st.html(CSS)


# --- formatting --------------------------------------------------------------------------------------


def blank(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def esc(value) -> str:
    return "" if blank(value) else html.escape(str(value))


def md_escape(text) -> str:
    """Stop titles from being read as Markdown/LaTeX in widget labels."""
    return re.sub(r"([\\`*_\[\]<>$~|#])", r"\\\1", str(text))


def fmt_num(value, suffix: str = "") -> str:
    if blank(value):
        return ""
    value = float(value)
    return (f"{int(value)}" if value.is_integer() else f"{value:.1f}") + suffix


def initials(name) -> str:
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def avatar_color(name) -> str:
    return AVATAR_COLORS[sum(map(ord, str(name))) % len(AVATAR_COLORS)]


def avatar(name) -> str:
    if blank(name):
        return '<span class="wi-avatar empty">?</span>'
    return (f'<span class="wi-avatar" style="background:{avatar_color(name)}" title="{esc(name)}">'
            f'{esc(initials(name))}</span>')


def person(name) -> str:
    label = esc(name) if not blank(name) else '<span class="wi-muted">Unassigned</span>'
    return f'<span class="wi-person">{avatar(name)}{label}</span>'


def state_badge(state) -> str:
    color = config.STATE_COLORS.get(state, "#999")
    return f'<span class="wi-state"><span class="wi-dot" style="background:{color}"></span>{esc(state)}</span>'


def icon(item_type) -> str:
    return config.TYPE_META.get(item_type, {}).get("icon", "•")


def item_label(item_id, item_type, title) -> str:
    return f"{icon(item_type)} {int(item_id)} · {title}"


def to_date(value):
    if blank(value) or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# --- session ------------------------------------------------------------------------------------------


def uid():
    return st.session_state.get("user_id")


def flash(message: str, icon_: str = "✅") -> None:
    st.session_state.setdefault("_flash", []).append((message, icon_))


def show_flash() -> None:
    for message, icon_ in st.session_state.pop("_flash", []):
        st.toast(message, icon=icon_)


def open_item(item_id) -> None:
    st.session_state["_dialog"] = ("edit", int(item_id))


def open_new(item_type: str = "User Story", parent_id=None, iteration_id=None, area_id=None) -> None:
    st.session_state["_dialog"] = ("new", {
        "type": item_type, "parent_id": parent_id, "iteration_id": iteration_id, "area_id": area_id,
    })


def render_pending_dialog() -> None:
    pending = st.session_state.pop("_dialog", None)
    if not pending:
        return
    kind, payload = pending
    if kind == "edit":
        _edit_dialog(payload)
    else:
        _new_dialog(payload)


def lookups() -> dict:
    users = repo.list_users()
    iterations = repo.list_iterations()
    areas = repo.list_areas()
    tags = repo.list_tags()
    return {
        "users": {int(r.id): r.name for r in users.itertuples()},
        "teams_by_user": {int(r.id): r.team for r in users.itertuples()},
        "active_users": [int(r.id) for r in users.itertuples() if r.active],
        "teams": sorted({r.team for r in users.itertuples() if r.team}, key=str.lower),
        "iterations": {int(r.id): r.name for r in iterations.itertuples()},
        "iteration_df": iterations,
        "areas": {int(r.id): r.name for r in areas.itertuples()},
        "tags": tags["name"].tolist(),
    }


def _index(options, value) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def item_table(df: pd.DataFrame, key: str, id_col: str = "ID", **kwargs) -> None:
    """Table where selecting a row opens the work item (the selection is cleared afterwards)."""
    counter = f"{key}__n"
    n = st.session_state.setdefault(counter, 0)
    widget_key = f"{key}_{n}"

    def _open():
        rows = st.session_state[widget_key].selection.rows
        if rows:
            open_item(int(df.iloc[rows[0]][id_col]))
            st.session_state[counter] = n + 1

    kwargs.setdefault("hide_index", True)
    kwargs.setdefault("width", "stretch")
    kwargs.setdefault("placeholder", "")
    st.dataframe(df, key=widget_key, on_select=_open, selection_mode="single-row", **kwargs)


def live_updates(key: str) -> None:
    """Show a refresh hint when other people change data while this page is open."""
    st.session_state[f"_dv_{key}"] = repo.data_version()
    _live_fragment(key)


@st.fragment(run_every="10s")
def _live_fragment(key: str) -> None:
    if repo.data_version() == st.session_state.get(f"_dv_{key}"):
        return
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.caption("🔄 There are new changes on this page.")
        if st.button("Refresh", key=f"live_refresh_{key}", icon=":material/refresh:", type="tertiary"):
            st.rerun(scope="app")


# --- board cards -------------------------------------------------------------------------------------------


def card_payload(row, *, lane: str = "_", column: str | None = None, show_iteration: bool = False,
                 show_parent: bool = False, show_state: bool = False, allowed=None) -> dict:
    """Data for one card of the Kanban component (plain values; the component escapes everything)."""
    t = row["type"]
    meta = []
    if t in ("User Story", "Bug") and not blank(row.get("story_points")):
        meta.append(f"SP {fmt_num(row['story_points'])}")
    if t in ("Epic", "Feature") and not blank(row.get("effort")):
        meta.append(f"Effort {fmt_num(row['effort'])}")
    if t == "Task" and not blank(row.get("remaining_work")):
        meta.append(f"Remaining {fmt_num(row['remaining_work'], 'h')}")
    if show_iteration and not blank(row.get("iteration_name")):
        meta.append(f"🗓 {row['iteration_name']}")
    if show_parent and not blank(row.get("parent_title")):
        meta.append(f"{icon(row['parent_type'])} {row['parent_title']}")
    total = int(row.get("child_count") or 0)
    assigned = None if blank(row.get("assigned_name")) else str(row["assigned_name"])
    return {
        "id": int(row["id"]),
        "lane": lane,
        "column": column or row["state"],
        "type": t,
        "icon": icon(t),
        "color": config.TYPE_META[t]["color"],
        "title": str(row["title"]),
        "priority": int(row["priority"]) if not blank(row.get("priority")) else 2,
        "assigned": assigned,
        "initials": initials(assigned) if assigned else "?",
        "avatar": avatar_color(assigned) if assigned else None,
        "meta": meta,
        "tags": [x for x in str(row.get("tags") or "").split(", ") if x],
        "progress": [int(row.get("child_done") or 0), total] if total and t != "Task" else None,
        "allowed": allowed if allowed is not None else [s for s in config.STATES[t]],
        "state": row["state"] if show_state else None,
        "stateColor": config.STATE_COLORS.get(row["state"]),
    }


def column_payload(state: str, count: int, *, limit=None, add=False, more_text=None) -> dict:
    return {"id": state, "label": state, "color": config.STATE_COLORS.get(state, "#888"), "count": int(count),
            "limit": int(limit) if limit else None, "add": add, "moreText": more_text}


# --- filters ----------------------------------------------------------------------------------------------

NONE_ID = -1


def filter_bar(df: pd.DataFrame, key: str, *, types=None, states=False, iterations=True,
               default_iterations=None, people=True, teams=True, areas=True, tags=True,
               priority=False) -> pd.DataFrame:
    """One row of filters; returns the filtered DataFrame."""
    lk = lookups()
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        text = st.text_input("Filter", key=f"{key}_q", placeholder="Title or ID", width=220,
                             label_visibility="collapsed")
        sel_types = []
        if types:
            sel_types = st.multiselect("Type", types, key=f"{key}_types", placeholder="Type",
                                       format_func=lambda t: f"{icon(t)} {t}", width=200,
                                       label_visibility="collapsed")
        sel_states = []
        if states:
            sel_states = st.multiselect("State", config.ALL_STATES, key=f"{key}_states", placeholder="State",
                                        width=170, label_visibility="collapsed")
        sel_people = []
        if people:
            opts = [NONE_ID] + list(lk["users"])
            sel_people = st.multiselect(
                "Assigned to", opts, key=f"{key}_people", placeholder="Assigned to", width=200,
                format_func=lambda i: "Unassigned" if i == NONE_ID else lk["users"][i],
                label_visibility="collapsed")
        sel_teams = []
        if teams and lk["teams"]:
            sel_teams = st.multiselect("Team", lk["teams"], key=f"{key}_teams", placeholder="Team", width=170,
                                       label_visibility="collapsed")
        sel_its = []
        if iterations:
            opts = [NONE_ID] + list(lk["iterations"])
            sel_its = st.multiselect(
                "Iteration", opts, default=default_iterations, key=f"{key}_its", placeholder="Iteration",
                format_func=lambda i: "No iteration" if i == NONE_ID else lk["iterations"][i], width=190,
                label_visibility="collapsed")
        sel_areas = []
        if areas and lk["areas"]:
            sel_areas = st.multiselect("Area", list(lk["areas"]), key=f"{key}_areas", placeholder="Area",
                                       format_func=lambda i: lk["areas"][i], width=160,
                                       label_visibility="collapsed")
        sel_tags = []
        if tags and lk["tags"]:
            sel_tags = st.multiselect("Tags", lk["tags"], key=f"{key}_tags", placeholder="Tags", width=170,
                                      label_visibility="collapsed")
        sel_prio = []
        if priority:
            sel_prio = st.multiselect("Priority", config.PRIORITIES, key=f"{key}_prio", placeholder="Priority",
                                      format_func=lambda p: config.PRIORITY_LABELS[p], width=160,
                                      label_visibility="collapsed")

    out = df
    if text:
        q = text.strip().lstrip("#")
        mask = out["title"].str.contains(re.escape(q), case=False, na=False)
        if q.isdigit():
            mask |= out["id"] == int(q)
        out = out[mask]
    if sel_types:
        out = out[out["type"].isin(sel_types)]
    if sel_states:
        out = out[out["state"].isin(sel_states)]
    if sel_people:
        ids = [i for i in sel_people if i != NONE_ID]
        mask = out["assigned_to"].isin(ids)
        if NONE_ID in sel_people:
            mask |= out["assigned_to"].isna()
        out = out[mask.fillna(False).astype(bool)]
    if sel_teams:
        out = out[out["assigned_team"].isin(sel_teams).fillna(False).astype(bool)]
    if sel_its:
        ids = [i for i in sel_its if i != NONE_ID]
        mask = out["iteration_id"].isin(ids)
        if NONE_ID in sel_its:
            mask |= out["iteration_id"].isna()
        out = out[mask.fillna(False).astype(bool)]
    if sel_areas:
        out = out[out["area_id"].isin(sel_areas).fillna(False).astype(bool)]
    if sel_tags:
        wanted = {t.lower() for t in sel_tags}
        out = out[out["tags"].map(lambda s: bool(wanted & {t.lower() for t in s.split(", ") if t}))]
    if sel_prio:
        out = out[out["priority"].isin(sel_prio)]
    return out


# --- dialog: edit work item --------------------------------------------------------------------------------------


def _snapshot(item: dict) -> dict:
    snap = {f: item.get(f) for f in repo.EDITABLE_FIELDS}
    snap["tags"] = list(item.get("tag_list") or [])
    snap["rev"] = item.get("rev")
    return snap


def _edit_dialog(item_id: int) -> None:
    item = repo.get_work_item(item_id)
    if not item or item.get("deleted_at"):
        flash(f"Work item {item_id} does not exist.", "⚠️")
        return
    # Fresh starting point every time the dialog is opened.
    st.session_state[f"_base{item_id}"] = _snapshot(item)
    st.session_state.pop(f"_conflict{item_id}", None)
    title = f"{icon(item['type'])} {item['type']} {item_id}"
    st.dialog(title, width="large", on_dismiss="rerun")(_edit_body)(item_id)


def _reload(item_id: int) -> None:
    """Discard pending edits in the form and start again from the database."""
    item = repo.get_work_item(item_id)
    if item:
        st.session_state[f"_base{item_id}"] = _snapshot(item)
    st.session_state.pop(f"_conflict{item_id}", None)
    st.session_state[f"_v{item_id}"] = st.session_state.get(f"_v{item_id}", 0) + 1


def _after_own_change(item_id: int, tab: str) -> None:
    """Our own link/comment changes bump the revision; keep the base in step so no false warning appears."""
    item = repo.get_work_item(item_id)
    base = st.session_state.get(f"_base{item_id}")
    if item and base is not None:
        base["rev"] = item["rev"]
    st.session_state[f"_tab{item_id}"] = tab


def _planning_inputs(item_type: str, values: dict, k: str) -> dict:
    out = {}
    fields = config.PLANNING_FIELDS[item_type]
    cols = st.columns(len(fields))
    for col, field in zip(cols, fields):
        label = config.FIELD_LABELS[field]
        with col:
            if field == "severity":
                out[field] = st.selectbox(label, config.SEVERITIES,
                                          index=_index(config.SEVERITIES, values.get(field) or "3 - Medium"),
                                          key=k + field)
            elif field in ("start_date", "target_date"):
                out[field] = st.date_input(label, value=to_date(values.get(field)), key=k + field,
                                           format="YYYY-MM-DD")
            elif field == "business_value":
                v = values.get(field)
                out[field] = st.number_input(label, min_value=0, step=1, key=k + field,
                                             value=None if blank(v) else int(v))
            else:
                v = values.get(field)
                unit = " (h)" if field in ("original_estimate", "remaining_work", "completed_work") else ""
                out[field] = st.number_input(label + unit, min_value=0.0, step=1.0, format="%.1f", key=k + field,
                                             value=None if blank(v) else float(v))
    return out


def _edit_body(item_id: int) -> None:
    show_flash()
    item = repo.get_work_item(item_id)
    if not item or item.get("deleted_at"):
        st.warning("This work item has been deleted.")
        return
    lk = lookups()
    item_type = item["type"]
    version = st.session_state.setdefault(f"_v{item_id}", 0)
    base = st.session_state.setdefault(f"_base{item_id}", _snapshot(item))
    k = f"wi{item_id}_{version}_"

    ancestors = repo.get_ancestors(item_id)
    if ancestors:
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            for a in ancestors:
                if st.button(f"{icon(a['type'])} {a['id']} {md_escape(a['title'])}  ›", key=f"{k}crumb{a['id']}",
                             type="tertiary"):
                    open_item(a["id"])
                    st.rerun()

    st.html(
        f'<div class="wi-meta">{state_badge(item["state"])}<span>{person(item.get("assigned_name"))}</span>'
        f'<span class="wi-muted">Created by {esc(item.get("created_by_name") or "—")} on '
        f'{esc(item["created_at"][:16])} · Updated {esc(item["updated_at"][:16])} · rev {esc(item["rev"])}</span></div>')

    conflict = st.session_state.get(f"_conflict{item_id}")
    if conflict:
        st.error(conflict["message"], icon="⚠️")
        c1, c2, _ = st.columns([1.3, 1.5, 2])
        if c1.button("Load latest version", key=f"{k}reload", icon=":material/refresh:"):
            _reload(item_id)
            st.rerun(scope="fragment")
        if c2.button("Overwrite with my changes", key=f"{k}force", icon=":material/warning:"):
            try:
                repo.update_work_item(item_id, conflict["changes"], uid(), tags=conflict["tags"])
                flash(f"#{item_id} saved (overwrote the other changes).")
                _reload(item_id)
            except BoardsError as exc:
                st.session_state[f"_conflict{item_id}"]["message"] = str(exc)
            st.rerun(scope="fragment")
    elif base.get("rev") is not None and item["rev"] != base["rev"]:
        c1, c2 = st.columns([4, 1.2], vertical_alignment="center")
        c1.info("Someone else changed this item after you opened it.", icon="🔄")
        if c2.button("Load latest", key=f"{k}reload_info", icon=":material/refresh:"):
            _reload(item_id)
            st.rerun(scope="fragment")

    links = repo.get_links(item_id)
    comments = repo.list_comments(item_id)
    labels = ["Details", f"Links ({len(links)})", f"Discussion ({len(comments)})", "History"]
    wanted = st.session_state.pop(f"_tab{item_id}", None)
    default_tab = next((label for label in labels if wanted and label.startswith(wanted)), None)
    tab_details, tab_links, tab_discussion, tab_history = st.tabs(labels, default=default_tab)

    with tab_details:
        _details_tab(item, base, lk, k, version)
    with tab_links:
        _links_tab(item, links, k)
    with tab_discussion:
        _discussion_tab(item_id, comments, k)
    with tab_history:
        _history_tab(item_id)


def _details_tab(item: dict, base: dict, lk: dict, k: str, version: int) -> None:
    item_id, item_type = int(item["id"]), item["type"]
    with st.form(k + "form", border=False):
        new_title = st.text_input("Title", base["title"], key=k + "title", max_chars=config.MAX_TITLE)
        c1, c2, c3, c4 = st.columns(4)
        states = config.STATES[item_type]
        state = c1.selectbox("State", states, index=_index(states, base["state"]), key=k + "state")
        user_opts = [None] + [u for u in lk["users"] if u in lk["active_users"] or u == base.get("assigned_to")]
        assigned = c2.selectbox("Assigned to", user_opts, index=_index(user_opts, base.get("assigned_to")),
                                format_func=lambda u: "Unassigned" if u is None else lk["users"][u],
                                key=k + "assigned")
        priority = c3.selectbox("Priority", config.PRIORITIES, index=_index(config.PRIORITIES, base["priority"]),
                                format_func=lambda p: config.PRIORITY_LABELS[p], key=k + "priority")
        value_area = c4.selectbox("Value area", config.VALUE_AREAS,
                                  index=_index(config.VALUE_AREAS, base["value_area"]), key=k + "value_area")
        c1, c2 = st.columns(2)
        it_opts = [None] + list(lk["iterations"])
        iteration = c1.selectbox("Iteration", it_opts, index=_index(it_opts, base.get("iteration_id")),
                                 format_func=lambda i: "No iteration" if i is None else lk["iterations"][i],
                                 key=k + "iteration")
        area_opts = [None] + list(lk["areas"])
        area = c2.selectbox("Area", area_opts, index=_index(area_opts, base.get("area_id")),
                            format_func=lambda a: "No area" if a is None else lk["areas"][a], key=k + "area")
        tags = st.multiselect("Tags", sorted(set(lk["tags"]) | set(base["tags"]), key=str.lower),
                              default=base["tags"], accept_new_options=True, key=k + "tags",
                              placeholder="Add tags (type to create new ones)")
        planning = _planning_inputs(item_type, base, k)
        desc_label = "Repro steps" if item_type == "Bug" else "Description"
        description = st.text_area(desc_label + " (Markdown)", base["description"], height=140,
                                   key=k + "description", max_chars=config.MAX_TEXT)
        acceptance = None
        if item_type != "Task":
            acceptance = st.text_area("Acceptance criteria (Markdown)", base["acceptance_criteria"], height=100,
                                      key=k + "acceptance", max_chars=config.MAX_TEXT)
        b1, b2, _ = st.columns([1, 1, 3])
        save = b1.form_submit_button("Save", type="primary", icon=":material/save:", width="stretch")
        save_close = b2.form_submit_button("Save & close", width="stretch")

    if save or save_close:
        form = {"title": new_title, "state": state, "assigned_to": assigned, "priority": priority,
                "value_area": value_area, "iteration_id": iteration, "area_id": area,
                "description": description, **planning}
        if acceptance is not None:
            form["acceptance_criteria"] = acceptance
        # Only send what the user actually changed, so other people's edits to other fields survive.
        changes = {f: v for f, v in form.items() if not repo._same(v, base.get(f))}
        tags_changed = sorted(t.lower() for t in tags) != sorted(t.lower() for t in base["tags"])
        try:
            changed = repo.update_work_item(
                item_id, changes, uid(), tags=tags if tags_changed else None,
                base={f: base.get(f) for f in changes}, base_tags=base["tags"] if tags_changed else None)
        except ConflictError as exc:
            st.session_state[f"_conflict{item_id}"] = {
                "message": str(exc), "changes": changes, "tags": tags if tags_changed else None}
            st.rerun(scope="fragment")
        except BoardsError as exc:
            st.error(str(exc))
        else:
            if changed:
                flash(f"#{item_id} saved: {', '.join(config.FIELD_LABELS.get(f, f) for f in changed)}")
            else:
                flash("Nothing to save.", "ℹ️")
            _reload(item_id)
            st.rerun(scope="app" if save_close else "fragment")

    with st.expander("Preview description", icon=":material/visibility:"):
        st.markdown(item["description"] or "_No description._")
        if item["acceptance_criteria"]:
            st.markdown("**Acceptance criteria**")
            st.markdown(item["acceptance_criteria"])

    with st.popover("Delete", icon=":material/delete:"):
        st.write(f"Move **{item_type} {item_id}** to the recycle bin? You can restore it from Settings.")
        if st.button("Confirm delete", type="primary", key=k + "delete"):
            try:
                repo.delete_work_item(item_id, uid())
                flash(f"#{item_id} moved to the recycle bin.", "🗑️")
            except BoardsError as exc:
                flash(str(exc), "⚠️")
            st.rerun()


def _link_row(row, k: str, remove_label: str | None, on_remove=None) -> None:
    c1, c2, c3, c4 = st.columns([6, 2, 2.2, 0.6], vertical_alignment="center")
    if c1.button(f"{icon(row['type'])} {row['id']} · {md_escape(row['title'])}", key=f"{k}open{row['kind']}{row['id']}",
                 type="tertiary"):
        open_item(row["id"])
        st.rerun()
    c2.html(state_badge(row["state"]))
    c3.html(person(row.get("assigned_name")))
    if on_remove is not None:
        if c4.button("", icon=":material/link_off:", key=f"{k}rm{row['kind']}{row['id']}", type="tertiary",
                     help=remove_label):
            try:
                on_remove()
                flash("Link removed.")
            except BoardsError as exc:
                flash(str(exc), "⚠️")
            st.rerun(scope="fragment")


def _links_tab(item: dict, links: pd.DataFrame, k: str) -> None:
    item_id, item_type = int(item["id"]), item["type"]

    def remove_parent():
        repo.update_work_item(item_id, {"parent_id": None}, uid())
        _after_own_change(item_id, "Links")

    def unlink_child(child_id):
        def run():
            repo.update_work_item(child_id, {"parent_id": None}, uid())
            _after_own_change(item_id, "Links")
        return run

    def remove_link(link_id):
        def run():
            repo.remove_link(link_id, uid())
            _after_own_change(item_id, "Links")
        return run

    parent = links[links["kind"] == "parent"]
    children = links[links["kind"] == "child"]
    others = links[~links["kind"].isin(["parent", "child"])]

    st.markdown("**Parent**")
    if parent.empty:
        st.caption("No parent.")
    for row in parent.to_dict("records"):
        _link_row(row, k, "Remove parent", remove_parent)

    st.markdown(f"**Children ({len(children)})**")
    if children.empty:
        st.caption("No children.")
    else:
        active = children[children["state"] != "Removed"]
        done = int((active["state"] == "Closed").sum())
        st.progress(done / len(active) if len(active) else 0.0, text=f"{done} of {len(active)} done")
        for row in children.to_dict("records"):
            _link_row(row, k, "Unlink child", unlink_child(int(row["id"])))

    siblings = repo.get_same_parent(item_id)
    if not siblings.empty:
        with st.expander(f"Same parent ({len(siblings)})", icon=":material/account_tree:"):
            for row in siblings.to_dict("records"):
                _link_row({**row, "kind": "same"}, k, None)

    st.markdown("**Other links**")
    if others.empty:
        st.caption("No other links yet.")
    for kind in ["sibling", "related", "predecessor", "successor", "duplicate_of", "duplicate"]:
        group = others[others["kind"] == kind]
        if group.empty:
            continue
        st.caption(config.LINK_KINDS[kind])
        for row in group.to_dict("records"):
            _link_row(row, k, f"Remove {config.LINK_KINDS[kind].lower()} link", remove_link(int(row["link_id"])))

    st.markdown("**Add link**")
    all_items = repo.load_work_items()
    all_items = all_items[all_items["id"] != item_id]
    labels = {int(r.id): item_label(r.id, r.type, r.title) for r in all_items.itertuples()}
    with st.form(k + "addlink", clear_on_submit=True, border=True):
        c1, c2 = st.columns([1.3, 4], vertical_alignment="bottom")
        kind = c1.selectbox("Link type", list(config.LINK_KINDS), format_func=config.LINK_KINDS.get, key=k + "lkind")
        target = c2.selectbox("Work item", list(labels), format_func=labels.get, index=None,
                              placeholder="Search by title or ID", key=k + "ltarget")
        if st.form_submit_button("Add link", icon=":material/add_link:"):
            try:
                repo.add_link(item_id, kind, target, uid())
                _after_own_change(item_id, "Links")
                flash(f"Linked as {config.LINK_KINDS[kind].lower()}.")
                st.rerun(scope="fragment")
            except BoardsError as exc:
                st.error(str(exc))

    st.markdown("**New child**")
    suggested = config.AGILE_CHILDREN[item_type] or ["Task"]
    child_types = suggested + [t for t in config.WORK_ITEM_TYPES if t not in suggested]
    with st.form(k + "addchild", clear_on_submit=True, border=True):
        c1, c2, c3 = st.columns([2, 5, 2], vertical_alignment="bottom")
        child_type = c1.selectbox("Type", child_types, format_func=lambda t: f"{icon(t)} {t}", key=k + "ctype")
        child_title = c2.text_input("Title", key=k + "ctitle", max_chars=config.MAX_TITLE)
        estimate = c3.number_input("Estimate", min_value=0.0, step=1.0, value=None, key=k + "cest",
                                   help="Story Points (stories/bugs), hours (tasks) or effort (epics/features)")
        if st.form_submit_button("Add child", icon=":material/add:"):
            data = {"type": child_type, "title": child_title, "parent_id": item_id,
                    "iteration_id": item.get("iteration_id"), "area_id": item.get("area_id"),
                    "assigned_to": uid() if child_type == "Task" else None}
            if estimate is not None:
                data[{"Task": "original_estimate", "Feature": "effort", "Epic": "effort"}.get(
                    child_type, "story_points")] = estimate
            try:
                new_id = repo.create_work_item(data, uid())
                _after_own_change(item_id, "Links")
                flash(f"{child_type} {new_id} created.")
                st.rerun(scope="fragment")
            except BoardsError as exc:
                st.error(str(exc))


def _discussion_tab(item_id: int, comments: pd.DataFrame, k: str) -> None:
    with st.form(k + "comment", clear_on_submit=True):
        body = st.text_area("Add a comment", placeholder="Write a comment (Markdown supported)", height=90,
                            key=k + "cbody", label_visibility="collapsed", max_chars=config.MAX_COMMENT)
        if st.form_submit_button("Comment", icon=":material/send:"):
            try:
                repo.add_comment(item_id, uid(), body)
                _after_own_change(item_id, "Discussion")
                st.rerun(scope="fragment")
            except BoardsError as exc:
                st.error(str(exc))
    for c in comments.itertuples():
        with st.container(border=True):
            st.html(f'<div class="wi-meta">{person(c.user_name)}'
                    f'<span class="wi-muted">{esc(c.created_at[:16])}</span></div>')
            st.markdown(c.body)
    if comments.empty:
        st.caption("No comments yet.")


def _history_tab(item_id: int) -> None:
    hist = repo.list_history(item_id)
    if hist.empty:
        st.caption("No history.")
        return
    table = pd.DataFrame({
        "When": hist["changed_at"].str[:16],
        "Who": hist["user_name"].fillna("—"),
        "Field": hist["field"].map(lambda f: config.FIELD_LABELS.get(f, f)),
        "From": hist["old_value"].fillna(""),
        "To": hist["new_value"].fillna(""),
    })
    st.dataframe(table, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(table)))


# --- dialog: new work item ---------------------------------------------------------------------------------------


def _new_dialog(defaults: dict) -> None:
    st.dialog("New work item", width="large")(_new_body)(defaults)


def _new_body(defaults: dict) -> None:
    lk = lookups()
    item_type = st.segmented_control(
        "Type", config.WORK_ITEM_TYPES, default=defaults.get("type") or "User Story", required=True,
        format_func=lambda t: f"{icon(t)} {t}", key="new_type",
    )
    k = f"new_{item_type}_"
    with st.form(k + "form", border=False):
        title = st.text_input("Title", key=k + "title", placeholder="e.g. As a customer, I want…",
                              max_chars=config.MAX_TITLE)
        c1, c2, c3 = st.columns(3)
        state = c1.selectbox("State", config.STATES[item_type], key=k + "state")
        user_opts = [None] + lk["active_users"]
        assigned = c2.selectbox("Assigned to", user_opts,
                                format_func=lambda u: "Unassigned" if u is None else lk["users"][u],
                                key=k + "assigned")
        priority = c3.selectbox("Priority", config.PRIORITIES, index=1,
                                format_func=lambda p: config.PRIORITY_LABELS[p], key=k + "priority")
        c1, c2, c3 = st.columns(3)
        it_opts = [None] + list(lk["iterations"])
        iteration = c1.selectbox("Iteration", it_opts, index=_index(it_opts, defaults.get("iteration_id")),
                                 format_func=lambda i: "No iteration" if i is None else lk["iterations"][i],
                                 key=k + "iteration")
        area_opts = [None] + list(lk["areas"])
        area = c2.selectbox("Area", area_opts, index=_index(area_opts, defaults.get("area_id")),
                            format_func=lambda a: "No area" if a is None else lk["areas"][a], key=k + "area")
        candidates = repo.parent_candidates(item_type)
        parent_labels = {int(r.id): item_label(r.id, r.type, r.title) for r in candidates.itertuples()}
        parent_opts = [None] + list(parent_labels)
        parent = c3.selectbox("Parent", parent_opts, index=_index(parent_opts, defaults.get("parent_id")),
                              format_func=lambda p: "No parent" if p is None else parent_labels[p], key=k + "parent")
        tags = st.multiselect("Tags", lk["tags"], accept_new_options=True, key=k + "tags",
                              placeholder="Add tags (type to create new ones)")
        planning = _planning_inputs(item_type, {}, k)
        description = st.text_area("Repro steps" if item_type == "Bug" else "Description",
                                   height=120, key=k + "description", max_chars=config.MAX_TEXT)
        open_after = st.checkbox("Open the item after creating it", key=k + "open")
        submitted = st.form_submit_button("Create", type="primary", icon=":material/add:")

    if submitted:
        data = {"type": item_type, "title": title, "state": state, "assigned_to": assigned, "priority": priority,
                "iteration_id": iteration, "area_id": area, "description": description, "parent_id": parent,
                **planning}
        try:
            new_id = repo.create_work_item(data, uid(), tags=tags)
        except BoardsError as exc:
            st.error(str(exc))
            return
        flash(f"{item_type} {new_id} created.")
        if open_after:
            open_item(new_id)
        st.rerun()
