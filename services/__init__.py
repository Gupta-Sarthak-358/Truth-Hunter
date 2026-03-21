from .user_service import (
    register_user,
    authenticate_user,
    change_user_password,
    change_username,
    record_failed_login,
    check_login_locked,
    delete_user_account,
)

from .task_service import (
    process_task_completion,
    add_new_task,
    add_recurring_task,
    update_task_category,
    delete_task_by_id,
    toggle_recurring_task,
    delete_category_by_id,
)

from .gamification_service import (
    check_and_award_all,
    update_user_stats,
    get_user_stats_for_display,
    prewarm_user_cache_async,
    refresh_user_cache_async,
    run_daily_sync_if_needed,
    run_daily_sync_if_needed_async,
    reset_user_progress,
)

__all__ = [
    # User
    "register_user",
    "authenticate_user",
    "change_user_password",
    "change_username",
    "record_failed_login",
    "check_login_locked",
    "delete_user_account",
    # Tasks
    "process_task_completion",
    "add_new_task",
    "add_recurring_task",
    "update_task_category",
    "delete_task_by_id",
    "toggle_recurring_task",
    "delete_category_by_id",
    # Gamification
    "check_and_award_all",
    "update_user_stats",
    "get_user_stats_for_display",
    "prewarm_user_cache_async",
    "refresh_user_cache_async",
    "run_daily_sync_if_needed",
    "run_daily_sync_if_needed_async",
    "reset_user_progress",
]
