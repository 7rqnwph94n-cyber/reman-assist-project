import os

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

from auth_utils import login_required, get_real_user, get_scoped_or_404
from models import (
    RoleEnum,
    Job,
    SurveyItem,
    DecisionEnum,
    MeasurementResultEnum,
    JobStatusEnum,
    db,
)
from services.job_services import ensure_survey_from_template, change_job_status
from utils.localization import t
from survey.routes import regenerate_bom_for_job


dev_tools_bp = Blueprint("dev_tools", __name__)


@dev_tools_bp.before_request
def _check_enabled():
    # Check all environment indicators — block if ANY signal production
    env = (
        os.environ.get("APP_ENV")
        or os.environ.get("ENV_MODE")
        or current_app.config.get("APP_ENV")
        or current_app.config.get("ENV")
        or ""
    ).lower()
    flask_config = (os.environ.get("FLASK_CONFIG") or "").lower()
    flask_env = (os.environ.get("FLASK_ENV") or "").lower()

    if env in {"prod", "production", "pilot"} or flask_config == "production" or flask_env == "production":
        abort(404)
    if current_app.config.get("TESTING") is False and current_app.config.get("DEBUG") is False:
        # Non-debug, non-test = treat as production-like
        abort(404)
    if not current_app.config.get("ENABLE_DEV_TOOLS"):
        abort(404)


def _require_admin():
    user = get_real_user()
    if not user or user.role != RoleEnum.ADMIN:
        abort(403)
    return user


@dev_tools_bp.route("/dev/tools", methods=["GET"])
@login_required
def dev_tools_home():
    user = _require_admin()
    flash(
        "Developer Tools are enabled. Impersonation is active if a role is set below. "
        "This mode should NOT be enabled in production.",
        "danger",
    )
    return render_template(
        "admin_tools.html",
        dev_role_override=session.get("dev_role_override"),
        real_role=user.role.value,
    )


@dev_tools_bp.route("/dev/role", methods=["POST"])
@login_required
def dev_role_set():
    _require_admin()
    role = (request.form.get("role") or "").strip()
    try:
        RoleEnum(role)
    except ValueError:
        flash("Unknown role.", "danger")
        return redirect(request.referrer or url_for("dev_tools.dev_tools_home"))

    session["dev_role_override"] = role
    flash(f"Role override set to {role}.", "success")
    return redirect(request.referrer or url_for("dev_tools.dev_tools_home"))


@dev_tools_bp.route("/dev/role/clear", methods=["POST"])
@login_required
def dev_role_clear():
    _require_admin()
    session.pop("dev_role_override", None)
    flash("Role override cleared.", "success")
    return redirect(request.referrer or url_for("dev_tools.dev_tools_home"))


def _load_job_from_form():
    job_id_raw = (request.form.get("job_id") or "").strip()
    if not job_id_raw:
        flash("No job selected. Open a Job or Survey page first.", "danger")
        return None
    try:
        job_id = int(job_id_raw)
    except ValueError:
        flash("Invalid job id.", "danger")
        return None
    try:
        job = get_scoped_or_404(Job, job_id)
    except Exception:
        flash("Job not found.", "danger")
        return None
    return job


def _fill_measurements(survey_items):
    for item in survey_items:
        if not getattr(item, "requires_measurement", False):
            continue
        lo_raw = item.spec_min
        hi_raw = item.spec_max
        value = None
        if lo_raw is not None and hi_raw is not None:
            try:
                lo = float(lo_raw)
                hi = float(hi_raw)
                value = (lo + hi) / 2.0
            except (TypeError, ValueError):
                value = None
        if value is None:
            item.measurement_value = item.measurement_value or "0"
            item.measurement_result = MeasurementResultEnum.WITHIN_SPEC
        else:
            item.measurement_value = f"{value:.3f}".rstrip("0").rstrip(".")
            item.measurement_result = MeasurementResultEnum.WITHIN_SPEC


@dev_tools_bp.route("/dev/survey/measurements", methods=["POST"])
@login_required
def dev_fill_measurements():
    user = _require_admin()
    job = _load_job_from_form()
    if not job:
        return redirect(request.referrer or url_for("dev_tools.dev_tools_home"))
    ensure_survey_from_template(job)
    survey_items = SurveyItem.query.filter_by(job_id=job.id).all()
    _fill_measurements(survey_items)
    db.session.commit()
    flash("Filled measurement values for this job.", "success")
    return redirect(request.referrer or url_for("survey.job_survey", job_id=job.id))


@dev_tools_bp.route("/dev/survey/complete", methods=["POST"])
@login_required
def dev_complete_survey():
    user = _require_admin()
    job = _load_job_from_form()
    if not job:
        return redirect(request.referrer or url_for("dev_tools.dev_tools_home"))
    ensure_survey_from_template(job)
    survey_items = SurveyItem.query.filter_by(job_id=job.id).all()
    for item in survey_items:
        if item.decision is None:
            item.decision = DecisionEnum.REPLACE
    _fill_measurements(survey_items)
    created = regenerate_bom_for_job(job, survey_items)
    change_job_status(job, JobStatusEnum.OFFICE, user=user, reason=f"Dev: {t('inspection')} completed")
    db.session.commit()
    flash(
        f"{t('inspection_caps')} completed. {created} part line(s) added to {t('parts_list')}.",
        "success",
    )
    return redirect(url_for("parts.job_parts", job_id=job.id))
