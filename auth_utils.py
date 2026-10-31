from functools import wraps

from flask import redirect, session, url_for, abort, current_app, request

from models import db, User, RoleEnum, Job


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))
        user = get_real_user()
        if user and getattr(user, "force_password_reset", False):
            allowed = {"auth.change_password", "auth.logout"}
            if request.endpoint not in allowed:
                return redirect(url_for("auth.change_password"))
        return view(**kwargs)

    return wrapped_view


def _normalize_role(role):
    if isinstance(role, RoleEnum):
        return role.value
    if role is None:
        return None
    raw = str(role).strip()
    if raw.startswith("RoleEnum."):
        raw = raw.split(".", 1)[1]
    try:
        return RoleEnum(raw).value
    except ValueError:
        pass
    raw_lower = raw.lower()
    for r in RoleEnum:
        if raw_lower == r.value.lower() or raw_lower == r.name.lower():
            return r.value
    return raw


def roles_required(*roles):
    """
    Require one of the given roles (RoleEnum or string).
    """

    allowed = {_normalize_role(r) for r in roles}

    def decorator(view):
        @wraps(view)
        def decorated(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                return redirect(url_for("auth.login"))

            user = db.session.get(User, user_id)
            if not user:
                abort(403)

            user_role_val = _normalize_role(user.role)
            if current_app.config.get("ENABLE_DEV_TOOLS"):
                override = session.get("dev_role_override")
                if override and user.role == RoleEnum.ADMIN:
                    try:
                        override_enum = RoleEnum(override)
                    except ValueError:
                        session.pop("dev_role_override", None)
                    else:
                        user_role_val = _normalize_role(override_enum)
            if user_role_val not in allowed:
                abort(403)

            return view(*args, **kwargs)

        return decorated

    return decorator


def job_access_required(*roles):
    """
    Require one of the given roles and access to the job referenced by job_id.
    """

    allowed = {_normalize_role(r) for r in roles}

    def decorator(view):
        @wraps(view)
        def decorated(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                return redirect(url_for("auth.login"))

            user = db.session.get(User, user_id)
            if not user:
                abort(403)

            user_role_val = _normalize_role(user.role)
            if current_app.config.get("ENABLE_DEV_TOOLS"):
                override = session.get("dev_role_override")
                if override and user.role == RoleEnum.ADMIN:
                    try:
                        override_enum = RoleEnum(override)
                    except ValueError:
                        session.pop("dev_role_override", None)
                    else:
                        user_role_val = _normalize_role(override_enum)
            if user_role_val not in allowed:
                abort(403)

            job_id = kwargs.get("job_id")
            if job_id is not None:
                job = db.session.get(Job, job_id)
                if not job:
                    abort(404)
                if not user_can_access_job(user, job):
                    abort(403)

            return view(*args, **kwargs)

        return decorated

    return decorator


class _UserProxy:
    def __init__(self, user, role_override):
        self._user = user
        self.role = role_override

    def __getattr__(self, name):
        return getattr(self._user, name)


def get_real_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db.session.get(User, uid)


def current_user():
    user = get_real_user()
    if not user:
        return None
    if current_app.config.get("ENABLE_DEV_TOOLS"):
        override = session.get("dev_role_override")
        if override and user.role == RoleEnum.ADMIN:
            try:
                override_enum = RoleEnum(override)
            except ValueError:
                session.pop("dev_role_override", None)
            else:
                return _UserProxy(user, override_enum)
    return user


def get_current_user():
    """Compatibility shim so views can call get_current_user()."""
    return current_user()


def get_org_filter(model=None):
    user = current_user()
    if not user:
        abort(403)
    org_id = getattr(user, "current_organization_id", None) or getattr(user, "organization_id", None)
    if not org_id:
        abort(403)
    if model is None:
        return org_id
    if hasattr(model, "organization_id"):
        return model.organization_id == org_id
    return None


def get_scoped_or_404(model, ident):
    if hasattr(model, "organization_id"):
        org_filter = get_org_filter(model)
        obj = model.query.filter(model.id == ident, org_filter).first()
    else:
        obj = db.session.get(model, ident)
    if not obj:
        abort(404)
    return obj


def user_can_access_job(user, job):
    """
    Basic job access check:
    - Admin/Office/Stores can access all.
    - Technicians can access jobs assigned to them or that they created.
    """
    if not user or not job:
        return False
    user_org = getattr(user, "current_organization_id", None) or getattr(user, "organization_id", None)
    job_org = getattr(job, "organization_id", None)
    if not user_org or not job_org or user_org != job_org:
        return False
    role_val = _normalize_role(user.role)
    if role_val in {RoleEnum.ADMIN.value, RoleEnum.OFFICE.value}:
        return True
    if role_val == RoleEnum.TECHNICIAN.value:
        return job.assigned_to_id == user.id or job.created_by_id == user.id
    return False


def require_job_access(job):
    if not user_can_access_job(current_user(), job):
        abort(403)
