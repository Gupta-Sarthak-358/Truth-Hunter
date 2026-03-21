from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required
from extensions import limiter
from services import (
    register_user,
    authenticate_user,
    record_failed_login,
    check_login_locked,
    refresh_user_cache_async,
    run_daily_sync_if_needed_async,
)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not username or not password:
            flash("Username and password are required", "error")
            return redirect(url_for("auth.signup"))

        if len(username) < 3:
            flash("Username must be at least 3 characters", "error")
            return redirect(url_for("auth.signup"))

        if len(password) < 6:
            flash("Password must be at least 6 characters", "error")
            return redirect(url_for("auth.signup"))

        if password != confirm:
            flash("Passwords don't match", "error")
            return redirect(url_for("auth.signup"))

        user_id = register_user(username, password)
        if user_id:
            flash("Account created! Please login.", "success")
            return redirect(url_for("auth.login"))
        else:
            flash("Username already exists", "error")

    return render_template("signup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if request.method == "POST":
        ip_address = request.remote_addr or "unknown"
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        is_locked, remaining = check_login_locked(ip_address, username)
        if is_locked:
            flash(f"Account locked. Try again in {remaining} minutes.", "error")
            return redirect(url_for("auth.login"))

        if not username or not password:
            flash("Username and password are required", "error")
            return redirect(url_for("auth.login"))

        user = authenticate_user(username, password, ip_address)

        if user:
            login_user(user)
            # Don't block login on daily sync; run it in the background.
            run_daily_sync_if_needed_async(user.id)
            refresh_user_cache_async(user.id)
            return redirect(url_for("dashboard.dashboard"))
        else:
            record_failed_login(ip_address, username)
            flash("Invalid username or password", "error")

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("homepage"))
