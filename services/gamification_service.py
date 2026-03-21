from db import get_cursor, PLACEHOLDER
import logging
import threading
import time
from models import (
    get_dashboard_day_data,
    get_dashboard_categories,
    get_gamification_stats,
    check_and_award_badges,
    check_and_award_freeze,
    get_user_monsters,
    get_recent_monsters,
    get_monster_types,
    reset_gamification_stats,
    reconcile_days,
    ensure_today_tasks,
)
from models.gamification import get_user_badges
from models.monsters import get_uncaught_monsters, _get_monster_catalog, _load_category_type_map
from models.gamification import check_and_grant_daily_reward
from utils import format_date_iso, utc_today, get_cached

logger = logging.getLogger(__name__)

DASHBOARD_DAY_DATA_TTL = 30
DASHBOARD_CATEGORIES_TTL = 60
DASHBOARD_RECENT_TTL = 30
STATS_TTL = 30
COLLECTION_TTL = 30
BADGES_TTL = 30
SHARED_MONSTER_TYPES_TTL = 60

# In-process "singleflight" to avoid spawning duplicate background jobs per-user.
# Note: this doesn't coordinate across multiple web instances. That's acceptable for now.
_daily_sync_inflight = set()
_daily_sync_lock = threading.Lock()


def _prewarm_user_cache_phase1(user_id):
    """Warm only what's needed for the first meaningful paint (dashboard fragments)."""
    today = format_date_iso(utc_today())

    get_cached(
        f"user:{user_id}:dashboard:day_data:{today}",
        lambda: get_dashboard_day_data(user_id, utc_today()),
        ttl=DASHBOARD_DAY_DATA_TTL,
    )
    get_cached(
        f"user:{user_id}:shared:categories",
        lambda: get_dashboard_categories(user_id),
        ttl=DASHBOARD_CATEGORIES_TTL,
    )
    get_cached(
        f"user:{user_id}:dashboard:recent_catches",
        lambda: get_recent_monsters(user_id, limit=3),
        ttl=DASHBOARD_RECENT_TTL,
    )
    get_cached(
        f"user:{user_id}:shared:stats",
        lambda: get_user_stats_for_display(user_id),
        ttl=STATS_TTL,
    )


def _prewarm_user_cache_phase2(user_id):
    """Warm heavier, non-critical pages after the app is already responsive."""
    get_cached(
        f"user:{user_id}:collection:caught:type:None:page:1",
        lambda: get_user_monsters(user_id, None, 1),
        ttl=COLLECTION_TTL,
    )
    get_cached(
        f"user:{user_id}:collection:uncaught:type:None",
        lambda: get_uncaught_monsters(user_id, None),
        ttl=COLLECTION_TTL,
    )
    get_cached(
        "shared:monster_types",
        get_monster_types,
        ttl=SHARED_MONSTER_TYPES_TTL,
    )
    _get_monster_catalog()
    get_cached(
        f"user:{user_id}:category_type_map",
        lambda: _load_category_type_map(user_id),
        ttl=DASHBOARD_CATEGORIES_TTL,
    )
    get_cached(
        f"user:{user_id}:badges:earned",
        lambda: get_user_badges(user_id),
        ttl=BADGES_TTL,
    )
    get_cached(
        f"user:{user_id}:profile:recent_catches",
        lambda: get_recent_monsters(user_id, limit=6),
        ttl=DASHBOARD_RECENT_TTL,
    )


def _prewarm_user_cache(user_id):
    start = time.time()
    try:
        _prewarm_user_cache_phase1(user_id)
        # Yield to interactive requests; then warm the rest.
        time.sleep(0.1)
        _prewarm_user_cache_phase2(user_id)

        logger.info(
            "User cache prewarmed",
            extra={
                "metric": "cache_prewarm",
                "user_id": user_id,
                "duration_ms": int((time.time() - start) * 1000),
            },
        )
    except Exception:
        logger.exception("User cache prewarm failed", extra={"user_id": user_id})


def prewarm_user_cache_async(user_id):
    worker = threading.Thread(
        target=_prewarm_user_cache,
        args=(user_id,),
        daemon=True,
        name=f"cache-prewarm-{user_id}",
    )
    worker.start()


def refresh_user_cache_async(user_id):
    from utils import invalidate_user_cache

    def _refresh():
        invalidate_user_cache(user_id)
        _prewarm_user_cache(user_id)

    worker = threading.Thread(
        target=_refresh,
        daemon=True,
        name=f"cache-refresh-{user_id}",
    )
    worker.start()


def check_and_award_all(user_id):
    """Check and award all badges and freeze charges"""
    start = time.time()
    check_and_award_badges(user_id)
    logger.info(
        "Gamification step complete",
        extra={"metric": "award_badges", "user_id": user_id, "duration_ms": int((time.time() - start) * 1000)},
    )
    start = time.time()
    check_and_award_freeze(user_id)
    logger.info(
        "Gamification step complete",
        extra={"metric": "award_freeze", "user_id": user_id, "duration_ms": int((time.time() - start) * 1000)},
    )


def update_user_stats(user_id):
    """Update all user statistics"""
    check_and_award_all(user_id)


def run_daily_sync_if_needed(user_id):
    """Run once-per-day maintenance outside dashboard reads."""
    today = format_date_iso(utc_today())

    with get_cursor() as cur:
        cur.execute(
            f"SELECT value FROM meta WHERE user_id = {PLACEHOLDER} AND key = 'last_sync_date'",
            (user_id,),
        )
        row = cur.fetchone()
        if row and row["value"] == today:
            return False, 0, 0

    start = time.time()
    reconcile_days(user_id)
    logger.info(
        "Daily sync step complete",
        extra={"metric": "daily_sync_reconcile_days", "user_id": user_id, "duration_ms": int((time.time() - start) * 1000)},
    )
    start = time.time()
    ensure_today_tasks(user_id)
    logger.info(
        "Daily sync step complete",
        extra={"metric": "daily_sync_ensure_today_tasks", "user_id": user_id, "duration_ms": int((time.time() - start) * 1000)},
    )
    start = time.time()
    daily_xp, daily_level = check_and_grant_daily_reward(user_id)
    logger.info(
        "Daily sync step complete",
        extra={"metric": "daily_sync_grant_reward", "user_id": user_id, "duration_ms": int((time.time() - start) * 1000)},
    )

    start = time.time()
    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO meta (user_id, key, value)
            VALUES ({PLACEHOLDER}, 'last_sync_date', {PLACEHOLDER})
            ON CONFLICT (user_id, key) DO UPDATE
            SET value = EXCLUDED.value
            """,
            (user_id, today),
        )
    logger.info(
        "Daily sync step complete",
        extra={"metric": "daily_sync_record_meta", "user_id": user_id, "duration_ms": int((time.time() - start) * 1000)},
    )

    return True, daily_xp, daily_level


def run_daily_sync_if_needed_async(user_id):
    """
    Fire-and-forget daily sync so requests don't block on cold-start work.
    If a sync runs, we also invalidate user caches so the next fragment fetch is correct.
    """

    with _daily_sync_lock:
        if user_id in _daily_sync_inflight:
            return
        _daily_sync_inflight.add(user_id)

    def _worker():
        try:
            from utils import invalidate_user_cache

            synced, _, _ = run_daily_sync_if_needed(user_id)
            if synced:
                invalidate_user_cache(user_id)
        except Exception:
            logger.exception("Daily sync async failed", extra={"user_id": user_id})
        finally:
            with _daily_sync_lock:
                _daily_sync_inflight.discard(user_id)

    threading.Thread(
        target=_worker,
        daemon=True,
        name=f"daily-sync-{user_id}",
    ).start()


def get_user_stats_for_display(user_id):
    """Get formatted stats for display"""
    stats = get_gamification_stats(user_id)

    return {
        "total_tasks": stats.get("total_tasks", 0),
        "current_streak": stats.get("current_streak", 0),
        "longest_streak": stats.get("longest_streak", 0),
        "level": stats.get("level", 1),
        "xp": stats.get("xp", 0),
        "xp_thresholds": stats.get("xp_thresholds", []),
        "xp_progress": _calculate_xp_progress(
            stats.get("xp", 0), stats.get("level", 1), stats.get("xp_thresholds", [])
        ),
        "perfect_days": stats.get("perfect_days", 0),
        "freeze_charges": stats.get("freeze_charges", 0),
        "unique_monsters": stats.get("unique_monsters", 0),
        "shiny_count": stats.get("shiny_count", 0),
        "legendary_count": stats.get("legendary_count", 0),
    }


def _calculate_xp_progress(xp, level, thresholds):
    """Calculate XP progress percentage to next level"""
    if level >= len(thresholds):
        return 100

    current_threshold = thresholds[level - 1] if level > 0 else 0
    next_threshold = thresholds[level] if level < len(thresholds) else xp

    if next_threshold == current_threshold:
        return 100

    progress = (xp - current_threshold) / (next_threshold - current_threshold) * 100
    return min(100, max(0, progress))


def reset_user_progress(user_id):
    """Reset all user progress"""
    reset_gamification_stats(user_id)
