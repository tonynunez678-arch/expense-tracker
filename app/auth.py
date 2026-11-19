"""Register, log in and log out."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import select

from . import db
from .models import User

bp = Blueprint("auth", __name__)


def _is_safe_redirect(target):
    """Only allow redirects to paths on this site (prevents open redirects)."""
    return bool(target) and target.startswith("/") and not target.startswith("//")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("expenses.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        error = None
        if not 3 <= len(username) <= 30:
            error = "Username must be 3 to 30 characters."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif db.session.scalar(select(User).filter_by(username=username)):
            error = "That username is already taken."

        if error:
            flash(error, "error")
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(f"Welcome, {username}! Add your first expense below.", "success")
            return redirect(url_for("expenses.dashboard"))

    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("expenses.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.session.scalar(select(User).filter_by(username=username))

        # Same message whether the username or password is wrong, so attackers
        # can't use the login form to discover which usernames exist.
        if user is None or not user.check_password(password):
            flash("Incorrect username or password.", "error")
        else:
            login_user(user, remember=bool(request.form.get("remember")))
            next_page = request.args.get("next")
            if not _is_safe_redirect(next_page):
                next_page = url_for("expenses.dashboard")
            return redirect(next_page)

    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
