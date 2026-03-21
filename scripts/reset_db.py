import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.pool import init_pool, get_cursor, PLACEHOLDER


def reset_user_data(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"DELETE FROM task_instances WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        cur.execute(
            f"DELETE FROM everyday_tasks WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        cur.execute(f"DELETE FROM categories WHERE user_id = {PLACEHOLDER}", (user_id,))
        cur.execute(
            f"DELETE FROM user_monsters WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        cur.execute(
            f"DELETE FROM user_badges WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        cur.execute(f"DELETE FROM meta WHERE user_id = {PLACEHOLDER}", (user_id,))
        cur.execute(
            f"""
            UPDATE gamification_stats SET 
                total_tasks = 0, completed_tasks = 0, current_streak = 0, 
                longest_streak = 0, perfect_days = 0, monsters_caught = 0,
                shiny_monsters = 0, freeze_charges = 3, last_perfect_day = NULL
            WHERE user_id = {PLACEHOLDER}
        """,
            (user_id,),
        )
        print(f"Reset all data for user_id={user_id}")


def reset_all_users():
    with get_cursor() as cur:
        cur.execute("SELECT id FROM users")
        users = cur.fetchall()
        for user in users:
            reset_user_data(user["id"])
        print(f"Reset {len(users)} users")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reset user data")
    parser.add_argument("--user-id", type=int, help="Reset specific user ID")
    parser.add_argument("--all", action="store_true", help="Reset all users")
    args = parser.parse_args()

    init_pool()

    if args.all:
        reset_all_users()
    elif args.user_id:
        reset_user_data(args.user_id)
    else:
        parser.print_help()
