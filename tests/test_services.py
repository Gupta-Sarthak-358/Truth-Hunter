import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.pool import get_cursor, PLACEHOLDER


@pytest.fixture
def test_user(db_pool):
    from db.pool import get_cursor, PLACEHOLDER

    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO users (username, password_hash)
            VALUES ({PLACEHOLDER}, {PLACEHOLDER})
            ON CONFLICT (username) DO UPDATE SET username = EXCLUDED.username
            RETURNING id
        """,
            (f"pytest_user_{os.getpid()}", "hash"),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            f"""
            INSERT INTO gamification_stats (user_id, total_tasks_completed, 
                current_streak, longest_streak, perfect_days, freeze_charges)
            VALUES ({PLACEHOLDER}, 0, 0, 0, 0, 3)
            ON CONFLICT (user_id) DO UPDATE SET freeze_charges = 3
        """,
            (user_id,),
        )

    yield user_id

    with get_cursor() as cur:
        cur.execute("DELETE FROM task_instances WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM everyday_tasks WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM categories WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM user_monsters WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM user_badges WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM meta WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM gamification_stats WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))


def test_create_category(test_user):
    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO categories (user_id, name, color)
            VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
            RETURNING id
        """,
            (test_user, "Test Category", "#4ade80"),
        )
        result = cur.fetchone()
        assert result is not None
        cat_id = result["id"]

        cur.execute("SELECT * FROM categories WHERE id = %s", (cat_id,))
        cat = cur.fetchone()
        assert cat["name"] == "Test Category"
        assert cat["color"] == "#4ade80"


def test_gamification_stats_default(test_user):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM gamification_stats WHERE user_id = %s", (test_user,))
        stats = cur.fetchone()
        assert stats["total_tasks_completed"] == 0
        assert stats["current_streak"] == 0
        assert stats["freeze_charges"] == 3


def test_process_task_completion(test_user):
    from services.task_service import add_new_task, process_task_completion
    from db.pool import get_cursor
    
    # Add a task
    task_id = add_new_task(test_user, "Critical Flow Task")
    assert task_id is not None
    
    # Process completion
    monster_id, is_shiny, leveled_up, new_level, xp_earned = process_task_completion(test_user, task_id)
    
    # Verify the task was marked completed
    with get_cursor() as cur:
        cur.execute("SELECT is_completed FROM task_instances WHERE id = %s", (task_id,))
        task = cur.fetchone()
        assert task["is_completed"] == 1
        
        # Check that gamification stats updated correctly
        cur.execute("SELECT total_tasks_completed, current_streak, xp FROM gamification_stats WHERE user_id = %s", (test_user,))
        stats = cur.fetchone()
        assert stats["total_tasks_completed"] == 1
        assert stats["current_streak"] == 1
        assert stats["xp"] > 0
        
        # Check if monster was awarded
        if monster_id:
            cur.execute("SELECT * FROM user_monsters WHERE user_id = %s AND monster_id = %s", (test_user, monster_id))
            caught = cur.fetchone()
            assert caught is not None


def test_streak_bonus(test_user):
    from services.task_service import add_new_task, process_task_completion
    from db.pool import get_cursor
    from utils import format_date_iso, utc_today
    from datetime import timedelta
    
    today = format_date_iso(utc_today())
    yesterday_date = format_date_iso(utc_today() - timedelta(days=1))

    # Manually set streak to 2, last completion to yesterday
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE gamification_stats 
            SET current_streak = 2, last_completion_date = %s, xp = 0
            WHERE user_id = %s
            """,
            (yesterday_date, test_user)
        )
        
    task_id_1 = add_new_task(test_user, "Streak Task 1")
    # This task brings streak from 2 -> 3. Expected XP: 10 * 1.2 = 12
    _, _, _, _, xp_earned_1 = process_task_completion(test_user, task_id_1)
    
    assert xp_earned_1 == 12
    
    with get_cursor() as cur:
        cur.execute("SELECT current_streak, xp FROM gamification_stats WHERE user_id = %s", (test_user,))
        stats = cur.fetchone()
        assert stats["current_streak"] == 3
        
    # Manually set streak to 6, last completion to yesterday
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE gamification_stats 
            SET current_streak = 6, last_completion_date = %s
            WHERE user_id = %s
            """,
            (yesterday_date, test_user)
        )

    task_id_2 = add_new_task(test_user, "Streak Task 2")
    # This task brings streak from 6 -> 7. Expected XP: 10 * 1.5 = 15
    _, _, _, _, xp_earned_2 = process_task_completion(test_user, task_id_2)
    
    assert xp_earned_2 == 15
    
    with get_cursor() as cur:
        cur.execute("SELECT current_streak FROM gamification_stats WHERE user_id = %s", (test_user,))
        stats = cur.fetchone()
        assert stats["current_streak"] == 7

def test_daily_rewards(test_user):
    from models.gamification import check_and_grant_daily_reward
    from db.pool import get_cursor
    
    # Clear the meta table in case of dirty test state
    with get_cursor() as cur:
        cur.execute("DELETE FROM meta WHERE user_id = %s AND key = 'last_daily'", (test_user,))
        
    # First visit today -> should grant 50 XP
    xp1, _ = check_and_grant_daily_reward(test_user)
    assert xp1 == 50
    
    # Second visit today -> should grant 0 XP
    xp2, _ = check_and_grant_daily_reward(test_user)
    assert xp2 == 0

def test_monster_evolution(test_user):
    from models.monsters import fuse_duplicate_monsters
    from db.pool import get_cursor
    from utils import format_date_iso, utc_today
    
    today = format_date_iso(utc_today())
    
    with get_cursor() as cur:
        # Insert 4 non-shiny monsters of id -999 (to avoid colliding with real data)
        for _ in range(4):
            cur.execute(
                "INSERT INTO user_monsters (user_id, monster_id, caught_date, is_shiny) VALUES (%s, %s, %s, 0)",
                (test_user, -999, today)
            )
            
    shinies_created = fuse_duplicate_monsters(test_user)
    assert shinies_created == 1
    
    with get_cursor() as cur:
        # Should be 1 non-shiny and 1 shiny left
        cur.execute("SELECT is_shiny, COUNT(*) as cnt FROM user_monsters WHERE user_id = %s AND monster_id = -999 GROUP BY is_shiny", (test_user,))
        results = cur.fetchall()
        
        shiny_count = 0
        non_shiny_count = 0
        for r in results:
            if r["is_shiny"] == 1:
                shiny_count = r["cnt"]
            else:
                non_shiny_count = r["cnt"]
                
        assert shiny_count == 1
        assert non_shiny_count == 1
