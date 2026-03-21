from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from db import get_cursor
from utils import utc_today

PLACEHOLDER = "%s"


class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

    @classmethod
    def get_by_id(cls, user_id):
        with get_cursor() as cur:
            cur.execute(
                f"SELECT id, username FROM users WHERE id = {PLACEHOLDER}", (user_id,)
            )
            row = cur.fetchone()
            if row:
                return cls(row["id"], row["username"])
        return None


def create_user(username, password):
    password_hash = generate_password_hash(password)
    user_id = None

    try:
        with get_cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO users (username, password_hash, password_changed_at)
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, CURRENT_TIMESTAMP)
                RETURNING id
            """,
                (username, password_hash),
            )

            row = cur.fetchone()
            user_id = row["id"] if row else None

            if user_id:
                cur.execute(
                    f"""
                    INSERT INTO gamification_stats (user_id) VALUES ({PLACEHOLDER})
                """,
                    (user_id,),
                )

                cur.execute(
                    f"""
                    INSERT INTO meta (user_id, key, value)
                    VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                    ON CONFLICT (user_id, key) DO UPDATE
                    SET value = EXCLUDED.value
                    """,
                    (user_id, f"last_processed_{user_id}", utc_today().isoformat()),
                )

        return user_id
    except Exception:
        return None


def verify_user(username, password):
    with get_cursor() as cur:
        cur.execute(f"SELECT * FROM users WHERE username = {PLACEHOLDER}", (username,))
        user = cur.fetchone()

    if user and check_password_hash(user["password_hash"], password):
        return User(user["id"], user["username"])
    return None


def get_user_password_changed_at(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"SELECT password_changed_at FROM users WHERE id = {PLACEHOLDER}",
            (user_id,),
        )
        row = cur.fetchone()
        return row["password_changed_at"] if row else None


def get_user_profile(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, username, created_at, password_changed_at
            FROM users
            WHERE id = {PLACEHOLDER}
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_user_password(user_id, password_hash):
    with get_cursor() as cur:
        cur.execute(
            f"""
            UPDATE users SET password_hash = {PLACEHOLDER}, password_changed_at = CURRENT_TIMESTAMP 
            WHERE id = {PLACEHOLDER}
        """,
            (password_hash, user_id),
        )


def update_user_username(user_id, new_username):
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE users SET username = {PLACEHOLDER} WHERE id = {PLACEHOLDER}",
            (new_username, user_id),
        )


def get_login_attempts(ip_address, username):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT attempts, locked_until FROM login_attempts
            WHERE ip_address = {PLACEHOLDER} AND username = {PLACEHOLDER}
        """,
            (ip_address, username),
        )
        return cur.fetchone()


def record_login_attempt(ip_address, username):
    with get_cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO login_attempts (ip_address, username, attempts)
            VALUES ({PLACEHOLDER}, {PLACEHOLDER}, 1)
            ON CONFLICT (ip_address, username) 
            DO UPDATE SET attempts = login_attempts.attempts + 1
        """,
            (ip_address, username),
        )


def clear_login_attempts(ip_address, username):
    with get_cursor() as cur:
        cur.execute(
            f"DELETE FROM login_attempts WHERE ip_address = {PLACEHOLDER} AND username = {PLACEHOLDER}",
            (ip_address, username),
        )


def delete_user(user_id):
    with get_cursor() as cur:
        cur.execute(f"DELETE FROM users WHERE id = {PLACEHOLDER}", (user_id,))
