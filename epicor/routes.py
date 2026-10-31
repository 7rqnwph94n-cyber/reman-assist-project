from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash

from auth_utils import login_required, roles_required, current_user, get_org_filter
from models import (
    db,
    EpicorSetting,
    EpicorAuthMethodEnum,
    EpicorEnvironmentEnum,
    EpicorWriteModeEnum,
    Template,
    AuditLog,
)
from services.epicor import test_connection, run_sample_query, sync_catalogue

epicor_bp = Blueprint("epicor", __name__)


def _get_setting() -> EpicorSetting | None:
    return (
        EpicorSetting.query.order_by(EpicorSetting.updated_at.desc(), EpicorSetting.id.desc()).first()
    )


def _log_admin(action: str, message: str, user=None) -> None:
    try:
        log = AuditLog(action=action, message=message, user_id=user.id if user else None)
        db.session.add(log)
    except Exception:
        pass


@epicor_bp.route("/admin/epicor/settings", methods=["GET", "POST"])
@login_required
@roles_required("Admin")
def epicor_settings():
    setting = _get_setting()
    org_id = get_org_filter()
    templates = Template.query.filter(Template.organization_id == org_id).order_by(Template.name).all()

    if request.method == "POST":
        action = request.form.get("action") or "save"
        if action == "save":
            if not setting:
                setting = EpicorSetting()
            setting.base_url = (request.form.get("base_url") or "").strip()
            setting.company = (request.form.get("company") or "").strip() or None
            setting.plant = (request.form.get("plant") or "").strip() or None
            env = request.form.get("environment") or EpicorEnvironmentEnum.TEST.value
            setting.environment = EpicorEnvironmentEnum(env)
            auth_method = request.form.get("auth_method") or EpicorAuthMethodEnum.API_KEY.value
            setting.auth_method = EpicorAuthMethodEnum(auth_method)
            setting.api_key_env_var = (request.form.get("api_key_env_var") or "").strip() or None
            setting.oauth_client_id = (request.form.get("oauth_client_id") or "").strip() or None
            setting.oauth_tenant_id = (request.form.get("oauth_tenant_id") or "").strip() or None
            setting.oauth_scope = (request.form.get("oauth_scope") or "").strip() or None
            setting.baq_part_cost = (request.form.get("baq_part_cost") or "").strip() or None
            setting.baq_stock = (request.form.get("baq_stock") or "").strip() or None
            setting.baq_po_status = (request.form.get("baq_po_status") or "").strip() or None
            write_mode_val = request.form.get("write_mode") or EpicorWriteModeEnum.NONE.value
            setting.write_mode = EpicorWriteModeEnum(write_mode_val)

            template_id = request.form.get("template_id")
            try:
                template_id_int = int(template_id) if template_id else None
            except ValueError:
                template_id_int = None
            setting.template_id = template_id_int

            db.session.add(setting)
            _log_admin("epicor_save", "Epicor settings saved", user=current_user())
            db.session.commit()
            flash("Epicor settings saved.", "success")
            return redirect(url_for("epicor.epicor_settings"))

        if action == "test_connection":
            if not setting:
                flash("Save settings first.", "warning")
                return redirect(url_for("epicor.epicor_settings"))
            ok, msg = test_connection(setting)
            setting.last_tested_at = datetime.now(timezone.utc)
            setting.last_test_status = "ok" if ok else "fail"
            setting.last_test_message = msg
            db.session.add(setting)
            _log_admin("epicor_test", msg, user=current_user())
            db.session.commit()
            flash(msg, "success" if ok else "danger")
            return redirect(url_for("epicor.epicor_settings"))

        if action == "sample_query":
            if not setting:
                flash("Save settings first.", "warning")
                return redirect(url_for("epicor.epicor_settings"))
            ok, msg, rows = run_sample_query(setting)
            setting.last_sample_at = datetime.now(timezone.utc)
            db.session.add(setting)
            _log_admin("epicor_sample", msg, user=current_user())
            db.session.commit()
            flash(msg, "success" if ok else "warning")
            return render_template(
                "epicor_settings.html",
                setting=setting,
                templates=templates,
                sample_rows=rows,
                auth_methods=EpicorAuthMethodEnum,
                envs=EpicorEnvironmentEnum,
                write_modes=EpicorWriteModeEnum,
            )

        if action == "sync_now":
            if not setting:
                flash("Save settings first.", "warning")
                return redirect(url_for("epicor.epicor_settings"))
            ok, msg = sync_catalogue(setting)
            _log_admin("epicor_sync", msg, user=current_user())
            db.session.commit()
            flash(msg, "success" if ok else "danger")
            return redirect(url_for("epicor.epicor_settings"))

    return render_template(
        "epicor_settings.html",
        setting=setting,
        templates=templates,
        sample_rows=None,
        auth_methods=EpicorAuthMethodEnum,
        envs=EpicorEnvironmentEnum,
        write_modes=EpicorWriteModeEnum,
    )
