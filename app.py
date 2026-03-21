import os
import json
import time
import logging
import csv
from io import StringIO
from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    g,
    make_response,
    Response,
)
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, current_user, login_required
from datetime import datetime, timezone

from db.pool import init_pool, db_pool
from db import get_db, get_cur, db_close
from routes import auth_bp, task_bp, dashboard_bp
from models import init_db
from extensions import limiter

env = os.environ.get("FLASK_ENV", "development")


class StructuredFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "user_id", None):
            log_data["user_id"] = getattr(record, "user_id")
        if getattr(record, "path", None):
            log_data["path"] = getattr(record, "path")
        if getattr(record, "duration_ms", None) is not None:
            log_data["duration_ms"] = getattr(record, "duration_ms")
        if getattr(record, "metric", None):
            log_data["metric"] = getattr(record, "metric")
            log_data["metric_value"] = getattr(record, "metric_value", 1)
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(StructuredFormatter())
root_logger.handlers = [handler]
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_object(__import__("config").config[env])
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"  # type: ignore
login_manager.login_message = None  # type: ignore
login_manager.session_protection = "strong"
limiter.init_app(app)


@app.route("/healthz")
def healthz():
    return "ok", 200


@login_manager.user_loader
def load_user(user_id):
    from models.user import User

    return User.get_by_id(int(user_id))


@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


@app.before_request
def refresh_session():
    if current_user.is_authenticated:
        from flask import session
        from utils import invalidate_user_cache
        from services import run_daily_sync_if_needed

        session.permanent = True
        if request.endpoint not in {"static", "auth.logout"}:
            synced, _, _ = run_daily_sync_if_needed(current_user.id)
            if synced:
                invalidate_user_cache(current_user.id)
    g.start_time = time.time()


@app.after_request
def log_request_time(response):
    duration_ms = int((time.time() - getattr(g, "start_time", time.time())) * 1000)
    extra = {
        "path": request.path,
        "method": request.method,
        "status": response.status_code,
        "duration_ms": duration_ms,
    }
    if current_user.is_authenticated:
        extra["user_id"] = current_user.id
    logger.info("Request completed", extra=extra)
    return response


@app.teardown_appcontext
def close_db_on_teardown(exception):
    if exception:
        extra = {"path": request.path} if request else {}
        logger.exception("Unhandled request exception", extra=extra)


with app.app_context():
    init_pool()
    logger.info("Initializing database...")
    init_db()
    logger.info("Startup complete.")


# ---------- BLUEPRINTS ----------
app.register_blueprint(auth_bp)
app.register_blueprint(task_bp)
app.register_blueprint(dashboard_bp)


# ---------- ERROR HANDLERS ----------


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", error_code=404, message="Page Not Found"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", error_code=500, message="Server Error"), 500


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", error_code=403, message="Forbidden"), 403


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", error_code=400, message="Bad Request"), 400


# ---------- HOMEPAGE ----------


@app.route("/")
def homepage():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.dashboard"))
    return render_template("homepage.html")


# ---------- DEBUG ROUTES ----------


@app.route("/debug/db")
@login_required
def debug_db():
    if env != "development":
        return {"error": "Debug endpoints disabled in production"}, 403

    return {
        "pool_min": db_pool.minconn,
        "pool_max": db_pool.maxconn,
        "status": "active",
    }


# ---------- EXPORT/IMPORT ----------


@app.route("/export_full")
@login_required
def export_full():
    user_id = current_user.id

    from models import get_gamification_stats, get_categories
    from models.monsters import get_recent_monsters
    from models.gamification import get_user_badges
    from db import PLACEHOLDER

    stats = get_gamification_stats(user_id)
    categories = get_categories(user_id)

    from utils import format_date_iso, utc_today
    from datetime import timedelta

    conn = get_db()
    cur = get_cur(conn)

    try:
        cur.execute(
            f"SELECT * FROM everyday_tasks WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        everyday_tasks = [dict(row) for row in cur.fetchall()]

        cur.execute(
            f"SELECT * FROM task_instances WHERE user_id = {PLACEHOLDER} AND date >= {PLACEHOLDER}",
            (user_id, format_date_iso(utc_today() - timedelta(days=90))),
        )
        task_instances = [dict(row) for row in cur.fetchall()]

        monsters = get_recent_monsters(user_id, limit=1000)
        badges = get_user_badges(user_id)
    finally:
        db_close(cur, conn)

    data = {
        "schema_version": 2,
        "export_date": datetime.now(timezone.utc).isoformat(),
        "gamification_stats": stats,
        "categories": categories,
        "everyday_tasks": everyday_tasks,
        "task_instances": task_instances,
        "monsters": monsters,
        "badges": badges,
    }

    response = make_response(json.dumps(data, indent=2))
    response.headers["Content-Disposition"] = (
        "attachment; filename=truth_hacker_full_backup.json"
    )
    response.headers["Content-type"] = "application/json"
    return response


@app.route("/export_collection")
@login_required
def export_collection():
    from models.monsters import export_collection as do_export_collection

    data = do_export_collection(current_user.id)
    response = make_response(json.dumps(data, indent=2))
    response.headers["Content-Disposition"] = (
        "attachment; filename=truth_hacker_collection_backup.json"
    )
    response.headers["Content-type"] = "application/json"
    return response


@app.route("/export")
@login_required
def export_tasks_csv():
    from db import PLACEHOLDER

    conn = get_db()
    cur = get_cur(conn)

    try:
        cur.execute(
            f"""
            SELECT name, date, weight, is_completed, is_locked, is_voided, category_id, notes, due_date, priority, sort_order
            FROM task_instances
            WHERE user_id = {PLACEHOLDER}
            ORDER BY date DESC, priority DESC, sort_order, name
        """,
            (current_user.id,),
        )
        rows = cur.fetchall()
    finally:
        db_close(cur, conn)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "name",
            "date",
            "weight",
            "is_completed",
            "is_locked",
            "is_voided",
            "category_id",
            "notes",
            "due_date",
            "priority",
            "sort_order",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["name"],
                row["date"],
                row["weight"],
                row["is_completed"],
                row["is_locked"],
                row["is_voided"],
                row["category_id"],
                row["notes"],
                row["due_date"],
                row["priority"],
                row["sort_order"],
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=truth_hacker_tasks.csv"},
    )


@app.route("/import_full", methods=["POST"])
@login_required
def import_full():
    if "file" not in request.files:
        flash("No file uploaded", "error")
        return redirect(url_for("dashboard.settings"))

    file = request.files["file"]
    if file.filename == "":
        flash("No file selected", "error")
        return redirect(url_for("dashboard.settings"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except json.JSONDecodeError:
        flash("Invalid JSON file", "error")
        return redirect(url_for("dashboard.settings"))

    if data.get("schema_version") != 2:
        flash("Incompatible backup version", "error")
        return redirect(url_for("dashboard.settings"))

    flash("Full restore is not yet implemented", "info")
    return redirect(url_for("dashboard.settings"))


@app.route("/migrate_monsters", methods=["POST"])
@login_required
def migrate_existing_monsters():
    user_id = current_user.id

    from db import get_cursor, PLACEHOLDER

    migrated = 0
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, name, category_id, date, is_completed
            FROM task_instances
            WHERE user_id = {PLACEHOLDER} AND is_completed = 1
            ORDER BY date ASC
        """,
            (user_id,),
        )
        tasks = cur.fetchall()

        for task in tasks:
            from models.monsters import award_monster

            monster_id, is_shiny, _, _, _ = award_monster(
                user_id, task["id"], task.get("category_id")
            )
            if monster_id:
                migrated += 1

        if migrated > 0:
            cur.execute(
                f"""
                INSERT INTO meta (user_id, key, value)
                VALUES ({PLACEHOLDER}, 'migrated_monsters', '1')
                ON CONFLICT (user_id, key) DO UPDATE SET value = '1'
                """,
                (user_id,),
            )

    flash(f"Migrated {migrated} monsters", "success")
    return redirect(url_for("dashboard.collection"))


@app.route("/import_collection", methods=["POST"])
@login_required
def import_collection():
    if "file" not in request.files:
        flash("No file uploaded", "error")
        return redirect(url_for("dashboard.settings"))

    file = request.files["file"]
    if file.filename == "":
        flash("No file selected", "error")
        return redirect(url_for("dashboard.settings"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except json.JSONDecodeError:
        flash("Invalid JSON file", "error")
        return redirect(url_for("dashboard.settings"))

    from models.monsters import import_collection as do_import

    if do_import(current_user.id, data):
        flash("Collection imported successfully", "success")
    else:
        flash("Failed to import collection", "error")

    return redirect(url_for("dashboard.settings"))
