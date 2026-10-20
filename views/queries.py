import pandas as pd
import streamlit as st

from boards import config, ui
from boards import repository as repo

st.title("Work items")
ui.live_updates("queries")

items = repo.load_work_items()

with st.container(horizontal=True, vertical_alignment="center"):
    preset = st.segmented_control(
        "View", ["All", "Assigned to me", "Created by me", "Open", "Recently updated"],
        default="All", required=True, key="q_preset", label_visibility="collapsed")
    st.button("New work item", icon=":material/add:", on_click=ui.open_new)

me = ui.uid()
if preset == "Assigned to me":
    items = items[(items["assigned_to"] == me).fillna(False).astype(bool)]
elif preset == "Created by me":
    items = items[(items["created_by"] == me).fillna(False).astype(bool)]
elif preset == "Open":
    items = items[~items["state"].isin(config.INACTIVE_STATES)]
elif preset == "Recently updated":
    items = items.sort_values("updated_at", ascending=False).head(50)

filtered = ui.filter_bar(items, "q", types=config.WORK_ITEM_TYPES, states=True, priority=True)
if preset == "Recently updated":
    filtered = filtered.sort_values("updated_at", ascending=False)

st.caption(f"{len(filtered)} work items")
table = pd.DataFrame({
    "ID": filtered["id"].astype(int),
    "Type": [f"{ui.icon(t)} {t}" for t in filtered["type"]],
    "Title": filtered["title"],
    "State": filtered["state"],
    "Assigned to": filtered["assigned_name"].fillna(""),
    "Team": filtered["assigned_team"].fillna(""),
    "Priority": filtered["priority"].astype(int),
    "Iteration": filtered["iteration_name"].fillna(""),
    "Area": filtered["area_name"].fillna(""),
    "Parent": [f"{int(p)}" if not ui.blank(p) else "" for p in filtered["parent_id"]],
    "Tags": filtered["tags"],
    "Story Points": filtered["story_points"],
    "Remaining (h)": filtered["remaining_work"],
    "Created": pd.to_datetime(filtered["created_at"]),
    "Updated": pd.to_datetime(filtered["updated_at"]),
})
ui.item_table(table, "queries", height=min(700, 38 + 35 * max(len(table), 1)), column_config={
    "ID": st.column_config.NumberColumn(width=60, format="%d"),
    "Title": st.column_config.TextColumn(width="large"),
    "Story Points": st.column_config.NumberColumn(format="%.0f", width=90),
    "Remaining (h)": st.column_config.NumberColumn(format="%.1f", width=90),
    "Created": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
    "Updated": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
})
st.download_button("Export CSV", table.to_csv(index=False).encode("utf-8-sig"), "work_items.csv", "text/csv",
                   icon=":material/download:")
