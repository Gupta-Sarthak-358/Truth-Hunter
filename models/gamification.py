from datetime import timedelta
from db import get_cursor
from utils import utc_today, format_date_iso
from constants import XP_THRESHOLDS

PLACEHOLDER = "%s"


def get_gamification_stats(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO gamification_stats (user_id)
            VALUES ({PLACEHOLDER})
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,),
        )

        cur.execute(
            f"""
            WITH monster_agg AS (
                SELECT
                    COUNT(*) AS total_monsters,
                    COUNT(DISTINCT monster_id) AS unique_monsters,
                    COUNT(*) FILTER (WHERE is_shiny = 1) AS shiny_count
                FROM user_monsters
                WHERE user_id = {PLACEHOLDER}
            ),
            legendary_agg AS (
                SELECT COUNT(*) AS legendary_count
                FROM user_monsters um
                JOIN monsters m ON um.monster_id = m.id
                WHERE um.user_id = {PLACEHOLDER}
                  AND m.rarity = 'legendary'
            )
            SELECT
                gs.total_tasks_completed,
                gs.current_streak,
                gs.longest_streak,
                gs.perfect_days,
                gs.type_complete_count,
                gs.xp,
                gs.level,
                gs.freeze_charges,
                COALESCE(ma.total_monsters, 0) AS total_monsters,
                COALESCE(ma.unique_monsters, 0) AS unique_monsters,
                COALESCE(ma.shiny_count, 0) AS shiny_count,
                COALESCE(la.legendary_count, 0) AS legendary_count
            FROM gamification_stats gs
            CROSS JOIN monster_agg ma
            CROSS JOIN legendary_agg la
            WHERE gs.user_id = {PLACEHOLDER}
            """,
            (user_id, user_id, user_id),
        )
        stats = cur.fetchone()

    return {
        "total_tasks": stats["total_tasks_completed"] if stats else 0,
        "current_streak": stats["current_streak"] if stats else 0,
        "longest_streak": stats["longest_streak"] if stats else 0,
        "total_monsters": stats["total_monsters"] if stats else 0,
        "unique_monsters": stats["unique_monsters"] if stats else 0,
        "shiny_count": stats["shiny_count"] if stats else 0,
        "legendary_count": stats["legendary_count"] if stats else 0,
        "perfect_days": stats["perfect_days"] if stats else 0,
        "type_complete_count": stats["type_complete_count"] if stats else 0,
        "xp": stats["xp"] if stats else 0,
        "level": stats["level"] if stats else 1,
        "freeze_charges": stats["freeze_charges"] if stats else 0,
        "xp_thresholds": XP_THRESHOLDS,
    }



def update_streak_on_completion(user_id, task_instance_id):
    from constants import FREEZE_USABLE_DAYS_GAP, XP_PER_TASK, XP_PER_WEIGHTED_TASK

    today = format_date_iso(utc_today())
    yesterday = format_date_iso(utc_today() - timedelta(days=1))

    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO gamification_stats (user_id)
            VALUES ({PLACEHOLDER})
            ON CONFLICT (user_id) DO NOTHING
            """,
            (user_id,),
        )

        cur.execute(
            f"""
            SELECT
                ti.weight,
                gs.current_streak,
                gs.longest_streak,
                gs.last_completion_date,
                gs.freeze_charges,
                gs.freeze_used_date,
                gs.xp,
                gs.level
            FROM task_instances ti
            JOIN gamification_stats gs ON gs.user_id = {PLACEHOLDER}
            WHERE ti.id = {PLACEHOLDER}
              AND ti.user_id = {PLACEHOLDER}
            """,
            (user_id, task_instance_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return None, False, False, 0, 0

        xp_earned = (
            XP_PER_WEIGHTED_TASK
            if row["weight"] == 2
            else XP_PER_TASK
        )

        current_streak = 1
        longest_streak = 1
        old_xp = 0
        old_level = 1

        old_xp = row["xp"] or 0
        old_level = row["level"] or 1
        last_date = row["last_completion_date"]
        current_streak = row["current_streak"] or 0
        longest_streak = row["longest_streak"] or 0

        if last_date:
            from datetime import date

            last_date_obj = date.fromisoformat(last_date)
            today_obj = utc_today()
            days_diff = (today_obj - last_date_obj).days

            if days_diff == 0:
                pass
            elif days_diff == 1:
                current_streak += 1
            else:
                freeze_charges = row["freeze_charges"] or 0
                freeze_used_date = row["freeze_used_date"]

                if (
                    freeze_charges > 0
                    and freeze_used_date != yesterday
                    and days_diff == FREEZE_USABLE_DAYS_GAP
                ):
                    current_streak += 1
                    cur.execute(
                        f"""
                        UPDATE gamification_stats
                        SET freeze_charges = freeze_charges - 1,
                            freeze_used_date = {PLACEHOLDER}
                        WHERE user_id = {PLACEHOLDER}
                        """,
                        (yesterday, user_id),
                    )
                else:
                    current_streak = 1
        else:
            current_streak = 1

        if current_streak >= 7:
            xp_earned = int(xp_earned * 1.5)
        elif current_streak >= 3:
            xp_earned = int(xp_earned * 1.2)

        new_xp = old_xp + xp_earned
        new_level = old_level
        for i, threshold in enumerate(XP_THRESHOLDS):
            if new_xp >= threshold:
                new_level = i + 1

        leveled_up = new_level > old_level

        if current_streak > longest_streak:
            longest_streak = current_streak

        cur.execute(
            f"""
            UPDATE gamification_stats 
            SET total_tasks_completed = total_tasks_completed + 1,
                current_streak = {PLACEHOLDER},
                longest_streak = {PLACEHOLDER},
                last_completion_date = {PLACEHOLDER},
                xp = {PLACEHOLDER},
                level = {PLACEHOLDER}
            WHERE user_id = {PLACEHOLDER}
        """,
            (current_streak, longest_streak, today, new_xp, new_level, user_id),
        )

        return None, False, leveled_up, new_level, xp_earned


def check_and_update_perfect_day(user_id):
    today = utc_today()
    yesterday = format_date_iso(today - timedelta(days=1))

    with get_cursor() as cur:
        cur.execute(
            f"SELECT perfect_days, last_perfect_day FROM gamification_stats WHERE user_id = {PLACEHOLDER}",
            (user_id,),
        )
        stats = cur.fetchone()

        if stats and stats["last_perfect_day"] == yesterday:
            return

        cur.execute(
            f"""
            SELECT
                SUM(CASE WHEN is_voided = 0 THEN weight ELSE 0 END) AS active_weight,
                SUM(CASE WHEN is_completed = 1 THEN weight ELSE 0 END) AS completed_weight
            FROM task_instances
            WHERE user_id = {PLACEHOLDER} AND date = {PLACEHOLDER}
        """,
            (user_id, yesterday),
        )
        row = cur.fetchone()

        if row and row["active_weight"] and row["active_weight"] > 0:
            if row["active_weight"] == row["completed_weight"]:
                cur.execute(
                    f"""
                    UPDATE gamification_stats
                    SET perfect_days = perfect_days + 1, last_perfect_day = {PLACEHOLDER}
                    WHERE user_id = {PLACEHOLDER}
                """,
                    (yesterday, user_id),
                )


def update_type_complete_count(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                mt.id AS type_id,
                COUNT(DISTINCT m.id) AS total_in_type,
                COUNT(DISTINCT um.monster_id) AS collected
            FROM monster_types mt
            LEFT JOIN monsters m ON m.type_id = mt.id
            LEFT JOIN user_monsters um ON um.monster_id = m.id AND um.user_id = {PLACEHOLDER}
            GROUP BY mt.id
        """,
            (user_id,),
        )
        type_rows = cur.fetchall()

        complete_count = 0
        for row in type_rows:
            if (
                row["collected"]
                and row["total_in_type"] > 0
                and row["collected"] >= row["total_in_type"]
            ):
                complete_count += 1

        cur.execute(
            f"UPDATE gamification_stats SET type_complete_count = {PLACEHOLDER} WHERE user_id = {PLACEHOLDER}",
            (complete_count, user_id),
        )


def check_and_award_freeze(user_id):
    from constants import (
        FREEZE_STREAK_MILESTONE,
        FREEZE_MONSTER_MILESTONE,
        FREEZE_BADGE_MILESTONE,
    )

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                gs.current_streak,
                gs.last_freeze_award,
                (
                    SELECT COUNT(DISTINCT monster_id)
                    FROM user_monsters
                    WHERE user_id = {PLACEHOLDER}
                ) AS unique_monsters,
                (
                    SELECT COUNT(*)
                    FROM user_badges
                    WHERE user_id = {PLACEHOLDER}
                ) AS badge_count
            FROM gamification_stats gs
            WHERE gs.user_id = {PLACEHOLDER}
            """,
            (user_id, user_id, user_id),
        )
        stats = cur.fetchone()

        if not stats:
            return

        current_streak = stats["current_streak"] or 0
        last_freeze_award = stats.get("last_freeze_award")
        unique_monsters = stats.get("unique_monsters") or 0
        badge_count = stats.get("badge_count") or 0

        today = format_date_iso(utc_today())
        should_award = False

        if current_streak > 0 and current_streak % FREEZE_STREAK_MILESTONE == 0:
            if last_freeze_award != today:
                should_award = True

        if not should_award:
            if unique_monsters > 0 and unique_monsters % FREEZE_MONSTER_MILESTONE == 0:
                if last_freeze_award != today:
                    should_award = True

        if not should_award:
            if badge_count > 0 and badge_count % FREEZE_BADGE_MILESTONE == 0:
                if last_freeze_award != today:
                    should_award = True

        if should_award:
            cur.execute(
                f"""
                UPDATE gamification_stats 
                SET freeze_charges = freeze_charges + 1, last_freeze_award = {PLACEHOLDER}
                WHERE user_id = {PLACEHOLDER}
            """,
                (today, user_id),
            )


def get_user_badges(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT b.*, ub.earned_date 
            FROM user_badges ub
            JOIN badges b ON ub.badge_id = b.id
            WHERE ub.user_id = {PLACEHOLDER}
        """,
            (user_id,),
        )
        badges = cur.fetchall()
    return [dict(row) for row in badges]


def check_and_award_badges(user_id):
    stats = get_gamification_stats(user_id)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT b.* FROM badges b
            WHERE b.id NOT IN (SELECT badge_id FROM user_badges WHERE user_id = {PLACEHOLDER})
        """,
            (user_id,),
        )
        available_badges = cur.fetchall()

        today = format_date_iso(utc_today())

        for badge in available_badges:
            condition_type = badge["condition_type"]
            condition_value = badge["condition_value"]
            should_award = False

            if (
                condition_type == "tasks_total"
                and stats["total_tasks"] >= condition_value
            ):
                should_award = True
            elif (
                condition_type == "streak"
                and stats["current_streak"] >= condition_value
            ):
                should_award = True
            elif (
                condition_type == "perfect_days"
                and stats["perfect_days"] >= condition_value
            ):
                should_award = True
            elif (
                condition_type == "unique_monsters"
                and stats["unique_monsters"] >= condition_value
            ):
                should_award = True
            elif (
                condition_type == "legendary_caught"
                and stats["legendary_count"] >= condition_value
            ):
                should_award = True
            elif (
                condition_type == "shiny_caught"
                and stats["shiny_count"] >= condition_value
            ):
                should_award = True
            elif (
                condition_type == "type_complete"
                and stats["type_complete_count"] >= condition_value
            ):
                should_award = True

            if should_award:
                cur.execute(
                    f"""
                    INSERT INTO user_badges (user_id, badge_id, earned_date)
                    VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                    ON CONFLICT (user_id, badge_id) DO NOTHING
                    """,
                    (user_id, badge["id"], today),
                )


def reset_gamification_stats(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            UPDATE gamification_stats SET 
                total_tasks_completed = 0, 
                current_streak = 0, 
                longest_streak = 0, 
                last_completion_date = NULL, 
                perfect_days = 0, 
                type_complete_count = 0, 
                xp = 0, 
                level = 1, 
                freeze_charges = 0, 
                last_perfect_day = NULL, 
                last_freeze_award = NULL 
            WHERE user_id = {PLACEHOLDER}
        """,
            (user_id,),
        )


def delete_user_gamification(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"DELETE FROM user_badges WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        cur.execute(
            f"DELETE FROM user_monsters WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        cur.execute(
            f"DELETE FROM gamification_stats WHERE user_id = {PLACEHOLDER}", (user_id,)
        )


def check_and_grant_daily_reward(user_id):
    from db.pool import get_cursor, PLACEHOLDER
    from utils import format_date_iso, utc_today
    from constants import XP_THRESHOLDS
    import logging

    logger = logging.getLogger(__name__)
    today = format_date_iso(utc_today())

    with get_cursor() as cur:
        # Check if already granted today
        cur.execute(
            f"SELECT value FROM meta WHERE user_id = {PLACEHOLDER} AND key = 'last_daily'",
            (user_id,),
        )
        row = cur.fetchone()

        if row and row["value"] == today:
            return 0, 0

        # Grant 50 XP
        cur.execute(
            f"""
            UPDATE gamification_stats 
            SET xp = xp + 50
            WHERE user_id = {PLACEHOLDER}
            RETURNING xp, level
            """,
            (user_id,),
        )
        stats = cur.fetchone()

        new_level = 0
        if stats:
            old_level = stats["level"]
            new_xp = stats["xp"]
            current_new_level = old_level

            for i, threshold in enumerate(XP_THRESHOLDS):
                if new_xp >= threshold:
                    current_new_level = i + 1

            if current_new_level > old_level:
                cur.execute(
                    f"UPDATE gamification_stats SET level = {PLACEHOLDER} WHERE user_id = {PLACEHOLDER}",
                    (current_new_level, user_id),
                )
                new_level = current_new_level

        # Record grant idempotently for the composite meta key shape.
        cur.execute(
            f"""
            INSERT INTO meta (user_id, key, value)
            VALUES ({PLACEHOLDER}, 'last_daily', {PLACEHOLDER})
            ON CONFLICT (user_id, key) DO UPDATE
            SET value = EXCLUDED.value
            """,
            (user_id, today),
        )

        logger.info("Daily Reward Granted", extra={"metric": "daily_reward", "user_id": user_id, "xp_earned": 50})
        if new_level > 0:
            logger.info("User Leveled Up", extra={"metric": "level_up", "user_id": user_id, "metric_value": new_level})

        return 50, new_level
