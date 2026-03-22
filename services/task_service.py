from models import (
    add_task,
    add_everyday_task,
    complete_task,
    delete_task,
    toggle_everyday_task,
    update_task,
    delete_category,
    award_monster,
    check_and_update_perfect_day,
    update_type_complete_count,
)
from models.gamification import update_streak_on_completion
import logging
import threading
import time

logger = logging.getLogger(__name__)

_deferred_lock = threading.Lock()
_deferred_inflight = set()
_deferred_pending = {}


def _run_deferred_post_completion(user_id, monster_id):
    """Run non-critical completion updates after the response path."""
    try:
        from services.gamification_service import check_and_award_all, refresh_user_cache_async

        needs_type_refresh = bool(monster_id)

        while True:
            try:
                step_start = time.time()
                check_and_update_perfect_day(user_id)
                logger.info(
                    "Task completion step complete",
                    extra={
                        "metric": "task_complete_perfect_day_deferred",
                        "user_id": user_id,
                        "duration_ms": int((time.time() - step_start) * 1000),
                    },
                )

                if needs_type_refresh:
                    step_start = time.time()
                    update_type_complete_count(user_id)
                    logger.info(
                        "Task completion step complete",
                        extra={
                            "metric": "task_complete_update_type_count_deferred",
                            "user_id": user_id,
                            "duration_ms": int((time.time() - step_start) * 1000),
                        },
                    )

                check_and_award_all(user_id)
                refresh_user_cache_async(user_id)
            except Exception:
                logger.exception("Deferred task completion post-processing failed")

            with _deferred_lock:
                pending = _deferred_pending.pop(user_id, None)
                if not pending:
                    _deferred_inflight.discard(user_id)
                    break
                needs_type_refresh = pending.get("needs_type_refresh", False)
    except Exception:
        logger.exception("Deferred task completion worker failed")


def _spawn_deferred_post_completion(user_id, monster_id):
    with _deferred_lock:
        if user_id in _deferred_inflight:
            state = _deferred_pending.setdefault(user_id, {"needs_type_refresh": False})
            state["needs_type_refresh"] = state["needs_type_refresh"] or bool(monster_id)
            return
        _deferred_inflight.add(user_id)

    worker = threading.Thread(
        target=_run_deferred_post_completion,
        args=(user_id, monster_id),
        daemon=True,
        name=f"task-post-process-{user_id}",
    )
    worker.start()

def process_task_completion(user_id, task_id, category_id=None):
    """Process task completion and award monster"""
    monster_id = None
    is_shiny = False
    leveled_up = False
    new_level = 0
    xp_earned = 0

    step_start = time.time()
    completed = complete_task(task_id, user_id)
    logger.info(
        "Task completion step complete",
        extra={"metric": "task_complete_toggle", "user_id": user_id, "duration_ms": int((time.time() - step_start) * 1000)},
    )
    if not completed:
        return None, False, False, 0, 0

    step_start = time.time()
    monster_id, is_shiny, _, _, _ = award_monster(
        user_id, task_id, category_id
    )
    logger.info(
        "Task completion step complete",
        extra={"metric": "task_complete_award_monster", "user_id": user_id, "duration_ms": int((time.time() - step_start) * 1000)},
    )

    step_start = time.time()
    _, _, leveled_up, new_level, xp_earned = update_streak_on_completion(user_id, task_id)
    logger.info(
        "Task completion step complete",
        extra={"metric": "task_complete_update_streak", "user_id": user_id, "duration_ms": int((time.time() - step_start) * 1000)},
    )

    _spawn_deferred_post_completion(user_id, monster_id)

    if monster_id:
        logger.info("Monster Caught", extra={"metric": "monster_caught", "user_id": user_id, "monster_id": monster_id, "is_shiny": is_shiny})

    if leveled_up:
        logger.info("User Leveled Up", extra={"metric": "level_up", "user_id": user_id, "metric_value": new_level})

    logger.info("Task Completed", extra={"metric": "task_completed", "user_id": user_id, "xp_earned": xp_earned})

    return monster_id, is_shiny, leveled_up, new_level, xp_earned


def add_new_task(user_id, name, category_id=None):
    """Add a new one-time task for today"""
    return add_task(user_id, name, category_id)


def add_recurring_task(user_id, name, category_id=None, recurrence="daily"):
    """Add a new recurring everyday task"""
    return add_everyday_task(user_id, name, category_id, recurrence)


def update_task_category(
    task_id, user_id, category_id=None, notes=None, due_date=None, priority=None
):
    """Update task properties"""
    update_task(task_id, user_id, category_id, notes, due_date, priority)


def delete_task_by_id(task_id, user_id):
    """Delete a task"""
    delete_task(task_id, user_id)


def toggle_recurring_task(task_id, user_id):
    """Toggle everyday task active status"""
    toggle_everyday_task(task_id, user_id)


def delete_category_by_id(category_id, user_id):
    """Delete a category"""
    delete_category(user_id, category_id)
