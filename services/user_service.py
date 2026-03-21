from models import (
    create_user,
    verify_user,
    update_user_password,
    update_user_username,
    record_login_attempt,
    clear_login_attempts,
    get_login_attempts,
    delete_user,
)


def register_user(username, password):
    """Register a new user"""
    user_id = create_user(username, password)
    return user_id


def authenticate_user(username, password, ip_address=None):
    """Authenticate a user by username/password"""
    user = verify_user(username, password)
    if user and ip_address is not None:
        clear_login_attempts(ip_address, username)
    return user


def record_failed_login(ip_address, username):
    """Record a failed login attempt"""
    record_login_attempt(ip_address, username)


def check_login_locked(ip_address, username):
    """Check if account is locked due to too many failed attempts"""
    from datetime import datetime, timezone

    attempt = get_login_attempts(ip_address, username)
    if attempt and attempt["locked_until"]:
        locked_until = attempt["locked_until"]
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            return True, int((locked_until - now).total_seconds() / 60)
    return False, 0


def change_user_password(user_id, new_password_hash):
    """Change user password"""
    from werkzeug.security import generate_password_hash

    password_hash = generate_password_hash(new_password_hash)
    update_user_password(user_id, password_hash)


def change_username(user_id, new_username):
    """Change username"""
    update_user_username(user_id, new_username)


def delete_user_account(user_id):
    """Delete user and all related data"""
    from models import delete_all_user_tasks, delete_user_gamification

    delete_all_user_tasks(user_id)
    delete_user_gamification(user_id)
    delete_user(user_id)
