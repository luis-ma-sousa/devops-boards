"""Drag-and-drop Kanban board built as a Streamlit v2 component (no external dependencies).

Cards are dragged with pointer events, so it works with a mouse, a pen and touch screens.
Clicking a card opens it; Alt+Left/Right moves the focused card between columns.
All user text is inserted with ``textContent``, never as HTML.
"""

from collections.abc import Callable

import streamlit as st

CSS = r"""
.kb {
  --kb-text: var(--st-text-color, #31333f);
  --kb-bg: var(--st-background-color, #ffffff);
  --kb-lane: var(--st-secondary-background-color, #f0f2f6);
  --kb-border: color-mix(in srgb, var(--kb-text) 16%, transparent);
  --kb-muted: color-mix(in srgb, var(--kb-text) 62%, transparent);
  --kb-primary: var(--st-primary-color, #0078d4);
  color: var(--kb-text);
  font-family: var(--st-font, "Source Sans Pro", "Source Sans 3", sans-serif);
  font-size: 14px;
  line-height: 1.35;
  overflow-x: auto;
  padding-bottom: 4px;
}
.kb-row {
  display: grid;
  grid-template-columns: repeat(var(--kb-cols), minmax(180px, 1fr));
  gap: 10px;
  min-width: calc(var(--kb-cols) * 190px);
}
.kb.kb-lanes .kb-row {
  grid-template-columns: minmax(210px, 1.25fr) repeat(var(--kb-cols), minmax(170px, 1fr));
  min-width: calc(220px + var(--kb-cols) * 180px);
}
.kb-col-head {
  display: flex; align-items: center; gap: 8px; font-weight: 600;
  border-top: 3px solid #888; padding: 7px 2px 5px;
}
.kb-col-name { flex: 1; }
.kb-count { font-weight: 400; color: var(--kb-muted); font-size: 13px; }
.kb-count.kb-over { color: #d03b3b; font-weight: 700; }
.kb-add, .kb-add-lane {
  border: 1px solid var(--kb-border); background: transparent; color: var(--kb-text);
  border-radius: 6px; cursor: pointer; font: inherit; font-size: 13px; padding: 1px 8px;
}
.kb-add:hover, .kb-add-lane:hover { border-color: var(--kb-primary); color: var(--kb-primary); }
.kb-add-lane { margin-top: 6px; }
.kb-lane { margin-top: 8px; }
.kb.kb-lanes .kb-lane { padding-top: 10px; border-top: 1px solid var(--kb-border); }
.kb-lane-label { font-weight: 600; color: var(--kb-muted); padding: 6px 2px; }
.kb-cell {
  background: color-mix(in srgb, var(--kb-lane) 70%, transparent);
  border-radius: 8px; padding: 6px; min-height: 76px;
  display: flex; flex-direction: column; gap: 6px;
}
.kb-cell.kb-over { outline: 2px dashed var(--kb-primary); outline-offset: -2px; }
.kb-cell.kb-deny { outline: 2px dashed #d03b3b; outline-offset: -2px; }
.kb-card {
  background: var(--kb-bg); border: 1px solid var(--kb-border); border-left: 4px solid #999;
  border-radius: 6px; padding: 7px 9px 8px; cursor: grab; user-select: none; -webkit-user-select: none;
  touch-action: none; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06); display: flex; flex-direction: column; gap: 4px;
}
.kb-card:hover { border-color: color-mix(in srgb, var(--kb-primary) 55%, transparent); }
.kb-card:focus-visible { outline: 2px solid var(--kb-primary); outline-offset: 1px; }
.kb-card.kb-static { cursor: pointer; touch-action: auto; }
.kb-card.kb-hidden { display: none; }
.kb-top { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--kb-muted); }
.kb-prio { margin-left: auto; }
.kb-title { font-weight: 600; font-size: 14px; overflow-wrap: anywhere; }
.kb-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 3px 10px; font-size: 12.5px; }
.kb-muted { color: var(--kb-muted); }
.kb-person { display: inline-flex; align-items: center; gap: 5px; }
.kb-avatar {
  width: 20px; height: 20px; border-radius: 50%; color: #fff; font-size: 9.5px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.kb-avatar.kb-none { background: color-mix(in srgb, var(--kb-text) 30%, transparent); }
.kb-state { display: inline-flex; align-items: center; gap: 4px; }
.kb-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.kb-tags { display: flex; flex-wrap: wrap; gap: 3px; }
.kb-tag {
  font-size: 11px; padding: 0 7px; border-radius: 10px; line-height: 1.6;
  background: color-mix(in srgb, var(--kb-text) 10%, transparent);
}
.kb-progress { font-size: 11.5px; color: var(--kb-muted); }
.kb-bar { height: 4px; border-radius: 2px; background: color-mix(in srgb, var(--kb-text) 14%, transparent); overflow: hidden; }
.kb-bar > span { display: block; height: 100%; background: #339933; }
.kb-placeholder {
  border: 2px dashed var(--kb-primary); border-radius: 6px;
  background: color-mix(in srgb, var(--kb-primary) 8%, transparent);
}
.kb-ghost {
  position: fixed; left: 0; top: 0; z-index: 100000; pointer-events: none; margin: 0;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.28); opacity: 0.96; cursor: grabbing;
}
.kb-more { font-size: 12px; color: var(--kb-muted); text-align: center; padding: 2px; }
.kb-empty { color: var(--kb-muted); padding: 18px 4px; }
"""

JS = r"""
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const root = parentElement;
  const previous = root.querySelector(".kb");
  if (previous) previous.remove();

  const hasLanes = data.lanes.some((lane) => lane.card || lane.title);
  const board = el("div", "kb" + (hasLanes ? " kb-lanes" : ""));
  board.style.setProperty("--kb-cols", String(data.columns.length));
  root.appendChild(board);

  const cardsById = new Map(data.cards.map((c) => [c.id, c]));
  const nonce = () => `${Date.now()}-${Math.random()}`;
  let drag = null;
  let scrollFrame = null;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function renderCard(card, isStatic) {
    const node = el("div", "kb-card" + (isStatic ? " kb-static" : ""));
    node.style.borderLeftColor = card.color;
    node.dataset.id = String(card.id);
    node.tabIndex = 0;
    node.setAttribute("role", "button");
    node.setAttribute("aria-label", `${card.type} ${card.id}: ${card.title}`);

    const top = el("div", "kb-top");
    top.append(el("span", null, card.icon), el("span", null, card.id));
    if (card.state) {
      const st = el("span", "kb-state");
      const dot = el("span", "kb-dot");
      dot.style.background = card.stateColor || "#999";
      st.append(dot, el("span", null, card.state));
      top.append(st);
    }
    const prio = el("span", "kb-prio", `P${card.priority}`);
    prio.title = "Priority";
    top.append(prio);
    node.append(top, el("div", "kb-title", card.title));

    const meta = el("div", "kb-meta");
    const person = el("span", "kb-person");
    const avatar = el("span", "kb-avatar" + (card.assigned ? "" : " kb-none"), card.assigned ? card.initials : "?");
    if (card.assigned) avatar.style.background = card.avatar;
    person.append(avatar, card.assigned ? el("span", null, card.assigned) : el("span", "kb-muted", "Unassigned"));
    meta.append(person);
    for (const item of card.meta || []) meta.append(el("span", "kb-muted", item));
    node.append(meta);

    if (card.tags && card.tags.length) {
      const tags = el("div", "kb-tags");
      for (const t of card.tags) tags.append(el("span", "kb-tag", t));
      node.append(tags);
    }
    if (card.progress) {
      const [done, total] = card.progress;
      node.append(el("div", "kb-progress", `${done}/${total} children done`));
      const bar = el("div", "kb-bar");
      const fill = el("span");
      fill.style.width = `${total ? Math.round((100 * done) / total) : 0}%`;
      bar.append(fill);
      node.append(bar);
    }

    node.addEventListener("keydown", (e) => onKey(e, card, isStatic));
    if (isStatic) {
      node.addEventListener("click", () => setTriggerValue("opened", { id: card.id, nonce: nonce() }));
    } else {
      node.addEventListener("pointerdown", onDown);
      node.addEventListener("pointermove", onMove);
      node.addEventListener("pointerup", onUp);
      node.addEventListener("pointercancel", cancelDrag);
      node.addEventListener("lostpointercapture", () => { if (drag && drag.started) cancelDrag(); });
    }
    return node;
  }

  // Header
  const head = el("div", "kb-row");
  if (hasLanes) head.append(el("div", "kb-col-head", data.laneTitle || ""));
  for (const col of data.columns) {
    const h = el("div", "kb-col-head");
    h.style.borderTopColor = col.color;
    const over = col.limit && col.count > col.limit;
    const count = el("span", "kb-count" + (over ? " kb-over" : ""), col.limit ? `${col.count}/${col.limit}` : col.count);
    if (col.limit) count.title = "WIP limit";
    h.append(el("span", "kb-col-name", col.label), count);
    if (col.add) {
      const add = el("button", "kb-add", "+");
      add.type = "button";
      add.title = data.addLabel || "New item";
      add.addEventListener("click", () => setTriggerValue("add", { column: col.id, lane: null, nonce: nonce() }));
      h.append(add);
    }
    head.append(h);
  }
  board.append(head);

  // Lanes and cells
  for (const lane of data.lanes) {
    const row = el("div", "kb-row kb-lane");
    if (hasLanes) {
      const laneHead = el("div");
      if (lane.card) laneHead.append(renderCard(lane.card, true));
      else laneHead.append(el("div", "kb-lane-label", lane.title || ""));
      if (lane.addLabel) {
        const add = el("button", "kb-add-lane", `+ ${lane.addLabel}`);
        add.type = "button";
        add.addEventListener("click", () => setTriggerValue("add", { column: null, lane: lane.id, nonce: nonce() }));
        laneHead.append(add);
      }
      row.append(laneHead);
    }
    for (const col of data.columns) {
      const cell = el("div", "kb-cell");
      cell.dataset.col = col.id;
      cell.dataset.lane = lane.id;
      for (const card of data.cards) {
        if (card.lane === lane.id && card.column === col.id) cell.append(renderCard(card, false));
      }
      if (col.moreText && !hasLanes) cell.append(el("div", "kb-more", col.moreText));
      row.append(cell);
    }
    board.append(row);
  }
  if (!data.cards.length && !hasLanes && data.emptyText) board.append(el("div", "kb-empty", data.emptyText));

  // --- drag and drop ---------------------------------------------------------------------------
  function cellAt(x, y) {
    const hit = root.elementFromPoint ? root.elementFromPoint(x, y) : document.elementFromPoint(x, y);
    return hit && hit.closest ? hit.closest(".kb-cell") : null;
  }

  function allowed(card, cell) {
    if (!cell) return false;
    if (card.allowed && !card.allowed.includes(cell.dataset.col)) return false;
    if (!data.laneMove && cell.dataset.lane !== card.lane) return false;
    return true;
  }

  function nextCard(node) {
    let next = node.nextElementSibling;
    while (next && (!next.classList.contains("kb-card") || next.classList.contains("kb-hidden"))) next = next.nextElementSibling;
    return next;
  }

  function clearHighlight() {
    board.querySelectorAll(".kb-over, .kb-deny").forEach((n) => n.classList.remove("kb-over", "kb-deny"));
  }

  function onDown(e) {
    if (e.button !== 0 || drag) return;
    const node = e.currentTarget;
    drag = { node, id: Number(node.dataset.id), x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY,
             pointerId: e.pointerId, started: false };
    node.setPointerCapture(e.pointerId);
  }

  function start() {
    const rect = drag.node.getBoundingClientRect();
    drag.started = true;
    drag.offX = drag.x0 - rect.left;
    drag.offY = drag.y0 - rect.top;
    const after = nextCard(drag.node);
    drag.origNext = after ? Number(after.dataset.id) : null;
    drag.ghost = drag.node.cloneNode(true);
    drag.ghost.classList.add("kb-ghost");
    drag.ghost.style.width = `${rect.width}px`;
    board.append(drag.ghost);
    const probe = drag.ghost.getBoundingClientRect();  // fixed elements can be offset by transformed ancestors
    drag.fixX = probe.left;
    drag.fixY = probe.top;
    drag.ph = el("div", "kb-placeholder");
    drag.ph.style.height = `${rect.height}px`;
    drag.node.after(drag.ph);
    drag.node.classList.add("kb-hidden");
    autoScroll();
  }

  function onMove(e) {
    if (!drag || e.pointerId !== drag.pointerId) return;
    drag.x = e.clientX;
    drag.y = e.clientY;
    if (!drag.started) {
      if (Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) < 6) return;
      start();
    }
    e.preventDefault();
    drag.ghost.style.transform = `translate(${e.clientX - drag.offX - drag.fixX}px, ${e.clientY - drag.offY - drag.fixY}px) rotate(1.5deg)`;
    track();
  }

  function track() {
    const card = cardsById.get(drag.id);
    const cell = cellAt(drag.x, drag.y);
    clearHighlight();
    if (!cell) return;
    if (!allowed(card, cell)) {
      cell.classList.add("kb-deny");
      return;
    }
    cell.classList.add("kb-over");
    let before = null;
    for (const other of cell.querySelectorAll(":scope > .kb-card:not(.kb-hidden)")) {
      const r = other.getBoundingClientRect();
      if (drag.y < r.top + r.height / 2) { before = other; break; }
    }
    cell.insertBefore(drag.ph, before || cell.querySelector(":scope > .kb-more"));
  }

  function finish(commit) {
    const d = drag;
    drag = null;
    if (scrollFrame) cancelAnimationFrame(scrollFrame);
    scrollFrame = null;
    clearHighlight();
    if (!d || !d.started) return d;
    d.ghost.remove();
    if (!commit) {
      d.ph.remove();
      d.node.classList.remove("kb-hidden");
      return null;
    }
    const cell = d.ph.parentElement;
    const after = nextCard(d.ph);
    d.ph.replaceWith(d.node);
    d.node.classList.remove("kb-hidden");
    const card = cardsById.get(d.id);
    const before = after && after !== d.node ? Number(after.dataset.id) : null;
    const to = cell.dataset.col, toLane = cell.dataset.lane;
    if (to === card.column && toLane === card.lane && before === d.origNext) return null;
    setTriggerValue("moved", { id: d.id, from: card.column, to, fromLane: card.lane, toLane, before, nonce: nonce() });
    return null;
  }

  function onUp(e) {
    if (!drag || e.pointerId !== drag.pointerId) return;
    try { drag.node.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
    const d = finish(true);
    if (d && !d.started) setTriggerValue("opened", { id: d.id, nonce: nonce() });
  }

  function cancelDrag() {
    if (drag) finish(false);
  }

  function scrollParent() {
    let node = root.host || board.parentElement;
    while (node && node !== document.body) {
      const style = getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) return node;
      node = node.parentElement || (node.getRootNode && node.getRootNode().host);
    }
    return document.scrollingElement;
  }

  function autoScroll() {
    const scroller = scrollParent();
    const step = () => {
      if (!drag || !drag.started) return;
      const edge = 70;
      let dy = 0;
      if (drag.y < edge) dy = -Math.ceil((edge - drag.y) / 5);
      else if (drag.y > window.innerHeight - edge) dy = Math.ceil((drag.y - (window.innerHeight - edge)) / 5);
      if (dy && scroller) { scroller.scrollTop += dy; track(); }
      scrollFrame = requestAnimationFrame(step);
    };
    scrollFrame = requestAnimationFrame(step);
  }

  function onKey(e, card, isStatic) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setTriggerValue("opened", { id: card.id, nonce: nonce() });
      return;
    }
    if (isStatic || !e.altKey || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    e.preventDefault();
    const cols = data.columns.map((c) => c.id).filter((c) => !card.allowed || card.allowed.includes(c));
    const idx = cols.indexOf(card.column) + (e.key === "ArrowRight" ? 1 : -1);
    if (idx < 0 || idx >= cols.length) return;
    setTriggerValue("moved", { id: card.id, from: card.column, to: cols[idx], fromLane: card.lane,
                               toLane: card.lane, before: null, nonce: nonce() });
  }

  const onEscape = (e) => { if (e.key === "Escape") cancelDrag(); };
  window.addEventListener("keydown", onEscape);
  return () => {
    window.removeEventListener("keydown", onEscape);
    if (scrollFrame) cancelAnimationFrame(scrollFrame);
  };
}
"""

_component = st.components.v2.component("boards_kanban", css=CSS, js=JS)


def _noop() -> None:
    return None


def event(key: str, name: str):
    """Read a trigger value (``moved``, ``opened`` or ``add``) of a mounted board inside a callback."""
    state = st.session_state.get(key)
    if state is None:
        return None
    if isinstance(state, dict):
        return state.get(name)
    return getattr(state, name, None)


def kanban(*, key: str, columns: list[dict], cards: list[dict], lanes: list[dict] | None = None,
           lane_move: bool = False, lane_title: str = "", add_label: str = "New item", empty_text: str = "",
           on_moved: Callable | None = None, on_opened: Callable | None = None, on_add: Callable | None = None):
    """Render the board.

    columns: ``{"id", "label", "color", "count", "limit", "add", "moreText"}``
    cards:   ``{"id", "lane", "column", "type", "icon", "color", "title", "priority", "assigned",
               "initials", "avatar", "meta", "tags", "progress", "allowed", "state", "stateColor"}``
    lanes:   ``{"id", "title" | "card", "addLabel"}``; omit for a plain board.
    """
    data = {
        "columns": columns,
        "cards": cards,
        "lanes": lanes or [{"id": "_"}],
        "laneMove": lane_move,
        "laneTitle": lane_title,
        "addLabel": add_label,
        "emptyText": empty_text,
    }
    return _component(
        data=data, key=key,
        on_moved_change=on_moved or _noop,
        on_opened_change=on_opened or _noop,
        on_add_change=on_add or _noop,
    )
