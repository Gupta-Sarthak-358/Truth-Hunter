import logging
import time

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from models import (
    get_dashboard_day_data,
    get_dashboard_categories,
    get_recent_monsters,
    get_history_data,
    get_efficiency_timeseries,
)
from models.monsters import (
    get_monster_types,
    get_user_monsters,
    get_uncaught_monsters,
    has_migrated_monsters,
)
from models.gamification import get_user_badges
from services import (
    get_user_stats_for_display,
    reset_user_progress,
    delete_user_account,
    change_user_password,
    refresh_user_cache_async,
)
from utils import (
    utc_today,
    format_date_iso,
    format_short_date,
    get_cached,
    get_cached_with_status,
)

dashboard_bp = Blueprint("dashboard", __name__)
logger = logging.getLogger(__name__)

DASHBOARD_EFFICIENCY_TTL = 15
DASHBOARD_EVERYDAY_TTL = 30
DASHBOARD_TODAY_TTL = 15
CATEGORIES_TTL = 60
RECENT_MONSTERS_TTL = 30
STATS_TTL = 30
BADGES_TTL = 30
COLLECTION_TTL = 30
SHARED_MONSTER_TYPES_TTL = 60


def _log_step(step_name, fn):
    start = time.time()
    result = fn()
    cache_status = None
    if isinstance(result, tuple) and len(result) == 2 and result[1] in {"hit", "miss"}:
        result, cache_status = result
    logger.info(
        "Dashboard step complete",
        extra={
            "metric": f"dashboard_{step_name}",
            "duration_ms": int((time.time() - start) * 1000),
            "cache_status": cache_status,
        },
    )
    return result


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    user_id = current_user.id
    # Render the dashboard shell immediately; heavy sections are lazy-loaded.
    return render_template("dashboard.html")


@dashboard_bp.route("/dashboard/fragment/side_stats")
@login_required
def dashboard_fragment_side_stats():
    user_id = current_user.id
    stats = _log_step(
        "stats",
        lambda: get_cached_with_status(
            f"user:{user_id}:shared:stats",
            lambda: get_user_stats_for_display(user_id),
            ttl=STATS_TTL,
        ),
    )
    return render_template("fragments/dashboard_side_stats.html", stats=stats)


@dashboard_bp.route("/dashboard/fragment/side_recent")
@login_required
def dashboard_fragment_side_recent():
    user_id = current_user.id
    recent_catches = _log_step(
        "recent_catches",
        lambda: get_cached_with_status(
            f"user:{user_id}:dashboard:recent_catches",
            lambda: get_recent_monsters(user_id, limit=3),
            ttl=RECENT_MONSTERS_TTL,
        ),
    )
    return render_template(
        "fragments/dashboard_side_recent.html", recent_catches=recent_catches
    )


@dashboard_bp.route("/dashboard/fragment/main")
@login_required
def dashboard_fragment_main():
    user_id = current_user.id
    today = format_date_iso(utc_today())

    day_data = _log_step(
        "day_data",
        lambda: get_cached_with_status(
            f"user:{user_id}:dashboard:day_data:{today}",
            lambda: get_dashboard_day_data(user_id, utc_today()),
            ttl=max(DASHBOARD_EVERYDAY_TTL, DASHBOARD_TODAY_TTL, DASHBOARD_EFFICIENCY_TTL),
        ),
    )
    categories = _log_step(
        "categories",
        lambda: get_cached_with_status(
            f"user:{user_id}:shared:categories",
            lambda: get_dashboard_categories(user_id),
            ttl=CATEGORIES_TTL,
        ),
    )
    stats = _log_step(
        "stats",
        lambda: get_cached_with_status(
            f"user:{user_id}:shared:stats",
            lambda: get_user_stats_for_display(user_id),
            ttl=STATS_TTL,
        ),
    )

    return render_template(
        "fragments/dashboard_main.html",
        today=today,
        efficiency=day_data["efficiency"],
        today_tasks=day_data["today_tasks"],
        everyday_tasks=day_data["everyday_tasks"],
        categories=categories,
        stats=stats,
    )


@dashboard_bp.route("/dashboard/fragment/modals")
@login_required
def dashboard_fragment_modals():
    user_id = current_user.id
    today = format_date_iso(utc_today())
    day_data = get_cached(
        f"user:{user_id}:dashboard:day_data:{today}",
        lambda: get_dashboard_day_data(user_id, utc_today()),
        ttl=max(DASHBOARD_EVERYDAY_TTL, DASHBOARD_TODAY_TTL, DASHBOARD_EFFICIENCY_TTL),
    )

    return render_template(
        "fragments/dashboard_modals.html",
        today_tasks=day_data["today_tasks"],
        everyday_tasks=day_data["everyday_tasks"],
    )


@dashboard_bp.route("/history")
@login_required
def history():
    user_id = current_user.id
    page = request.args.get("page", 1, type=int)

    history_data, total_days, page = get_history_data(user_id, page)

    return render_template(
        "history.html", history=history_data, total_days=total_days, current_page=page
    )


@dashboard_bp.route("/graphs")
@login_required
def graphs():
    user_id = current_user.id
    dates, efficiencies, rolling_avg = get_efficiency_timeseries(user_id)

    return render_template(
        "graphs.html",
        dates=dates,
        efficiencies=efficiencies,
        rolling=rolling_avg,
    )


@dashboard_bp.route("/collection")
@login_required
def collection():
    user_id = current_user.id
    type_id = request.args.get("type", type=int)
    page = request.args.get("page", 1, type=int)

    monsters, total = get_cached(
        f"user:{user_id}:collection:caught:type:{type_id}:page:{page}",
        lambda: get_user_monsters(user_id, type_id, page),
        ttl=COLLECTION_TTL,
    )
    uncaught_monsters = get_cached(
        f"user:{user_id}:collection:uncaught:type:{type_id}",
        lambda: get_uncaught_monsters(user_id, type_id),
        ttl=COLLECTION_TTL,
    )
    types = get_cached(
        "shared:monster_types", get_monster_types, ttl=SHARED_MONSTER_TYPES_TTL
    )
    migrated = has_migrated_monsters(user_id)
    stats = get_cached(
        f"user:{user_id}:shared:stats",
        lambda: get_user_stats_for_display(user_id),
        ttl=STATS_TTL,
    )
    total_monsters = total + len(uncaught_monsters)

    monsters_by_type = {}
    for m in monsters:
        m["caught_date_label"] = format_short_date(m.get("caught_date"))
        type_name = m["type_name"]
        if type_name not in monsters_by_type:
            monsters_by_type[type_name] = []
        monsters_by_type[type_name].append(m)

    return render_template(
        "collection.html",
        monsters=monsters,
        uncaught_monsters=uncaught_monsters,
        monsters_by_type=monsters_by_type,
        types=types,
        stats=stats,
        total=total,
        total_monsters=total_monsters,
        has_migrated=migrated,
        migrated=migrated,
        selected_type=type_id,
    )


@dashboard_bp.route("/profile")
@login_required
def profile():
    user_id = current_user.id

    from db import get_cursor, PLACEHOLDER
    from models.user import get_user_profile

    profile_data = get_user_profile(user_id)
    stats = get_cached(
        f"user:{user_id}:shared:stats",
        lambda: get_user_stats_for_display(user_id),
        ttl=STATS_TTL,
    )
    recent_catches = get_cached(
        f"user:{user_id}:profile:recent_catches",
        lambda: get_recent_monsters(user_id, limit=6),
        ttl=RECENT_MONSTERS_TTL,
    )
    earned_badges = get_cached(
        f"user:{user_id}:badges:earned",
        lambda: get_user_badges(user_id),
        ttl=BADGES_TTL,
    )

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                mt.id,
                mt.name,
                mt.icon,
                mt.color,
                COUNT(DISTINCT m.id) AS total_monsters,
                COUNT(DISTINCT um.monster_id) AS caught_monsters
            FROM monster_types mt
            LEFT JOIN monsters m ON m.type_id = mt.id
            LEFT JOIN user_monsters um
                ON um.monster_id = m.id
               AND um.user_id = {PLACEHOLDER}
            GROUP BY mt.id, mt.name, mt.icon, mt.color
            ORDER BY mt.name
            """,
            (user_id,),
        )
        type_progress = [dict(row) for row in cur.fetchall()]

    collection_completion = 0
    if type_progress:
        total_monsters = sum(row["total_monsters"] for row in type_progress)
        caught_monsters = sum(row["caught_monsters"] for row in type_progress)
        if total_monsters > 0:
            collection_completion = round((caught_monsters / total_monsters) * 100)

    joined_at = None
    if profile_data and profile_data.get("created_at"):
        joined_at = profile_data["created_at"].strftime("%b %d, %Y")

    return render_template(
        "profile.html",
        profile=profile_data,
        joined_at=joined_at,
        stats=stats,
        recent_catches=recent_catches,
        earned_badges=earned_badges,
        type_progress=type_progress,
        collection_completion=collection_completion,
    )


@dashboard_bp.route("/collection/fuse", methods=["POST"], endpoint="collection_fuse")
@dashboard_bp.route("/collection/fuse", methods=["POST"])
@login_required
def fuse_collection():
    user_id = current_user.id
    from models.monsters import fuse_duplicate_monsters
    shinies_created = fuse_duplicate_monsters(user_id)
    refresh_user_cache_async(user_id)
    
    if shinies_created > 0:
        flash(f"🧬 Evolution successful! Created {shinies_created} new Shiny monster(s)!", "success")
    else:
        flash("No monsters were eligible for fusion. You need 3 identical non-shiny monsters.", "info")
        
    return redirect(url_for("dashboard.collection"))


@dashboard_bp.route("/badges")
@login_required
def badges():
    user_id = current_user.id

    earned_badges = get_cached(
        f"user:{user_id}:badges:earned",
        lambda: get_user_badges(user_id),
        ttl=BADGES_TTL,
    )
    stats = get_cached(
        f"user:{user_id}:shared:stats",
        lambda: get_user_stats_for_display(user_id),
        ttl=STATS_TTL,
    )
    types = get_cached(
        "shared:monster_types", get_monster_types, ttl=SHARED_MONSTER_TYPES_TTL
    )

    from db import get_cursor

    with get_cursor() as cur:
        cur.execute("SELECT * FROM badges ORDER BY condition_value")
        all_badges = cur.fetchall()

    earned_ids = [b.get("badge_id", b.get("id")) for b in earned_badges]

    return render_template(
        "badges.html",
        earned_badges=earned_badges,
        all_badges=[dict(b) for b in all_badges],
        earned_ids=earned_ids,
        stats=stats,
        types=types,
    )


@dashboard_bp.route("/categories")
@login_required
def categories():
    user_id = current_user.id
    cats = get_cached(
        f"user:{user_id}:shared:categories",
        lambda: get_categories(user_id),
        ttl=CATEGORIES_TTL,
    )
    types = get_cached(
        "shared:monster_types", get_monster_types, ttl=SHARED_MONSTER_TYPES_TTL
    )

    return render_template("categories.html", categories=cats, monster_types=types)


@dashboard_bp.route("/categories/add", methods=["POST"])
@login_required
def add_category():
    user_id = current_user.id
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#4a90d9")
    monster_type_id = request.form.get("monster_type_id")

    if not name:
        flash("Category name required", "error")
        return redirect(url_for("dashboard.categories"))

    from models import add_category as add_cat

    add_cat(user_id, name, color, monster_type_id or None)
    refresh_user_cache_async(user_id)

    flash("Category added!", "success")
    return redirect(url_for("dashboard.categories"))


@dashboard_bp.route("/categories/delete/<int:cat_id>", methods=["POST"])
@login_required
def delete_category(cat_id):
    user_id = current_user.id
    from services import delete_category_by_id

    delete_category_by_id(cat_id, user_id)
    refresh_user_cache_async(user_id)
    flash("Category deleted", "success")
    return redirect(url_for("dashboard.categories"))


@dashboard_bp.route("/categories/edit/<int:cat_id>", methods=["POST"])
@login_required
def edit_category(cat_id):
    user_id = current_user.id
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#4a90d9")
    monster_type_id = request.form.get("monster_type_id")

    from models import update_category

    update_category(user_id, cat_id, name, color, monster_type_id or None)
    refresh_user_cache_async(user_id)

    flash("Category updated", "success")
    return redirect(url_for("dashboard.categories"))


@dashboard_bp.route("/categories/edit", methods=["POST"])
@login_required
def edit_category_post():
    user_id = current_user.id
    cat_id = request.form.get("cat_id")
    if not cat_id:
        flash("Category ID required", "error")
        return redirect(url_for("dashboard.categories"))
    
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#4a90d9")
    monster_type_id = request.form.get("monster_type_id")

    from models import update_category

    update_category(user_id, int(cat_id), name, color, monster_type_id or None)
    refresh_user_cache_async(user_id)

    flash("Category updated", "success")
    return redirect(url_for("dashboard.categories"))


@dashboard_bp.route("/settings")
@login_required
def settings():
    user_id = current_user.id

    from models.user import get_user_password_changed_at

    password_changed_at = get_user_password_changed_at(user_id)
    password_changed_str = (
        password_changed_at.strftime("%b %d, %Y") if password_changed_at else None
    )

    stats = get_user_stats_for_display(user_id)

    return render_template(
        "settings.html", password_changed_at=password_changed_str, stats=stats
    )


@dashboard_bp.route("/settings/change_password", methods=["POST"])
@login_required
def change_password():
    user_id = current_user.id
    new_password = request.form.get("new_password", "")

    if len(new_password) < 6:
        flash("Password must be at least 6 characters", "error")
        return redirect(url_for("dashboard.settings"))

    change_user_password(user_id, new_password)
    refresh_user_cache_async(user_id)
    flash("Password updated!", "success")
    return redirect(url_for("dashboard.settings"))


@dashboard_bp.route("/settings/change_username", methods=["POST"])
@login_required
def change_username():
    user_id = current_user.id
    new_username = request.form.get("new_username", "").strip()

    if len(new_username) < 3:
        return jsonify({"success": False, "error": "Username must be at least 3 characters"}), 400

    from models.user import update_user_username

    try:
        update_user_username(user_id, new_username)
    except Exception:
        return jsonify({"success": False, "error": "Username already exists"}), 409

    current_user.username = new_username
    refresh_user_cache_async(user_id)
    return jsonify({"success": True, "username": new_username})


@dashboard_bp.route("/settings/reset_progress", methods=["POST"])
@login_required
def reset_progress():
    user_id = current_user.id
    confirm = request.form.get("confirm", "").strip()

    if confirm != "RESET":
        flash('Type "RESET" to confirm progress reset', "error")
        return redirect(url_for("dashboard.settings"))

    from models import delete_all_user_tasks, delete_user_gamification

    delete_all_user_tasks(user_id)
    delete_user_gamification(user_id)
    reset_user_progress(user_id)
    refresh_user_cache_async(user_id)

    flash("Progress has been reset", "success")
    return redirect(url_for("dashboard.dashboard"))


@dashboard_bp.route("/settings/delete_account", methods=["POST"])
@login_required
def delete_account():
    user_id = current_user.id
    confirm = request.form.get("confirm_delete", "").strip()

    if confirm != "DELETE":
        flash('Type "DELETE" to confirm account deletion', "error")
        return redirect(url_for("dashboard.settings"))

    from flask_login import logout_user

    delete_user_account(user_id)
    logout_user()

    flash("Account deleted", "info")
    return redirect(url_for("homepage"))
