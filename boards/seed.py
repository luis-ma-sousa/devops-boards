"""Demo project (a retail data, dashboarding and AI/ML team) with simulated history."""

import random
from datetime import date, datetime, timedelta

from sqlalchemy import text

from . import db
from . import repository as repo

USERS = [
    ("Ana Ferreira", "ana.ferreira@example.com", "Product"),
    ("Bruno Costa", "bruno.costa@example.com", "Product"),
    ("Carla Mendes", "carla.mendes@example.com", "BI & Dashboards"),
    ("Diogo Santos", "diogo.santos@example.com", "Data Engineering"),
    ("Gonçalo Pereira", "goncalo.pereira@example.com", "Data Science"),
    ("Marta Lopes", "marta.lopes@example.com", "ML Engineering"),
    ("Inês Rodrigues", "ines.rodrigues@example.com", "Data Quality"),
    ("Filipe Almeida", "filipe.almeida@example.com", "Design"),
]
DEVELOPERS = ["Carla Mendes", "Diogo Santos", "Gonçalo Pereira", "Marta Lopes"]
AREAS = ["BI & Dashboards", "Customer Analytics", "Data Science", "Data Platform"]
GOALS = [
    "Certified sales dataset and the first executive dashboard",
    "Margin reporting and stock-out alerts",
    "Customer segments and the first demand forecast",
    "Mobile dashboard, basket analysis and promotion uplift",
    "Churn score and late data feed alerts",
    "Model monitoring and campaign measurement",
]

# (epic, area, tags, [(feature, [(story, points, sprint offset | None, state in the current sprint)])])
BACKLOG = [
    ("Store Performance Dashboards", "BI & Dashboards", ["dashboards"], [
        ("Executive sales dashboard", [
            ("As a regional manager, I want daily sales vs. target per store", 5, -3, None),
            ("As a regional manager, I want like-for-like growth compared with last year", 3, -3, None),
            ("As a CFO, I want gross margin by category and region", 5, -2, None),
            ("As a store manager, I want the sales dashboard on my phone", 8, 0, "Active"),
        ]),
        ("Inventory and stock-out reporting", [
            ("As a merchandiser, I want stock cover in days per SKU and store", 5, -2, None),
            ("As a merchandiser, I want a daily list of likely stock-outs", 3, -2, None),
            ("As a supply planner, I want inventory value ageing per warehouse", 3, 0, "Closed"),
        ]),
        ("Self-service analytics", [
            ("As an analyst, I want a certified sales dataset in the BI tool", 5, -3, None),
            ("As an analyst, I want row-level security by region", 8, 1, None),
            ("As a business user, I want to ask questions about sales in plain language", 5, None, None),
        ]),
    ]),
    ("Customer Analytics", "Customer Analytics", ["customer"], [
        ("Customer segmentation", [
            ("As a CRM manager, I want RFM customer segments refreshed every week", 8, -1, None),
            ("As a CRM manager, I want segment sizes and trends in a dashboard", 3, -1, None),
        ]),
        ("Churn and loyalty", [
            ("As a loyalty manager, I want a churn risk score for every member", 8, 1, None),
            ("As a loyalty manager, I want to measure campaign uplift against a control group", 13, 2, None),
        ]),
        ("Basket analysis", [
            ("As a category manager, I want to see products that are often bought together", 8, 0, "Resolved"),
            ("As a category manager, I want basket size and value trends per store", 3, 0, "Closed"),
            ("As a marketer, I want next-best-offer suggestions per segment", 5, 0, "New"),
        ]),
    ]),
    ("Demand Forecasting (ML)", "Data Science", ["ml"], [
        ("Weekly demand forecast", [
            ("As a supply planner, I want a 12-week demand forecast per SKU and store", 8, -1, None),
            ("As a supply planner, I want forecast accuracy (MAPE) tracked per category", 5, -1, None),
        ]),
        ("Promotions and pricing", [
            ("As a pricing analyst, I want the expected uplift of a promotion before it runs", 5, 0, "Active"),
            ("As a pricing analyst, I want price elasticity estimates per category", 3, 1, None),
        ]),
    ]),
    ("Data Platform and MLOps", "Data Platform", ["platform"], [
        ("Data pipelines", [
            ("As a data engineer, I want POS transactions loaded every hour", 5, -3, None),
            ("As a data engineer, I want an alert when a source feed is late or incomplete", 3, 1, None),
        ]),
        ("Model deployment and monitoring", [
            ("As an ML engineer, I want models deployed through a CI/CD pipeline", 5, -2, None),
            ("As an ML engineer, I want drift monitoring for models in production", 8, 2, None),
        ]),
    ]),
]

# (title, feature, severity, sprint offset, state in the current sprint)
BUGS = [
    ("Sales dashboard counts returns twice", "Executive sales dashboard", "2 - High", -2, None),
    ("Stock cover shows negative days for new SKUs", "Inventory and stock-out reporting", "3 - Medium", -1, None),
    ("RFM job fails when a customer has no purchases", "Customer segmentation", "2 - High", 0, "Active"),
    ("Basket report ignores online orders", "Basket analysis", "3 - Medium", 0, "Closed"),
    ("Plain-language questions return last year's figures", "Self-service analytics", "4 - Low", None, None),
    ("Forecast pipeline times out for stores with over 20,000 SKUs", "Weekly demand forecast", "1 - Critical", 0,
     "New"),
    ("Hourly POS load duplicates rows after a retry", "Data pipelines", "2 - High", 1, None),
    ("RFM refresh crashes on customers without orders", "Customer segmentation", "3 - Medium", None, None),
]

# (item title, link kind seen from that item, other item title)
LINKS = [
    ("As a pricing analyst, I want the expected uplift of a promotion before it runs", "predecessor",
     "As a supply planner, I want a 12-week demand forecast per SKU and store"),
    ("As a marketer, I want next-best-offer suggestions per segment", "predecessor",
     "As a category manager, I want to see products that are often bought together"),
    ("Forecast pipeline times out for stores with over 20,000 SKUs", "related",
     "As a data engineer, I want POS transactions loaded every hour"),
    ("Hourly POS load duplicates rows after a retry", "related",
     "As a data engineer, I want POS transactions loaded every hour"),
    ("RFM refresh crashes on customers without orders", "duplicate_of",
     "RFM job fails when a customer has no purchases"),
    ("As an ML engineer, I want drift monitoring for models in production", "sibling",
     "As a supply planner, I want forecast accuracy (MAPE) tracked per category"),
]

TASK_TEMPLATES = [
    ("Wireframe and UX review", "design", ["ux"]),
    ("Ingest source data", "dev", ["pipeline"]),
    ("Transform and model the data", "dev", ["sql"]),
    ("Build the report or model", "dev", []),
    ("Data quality checks and UAT", "qa", ["data-quality"]),
    ("Peer review and documentation", "dev", []),
]

COMMENTS = [
    "Reconciled the numbers with the finance close, they match.",
    "Blocked: waiting for access to the loyalty data warehouse.",
    "Notebook and PR are ready, only the review is missing.",
    "Some stores send no POS file on Sundays, I will open a bug.",
    "Could we split this into the data model and the visuals?",
    "Showed it to two regional managers, the feedback was positive.",
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
                           ("project_name", '"Retail Data & AI"')):
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
                              "description": f"Business goal: **{epic_title}** for the retail business."}, po, epic_created, tags=epic_tags)
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
                    story_tags = rnd.sample(["sql", "python", "power-bi", "data-quality", "performance", "mvp"],
                                            rnd.randint(0, 2))
                    sid = create({
                        "type": "User Story", "title": s_title, "parent_id": fid, "area_id": areas[area],
                        "story_points": float(points), "priority": rnd.choice([1, 2, 2, 3, 4]),
                        "assigned_to": owner if sprint else None, "iteration_id": sprint["id"] if sprint else None,
                        "description": f"{s_title}, so that decisions are based on reliable data.",
                        "acceptance_criteria": "- Figures reconcile with the source system\n"
                                               "- Data refreshes on schedule\n"
                                               "- Documented in the data catalogue",
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
            bug_tags = tags + ["business-reported"] if severity[0] in "12" else tags
            bid = create({"type": "Bug", "title": b_title, "parent_id": fid, "area_id": area_id,
                          "severity": severity, "priority": int(severity[0]),
                          "story_points": float(rnd.choice([1, 2, 3])),
                          "assigned_to": owner if sprint else None, "iteration_id": sprint["id"] if sprint else None,
                          "description": "1. Open the report or job\n2. Repeat what the title describes\n"
                                         "3. **Result:** wrong figures or a failure\n\n"
                                         "**Expected:** values match the source system"},
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
