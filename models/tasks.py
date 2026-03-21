from datetime import date, timedelta
from db import get_cursor
from utils import utc_today, format_date_iso

PLACEHOLDER = "%s"
ALLOWED_RECURRENCES = {"daily", "weekdays", "mwf", "tth", "weekly"}


def is_valid_recurrence(recurrence):
    return recurrence in ALLOWED_RECURRENCES


def _should_schedule_on_weekday(recurrence_type, weekday):
    recurrence_type = recurrence_type or "daily"

    if recurrence_type == "daily":
        return True
    if recurrence_type == "mwf":
        return weekday in (0, 2, 4)
    if recurrence_type == "tth":
        return weekday in (1, 3)
    if recurrence_type == "weekly":
        return weekday == 0
    if recurrence_type == "weekdays":
        return weekday in (0, 1, 2, 3, 4)
    return False

# =======================
# Categories
# =======================


def get_categories(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                c.*,
                COALESCE(ti.task_count, 0) + COALESCE(et.task_count, 0) AS task_count
            FROM categories c
            LEFT JOIN (
                SELECT category_id, COUNT(*) AS task_count
                FROM task_instances
                WHERE user_id = {PLACEHOLDER}
                  AND category_id IS NOT NULL
                GROUP BY category_id
            ) ti ON ti.category_id = c.id
            LEFT JOIN (
                SELECT category_id, COUNT(*) AS task_count
                FROM everyday_tasks
                WHERE user_id = {PLACEHOLDER}
                  AND category_id IS NOT NULL
                GROUP BY category_id
            ) et ON et.category_id = c.id
            WHERE c.user_id = {PLACEHOLDER}
            ORDER BY c.name
        """,
            (user_id, user_id, user_id),
        )
        categories = cur.fetchall()
    return [dict(row) for row in categories]


def get_dashboard_categories(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, name
            FROM categories
            WHERE user_id = {PLACEHOLDER}
            ORDER BY name
            """,
            (user_id,),
        )
        categories = cur.fetchall()
    return [dict(row) for row in categories]


def add_category(user_id, name, color="#4a90d9", monster_type_id=None):
    if monster_type_id == "" or monster_type_id == "None":
        monster_type_id = None
    try:
        with get_cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO categories (user_id, name, color, monster_type_id)
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                RETURNING id
            """,
                (user_id, name, color, monster_type_id),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception:
        return None


def delete_category(user_id, category_id):
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE task_instances SET category_id = NULL WHERE user_id = {PLACEHOLDER} AND category_id = {PLACEHOLDER}",
            (user_id, category_id),
        )
        cur.execute(
            f"UPDATE everyday_tasks SET category_id = NULL WHERE user_id = {PLACEHOLDER} AND category_id = {PLACEHOLDER}",
            (user_id, category_id),
        )
        cur.execute(
            f"DELETE FROM categories WHERE user_id = {PLACEHOLDER} AND id = {PLACEHOLDER}",
            (user_id, category_id),
        )


def update_category(user_id, category_id, name, color="#4a90d9", monster_type_id=None):
    if category_id == "" or category_id == "None":
        category_id = None
    else:
        category_id = int(category_id)
    if monster_type_id == "" or monster_type_id == "None":
        monster_type_id = None
    with get_cursor() as cur:
        cur.execute(
            f"""
            UPDATE categories 
            SET name = {PLACEHOLDER}, color = {PLACEHOLDER}, monster_type_id = {PLACEHOLDER}
            WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER}
        """,
            (name, color, monster_type_id, category_id, user_id),
        )


# =======================
# Task Meta (last processed)
# =======================


def get_last_processed_date(user_id):
    key = f"last_processed_{user_id}"
    with get_cursor() as cur:
        cur.execute(
            f"SELECT value FROM meta WHERE user_id = {PLACEHOLDER} AND key = {PLACEHOLDER}",
            (user_id, key),
        )
        row = cur.fetchone()

        if not row:
            today = utc_today().isoformat()
            cur.execute(
                f"""
                INSERT INTO meta (user_id, key, value)
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                ON CONFLICT (user_id, key) DO UPDATE
                SET value = EXCLUDED.value
                """,
                (user_id, key, today),
            )
            return date.fromisoformat(today)

        return date.fromisoformat(row["value"])


def set_last_processed_date(user_id, d):
    key = f"last_processed_{user_id}"
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE meta SET value = {PLACEHOLDER} WHERE user_id = {PLACEHOLDER} AND key = {PLACEHOLDER}",
            (format_date_iso(d), user_id, key),
        )
        if cur.rowcount == 0:
            cur.execute(
                f"""
                INSERT INTO meta (user_id, key, value)
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                ON CONFLICT (user_id, key) DO UPDATE
                SET value = EXCLUDED.value
                """,
                (user_id, key, format_date_iso(d)),
            )


# =======================
# Everyday Tasks
# =======================


def get_everyday_tasks(user_id):
    today_date = utc_today()
    today = format_date_iso(today_date)
    today_weekday = today_date.weekday()

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                et.id as everyday_def_id,
                et.active,
                et.recurrence,
                et.sort_order as everyday_sort_order,
                ti.*
            FROM everyday_tasks et
            LEFT JOIN task_instances ti
              ON ti.everyday_task_id = et.id
             AND ti.user_id = et.user_id
             AND ti.date = {PLACEHOLDER}
             AND ti.weight = 2
            WHERE et.user_id = {PLACEHOLDER}
              AND et.active = 1
              AND (
                    et.recurrence = 'daily'
                 OR (et.recurrence = 'mwf' AND {PLACEHOLDER} IN (0, 2, 4))
                 OR (et.recurrence = 'tth' AND {PLACEHOLDER} IN (1, 3))
                 OR (et.recurrence = 'weekly' AND {PLACEHOLDER} = 0)
                 OR (et.recurrence = 'weekdays' AND {PLACEHOLDER} IN (0, 1, 2, 3, 4))
              )
            ORDER BY COALESCE(ti.sort_order, et.sort_order), COALESCE(ti.name, et.name)
        """,
            (today, user_id, today_weekday, today_weekday, today_weekday, today_weekday),
        )
        rows = [dict(row) for row in cur.fetchall()]

    missing_defs = [row["everyday_def_id"] for row in rows if row.get("id") is None]
    tasks = [row for row in rows if row.get("id") is not None]

    if missing_defs:
        ensure_today_tasks(user_id)
        with get_cursor() as cur:
            cur.execute(
                f"""
                SELECT ti.*, et.id as everyday_def_id, et.active, et.recurrence
                FROM task_instances ti
                JOIN everyday_tasks et ON ti.everyday_task_id = et.id
                WHERE ti.user_id = {PLACEHOLDER} AND ti.date = {PLACEHOLDER} AND ti.weight = 2
                ORDER BY ti.sort_order, ti.name
            """,
                (user_id, today),
            )
            tasks = [dict(row) for row in cur.fetchall()]
    return tasks


def get_dashboard_day_data(user_id, for_date=None):
    target_date = format_date_iso(for_date or utc_today())

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                ti.*,
                et.id AS everyday_def_id,
                et.active,
                et.recurrence
            FROM task_instances ti
            LEFT JOIN everyday_tasks et ON ti.everyday_task_id = et.id
            WHERE ti.user_id = {PLACEHOLDER}
              AND ti.date = {PLACEHOLDER}
            ORDER BY
                ti.weight ASC,
                CASE WHEN ti.weight = 1 THEN ti.priority ELSE 0 END DESC,
                ti.sort_order,
                ti.name
            """,
            (user_id, target_date),
        )
        rows = [dict(row) for row in cur.fetchall()]

    today_tasks = [row for row in rows if row.get("weight") == 1]
    everyday_tasks = [row for row in rows if row.get("weight") == 2]

    active_weight = 0
    completed_weight = 0
    for row in rows:
        if row.get("is_voided"):
            continue
        weight = row.get("weight") or 0
        active_weight += weight
        if row.get("is_completed"):
            completed_weight += weight

    efficiency = round((completed_weight / active_weight) * 100) if active_weight > 0 else 0

    return {
        "today_tasks": today_tasks,
        "everyday_tasks": everyday_tasks,
        "efficiency": efficiency,
    }


def add_everyday_task(user_id, name, category_id=None, recurrence="daily"):
    if category_id == "" or category_id == "None":
        category_id = None
    if not is_valid_recurrence(recurrence):
        recurrence = "daily"
    with get_cursor() as cur:
        cur.execute(
            f"SELECT COALESCE(MAX(sort_order), 0) + 1 as next_order FROM everyday_tasks WHERE user_id = {PLACEHOLDER}",
            (user_id,),
        )
        next_order_row = cur.fetchone()
        next_order = next_order_row["next_order"] if next_order_row else 1

        cur.execute(
            f"""
            INSERT INTO everyday_tasks (user_id, name, category_id, recurrence, sort_order)
            VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
            RETURNING id
        """,
            (user_id, name, category_id, recurrence, next_order),
        )
        row = cur.fetchone()
        everyday_task_id = row["id"] if row else None

        if everyday_task_id:
            today_date = utc_today()
            if _should_schedule_on_weekday(recurrence, today_date.weekday()):
                cur.execute(
                    f"""
                    INSERT INTO task_instances (user_id, name, date, weight, everyday_task_id, category_id, sort_order)
                    VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, 2, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                    ON CONFLICT (name, date, user_id) DO NOTHING
                    """,
                    (
                        user_id,
                        name,
                        format_date_iso(today_date),
                        everyday_task_id,
                        category_id,
                        next_order,
                    ),
                )

        return everyday_task_id


def toggle_everyday_task(task_id, user_id):
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE everyday_tasks SET active = NOT active WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER}",
            (task_id, user_id),
        )


def delete_everyday_task(task_id, user_id):
    with get_cursor() as cur:
        cur.execute(
            f"DELETE FROM everyday_tasks WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER}",
            (task_id, user_id),
        )


def reorder_tasks(user_id, task_orders):
    if not isinstance(task_orders, dict):
        return
    with get_cursor() as cur:
        for task_id, sort_order in task_orders.items():
            cur.execute(
                f"UPDATE task_instances SET sort_order = {PLACEHOLDER} WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER}",
                (int(sort_order), int(task_id), user_id),
            )


# =======================
# Task Instances
# =======================


def ensure_today_tasks(user_id):
    today_date = utc_today()
    today = format_date_iso(today_date)
    today_weekday = today_date.weekday()

    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_instances (user_id, name, date, weight, everyday_task_id, category_id, sort_order)
            SELECT
                et.user_id,
                et.name,
                {PLACEHOLDER},
                2,
                et.id,
                et.category_id,
                et.sort_order
            FROM everyday_tasks et
            WHERE et.user_id = {PLACEHOLDER}
              AND et.active = 1
              AND (
                    et.recurrence = 'daily'
                 OR (et.recurrence = 'mwf' AND {PLACEHOLDER} IN (0, 2, 4))
                 OR (et.recurrence = 'tth' AND {PLACEHOLDER} IN (1, 3))
                 OR (et.recurrence = 'weekly' AND {PLACEHOLDER} = 0)
                 OR (et.recurrence = 'weekdays' AND {PLACEHOLDER} IN (0, 1, 2, 3, 4))
              )
            ON CONFLICT (name, date, user_id) DO NOTHING
            """,
            (today, user_id, today_weekday, today_weekday, today_weekday, today_weekday),
        )


def get_today_tasks(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM task_instances
            WHERE user_id = {PLACEHOLDER} AND date = {PLACEHOLDER} AND weight = 1
            ORDER BY priority DESC, sort_order, name
        """,
            (user_id, format_date_iso(utc_today())),
        )
        tasks = cur.fetchall()
    return [dict(row) for row in tasks]


def add_task(user_id, name, category_id=None, weight=1, due_date=None, priority=0):
    if category_id == "" or category_id == "None":
        category_id = None
    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_instances (user_id, name, date, weight, category_id, due_date, priority)
            VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
            RETURNING id
        """,
            (
                user_id,
                name,
                format_date_iso(utc_today()),
                weight,
                category_id,
                due_date,
                priority,
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def get_task(task_id, user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM task_instances WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER}
        """,
            (task_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_task(
    task_id, user_id, category_id=None, notes=None, due_date=None, priority=None
):
    updates = []
    params = []

    if category_id is not None:
        updates.append(f"category_id = {PLACEHOLDER}")
        params.append(category_id if category_id != "" else None)
    if notes is not None:
        updates.append(f"notes = {PLACEHOLDER}")
        params.append(notes)
    if due_date is not None:
        updates.append(f"due_date = {PLACEHOLDER}")
        params.append(due_date if due_date != "" else None)
    if priority is not None:
        updates.append(f"priority = {PLACEHOLDER}")
        params.append(priority)

    if not updates:
        return

    params.extend([task_id, user_id])
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE task_instances SET {', '.join(updates)} WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER}",
            params,
        )


def complete_task(task_id, user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            UPDATE task_instances 
            SET is_completed = 1 
            WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER} AND date = {PLACEHOLDER}
        """,
            (task_id, user_id, format_date_iso(utc_today())),
        )
        return cur.rowcount > 0


def delete_task(task_id, user_id):
    with get_cursor() as cur:
        cur.execute(
            f"DELETE FROM task_instances WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER}",
            (task_id, user_id),
        )


def void_task(task_id, user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            UPDATE task_instances 
            SET is_voided = 1 
            WHERE id = {PLACEHOLDER} AND user_id = {PLACEHOLDER}
        """,
            (task_id, user_id),
        )


def reconcile_days(user_id):
    last = get_last_processed_date(user_id)
    today = utc_today()

    with get_cursor() as cur:
        cur.execute(
            f"SELECT id, name, category_id, recurrence, sort_order FROM everyday_tasks WHERE user_id = {PLACEHOLDER} AND active = 1",
            (user_id,),
        )
        everyday = cur.fetchall()

        d = last + timedelta(days=1)
        while d < today:
            for task in everyday:
                recurrence_type = task.get("recurrence") or "daily"
                if not _should_schedule_on_weekday(recurrence_type, d.weekday()):
                    continue

                cur.execute(
                    f"""
                    INSERT INTO task_instances
                    (user_id, name, date, weight, is_completed, is_locked, everyday_task_id, category_id, sort_order)
                    VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, 2, 0, 1, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                    ON CONFLICT (name, date, user_id) DO NOTHING
                    """,
                    (
                        user_id,
                        task["name"],
                        format_date_iso(d),
                        task["id"],
                        task.get("category_id"),
                        task.get("sort_order") or 0,
                    ),
                )
            d += timedelta(days=1)

    set_last_processed_date(user_id, today)


def copy_yesterday_tasks(user_id):
    yesterday = format_date_iso(utc_today() - timedelta(days=1))
    today = format_date_iso(utc_today())

    with get_cursor() as cur:
        cur.execute(
            f"SELECT name, category_id, weight, sort_order FROM task_instances WHERE user_id = {PLACEHOLDER} AND date = {PLACEHOLDER}",
            (user_id, yesterday),
        )
        yesterday_tasks = cur.fetchall()

        copied = 0
        for task in yesterday_tasks:
            try:
                cur.execute(
                    f"""
                    INSERT INTO task_instances (user_id, name, date, weight, everyday_task_id, category_id, sort_order)
                    VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, NULL, {PLACEHOLDER}, {PLACEHOLDER})
                """,
                    (
                        user_id,
                        task["name"],
                        today,
                        task.get("weight") or 1,
                        task.get("category_id"),
                        task.get("sort_order") or 0,
                    ),
                )
                copied += 1
            except Exception:
                pass

        return copied


def calculate_efficiency(user_id, for_date):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                SUM(weight) AS total_weight,
                SUM(CASE WHEN is_completed = 1 THEN weight ELSE 0 END) AS completed_weight
            FROM task_instances
            WHERE user_id = {PLACEHOLDER} AND date = {PLACEHOLDER} AND is_voided = 0
        """,
            (user_id, format_date_iso(for_date)),
        )
        row = cur.fetchone()

    if not row or not row["total_weight"] or row["total_weight"] == 0:
        return 0

    return (
        round((row["completed_weight"] / row["total_weight"]) * 100)
        if row["total_weight"] > 0
        else 0
    )


def get_history_data(user_id, page=1, per_page=20):
    from constants import HISTORY_DAYS_PER_PAGE

    if per_page is None:
        per_page = HISTORY_DAYS_PER_PAGE

    offset = (page - 1) * per_page

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(DISTINCT date) as total_days FROM task_instances WHERE user_id = {PLACEHOLDER}
        """,
            (user_id,),
        )
        total_row = cur.fetchone()
        total_days = total_row["total_days"] if total_row else 0

        cur.execute(
            f"""
            SELECT DISTINCT date
            FROM task_instances
            WHERE user_id = {PLACEHOLDER}
            ORDER BY date DESC
            LIMIT {per_page} OFFSET {offset}
        """,
            (user_id,),
        )
        paged_dates = [row["date"] for row in cur.fetchall()]

        if not paged_dates:
            return [], 0, 1

        cur.execute(
            f"""
            SELECT
                ti.date,
                ti.name,
                ti.is_completed,
                ti.weight,
                SUM(ti2.weight) AS total_weight,
                SUM(CASE WHEN ti2.is_completed = 1 THEN ti2.weight ELSE 0 END) AS completed_weight
            FROM task_instances ti
            JOIN task_instances ti2 ON ti.date = ti2.date AND ti.user_id = ti2.user_id
            WHERE ti.user_id = {PLACEHOLDER} AND ti.date = ANY({PLACEHOLDER})
            GROUP BY ti.date, ti.name, ti.is_completed, ti.weight
            ORDER BY ti.date DESC, ti.weight DESC, ti.name ASC
        """,
            (user_id, paged_dates),
        )
        rows = cur.fetchall()

    days = {}
    for row in rows:
        d = row["date"]
        if d not in days:
            days[d] = {"date": d, "tasks": [], "total_weight": 0, "completed_weight": 0}
        days[d]["tasks"].append(
            {
                "name": row["name"],
                "is_completed": row["is_completed"],
                "weight": row["weight"],
            }
        )
        days[d]["total_weight"] = row["total_weight"]
        days[d]["completed_weight"] = row["completed_weight"]

    history_data = []
    for d in sorted(days.keys(), reverse=True):
        day = days[d]
        eff = (
            round((day["completed_weight"] / day["total_weight"]) * 100)
            if day["total_weight"] > 0
            else 0
        )
        history_data.append(
            {
                "date": day["date"],
                "efficiency": eff,
                "completed": day["completed_weight"],
                "total": day["total_weight"],
                "tasks": day["tasks"],
            }
        )

    return history_data, total_days, page


def get_efficiency_timeseries(user_id):
    today = format_date_iso(utc_today())
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                ti.date,
                ROUND(
                    COUNT(*) FILTER (WHERE ti2.is_completed = 1 AND ti2.is_voided = 0) * 100.0 /
                    NULLIF(COUNT(*) FILTER (WHERE ti2.is_voided = 0), 0), 1
                ) AS efficiency
            FROM task_instances ti
            JOIN task_instances ti2 ON ti.date = ti2.date AND ti.user_id = ti2.user_id
            WHERE ti.user_id = {PLACEHOLDER} AND ti.date < {PLACEHOLDER}
            GROUP BY ti.date
            ORDER BY ti.date ASC
        """,
            (user_id, today),
        )
        rows = cur.fetchall()

    dates = [row["date"] for row in rows]
    efficiencies = [float(row["efficiency"] or 0) for row in rows]

    rolling = []
    for i in range(len(efficiencies)):
        window = efficiencies[max(0, i - 6) : i + 1]
        rolling.append(round(sum(window) / len(window), 2) if window else 0)

    return dates, efficiencies, rolling


def delete_all_user_tasks(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"DELETE FROM task_instances WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        cur.execute(
            f"DELETE FROM everyday_tasks WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        cur.execute(f"DELETE FROM categories WHERE user_id = {PLACEHOLDER}", (user_id,))
        cur.execute(f"DELETE FROM meta WHERE user_id = {PLACEHOLDER}", (user_id,))
