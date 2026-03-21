from flask import Blueprint, redirect, url_for, request, flash
from flask_login import current_user, login_required
from services import (
    add_new_task,
    add_recurring_task,
    update_task_category,
    toggle_recurring_task,
    process_task_completion,
    refresh_user_cache_async,
)
from models import get_task, reorder_tasks, copy_yesterday_tasks
from models.tasks import is_valid_recurrence
from models.monsters import get_monster_types
task_bp = Blueprint("tasks", __name__, url_prefix="/tasks")


@task_bp.route("/toggle/<int:task_id>", methods=["POST"])
@login_required
def toggle(task_id):
    user_id = current_user.id
    task = get_task(task_id, user_id)

    if not task:
        flash("Task not found", "error")
        return redirect(url_for("dashboard.dashboard"))

    task.get("date")
    from utils import utc_today, format_date_iso

    today = format_date_iso(utc_today())

    if task["date"] != today:
        flash("Can only toggle today's tasks", "error")
        return redirect(url_for("dashboard.dashboard"))

    was_completed = task["is_completed"]

    if not was_completed:
        monster_id, is_shiny, leveled_up, new_level, xp_earned = (
            process_task_completion(user_id, task_id, task.get("category_id"))
        )

        if monster_id:
            get_monster_types()

            if is_shiny:
                flash("✨ SHINY! You caught something special!", "legendary")
            else:
                flash("You caught a monster!", "success")

            if leveled_up:
                flash(f"🎉 LEVEL UP! You're now level {new_level}!", "levelup")
    else:
        flash("Task already completed", "info")

    refresh_user_cache_async(user_id)
    return redirect(url_for("dashboard.dashboard"))


@task_bp.route("/add", methods=["POST"])
@login_required
def add_task():
    user_id = current_user.id
    name = request.form.get("name", "").strip()
    category_id = request.form.get("category_id")

    if not name:
        flash("Task name required", "error")
        return redirect(url_for("dashboard.dashboard"))

    add_new_task(user_id, name, category_id or None)
    refresh_user_cache_async(user_id)
    flash("Task added!", "success")
    return redirect(url_for("dashboard.dashboard"))


@task_bp.route("/add_everyday", methods=["POST"])
@login_required
def add_everyday():
    user_id = current_user.id
    name = request.form.get("name", "").strip()
    category_id = request.form.get("category_id")
    recurrence = request.form.get("recurrence", "daily")

    if not name:
        flash("Task name required", "error")
        return redirect(url_for("dashboard.dashboard"))

    if not is_valid_recurrence(recurrence):
        flash("Invalid recurrence option", "error")
        return redirect(url_for("dashboard.dashboard"))

    add_recurring_task(user_id, name, category_id or None, recurrence)
    refresh_user_cache_async(user_id)
    flash("Recurring task added!", "success")
    return redirect(url_for("dashboard.dashboard"))


@task_bp.route("/toggle_everyday/<int:task_id>", methods=["POST"])
@login_required
def toggle_everyday(task_id):
    user_id = current_user.id
    toggle_recurring_task(task_id, user_id)
    refresh_user_cache_async(user_id)
    return redirect(url_for("dashboard.dashboard"))


@task_bp.route("/update/<int:task_id>", methods=["POST"])
@login_required
def update(task_id):
    user_id = current_user.id
    category_id = request.form.get("category")
    notes = request.form.get("notes")
    due_date = request.form.get("due_date")
    priority = request.form.get("priority")

    if priority:
        try:
            priority = int(priority)
        except ValueError:
            flash("Invalid priority value", "error")
            return redirect(url_for("dashboard.dashboard"))

    update_task_category(task_id, user_id, category_id, notes, due_date, priority)
    refresh_user_cache_async(user_id)
    return redirect(url_for("dashboard.dashboard"))


@task_bp.route("/reorder", methods=["POST"])
@login_required
def reorder():
    user_id = current_user.id
    orders_str = request.form.get("orders", "{}")
    import json

    try:
        orders = json.loads(orders_str)
        reorder_tasks(user_id, orders)
        refresh_user_cache_async(user_id)
    except json.JSONDecodeError:
        pass
    return "", 204


@task_bp.route("/copy_yesterday", methods=["POST"])
@login_required
def copy_yesterday():
    user_id = current_user.id
    copied = copy_yesterday_tasks(user_id)
    refresh_user_cache_async(user_id)
    if copied > 0:
        flash(f"Copied {copied} tasks from yesterday", "success")
    else:
        flash("No tasks to copy from yesterday", "info")
    return redirect(url_for("dashboard.dashboard"))
