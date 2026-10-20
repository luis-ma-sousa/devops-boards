"""Demo data with simulated history, so burndown, velocity and cumulative flow have something to show."""

import random
from datetime import date, datetime, timedelta

from sqlalchemy import text

from . import db
from . import repository as repo

USERS = [
    ("Ana Ferreira", "ana.ferreira@example.com", "Product"),
    ("Bruno Costa", "bruno.costa@example.com", "Product"),
    ("Carla Mendes", "carla.mendes@example.com", "Web"),
    ("Diogo Santos", "diogo.santos@example.com", "Mobile"),
    ("Gonçalo Pereira", "goncalo.pereira@example.com", "Platform"),
    ("Inês Rodrigues", "ines.rodrigues@example.com", "QA"),
    ("Filipe Almeida", "filipe.almeida@example.com", "Design"),
]
DEVELOPERS = ["Carla Mendes", "Diogo Santos", "Gonçalo Pereira"]
AREAS = ["Web", "Mobile", "API", "Infrastructure"]
GOALS = [
    "Authentication and catalogue foundations",
    "Invoices in the account area",
    "Push notifications and instant payments",
    "Checkout redesign and refunds",
    "Offline mode and alerts",
    "Stabilisation and end-to-end tests",
]

# (epic, area, tags, [(feature, [(story, points, sprint offset | None, state in the current sprint)])])
BACKLOG = [
    ("Customer Portal", "Web", ["customer"], [
        ("Authentication and account management", [
            ("As a customer, I want to sign up with email and password", 5, -3, None),
            ("As a customer, I want to reset my password by email", 3, -3, None),
            ("As a customer, I want to sign in with Google", 5, -2, None),
            ("As a customer, I want to enable two-factor authentication", 8, 0, "Active"),
        ]),
        ("Account area and invoices", [
            ("As a customer, I want to see my invoice history", 5, -2, None),
            ("As a customer, I want to download invoices as PDF", 3, -2, None),
            ("As a customer, I want to update my billing details", 3, 0, "Closed"),
        ]),
        ("Search and catalogue", [
            ("As a visitor, I want to search products by name", 5, -3, None),
            ("As a visitor, I want to filter products by category and price", 8, 1, None),
            ("As a visitor, I want to see related products", 5, None, None),
        ]),
    ]),
    ("Mobile App v2", "Mobile", ["mobile"], [
        ("Push notifications", [
            ("As a user, I want a notification when my order status changes", 8, -1, None),
            ("As a user, I want to configure my notification preferences", 3, -1, None),
        ]),
        ("Offline mode", [
            ("As a user, I want to see my orders without a connection", 8, 1, None),
            ("As a user, I want my changes to sync when I am back online", 13, 2, None),
        ]),
        ("Checkout redesign", [
            ("As a user, I want a 3-step checkout", 8, 0, "Resolved"),
            ("As a user, I want to save favourite addresses", 3, 0, "Closed"),
            ("As a user, I want to pay with Apple Pay or Google Pay", 5, 0, "New"),
        ]),
    ]),
    ("Payments Platform", "API", ["payments"], [
        ("Instant bank payments", [
            ("As a customer, I want to pay with an instant bank transfer", 8, -1, None),
            ("As an operator, I want payments to be reconciled automatically", 5, -1, None),
        ]),
        ("Refunds", [
            ("As an operator, I want to issue partial refunds", 5, 0, "Active"),
            ("As a customer, I want to track the status of my refund", 3, 1, None),
        ]),
    ]),
    ("Observability and Reliability", "Infrastructure", ["tech-debt"], [
        ("Monitoring and alerts", [
            ("As an engineer, I want latency dashboards per endpoint", 5, -3, None),
            ("As an engineer, I want an alert when the error rate goes above 2%", 3, 1, None),
        ]),
        ("CI/CD pipeline", [
            ("As a developer, I want automatic deployments to staging", 5, -2, None),
            ("As a developer, I want end-to-end tests in the pipeline", 8, 2, None),
        ]),
    ]),
]

# (title, feature, severity, sprint offset, state in the current sprint)
BUGS = [
    ("500 error when signing up with accented characters in the name", "Authentication and account management",
     "2 - High", -2, None),
    ("PDF invoices show the wrong date (time zone)", "Account area and invoices", "3 - Medium", -1, None),
    ("Duplicate notifications on Android", "Push notifications", "2 - High", 0, "Active"),
    ("Pay button rendered twice on small screens", "Checkout redesign", "3 - Medium", 0, "Closed"),
    ("Search returns nothing for terms with hyphens", "Search and catalogue", "4 - Low", None, None),
    ("Reconciliation times out with more than 1000 transactions", "Instant bank payments", "1 - Critical", 0, "New"),
    ("App crashes when opened without a connection", "Offline mode", "2 - High", 1, None),
    ("Notifications arrive twice on Android 14", "Push notifications", "3 - Medium", None, None),
]

# (item title, link kind seen from that item, other item title)
LINKS = [
    ("As a user, I want my changes to sync when I am back online", "predecessor",
     "As a user, I want to see my orders without a connection"),
    ("As a user, I want to pay with Apple Pay or Google Pay", "predecessor", "As a user, I want a 3-step checkout"),
    ("Reconciliation times out with more than 1000 transactions", "related",
     "As an operator, I want payments to be reconciled automatically"),
    ("App crashes when opened without a connection", "related",
     "As a user, I want to see my orders without a connection"),
    ("Notifications arrive twice on Android 14", "duplicate_of", "Duplicate notifications on Android"),
    ("As a customer, I want to track the status of my refund", "sibling",
     "As a user, I want a notification when my order status changes"),
]

TASK_TEMPLATES = [
    ("UI design", "design", ["ux"]),
    ("Implement API", "dev", ["backend"]),
    ("Implement frontend", "dev", ["frontend"]),
    ("Unit tests", "dev", []),
    ("Acceptance tests", "qa", []),
    ("Code review", "dev", []),
]

COMMENTS = [
    "Checked with the customer, the acceptance criteria are final.",
    "Blocked waiting for credentials for the test environment.",
    "PR is open, only the review is missing.",
    "Found an edge case with expired sessions, I will open a bug.",
    "Could we split this into two stories?",
    "Tested on staging, all good.",
]


def load_demo() -> None:
    rnd = random.Random(7)
    today = date.today()
    now_dt = datetime.now().replace(microsecond=0)
    latest = now_dt - timedelta(minutes=5)

    def stamp(dt: datetime) -> str:
        return min(dt, latest).strftime("%Y-%m-%d %H:%M:%S")

    def at(day: date, lo: int = 9, hi: int = 18) -> datetime:
        return datetime.combine(day, datetime.min.time()) + timedelta(hours=rnd.randint(lo, hi - 1),
                                                                      minutes=rnd.randint(0, 59))

    def after(dt: datetime, min_h: float, max_h: float) -> datetime:
        return min(dt + timedelta(hours=rnd.uniform(min_h, max_h)), latest)

    with db.write() as conn:
        # Automation rules are off while simulating; parent states are computed at the end.
        for key, value in (("auto_activate_parent", "false"), ("auto_close_parent", "false"),
                           ("project_name", '"Online Store"')):
            repo._upsert(conn, db.settings, {"key": key, "value": value}, ["key"])

        created = stamp(now_dt - timedelta(days=60))
        users = {}
        for name, email, team in USERS:
            users[name] = conn.execute(db.users.insert().values(
                name=name, email=email, team=team, active=1, created_at=created)).inserted_primary_key[0]
        po = users["Ana Ferreira"]
        qa = users["Inês Rodrigues"]
        designer = users["Filipe Almeida"]
        devs = [users[n] for n in DEVELOPERS]
        owners = {"dev": devs, "qa": [qa], "design": [designer]}

        areas = {a: conn.execute(db.areas.insert().values(name=a)).inserted_primary_key[0] for a in AREAS}

        cur_start = today - timedelta(days=today.weekday() + 7)  # Monday of last week
        sprints = {}
        for i, offset in enumerate(range(-3, 3)):
            start = cur_start + timedelta(days=14 * offset)
            end = start + timedelta(days=11)
            sprint_id = conn.execute(db.iterations.insert().values(
                name=f"Sprint {i + 1}", start_date=start.isoformat(), end_date=end.isoformat(), goal=GOALS[i],
            )).inserted_primary_key[0]
            sprints[offset] = {"id": sprint_id, "start": start, "end": end}
        hours = {"Product": 2, "Design": 4}
        for offset in (0, 1):
            for name, _, team in USERS:
                conn.execute(db.capacity.insert().values(
                    iteration_id=sprints[offset]["id"], user_id=users[name], hours_per_day=hours.get(team, 6),
                    days_off=rnd.choice([0, 0, 0, 1])))

        def create(data, user, ts, tags=None):
            return repo._create(conn, data, user, tags=tags, ts=stamp(ts))

        def move(item_id, state, user, ts, **extra):
            repo._update(conn, item_id, {"state": state, **extra}, user, ts=stamp(ts))

        def simulate_requirement(item_id, state, sprint, owner, created_dt):
            """Walk New → Active → Resolved → Closed inside the sprint. Returns (activated, finished)."""
            if state == "New":
                return None, None
            s_start = datetime.combine(sprint["start"], datetime.min.time())
            s_end = datetime.combine(sprint["end"], datetime.min.time()) + timedelta(hours=18)
            span = max((min(s_end, latest) - s_start).total_seconds() / 3600, 4)
            t_active = max(s_start + timedelta(hours=rnd.uniform(1, span * 0.35)), created_dt + timedelta(hours=1))
            move(item_id, "Active", owner, t_active)
            if state == "Active":
                return t_active, None
            t_resolved = min(after(t_active, 24, max(30, span * 0.5)), s_end)
            move(item_id, "Resolved", owner, t_resolved)
            if state == "Resolved":
                return t_active, t_resolved
            t_closed = min(after(t_resolved, 2, 30), s_end)
            move(item_id, "Closed", po, t_closed)
            return t_active, t_closed

        def add_tasks(story_id, story_state, sprint, area_id, t_active, t_end, created_dt):
            templates = rnd.sample(TASK_TEMPLATES[1:4], 2) + rnd.sample(
                [TASK_TEMPLATES[0], TASK_TEMPLATES[4], TASK_TEMPLATES[5]], rnd.randint(1, 2))
            n = len(templates)
            for idx, (title, role, tags) in enumerate(templates):
                owner = rnd.choice(owners[role])
                estimate = float(rnd.choice([2, 3, 4, 6, 8]))
                tid = create({"type": "Task", "title": title, "parent_id": story_id, "assigned_to": owner,
                              "iteration_id": sprint["id"], "area_id": area_id, "original_estimate": estimate},
                             owner, created_dt + timedelta(minutes=10 + idx), tags=tags)
                if story_state == "New" or t_active is None:
                    continue
                # Active stories: first tasks done, the next one in progress, the rest not started.
                if story_state == "Active":
                    task_state = "Closed" if idx < n // 2 else ("Active" if idx == n // 2 else "New")
                else:
                    task_state = "Closed"
                if task_state == "New":
                    continue
                window_end = t_end or latest
                total_h = max((window_end - t_active).total_seconds() / 3600, 2)
                t_start = t_active + timedelta(hours=total_h * idx / (n + 1) * rnd.uniform(0.6, 1.0))
                move(tid, "Active", owner, t_start)
                t_mid = min(after(t_start, 3, max(4, total_h / (n + 1))), window_end)
                repo._update(conn, tid, {"remaining_work": max(1.0, round(estimate / 2)),
                                         "completed_work": round(estimate / 2)}, owner, ts=stamp(t_mid))
                if task_state == "Closed":
                    t_done = max(min(after(t_mid, 2, max(3, total_h / (n + 1))), window_end), t_mid)
                    move(tid, "Closed", owner, t_done, completed_work=estimate)

        ids_by_title = {}
        feature_ids = {}
        for epic_title, area, epic_tags, features in BACKLOG:
            epic_created = now_dt - timedelta(days=rnd.randint(55, 70))
            epic_id = create({"type": "Epic", "title": epic_title, "area_id": areas[area], "priority": 1,
                              "assigned_to": po, "business_value": rnd.randint(50, 100),
                              "effort": float(rnd.choice([40, 60, 80])),
                              "description": f"Business goal: **{epic_title}**."}, po, epic_created, tags=epic_tags)
            for f_title, stories in features:
                f_created = epic_created + timedelta(days=rnd.randint(1, 5))
                fid = create({"type": "Feature", "title": f_title, "parent_id": epic_id, "area_id": areas[area],
                              "priority": rnd.choice([1, 2, 2, 3]), "assigned_to": po,
                              "effort": float(sum(s[1] for s in stories)),
                              "target_date": (today + timedelta(days=rnd.randint(10, 60))).isoformat()},
                             po, f_created, tags=epic_tags)
                feature_ids[f_title] = (fid, areas[area], epic_tags)
                for s_title, points, offset, cur_state in stories:
                    sprint = sprints.get(offset) if offset is not None else None
                    base_day = min(sprint["start"], today) if sprint else today
                    s_created = max(at(base_day - timedelta(days=rnd.randint(4, 20))), f_created + timedelta(hours=2))
                    owner = rnd.choice(devs)
                    story_tags = rnd.sample(["frontend", "backend", "ux", "security", "performance", "mvp"],
                                            rnd.randint(0, 2))
                    sid = create({
                        "type": "User Story", "title": s_title, "parent_id": fid, "area_id": areas[area],
                        "story_points": float(points), "priority": rnd.choice([1, 2, 2, 3, 4]),
                        "assigned_to": owner if sprint else None, "iteration_id": sprint["id"] if sprint else None,
                        "description": f"{s_title}, so that the experience is simpler and faster.",
                        "acceptance_criteria": "- Given I am signed in\n- When I perform the action\n"
                                               "- Then I see a confirmation on screen",
                    }, po, s_created, tags=story_tags + epic_tags)
                    ids_by_title[s_title] = sid
                    if sprint is None:
                        continue
                    state = "Closed" if offset < 0 else (cur_state or "New") if offset == 0 else "New"
                    t_active, t_end = simulate_requirement(sid, state, sprint, owner, s_created)
                    if offset <= 1:
                        add_tasks(sid, state, sprint, areas[area], t_active, t_end, s_created)

        for b_title, feature, severity, offset, cur_state in BUGS:
            fid, area_id, tags = feature_ids[feature]
            sprint = sprints.get(offset) if offset is not None else None
            base_day = min(sprint["start"], today) if sprint else today
            b_created = at(base_day - timedelta(days=rnd.randint(1, 8)))
            owner = rnd.choice(devs)
            bug_tags = tags + ["customer-reported"] if severity[0] in "12" else tags
            bid = create({"type": "Bug", "title": b_title, "parent_id": fid, "area_id": area_id,
                          "severity": severity, "priority": int(severity[0]),
                          "story_points": float(rnd.choice([1, 2, 3])),
                          "assigned_to": owner if sprint else None, "iteration_id": sprint["id"] if sprint else None,
                          "description": "1. Open the app\n2. Repeat the flow in the title\n"
                                         "3. **Result:** error\n\n**Expected:** the flow finishes without errors"},
                         qa, b_created, tags=bug_tags)
            ids_by_title[b_title] = bid
            if sprint is None:
                continue
            state = "Closed" if offset < 0 else (cur_state or "New") if offset == 0 else "New"
            t_active, t_end = simulate_requirement(bid, state, sprint, owner, b_created)
            if offset == 0:
                add_tasks(bid, state, sprint, area_id, t_active, t_end, b_created)

        # Parent states (Features, then Epics) derived from their children.
        for parent_type in ("Feature", "Epic"):
            for (pid,) in conn.execute(text("SELECT id FROM work_items WHERE type = :t"), {"t": parent_type}).all():
                kids = conn.execute(text(
                    "SELECT state, activated_at, closed_at FROM work_items WHERE parent_id = :id"), {"id": pid},
                ).mappings().all()
                started = [k["activated_at"] for k in kids if k["activated_at"]]
                if not started:
                    continue
                move(pid, "Active", po, datetime.fromisoformat(min(started)))
                if kids and all(k["state"] == "Closed" for k in kids):
                    move(pid, "Closed", po, datetime.fromisoformat(max(k["closed_at"] for k in kids)))

        link_ts = stamp(now_dt - timedelta(days=3))
        for a_title, kind, b_title in LINKS:
            a, b = ids_by_title[a_title], ids_by_title[b_title]
            link_type, source, target = repo._stored_link(kind, a, b)
            conn.execute(db.work_item_links.insert().values(
                source_id=source, target_id=target, link_type=link_type, created_by=po, created_at=link_ts))

        current_items = [r[0] for r in conn.execute(text(
            "SELECT id FROM work_items WHERE iteration_id = :it AND type IN ('User Story', 'Bug')"),
            {"it": sprints[0]["id"]})]
        all_users = list(users.values())
        for item_id in rnd.sample(current_items, min(6, len(current_items))):
            for body in rnd.sample(COMMENTS, rnd.randint(1, 2)):
                conn.execute(db.comments.insert().values(
                    work_item_id=item_id, user_id=rnd.choice(all_users), body=body,
                    created_at=stamp(at(today - timedelta(days=rnd.randint(0, 6))))))

        repo._upsert(conn, db.settings, {"key": "auto_activate_parent", "value": "true"}, ["key"])
