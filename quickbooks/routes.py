"""
QuickBooks Online integration routes.

Admin routes for connection management and Office routes for sync operations.
"""

from datetime import datetime, timezone
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)

from auth_utils import login_required, roles_required, current_user, get_org_filter
from models import (
    db,
    QuickBooksConnection,
    QuickBooksSyncLog,
    Job,
    PartRequirement,
    AuditLog,
    QBSyncStatusEnum,
    RoleEnum,
)
from services.quickbooks_service import (
    QuickBooksService,
    QuickBooksError,
    get_authorization_url,
    exchange_code_for_tokens,
)

quickbooks_bp = Blueprint("quickbooks", __name__)


def _get_connection():
    """Get QB connection for current org."""
    org_id = get_org_filter()
    return QuickBooksConnection.query.filter_by(
        organization_id=org_id, is_active=True
    ).first()


def _log_admin(action: str, message: str, user=None):
    """Log admin action."""
    try:
        log = AuditLog(
            action=action, message=message, user_id=user.id if user else None
        )
        db.session.add(log)
    except Exception:
        pass


# ─────────────────────────────────────────
# Admin: Connection Settings (Admin only)
# ─────────────────────────────────────────


@quickbooks_bp.route("/admin/quickbooks/settings")
@login_required
@roles_required(RoleEnum.ADMIN.value)
def quickbooks_settings():
    """Display QB connection status and settings."""
    connection = _get_connection()

    # Get recent sync logs
    org_id = get_org_filter()
    recent_logs = (
        QuickBooksSyncLog.query.filter_by(organization_id=org_id)
        .order_by(QuickBooksSyncLog.synced_at.desc())
        .limit(20)
        .all()
    )

    # Get accounts if connected (for dropdown configuration)
    income_accounts = []
    expense_accounts = []
    if connection and connection.is_active:
        try:
            qb = QuickBooksService(org_id)
            income_accounts = qb.get_accounts("Income")
            expense_accounts = qb.get_accounts("Expense")
        except QuickBooksError:
            pass

    return render_template(
        "quickbooks_settings.html",
        connection=connection,
        recent_logs=recent_logs,
        income_accounts=income_accounts,
        expense_accounts=expense_accounts,
    )


@quickbooks_bp.route("/admin/quickbooks/connect")
@login_required
@roles_required(RoleEnum.ADMIN.value)
def quickbooks_connect():
    """Initiate OAuth flow."""
    try:
        auth_url, state = get_authorization_url()
        session["qb_oauth_state"] = state
        _log_admin("qb_connect_start", "Initiated QB OAuth flow", user=current_user())
        return redirect(auth_url)
    except Exception as e:
        flash(f"Failed to start QuickBooks connection: {e}", "danger")
        return redirect(url_for("quickbooks.quickbooks_settings"))


@quickbooks_bp.route("/admin/quickbooks/callback")
@login_required
@roles_required(RoleEnum.ADMIN.value)
def quickbooks_callback():
    """Handle OAuth callback."""
    # Verify state
    state = request.args.get("state")
    stored_state = session.pop("qb_oauth_state", None)

    if not state or state != stored_state:
        flash("Invalid OAuth state. Please try again.", "danger")
        return redirect(url_for("quickbooks.quickbooks_settings"))

    code = request.args.get("code")
    realm_id = request.args.get("realmId")
    error = request.args.get("error")

    if error:
        flash(f"QuickBooks authorization failed: {error}", "danger")
        return redirect(url_for("quickbooks.quickbooks_settings"))

    if not code or not realm_id:
        flash("Missing authorization code or company ID.", "danger")
        return redirect(url_for("quickbooks.quickbooks_settings"))

    try:
        org_id = get_org_filter()
        user = current_user()

        connection = exchange_code_for_tokens(
            code=code,
            realm_id=realm_id,
            organization_id=org_id,
            user_id=user.id if user else None,
        )

        # Test the connection
        qb = QuickBooksService(org_id)
        ok, msg = qb.test_connection()

        _log_admin("qb_connected", f"Connected to QB: {msg}", user=user)
        flash(f"Successfully connected to QuickBooks! {msg}", "success")

    except Exception as e:
        flash(f"Failed to complete QuickBooks connection: {e}", "danger")

    return redirect(url_for("quickbooks.quickbooks_settings"))


@quickbooks_bp.route("/admin/quickbooks/disconnect", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def quickbooks_disconnect():
    """Disconnect from QuickBooks."""
    connection = _get_connection()
    if connection:
        connection.is_active = False
        _log_admin("qb_disconnected", "Disconnected from QB", user=current_user())
        db.session.commit()
        flash("QuickBooks has been disconnected.", "success")
    else:
        flash("No active QuickBooks connection found.", "warning")

    return redirect(url_for("quickbooks.quickbooks_settings"))


@quickbooks_bp.route("/admin/quickbooks/test", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def quickbooks_test():
    """Test QB connection."""
    connection = _get_connection()
    if not connection:
        flash("QuickBooks is not connected.", "warning")
        return redirect(url_for("quickbooks.quickbooks_settings"))

    try:
        org_id = get_org_filter()
        qb = QuickBooksService(org_id)
        ok, msg = qb.test_connection()
        _log_admin("qb_test", msg, user=current_user())
        flash(msg, "success" if ok else "danger")
    except QuickBooksError as e:
        flash(f"Connection test failed: {e}", "danger")

    return redirect(url_for("quickbooks.quickbooks_settings"))


@quickbooks_bp.route("/admin/quickbooks/settings/save", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value)
def quickbooks_save_settings():
    """Save QB configuration settings."""
    connection = _get_connection()
    if not connection:
        flash("QuickBooks is not connected.", "warning")
        return redirect(url_for("quickbooks.quickbooks_settings"))

    connection.default_income_account_id = request.form.get("income_account") or None
    connection.default_expense_account_id = request.form.get("expense_account") or None
    connection.auto_create_customers = request.form.get("auto_create_customers") == "1"
    connection.invoice_prefix = (
        (request.form.get("invoice_prefix") or "").strip()[:32] or None
    )

    _log_admin("qb_settings_saved", "QB settings updated", user=current_user())
    db.session.commit()
    flash("QuickBooks settings saved.", "success")

    return redirect(url_for("quickbooks.quickbooks_settings"))


# ─────────────────────────────────────────
# Office: Invoice Sync (Admin + Office)
# ─────────────────────────────────────────


@quickbooks_bp.route("/jobs/<int:job_id>/quickbooks/sync-invoice", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def sync_job_invoice(job_id):
    """Create or update QB invoice for a job."""
    org_id = get_org_filter()
    job = Job.query.filter_by(id=job_id, organization_id=org_id).first_or_404()

    connection = _get_connection()
    if not connection:
        flash("QuickBooks is not connected. Contact your administrator.", "warning")
        return redirect(request.referrer or url_for("jobs.job_detail", job_id=job_id))

    try:
        qb = QuickBooksService(org_id)
        user = current_user()

        success, qb_id, error = qb.create_or_update_invoice(
            job=job,
            user_id=user.id if user else None,
        )

        if success:
            action = "updated" if job.qb_invoice_number else "created"
            flash(
                f"Invoice {action} in QuickBooks: #{job.qb_invoice_number}", "success"
            )
        else:
            flash(f"Failed to sync invoice: {error}", "danger")

    except QuickBooksError as e:
        flash(f"QuickBooks error: {e}", "danger")

    # Return to referrer or job detail
    return redirect(request.referrer or url_for("jobs.job_detail", job_id=job_id))


@quickbooks_bp.route("/jobs/<int:job_id>/quickbooks/status")
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def job_quickbooks_status(job_id):
    """AJAX: Get QB sync status for a job."""
    org_id = get_org_filter()
    job = Job.query.filter_by(id=job_id, organization_id=org_id).first_or_404()

    return jsonify(
        {
            "qb_invoice_id": job.qb_invoice_id,
            "qb_invoice_number": job.qb_invoice_number,
            "qb_invoice_url": job.qb_invoice_url,
            "qb_sync_status": job.qb_sync_status.value if job.qb_sync_status else None,
            "qb_last_sync_at": (
                job.qb_last_sync_at.isoformat() if job.qb_last_sync_at else None
            ),
            "qb_sync_error": job.qb_sync_error,
        }
    )


# ─────────────────────────────────────────
# Office: Expense Sync (Admin + Office)
# ─────────────────────────────────────────


@quickbooks_bp.route("/jobs/<int:job_id>/quickbooks/sync-expenses", methods=["POST"])
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def sync_job_expenses(job_id):
    """Sync part requirements as expenses to QB."""
    org_id = get_org_filter()
    job = Job.query.filter_by(id=job_id, organization_id=org_id).first_or_404()

    connection = _get_connection()
    if not connection:
        flash("QuickBooks is not connected. Contact your administrator.", "warning")
        return redirect(request.referrer or url_for("parts.job_parts", job_id=job_id))

    # Get part requirements that haven't been synced yet
    parts = (
        PartRequirement.query.filter_by(job_id=job_id)
        .filter(PartRequirement.qb_expense_id.is_(None))
        .all()
    )

    if not parts:
        flash("No unsynced parts to export.", "info")
        return redirect(request.referrer or url_for("parts.job_parts", job_id=job_id))

    try:
        qb = QuickBooksService(org_id)
        user = current_user()

        success, failed, errors = qb.create_expense(
            part_requirements=parts,
            job=job,
            user_id=user.id if user else None,
        )

        if success > 0:
            flash(f"Exported {success} part(s) to QuickBooks expenses.", "success")
        if failed > 0:
            flash(
                f"Failed to export {failed} part(s): {'; '.join(errors[:3])}", "warning"
            )

    except QuickBooksError as e:
        flash(f"QuickBooks error: {e}", "danger")

    return redirect(request.referrer or url_for("parts.job_parts", job_id=job_id))


# ─────────────────────────────────────────
# Sync Logs (Admin + Office)
# ─────────────────────────────────────────


@quickbooks_bp.route("/admin/quickbooks/logs")
@login_required
@roles_required(RoleEnum.ADMIN.value, RoleEnum.OFFICE.value)
def quickbooks_logs():
    """View sync history."""
    org_id = get_org_filter()

    page = request.args.get("page", 1, type=int)
    per_page = 50

    logs = (
        QuickBooksSyncLog.query.filter_by(organization_id=org_id)
        .order_by(QuickBooksSyncLog.synced_at.desc())
        .paginate(page=page, per_page=per_page)
    )

    return render_template(
        "quickbooks_logs.html",
        logs=logs,
    )
