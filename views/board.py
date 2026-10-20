import streamlit as st

from boards import config, ui
from boards import repository as repo
from boards.errors import BoardsError, ConflictError
from boards.kanban import event, kanban

CLOSED_LIMIT = 25
KEY = "board_kanban"

st.title("Boards")
ui.live_updates("board")

level = st.segmented_control("Backlog", list(config.BACKLOG_LEVELS), default="Stories", required=True,
                             key="board_level", label_visibility="collapsed")
types = config.BACKLOG_LEVELS[level]


def on_moved() -> None:
    """Apply a drag and drop before the page reloads, so the board never flickers back."""
    move = event(KEY, "moved")
    if not move:
        return
    items = repo.load_work_items()
    column = items[(items["state"] == move["to"]) & items["type"].isin(types) & (items["id"] != move["id"])]
    order = column.sort_values(["backlog_rank", "id"])["id"].astype(int).tolist()
    position = order.index(move["before"]) if move.get("before") in order else len(order)
    order.insert(position, int(move["id"]))
    try:
        repo.move_item(int(move["id"]), ui.uid(), state=move["to"] if move["to"] != move["from"] else None,
                       expected_state=move["from"], order_ids=order)
        if move["to"] != move["from"]:
            ui.flash(f"#{move['id']} moved to {move['to']}", "↪️")
    except ConflictError:
        ui.flash(f"#{move['id']} was just moved by someone else. The board has been refreshed.", "⚠️")
    except BoardsError as exc:
        ui.flash(str(exc), "⚠️")


def on_opened() -> None:
    opened = event(KEY, "opened")
    if opened:
        ui.open_item(opened["id"])


def on_add() -> None:
    if event(KEY, "add"):
        ui.open_new(types[0])


items = repo.load_work_items()
scope = items[items["type"].isin(types) & items["state"].isin(config.BOARD_COLUMNS)]
filtered = ui.filter_bar(scope, "board", types=types if len(types) > 1 else None)
wip = (repo.get_setting("wip_limits") or {}).get(level, {})

columns, cards = [], []
for i, state in enumerate(config.BOARD_COLUMNS):
    col = filtered[filtered["state"] == state].sort_values(["backlog_rank", "id"])
    more = None
    if state == "Closed" and len(col) > CLOSED_LIMIT:
        hidden = len(col) - CLOSED_LIMIT
        col = col.sort_values("closed_at", ascending=False).head(CLOSED_LIMIT).sort_values(["backlog_rank", "id"])
        more = f"+{hidden} older closed items (see Work items)"
    columns.append(ui.column_payload(state, int((filtered["state"] == state).sum()), limit=wip.get(state),
                                     add=i == 0, more_text=more))
    cards += [ui.card_payload(r, show_iteration=True, show_parent=True,
                              allowed=[s for s in config.BOARD_COLUMNS if s in config.STATES[r["type"]]])
              for r in col.to_dict("records")]

st.caption("Drag cards between columns to change their state, or within a column to reorder. "
           "Click a card to open it.")
kanban(key=KEY, columns=columns, cards=cards, add_label=f"New {types[0]}",
       empty_text=f"No {level.lower()} match the filters.",
       on_moved=on_moved, on_opened=on_opened, on_add=on_add)
