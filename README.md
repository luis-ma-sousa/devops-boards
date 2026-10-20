# Boards: an Azure DevOps Boards clone in Streamlit

Agile work tracking with **Epics → Features → User Stories / Bugs → Tasks**, drag-and-drop Kanban
boards, hierarchical backlogs, sprints with a taskboard, capacity and burndown, links between work
items and a personal home page. Built for several people working at the same time.

## Run it (Windows, macOS, Linux)

1. Download the project: **Code → Download ZIP** on GitHub (then unzip), or `git clone` it.
2. Start it:
   - **Windows**: double-click `run.bat`.
   - **macOS**: double-click `run.command`. The first time macOS may say it is from an unidentified
     developer: right-click the file → **Open** → **Open**.
   - **Linux** (or a Mac terminal): `bash run.sh`
3. The browser opens on the app. Keep the window open while you use it; close it (or press Ctrl+C)
   to stop.

The first start takes about a minute: it creates a private Python environment in `.venv` and
installs what the app needs. Later starts take a few seconds. If Python 3.11+ is not installed, the
script offers to set it up with [uv](https://astral.sh/uv) (no admin rights needed); you can also
install Python from [python.org](https://www.python.org/downloads/) yourself.

The window also prints a network address (e.g. `http://192.168.1.20:8501`) that colleagues on the
same network can open. On Windows, allow the firewall prompt the first time.

On the first visit you can **create the first user** or **load the demo project** (Online Store:
4 epics, 10 features, 25 stories, 8 bugs, ~90 tasks, 6 sprints, 7 people).

Developers can still run it the usual way: `pip install -r requirements.txt` and `streamlit run app.py`.

## Features

| Page | What it does |
|---|---|
| **Home** | Your own work (in progress, up next, done this week), the current sprint and your part in it, project progress per epic, and updates teammates made on your items |
| **Boards** | Kanban per backlog level (Epics / Features / Stories) with New → Active → Resolved → Closed columns. **Drag cards** between columns or within a column, click a card to open it, WIP limits, filters (text, person, team, iteration, area, tags) |
| **Backlogs** | Ordered list with the hierarchy (show children), reorder (up/down/top), bulk actions (iteration, state, person) and **grid editing** |
| **Sprints** | Taskboard (one row per story, **drag tasks** between states or to another story), sprint backlog, capacity per person, burndown (points, hours or items) and planning (move items between backlog and sprint, with a velocity warning) |
| **Work items** | Queries with quick views (assigned to me, created by me…), every filter and CSV export |
| **People** | Create, edit and deactivate people (name, email and a free-text **team**) and see who is in each team |
| **Settings** | Project name, automation rules, strict hierarchy, iterations (including generating several sprints), areas, tags, WIP limits, recycle bin, integrity check, backups and exports |

### Work items

Click a card (or type an ID in the sidebar) to open the work item:

- **Details**: title, state (with automatic reason), assignee, priority, value area, iteration, area,
  tags (created as you type), Story Points / effort / hours / severity depending on the type,
  description and acceptance criteria in Markdown.
- **Links**: parent, children (with progress), items with the same parent, and links of any kind to
  any other work item: **Parent, Child, Sibling, Related, Predecessor, Successor, Duplicate of,
  Duplicate**.
- **Discussion** (comments) and **History** (every field change, who and when).
- Deleting sends the item to the recycle bin, from where it can be restored.

### Process rules (Agile template)

| Type | Recommended parent | States |
|---|---|---|
| 👑 Epic | — | New, Active, Resolved, Closed, Removed |
| 🏆 Feature | Epic | New, Active, Resolved, Closed, Removed |
| 📘 User Story | Feature | New, Active, Resolved, Closed, Removed |
| 🐞 Bug | Feature or User Story | New, Active, Resolved, Closed |
| 📋 Task | User Story or Bug | New, Active, Closed, Removed |

By default any item can be the parent of any other (cycles are always blocked). Turn on
**Strict Agile hierarchy** in Settings to enforce the table above. Optional automation rules activate
a parent when a child starts and close it when all children are done. Closing a task sets its
remaining work to 0.

## Several people at the same time

There is no login: everyone picks who they are in the sidebar ("Working as"). The choice is kept in
the address (`?user=3`), so a bookmark opens the app as that person.

- **Conflicts are detected, not overwritten.** The edit form only saves the fields you changed. If
  someone else changed the *same* field after you opened the item, you get a warning and can reload
  their version or overwrite it. Edits to *different* fields are merged.
- **Board moves are checked too.** If a card was already moved by someone else, your drag is
  rejected and the board refreshes.
- **Pages notice other people's changes** and offer a *Refresh* button.
- **Writes are atomic.** Every change runs in one transaction (SQLite `BEGIN IMMEDIATE`, PostgreSQL
  row locks), so concurrent writes never interleave halfway.

### Database

SQLite (`data/boards.db`) is the default and is fine for a small team on one server. For a shared
deployment, use PostgreSQL by setting `DATABASE_URL`:

```bash
export DATABASE_URL="postgresql://user:password@host:5432/boards"
streamlit run app.py
```

On Streamlit Community Cloud, add `DATABASE_URL` to the app's *Secrets* (its file system is
temporary, so SQLite data would be lost on restart). Any hosted PostgreSQL works (Neon, Supabase,
RDS…). The schema is created automatically.

The schema protects itself with CHECK, UNIQUE and FOREIGN KEY constraints (invalid types, states,
priorities, negative estimates, duplicate emails or links are refused even if written directly).
SQLite runs in WAL mode with foreign keys on. *Settings → Data* runs an integrity check and offers a
consistent backup (SQLite) and a full JSON export (any database).

> **No login means anyone who can open the app can edit anything.** Run it on a private network,
> behind your company's single sign-on proxy, or on a host with access control.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                                        # SQLite
TEST_DATABASE_URL=embedded pytest             # SQLite + a throwaway PostgreSQL (needs pgserver)
TEST_DATABASE_URL=postgresql://... pytest     # SQLite + your PostgreSQL (it will be wiped)
```

The suite (over 200 tests per database) covers:

- **Users**: required name, valid and unique email (case-insensitive), free-text team, last active
  user, unassigning work when someone is deleted, inactive people cannot get new work.
- **Work items**: type, title, state per type, priority, numbers, dates, references and unknown
  fields are validated; failed writes leave nothing behind; history, revisions, timestamps,
  automation rules, tags, recycle bin, ordering and bulk edits.
- **Hierarchy and links**: no self-parenting, no cycles at any depth, strict mode, every link type,
  duplicates, circular dependencies, links to deleted items.
- **Concurrency**: conflicting and merged edits, stale board moves, and real parallel writes from
  many threads (creates, moves, sign-ups with the same email, tags with different case, comments).
- **Database integrity**: constraints hold for rows written directly, foreign keys, rollback on
  crashes mid-transaction, schema versioning, backups, exports, integrity report.
- **App**: every page renders with demo data and with an empty project; user text is escaped; the
  selected person survives a reload.

GitHub Actions runs the tests on Windows, macOS and Linux (SQLite) and on PostgreSQL, and starts the
app with `run.bat` / `run.sh` on all three systems, for every push.

## Project structure

```
run.bat / run.command / run.sh   double-click launchers (Windows / macOS / Linux)
launch.py              cross-platform launcher: sets up .venv, installs, starts, opens the browser
app.py                 navigation, sidebar, onboarding
boards/
  config.py            types, states, hierarchy, link types, colours, fields
  db.py                engine, schema, transactions, integrity check, backups
  repository.py        data access, validation, conflicts, links, automation rules
  analytics.py         sprint burndown, velocity (planning hint), epic progress
  charts.py            Altair charts that follow the light/dark theme
  kanban.py            drag-and-drop board (Streamlit v2 component, no dependencies)
  ui.py                formatting, filters, work item dialogs
  seed.py              demo data
views/                 one file per page
tests/                 pytest suite
```
