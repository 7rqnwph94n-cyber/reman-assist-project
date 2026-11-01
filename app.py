import os
from urllib.parse import urlparse
import json
import random
import pandas as pd
import io
import csv
import tempfile
import shutil
import zipfile
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from types import SimpleNamespace
import click
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    session,
    send_from_directory,
    abort,
    send_file,
    make_response,
    g,
    has_request_context,
    current_app,
)
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_migrate import Migrate

from config import get_config, DEFAULT_UPLOAD_FOLDER
from services.seed_data import seed_database
from services.bom import regenerate_bom_for_job
from services.bom_services import apply_supersedes
from models import (
    db,
    Organization,
    User,
    Job,
    SurveyItem,
    PartRequirement,
    Attachment,
    PreSurveyResult,
    ErrorLog,
    Template,
    TemplateItem,
    TemplateGroup,
    RoleEnum,
    JobStatusEnum,
    DecisionEnum,
    StockStatusEnum,
    MeasurementResultEnum,
    StoreItem,
    PickList,
    PickListItem,
    PickListStatusEnum,
    AuditLog,
    CostingStageEnum,
    LineClassEnum,
    ProcurementStatusEnum,
    MatchStatusEnum,
    CostingTemplateProfile,
    CostingTemplateLine,
    CostingSheet,
    CostingLine,
    QuickBooksConnection,
    QuickBooksSyncLog,
    QuickBooksCustomerMap,
    QBSyncStatusEnum,
)
from auth_utils import login_required, roles_required, current_user, get_current_user, user_can_access_job, get_real_user
from services.job_services import ensure_survey_from_template
from services.job_services import change_job_status, log_event
from utils.localization import t, format_date, format_currency, format_units, unit_hint, get_region, get_locale, get_currency
from utils.tenant_scope import install_tenant_query_guard, set_current_org_id
from utils.integrations import register_optional_blueprint
from utils.runtime_db import (
    validate_database_config,
    record_runtime_db_details,
    log_runtime_db_details,
    get_migration_revisions,
)
from utils.startup_checks import (
    apply_startup_mode_adjustments,
    check_schema,
    check_migrations,
    check_redis,
)
from utils.request_hooks import register_request_hooks
from utils.error_handlers import register_error_handlers
from utils.blueprints import register_app_blueprints
from utils.diagnostics import register_diagnostic_routes


# ---------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------
def register_cli(app: Flask) -> None:
    """
    Register lightweight CLI commands for admin/user management.
    """

    @app.cli.command("create-admin")
    @click.option(
        "--username",
        "-u",
        default="admin",
        show_default=True,
        help="Username for the admin account.",
    )
    @click.option(
        "--password",
        "-p",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Password for the admin account.",
    )
    @click.option(
        "--role",
        "-r",
        default=RoleEnum.ADMIN.value,
        show_default=True,
        help="Role to assign (defaults to Admin).",
    )
    @click.option(
        "--update",
        is_flag=True,
        default=False,
        help="Update password/role if user already exists.",
    )
    def create_admin(username, password, role, update):
        """
        Create or update an admin (or other role) user.
        """
        with app.app_context():
            db.create_all()

            org = Organization.query.first()
            if not org:
                org = Organization(name="Default Org", slug="default")
                db.session.add(org)
                db.session.commit()

            user = User.query.filter_by(username=username).first()
            if user and not update:
                click.echo(f"User '{username}' already exists. Use --update to reset password/role.")
                return

            if not user:
                user = User(username=username, organization_id=org.id)
            if not user.organization_id:
                user.organization_id = org.id

            try:
                role_enum = RoleEnum(role)
            except ValueError:
                click.echo(f"Invalid role '{role}'. Allowed: {[r.value for r in RoleEnum]}")
                return

            user.role = role_enum
            user.password_hash = generate_password_hash(password)
            db.session.add(user)
            db.session.commit()

            action = "Updated" if user and update else "Created"
            click.echo(f"{action} user '{username}' with role '{role_enum.value}'.")

    def _is_production_env() -> bool:
        env = (
            os.environ.get("APP_ENV")
            or os.environ.get("FLASK_ENV")
            or app.config.get("APP_ENV")
            or app.config.get("ENV")
            or ""
        ).lower()
        if env in {"prod", "production"}:
            return True
        if env in {"dev", "development", "test", "testing"}:
            return False
        if app.config.get("TESTING"):
            return False
        if app.config.get("DEBUG") is False and not app.config.get("TESTING"):
            return True
        return False

    def _assert_seed_allowed(reset: bool) -> None:
        if reset:
            if _is_production_env():
                raise click.ClickException(
                    "Refusing to run seed reset in production. "
                    "Set ALLOW_DANGEROUS_COMMANDS=1 and APP_ENV=dev to proceed."
                )
            if os.environ.get("ALLOW_DANGEROUS_COMMANDS") != "1":
                raise click.ClickException(
                    "Seed reset blocked. Set ALLOW_DANGEROUS_COMMANDS=1 to proceed."
                )
        else:
            if _is_production_env() and os.environ.get("ALLOW_SEED_IN_PROD") != "1":
                raise click.ClickException(
                    "Seeding in production is disabled. Set ALLOW_SEED_IN_PROD=1 to proceed."
                )

    def _assert_demo_reset_allowed() -> None:
        env = (os.environ.get("APP_ENV") or "").lower()
        if (os.environ.get("FLASK_CONFIG") or "").lower() == "production":
            app.logger.warning("Demo reset blocked: FLASK_CONFIG=production")
            raise click.ClickException("Demo reset blocked in production config.")
        if env == "production":
            app.logger.warning("Demo reset blocked: APP_ENV=production")
            raise click.ClickException("Demo reset blocked in production environment.")
        if env != "demo" or os.environ.get("DEMO_RESET_ENABLED") != "1":
            app.logger.warning("Demo reset blocked (APP_ENV=%s, DEMO_RESET_ENABLED=%s)", env, os.environ.get("DEMO_RESET_ENABLED"))
            raise click.ClickException(
                "Demo reset blocked. Requires APP_ENV=demo and DEMO_RESET_ENABLED=1."
            )
        db_url = os.environ.get("DATABASE_URL") or ""
        if db_url:
            host = urlparse(db_url).hostname or ""
            prod_markers = ("prod", "production", "live", "reman")
            if host not in {"localhost", "127.0.0.1"} and any(m in host for m in prod_markers):
                app.logger.warning("Demo reset blocked: DATABASE_URL host=%s", host)
                raise click.ClickException("Demo reset blocked: non-local database host.")

    @app.cli.command("seed")
    @click.option("--users", default=4, show_default=True, type=int)
    @click.option("--templates", default=5, show_default=True, type=int)
    @click.option("--jobs", default=50, show_default=True, type=int)
    @click.option("--items-per-template", default=80, show_default=True, type=int)
    @click.option("--bom-lines-per-job", default=120, show_default=True, type=int)
    @click.option("--with-attachments", is_flag=True, default=False)
    @click.option("--reset", is_flag=True, default=False)
    def seed_cmd(users, templates, jobs, items_per_template, bom_lines_per_job, with_attachments, reset):
        """
        Seed deterministic data for tests/dev.
        """
        _assert_seed_allowed(reset)
        if reset:
            click.echo("Resetting database...")
            db.drop_all()
        db.create_all()
        seed_database(
            users=users,
            templates=templates,
            jobs=jobs,
            items_per_template=items_per_template,
            bom_lines_per_job=bom_lines_per_job,
            with_attachments=with_attachments,
            upload_folder=app.config.get("UPLOAD_FOLDER"),
        )
        click.echo("Seed complete.")

    @app.cli.command("demo-reset")
    @click.option("--seed", is_flag=True, default=False, help="Seed demo data after reset.")
    def demo_reset(seed: bool):
        """
        Hard reset for demo environments only.
        """
        _assert_demo_reset_allowed()
        click.echo("Resetting demo database...")
        db.drop_all()
        db.create_all()
        if seed:
            seed_database(
                users=4,
                templates=5,
                jobs=25,
                items_per_template=60,
                bom_lines_per_job=80,
                with_attachments=False,
                upload_folder=app.config.get("UPLOAD_FOLDER"),
            )
            click.echo("Demo seed complete.")
        else:
            click.echo("Demo reset complete (no seed).")

    @app.cli.group("bom")
    def bom_group():
        """Parts list maintenance commands."""

    @bom_group.command("regenerate")
    @click.option("--job-id", type=int, required=False)
    @click.option("--job-number", type=str, required=False)
    def bom_regenerate(job_id, job_number):
        """Regenerate parts list lines for a single job."""
        if not job_id and not job_number:
            raise click.ClickException("Provide --job-id or --job-number.")
        job = None
        if job_id:
            job = db.session.get(Job, job_id)
        if not job and job_number:
            job = Job.query.filter_by(job_number=job_number).first()
        if not job:
            raise click.ClickException("Job not found.")

        survey_items = (
            SurveyItem.query.filter_by(job_id=job.id)
            .order_by(SurveyItem.section, SurveyItem.pos, SurveyItem.id)
            .all()
        )
        created = regenerate_bom_for_job(job, survey_items, {})
        apply_supersedes(job.id)
        log_event(
            action="bom_regenerated",
            message=f"Regenerated {t('parts_list')} ({created} lines)",
            job=job,
            user=get_real_user(),
        )
        db.session.commit()
        click.echo(f"Regenerated {t('parts_list')} for {job.job_number}: {created} line(s).")

    @bom_group.command("backfill")
    @click.option("--missing-only/--all", default=True, show_default=True)
    @click.option("--limit", type=int, default=100, show_default=True)
    def bom_backfill(missing_only, limit):
        """Backfill parts lists for jobs with decisions but missing parts list lines."""
        jobs = Job.query.order_by(Job.id.desc()).limit(limit).all()
        updated = 0
        for job in jobs:
            bom_count = PartRequirement.query.filter_by(job_id=job.id).count()
            if missing_only and bom_count > 0:
                continue
            has_decisions = (
                SurveyItem.query.filter(
                    SurveyItem.job_id == job.id,
                    SurveyItem.decision.isnot(None),
                ).count()
                > 0
            )
            if not has_decisions:
                continue
            survey_items = (
                SurveyItem.query.filter_by(job_id=job.id)
                .order_by(SurveyItem.section, SurveyItem.pos, SurveyItem.id)
                .all()
            )
            created = regenerate_bom_for_job(job, survey_items, {})
            if created == 0:
                continue
            apply_supersedes(job.id)
            log_event(
                action="bom_backfilled",
                message=f"Backfilled {t('parts_list')} ({created} lines)",
                job=job,
                user=get_real_user(),
            )
            updated += 1
        db.session.commit()
        click.echo(f"Backfill complete. Jobs updated: {updated}.")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = DEFAULT_UPLOAD_FOLDER
# Note: Upload folder creation moved to create_app() to avoid import-time errors
migrate = Migrate()
csrf = CSRFProtect()


# ---------------------------------------------------------------------
# Custom request class for large form submissions
# ---------------------------------------------------------------------
class LargeFormRequest(Flask.request_class):
    # Allow larger survey posts; uses constants from constants.py
    from constants import MAX_FORM_MEMORY_MB, MB
    try:
        max_mb = int(os.environ.get("MAX_FORM_MEMORY_MB", str(MAX_FORM_MEMORY_MB)))
    except ValueError:
        max_mb = MAX_FORM_MEMORY_MB
    max_form_memory_size = max_mb * MB


# ---------------------------------------------------------------------
# Flask application factory
# ---------------------------------------------------------------------
app = Flask(__name__)
_default_app = app


def create_app(config_object=None, *, app_instance=None, config_overrides=None):
    """
    Configure the default app idempotently, or an explicitly supplied fresh app.
    Apply overrides before initialising extensions and their database engines.
    """
    app = app_instance if app_instance is not None else _default_app
    if getattr(app, "_configured", False):
        return app

    app.request_class = LargeFormRequest
    config_obj = config_object or get_config()
    app.config.from_object(config_obj)
    if os.environ.get("APP_ENV"):
        app.config["APP_ENV"] = os.environ.get("APP_ENV")
    if "ENABLE_DEV_TOOLS" in os.environ:
        app.config["ENABLE_DEV_TOOLS"] = os.environ.get("ENABLE_DEV_TOOLS", "").lower() in {"1", "true", "yes", "on"}
    if config_overrides:
        app.config.update(config_overrides)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        app.config["ENFORCE_CSRF"] = False
        app.config["WTF_CSRF_ENABLED"] = False
    else:
        app.config.setdefault("WTF_CSRF_ENABLED", app.config.get("ENFORCE_CSRF", True))
    validate_database_config(app, BASE_DIR)
    # Logging setup after config load
    log_level_name = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_file = app.config.get("LOG_FILE")
    log_format = str(app.config.get("LOG_FORMAT", "text")).lower() or "text"
    handlers = []
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5))
    handlers.append(logging.StreamHandler())

    class RequestContextFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if has_request_context():
                record.request_id = getattr(g, "request_id", None)
                record.path = request.path
                record.method = request.method
                record.remote_addr = request.headers.get("X-Forwarded-For", request.remote_addr)
            else:
                record.request_id = None
                record.path = None
                record.method = None
                record.remote_addr = None
            return True

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "ts": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.request_id:
                payload.update(
                    {
                        "request_id": record.request_id,
                        "method": record.method,
                        "path": record.path,
                        "remote_addr": record.remote_addr,
                    }
                )
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=True)

    if log_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
            " rid=%(request_id)s method=%(method)s path=%(path)s"
        )

    root = logging.getLogger()
    root.setLevel(log_level)
    if not root.handlers:
        for handler in handlers:
            handler.setFormatter(formatter)
            handler.addFilter(RequestContextFilter())
            root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.addFilter(RequestContextFilter())

    csrf.init_app(app)

    # Ensure upload folder exists and is safe for production use
    env = (app.config.get("APP_ENV") or app.config.get("ENV") or "").lower()
    if env in {"prod", "production"} and not os.environ.get("PYTEST_CURRENT_TEST"):
        if not os.environ.get("UPLOAD_FOLDER"):
            raise RuntimeError("UPLOAD_FOLDER environment variable is required in production.")
        # Only try to create if it doesn't exist (server admin should pre-create in production)
        if not os.path.exists(app.config["UPLOAD_FOLDER"]):
            try:
                os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            except PermissionError as e:
                raise RuntimeError(
                    f"Cannot create UPLOAD_FOLDER at {app.config['UPLOAD_FOLDER']}. "
                    f"Please create this directory and set appropriate permissions. Error: {e}"
                )
        # Verify it's writable
        if not os.access(app.config["UPLOAD_FOLDER"], os.W_OK):
            raise RuntimeError(
                f"UPLOAD_FOLDER {app.config['UPLOAD_FOLDER']} is not writable. "
                f"Please check permissions."
            )
    else:
        # Development/testing: create upload folder automatically
        try:
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        except PermissionError:
            # Fall back to local ./uploads directory
            fallback = os.path.join(BASE_DIR, "uploads")
            app.logger.warning(
                f"Cannot create upload folder at {app.config['UPLOAD_FOLDER']}, "
                f"using fallback: {fallback}"
            )
            app.config["UPLOAD_FOLDER"] = fallback
            os.makedirs(fallback, exist_ok=True)

    if "sqlalchemy" not in app.extensions:
        db.init_app(app)
    if "migrate" not in app.extensions:
        migrate.init_app(app, db)

    # Tenant query guard: automatically filters SELECT queries for these models
    # by the current user's organization_id. Models listed here MUST have an
    # organization_id column. Child models (TemplateSection, CostingSheet,
    # PreSurveyResult, IllustrationPage, etc.) are NOT listed because they
    # inherit tenant scope through their parent FK queries (e.g. CostingSheet
    # is always fetched via Job, which IS guarded).
    install_tenant_query_guard(
        [
            User,
            Job,
            SurveyItem,
            PartRequirement,
            Attachment,
            Template,
            TemplateItem,
            StoreItem,
            PickList,
            PickListItem,
            QuickBooksConnection,
            QuickBooksSyncLog,
            QuickBooksCustomerMap,
        ]
    )

    apply_startup_mode_adjustments(app)

    # Disable CSRF guard automatically for testing contexts unless explicitly forced on
    if app.config.get("TESTING"):
        app.config.setdefault("ENFORCE_CSRF", False)
        app.config["WTF_CSRF_ENABLED"] = False

    register_request_hooks(
        app,
        current_user_fn=current_user,
        set_current_org_id_fn=set_current_org_id,
    )

    register_app_blueprints(app, register_optional_blueprint)
    if "uploaded_file" not in app.view_functions:
        app.add_url_rule("/uploads/<path:filename>", view_func=uploaded_file)
    if inject_globals not in app.template_context_processors[None]:
        app.context_processor(inject_globals)

    with app.app_context():
        record_runtime_db_details(app, db)
        check_schema(app, db)
        check_migrations(app, db)
        check_redis(app)
        current_rev, head_rev, rev_error = get_migration_revisions(app, db)
        log_runtime_db_details(app, db)
        if rev_error:
            app.logger.info("Startup migration revisions unavailable: %s", rev_error)
        else:
            app.logger.info("Startup Alembic current=%s head=%s", current_rev, head_rev)

    register_cli(app)
    register_error_handlers(
        app,
        db=db,
        ErrorLog=ErrorLog,
        current_user_fn=current_user,
    )
    register_diagnostic_routes(app, db=db)

    app._configured = True
    return app

# ---------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------
def job_age_days(job):
    """Return whole days since job was created (or None)."""
    if not job.created_at:
        return None
    delta = datetime.utcnow() - job.created_at
    return delta.days


def next_action_for_job(job, user):
    """
    Very simple 'next action' text based on job status and user role.
    This is just for the dashboard; tweak wordings any time.
    """
    role = getattr(user, "role", None)

    if job.status == JobStatusEnum.PRE_SURVEY:
        if role == RoleEnum.TECHNICIAN:
            return f"Start {t('strip_inspection_lower')}"
        else:
            return "Assign to technician" if not job.assigned_to else f"Start {t('strip_inspection_lower')}"

    if job.status == JobStatusEnum.SURVEY:
        if role == RoleEnum.TECHNICIAN:
            return f"Complete {t('strip_inspection_lower')}"
        else:
            return f"Review {t('inspection')} & generate {t('parts_list')}"

    if job.status == JobStatusEnum.OFFICE:
        return f"Complete {t('parts_list_lower')} & order parts"

    if job.status == JobStatusEnum.BUILD:
        if role == RoleEnum.TECHNICIAN:
            return "Build & test engine"
        else:
            return "Monitor build progress"

    if job.status == JobStatusEnum.COMPLETE:
        return "Job complete"

    return "View job"



# ---------------------------------------------------------------------
# Simple helpers
# ---------------------------------------------------------------------
@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    app = current_app
    def _is_inline_image(path):
        return os.path.splitext(path)[1].lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}

    # Prevent path traversal
    safe_path = os.path.normpath(filename).lstrip(os.sep)
    full_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_path)
    if not full_path.startswith(os.path.abspath(app.config["UPLOAD_FOLDER"])):
        abort(403)

    # Allow engine diagrams under section_images for any authenticated user
    parts = safe_path.split(os.sep)
    if parts and parts[0] == "section_images":
        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            safe_path,
            as_attachment=not _is_inline_image(safe_path),
        )
    # Allow illustration assets for authenticated users (template/strip survey diagrams)
    if parts and parts[0] == "illustrations":
        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            safe_path,
            as_attachment=not _is_inline_image(safe_path),
        )

    # Attempt to resolve to an attachment/job for authorization
    att = Attachment.query.filter(Attachment.file_path == safe_path).first()
    job = None
    if att:
        job = db.session.get(Job, att.job_id) if att.job_id else None
    if not job:
        pre = PreSurveyResult.query.filter(PreSurveyResult.thumbnail_path == safe_path).first()
        if pre:
            job = db.session.get(Job, pre.job_id) if pre.job_id else None

    if job and user_can_access_job(current_user(), job):
        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            safe_path,
            as_attachment=not _is_inline_image(safe_path),
        )

    abort(403)


# ---------------------------------------------------------------------
# Template globals
# ---------------------------------------------------------------------
@app.context_processor
def inject_globals():
    app = current_app
    def testid(value: str) -> str:
        if not app.config.get("ENABLE_TEST_SELECTORS"):
            return ""
        clean = (value or "").strip().replace('"', "").replace("'", "")
        if not clean:
            return ""
        return f'data-testid="{clean}"'

    return {
        "JobStatusEnum": JobStatusEnum,
        "DecisionEnum": DecisionEnum,
        "StockStatusEnum": StockStatusEnum,
        "MeasurementResultEnum": MeasurementResultEnum,
        "PickListStatusEnum": PickListStatusEnum,
        "CostingStageEnum": CostingStageEnum,
        "LineClassEnum": LineClassEnum,
        "ProcurementStatusEnum": ProcurementStatusEnum,
        "MatchStatusEnum": MatchStatusEnum,
        "RoleEnum": RoleEnum,
        "current_user": current_user(),
        "real_user": get_real_user(),
        "job_age_days": job_age_days,
        "next_action_for_job": next_action_for_job,
        "csrf_token": generate_csrf,
        "testid": testid,
        "csp_nonce": lambda: getattr(g, "csp_nonce", ""),
        "DEV_TOOLS_ENABLED": app.config.get("ENABLE_DEV_TOOLS", False),
        "t": t,
        "format_date": format_date,
        "format_currency": format_currency,
        "format_units": format_units,
        "unit_hint": unit_hint,
        "REGION": get_region(),
        "LOCALE": get_locale(),
        "CURRENCY": get_currency(),
        "HAS_EPICOR_SETTINGS_ROUTE": "epicor.epicor_settings" in app.view_functions,
        "HAS_QUICKBOOKS_SETTINGS_ROUTE": "quickbooks.quickbooks_settings" in app.view_functions,
    }


 # Helper: rebuild BOM from survey
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# Admin: seed StoreItem rows from a template (one-off per template)
# Triggered from the Templates admin UI, NOT from Stores.

# ---------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------
if __name__ == "__main__":
    create_app()
    app.run(debug=app.config.get("DEBUG", False), host="0.0.0.0", port=5001)
