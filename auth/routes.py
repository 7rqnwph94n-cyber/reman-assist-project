from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from time import time, sleep

from models import db, User, RoleEnum
from auth_utils import login_required, roles_required, current_user, get_org_filter
from services.job_services import log_event
from utils.queries import get_or_404 as _get_or_404

try:
    import redis  # type: ignore
except Exception:
    redis = None

auth_bp = Blueprint("auth", __name__)
_LOGIN_ATTEMPTS = {}


def _login_key(username: str) -> str:
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    uname = (username or "").strip().lower()
    return f"{ip}:{uname}"


def _get_login_limits():
    cfg = current_app.config
    return {
        "user_max": int(cfg.get("LOGIN_MAX_ATTEMPTS", 6)),
        "window": int(cfg.get("LOGIN_WINDOW_SECONDS", 900)),
        "lockout": int(cfg.get("LOGIN_LOCKOUT_SECONDS", 900)),
        "ip_max": int(cfg.get("LOGIN_IP_MAX_ATTEMPTS", 20)),
    }


def _login_ip_key() -> str:
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    return f"{ip}:*"


def _password_policy_errors(password: str) -> list[str]:
    cfg = current_app.config
    errors = []
    min_len = int(cfg.get("PASSWORD_MIN_LENGTH", 10))
    if len(password) < min_len:
        errors.append(f"Password must be at least {min_len} characters.")
    if cfg.get("PASSWORD_REQUIRE_UPPER") and not any(c.isupper() for c in password):
        errors.append("Password must include an uppercase letter.")
    if cfg.get("PASSWORD_REQUIRE_LOWER") and not any(c.islower() for c in password):
        errors.append("Password must include a lowercase letter.")
    if cfg.get("PASSWORD_REQUIRE_DIGIT") and not any(c.isdigit() for c in password):
        errors.append("Password must include a number.")
    if cfg.get("PASSWORD_REQUIRE_SPECIAL") and not any(not c.isalnum() for c in password):
        errors.append("Password must include a symbol.")
    return errors

def _get_redis_client():
    if not redis:
        return None
    url = current_app.config.get("REDIS_URL")
    if not url:
        return None
    client = current_app.extensions.get("redis_client")
    if client:
        return client
    client = redis.Redis.from_url(url)
    current_app.extensions["redis_client"] = client
    return client


def _is_locked(key: str, window: int, lockout_seconds: int) -> int | None:
    client = _get_redis_client()
    if client:
        try:
            lock_key = f"login:lock:{key}"
            ttl = client.ttl(lock_key)
            if ttl and ttl > 0:
                return int(ttl)
            return None
        except Exception:
            # Redis is unavailable; fall back to in-memory tracking.
            pass

    record = _LOGIN_ATTEMPTS.get(key)
    if not record:
        return None
    now = time()
    lockout_until = record.get("lockout_until") or 0
    if lockout_until > now:
        return int(lockout_until - now)
    # prune stale failures
    failures = [t for t in record.get("failures", []) if now - t < window]
    record["failures"] = failures
    if lockout_until and not failures:
        record["lockout_until"] = 0
    return None


def _register_failed_login(key: str, max_attempts: int, window: int, lockout_seconds: int) -> int | None:
    client = _get_redis_client()
    if client:
        try:
            fail_key = f"login:fail:{key}"
            lock_key = f"login:lock:{key}"
            count = client.incr(fail_key)
            if count == 1:
                client.expire(fail_key, window)
            if count >= max_attempts:
                client.setex(lock_key, lockout_seconds, "1")
                client.delete(fail_key)
                return int(lockout_seconds)
            return None
        except Exception:
            # Redis is unavailable; fall back to in-memory tracking.
            pass

    now = time()
    record = _LOGIN_ATTEMPTS.setdefault(key, {"failures": [], "lockout_until": 0})
    record["failures"] = [t for t in record["failures"] if now - t < window]
    record["failures"].append(now)
    if len(record["failures"]) >= max_attempts:
        record["lockout_until"] = now + lockout_seconds
        record["failures"] = []
        return int(lockout_seconds)
    return None


def _clear_login_attempts(key: str) -> None:
    client = _get_redis_client()
    if client:
        try:
            client.delete(f"login:fail:{key}", f"login:lock:{key}")
            return
        except Exception:
            # Redis is unavailable; fall back to in-memory cleanup.
            pass
    _LOGIN_ATTEMPTS.pop(key, None)


# Removed: _get_or_404 now imported from utils.queries


@auth_bp.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("jobs.dashboard"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        key_user = _login_key(username)
        key_ip = _login_ip_key()
        limits = _get_login_limits()
        window = limits["window"]
        lockout_seconds = limits["lockout"]
        remaining = _is_locked(key_user, window, lockout_seconds) or _is_locked(key_ip, window, lockout_seconds)
        if remaining:
            mins = max(1, remaining // 60)
            flash(f"Too many login attempts. Try again in {mins} minute(s).", "danger")
            return render_template("login.html")

        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            if not current_app.config.get("TESTING"):
                sleep(0.2)
            locked_for = _register_failed_login(key_user, limits["user_max"], window, lockout_seconds)
            locked_for_ip = _register_failed_login(key_ip, limits["ip_max"], window, lockout_seconds)
            flash("Invalid username or password.", "danger")
            locked_for = locked_for or locked_for_ip
            if locked_for:
                mins = max(1, locked_for // 60)
                flash(f"Too many login attempts. Locked for {mins} minute(s).", "danger")
            return render_template("login.html")

        _clear_login_attempts(key_user)
        _clear_login_attempts(key_ip)
        session.clear()
        session["user_id"] = user.id
        log_event(
            action="login",
            message=f"User logged in: {user.username}",
            user=user,
        )
        db.session.commit()
        flash("Logged in successfully.", "success")

        if getattr(user, "force_password_reset", False):
            flash("Password reset required before continuing.", "warning")
            return redirect(url_for("auth.change_password"))

        if user.role == RoleEnum.STORES:
            return redirect(url_for("stores.stores_hub", view="master"))
        else:
            return redirect(url_for("jobs.dashboard"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    user = current_user()
    session.clear()
    if user:
        log_event(
            action="logout",
            message=f"User logged out: {user.username}",
            user=user,
        )
        db.session.commit()
    return redirect(url_for("auth.login"))


@auth_bp.route("/admin/users")
@login_required
@roles_required(RoleEnum.ADMIN.value)
def users_list():
    org_id = get_org_filter()
    users = User.query.filter(User.organization_id == org_id).order_by(User.username).all()
    return render_template("users_list.html", users=users)


@auth_bp.route("/admin/users/create", methods=["GET", "POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def user_create():
    if request.method == "POST":
        org_id = get_org_filter()
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        role = request.form.get("role")

        if not username or not password or not role:
            flash("All fields are required.", "danger")
            return redirect(url_for("auth.user_create"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists.", "danger")
            return redirect(url_for("auth.user_create"))

        valid_roles = [r.value for r in RoleEnum]
        if role not in valid_roles:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("auth.user_create"))

        policy_errors = _password_policy_errors(password)
        if policy_errors:
            for msg in policy_errors:
                flash(msg, "danger")
            return redirect(url_for("auth.user_create"))

        user = User(
            username=username,
            role=role,
            password_hash=generate_password_hash(password),
            force_password_reset=True,
            organization_id=org_id,
        )
        db.session.add(user)
        db.session.commit()
        flash("User created.", "success")
        return redirect(url_for("auth.users_list"))

    return render_template("user_create.html", RoleEnum=RoleEnum)


@auth_bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def user_delete(user_id):
    if user_id == session.get("user_id"):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("auth.users_list"))

    user = _get_or_404(User, user_id)
    db.session.delete(user)
    db.session.commit()
    flash("User deleted.", "success")
    return redirect(url_for("auth.users_list"))


@auth_bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    force_reset = getattr(user, "force_password_reset", False)
    if request.method == "POST":
        current_pw = (request.form.get("current_password") or "").strip()
        new_pw = (request.form.get("new_password") or "").strip()
        confirm_pw = (request.form.get("confirm_password") or "").strip()

        if not force_reset:
            if not current_pw or not check_password_hash(user.password_hash, current_pw):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("auth.change_password"))

        if not new_pw or new_pw != confirm_pw:
            flash("New password confirmation does not match.", "danger")
            return redirect(url_for("auth.change_password"))

        policy_errors = _password_policy_errors(new_pw)
        if policy_errors:
            for msg in policy_errors:
                flash(msg, "danger")
            return redirect(url_for("auth.change_password"))

        user.password_hash = generate_password_hash(new_pw)
        user.force_password_reset = False
        log_event(
            action="password_changed",
            message=f"Password updated for {user.username}",
            user=user,
        )
        db.session.commit()
        flash("Password updated.", "success")
        if user.role == RoleEnum.STORES:
            return redirect(url_for("stores.stores_hub", view="master"))
        return redirect(url_for("jobs.dashboard"))

    return render_template("change_password.html", force_reset=force_reset)
