"""Process definition, modelled on the Azure DevOps *Agile* process template."""

# --- Work item types ---------------------------------------------------------------------------

WORK_ITEM_TYPES = ["Epic", "Feature", "User Story", "Bug", "Task"]

TYPE_META = {
    "Epic": {"icon": "👑", "color": "#FF7B00", "slug": "epic"},
    "Feature": {"icon": "🏆", "color": "#773B93", "slug": "feature"},
    "User Story": {"icon": "📘", "color": "#009CCC", "slug": "story"},
    "Bug": {"icon": "🐞", "color": "#CC293D", "slug": "bug"},
    "Task": {"icon": "📋", "color": "#F2CB1D", "slug": "task"},
}

# Recommended hierarchy. Enforced only when the "strict_hierarchy" setting is on;
# otherwise any item can be the parent of any other (cycles are always rejected).
AGILE_PARENTS = {
    "Epic": [],
    "Feature": ["Epic"],
    "User Story": ["Feature"],
    "Bug": ["Feature", "User Story"],
    "Task": ["User Story", "Bug"],
}
AGILE_CHILDREN = {
    t: [c for c, parents in AGILE_PARENTS.items() if t in parents] for t in WORK_ITEM_TYPES
}

# --- States ---------------------------------------------------------------------------------------

STATES = {
    "Epic": ["New", "Active", "Resolved", "Closed", "Removed"],
    "Feature": ["New", "Active", "Resolved", "Closed", "Removed"],
    "User Story": ["New", "Active", "Resolved", "Closed", "Removed"],
    "Bug": ["New", "Active", "Resolved", "Closed"],
    "Task": ["New", "Active", "Closed", "Removed"],
}
ALL_STATES = ["New", "Active", "Resolved", "Closed", "Removed"]
DONE_STATES = {"Closed"}
INACTIVE_STATES = {"Closed", "Removed"}

STATE_COLORS = {
    "New": "#B2B2B2",
    "Active": "#007ACC",
    "Resolved": "#FF9D00",
    "Closed": "#339933",
    "Removed": "#8A8886",
}

STATE_REASONS = {
    "New": "New",
    "Active": "Implementation started",
    "Resolved": "Code complete and unit tests pass",
    "Closed": "Acceptance tests pass",
    "Removed": "Removed from the backlog",
}

# --- Backlogs and boards ------------------------------------------------------------------------

BACKLOG_LEVELS = {
    "Epics": ["Epic"],
    "Features": ["Feature"],
    "Stories": ["User Story", "Bug"],
}
BOARD_COLUMNS = ["New", "Active", "Resolved", "Closed"]
TASKBOARD_COLUMNS = ["New", "Active", "Closed"]

# --- Links -------------------------------------------------------------------------------------------
# Stored link types. Symmetric links are saved once (lowest id as source).
# "predecessor": source must finish before target.  "duplicate": source is a duplicate of target.
STORED_LINK_TYPES = {
    "related": {"symmetric": True},
    "sibling": {"symmetric": True},
    "predecessor": {"symmetric": False},
    "duplicate": {"symmetric": False},
}

# Link kinds as the user sees them, from the point of view of the current item.
LINK_KINDS = {
    "parent": "Parent",
    "child": "Child",
    "sibling": "Sibling",
    "related": "Related",
    "predecessor": "Predecessor",
    "successor": "Successor",
    "duplicate_of": "Duplicate of",
    "duplicate": "Duplicate",
}

# --- Fields ----------------------------------------------------------------------------------------

PRIORITIES = [1, 2, 3, 4]
PRIORITY_LABELS = {1: "1 - Critical", 2: "2 - High", 3: "3 - Medium", 4: "4 - Low"}
SEVERITIES = ["1 - Critical", "2 - High", "3 - Medium", "4 - Low"]
VALUE_AREAS = ["Business", "Architectural"]

MAX_TITLE = 255
MAX_TEXT = 20000
MAX_COMMENT = 10000
MAX_NAME = 120
MAX_TAG = 60
MAX_ESTIMATE = 100000

FIELD_LABELS = {
    "title": "Title",
    "description": "Description",
    "acceptance_criteria": "Acceptance criteria",
    "state": "State",
    "reason": "Reason",
    "priority": "Priority",
    "severity": "Severity",
    "value_area": "Value area",
    "story_points": "Story Points",
    "effort": "Effort",
    "business_value": "Business value",
    "original_estimate": "Original estimate",
    "remaining_work": "Remaining work",
    "completed_work": "Completed work",
    "assigned_to": "Assigned to",
    "iteration_id": "Iteration",
    "area_id": "Area",
    "parent_id": "Parent",
    "start_date": "Start date",
    "target_date": "Target date",
    "tags": "Tags",
    "links": "Links",
    "created": "Created",
    "deleted": "Deleted",
    "restored": "Restored",
}

# Planning fields that make sense for each type.
PLANNING_FIELDS = {
    "Epic": ["effort", "business_value", "start_date", "target_date"],
    "Feature": ["effort", "business_value", "start_date", "target_date"],
    "User Story": ["story_points"],
    "Bug": ["story_points", "severity"],
    "Task": ["original_estimate", "remaining_work", "completed_work"],
}

# Validated categorical palette (light / dark) for charts.
CHART_PALETTE = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}

DEFAULT_SETTINGS = {
    "project_name": "My Project",
    "auto_activate_parent": True,
    "auto_close_parent": False,
    "strict_hierarchy": False,
    "wip_limits": {"Epics": {}, "Features": {}, "Stories": {"Active": 5, "Resolved": 4}},
}
