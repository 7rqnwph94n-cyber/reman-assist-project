from datetime import datetime, timezone
from enum import Enum
import enum

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.orm.attributes import NO_VALUE

db = SQLAlchemy()

# ─────────────────────────────────────────
# Enums
# ─────────────────────────────────────────


def _enum_names(enum_cls):
    return [item.name for item in enum_cls]


def _enum_values(enum_cls):
    return [item.value for item in enum_cls]


class RoleEnum(str, Enum):
    TECHNICIAN = "Technician"
    OFFICE = "Office"
    STORES = "Stores"
    ADMIN = "Admin"


class JobStatusEnum(str, Enum):
    PRE_SURVEY = "pre_survey"
    SURVEY = "survey"
    OFFICE = "office"
    BUILD = "build"
    HOLD = "hold"
    COMPLETE = "complete"


class InvalidJobTransition(ValueError):
    """Raised when a job status change violates lifecycle rules."""


JOB_STATUS_TRANSITIONS = {
    JobStatusEnum.PRE_SURVEY: {JobStatusEnum.SURVEY, JobStatusEnum.OFFICE, JobStatusEnum.HOLD},
    JobStatusEnum.SURVEY: {JobStatusEnum.PRE_SURVEY, JobStatusEnum.OFFICE, JobStatusEnum.HOLD},
    JobStatusEnum.OFFICE: {JobStatusEnum.SURVEY, JobStatusEnum.BUILD, JobStatusEnum.COMPLETE, JobStatusEnum.HOLD},
    JobStatusEnum.BUILD: {JobStatusEnum.OFFICE, JobStatusEnum.COMPLETE, JobStatusEnum.HOLD},
    JobStatusEnum.HOLD: {
        JobStatusEnum.PRE_SURVEY,
        JobStatusEnum.SURVEY,
        JobStatusEnum.OFFICE,
        JobStatusEnum.BUILD,
    },
    JobStatusEnum.COMPLETE: {JobStatusEnum.HOLD},
}


def _coerce_job_status(value):
    if isinstance(value, JobStatusEnum):
        return value
    if isinstance(value, str):
        if value in JobStatusEnum.__members__:
            return JobStatusEnum[value]
        try:
            return JobStatusEnum(value)
        except ValueError:
            return None
    return None


class DecisionEnum(str, Enum):
    REUSE = "reuse"
    REPLACE = "replace"
    SCRAP = "scrap"
    INSPECT = "inspect"
    NEW = "new"
    MACHINING = "machining"


class StockStatusEnum(str, Enum):
    PENDING = "pending"
    IN_STOCK = "in_stock"
    TO_ORDER = "to_order"
    ORDERED = "ordered"
    RECEIVED = "received"
    BACKORDER = "backorder"
    FITTED = "fitted"  # for when a part has been used/fitted
    NOT_REQUIRED = "not_required"  # for cancelled / no longer needed


class MeasurementResultEnum(str, Enum):
    WITHIN_SPEC = "within_spec"
    OUT_OF_SPEC = "out_of_spec"
    NOT_MEASURED = "not_measured"


class PickListStatusEnum(str, Enum):
    NEW = "new"
    PICKED = "picked"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


# ─────────────────────────────────────────
# Costing / office sheet enums
# ─────────────────────────────────────────


class CostingStageEnum(str, Enum):
    AWAITING_SAS = "awaiting_sas"
    COSTING_IN_PROGRESS = "costing_in_progress"
    AWAITING_PO = "awaiting_po"
    ENGINE_IN_BUILD = "engine_in_build"
    COMPLETE = "complete"


COSTING_STAGE_TRANSITIONS = {
    CostingStageEnum.AWAITING_SAS: {CostingStageEnum.COSTING_IN_PROGRESS},
    CostingStageEnum.COSTING_IN_PROGRESS: {CostingStageEnum.AWAITING_PO, CostingStageEnum.AWAITING_SAS},
    CostingStageEnum.AWAITING_PO: {CostingStageEnum.ENGINE_IN_BUILD, CostingStageEnum.COSTING_IN_PROGRESS},
    CostingStageEnum.ENGINE_IN_BUILD: {CostingStageEnum.COMPLETE, CostingStageEnum.AWAITING_PO},
    CostingStageEnum.COMPLETE: set(),
}


class InvalidCostingTransition(ValueError):
    """Raised when a costing stage change violates lifecycle rules."""


class LineClassEnum(str, Enum):
    REPLACE_100 = "replace_100"
    AS_REQUIRED = "as_required"
    MENU_ITEM = "menu_item"
    KIT_PART = "kit_part"
    CONSUMABLE = "consumable"
    STANDARD = "standard"


class ProcurementStatusEnum(str, Enum):
    NOT_COSTED = "not_costed"
    COSTED = "costed"
    PO_RAISED = "po_raised"
    ORDERED = "ordered"
    RECEIVED = "received"
    ISSUED = "issued"


class MatchStatusEnum(str, Enum):
    MATCHED = "matched"
    UNMATCHED_BOM = "unmatched_bom"
    UNMATCHED_SHEET = "unmatched_sheet"
    AMBIGUOUS = "ambiguous"


# ─────────────────────────────────────────
# Epicor integration enums
# ─────────────────────────────────────────


class EpicorAuthMethodEnum(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"


class EpicorEnvironmentEnum(str, Enum):
    PROD = "prod"
    TEST = "test"


class EpicorWriteModeEnum(str, Enum):
    NONE = "none"
    DMT = "dmt"
    REST = "rest"


# ─────────────────────────────────────────
# QuickBooks integration enums
# ─────────────────────────────────────────


class QuickBooksEnvironmentEnum(str, Enum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class QBSyncStatusEnum(str, Enum):
    NEVER_SYNCED = "never_synced"
    SYNCED = "synced"
    FAILED = "failed"
    NEEDS_UPDATE = "needs_update"


class QBSyncTypeEnum(str, Enum):
    INVOICE = "invoice"
    EXPENSE = "expense"
    CUSTOMER = "customer"
    VENDOR = "vendor"


# ─────────────────────────────────────────
# Core models
# ─────────────────────────────────────────


class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    role = db.Column(
        db.Enum(RoleEnum, values_callable=_enum_names, name="roleenum"),
        nullable=False,
    )
    force_password_reset = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # All jobs this user is assigned to as technician
    assigned_jobs = db.relationship(
        "Job",
        foreign_keys="Job.assigned_to_id",
        back_populates="assigned_to",
        lazy="dynamic",
    )
    organization = db.relationship("Organization", backref="users", lazy=True)

    @property
    def current_organization_id(self):
        return self.organization_id


class Job(db.Model):
    __tablename__ = "jobs"
    __table_args__ = (
        db.CheckConstraint("job_pack_id <> ''", name="ck_jobs_job_pack_id_not_empty"),
        db.UniqueConstraint("organization_id", "job_pack_id", name="uq_jobs_org_job_pack_id"),
        db.UniqueConstraint("organization_id", "job_number", name="uq_jobs_org_job_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_pack_id = db.Column(db.String(64), nullable=False)
    job_number = db.Column(db.String(64), nullable=False)
    customer_name = db.Column(db.String(128), index=True)
    engine_type = db.Column(db.String(128), index=True)
    serial_number = db.Column(db.String(128), index=True)  # engine/part serial

    status = db.Column(
        db.Enum(JobStatusEnum, values_callable=_enum_names, name="jobstatusenum"),
        nullable=False,
        default=JobStatusEnum.PRE_SURVEY,
        index=True,
    )
    survey_layout = db.Column(
        db.String(32),
        nullable=False,
        default="classic",
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )
    survey_version = db.Column(db.Integer, default=0, nullable=False)
    parts_version = db.Column(db.Integer, default=0, nullable=False)
    report_revision = db.Column(db.Integer, default=0, nullable=False)

    # Release / final approval
    release_signed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    release_signed_at = db.Column(db.DateTime, nullable=True)
    release_signed_by = db.relationship("User", foreign_keys=[release_signed_by_id])

    # QuickBooks integration fields
    qb_invoice_id = db.Column(db.String(128), nullable=True, index=True)
    qb_invoice_number = db.Column(db.String(64), nullable=True)
    qb_invoice_url = db.Column(db.String(512), nullable=True)
    qb_sync_status = db.Column(
        db.Enum(QBSyncStatusEnum, values_callable=_enum_values, name="qbsyncstatusenum"),
        default=QBSyncStatusEnum.NEVER_SYNCED,
        nullable=True,
    )
    qb_last_sync_at = db.Column(db.DateTime, nullable=True)
    qb_sync_error = db.Column(db.Text, nullable=True)

    # 🔹 Link to template (Job Pack spec)
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("templates.id"),
        nullable=True,
        index=True,
    )
    template_version = db.Column(db.Integer, nullable=True)

    # 🔹 Tech assigned to this job
    assigned_to_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    # 🔹 Who created the job pack (Office/Admin)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True,
    )

    # Relationships
    template = db.relationship("Template", back_populates="jobs")

    assigned_to = db.relationship(
        "User",
        foreign_keys=[assigned_to_id],
        back_populates="assigned_jobs",
    )

    created_by = db.relationship(
        "User",
        foreign_keys=[created_by_id],
    )

    survey_items = db.relationship(
        "SurveyItem",
        backref="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    part_requirements = db.relationship(
        "PartRequirement",
        backref="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    attachments = db.relationship(
        "Attachment",
        backref="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    revisions = db.relationship(
        "JobReportRevisionLog",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Pick lists issued for this job
    pick_lists = db.relationship(
        "PickList",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # One costing sheet per job (office module)
    costing_sheet = db.relationship(
        "CostingSheet",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )
    organization = db.relationship("Organization", backref="jobs", lazy=True)

    def transition_to(self, new_status: JobStatusEnum) -> None:
        current_status = _coerce_job_status(self.status)
        target_status = _coerce_job_status(new_status)
        if current_status is None or target_status is None:
            raise InvalidJobTransition(
                f"Invalid status transition payload: {self.status!r} -> {new_status!r}"
            )
        if current_status == target_status:
            return
        allowed = JOB_STATUS_TRANSITIONS.get(current_status, set())
        if target_status not in allowed:
            raise InvalidJobTransition(
                f"Illegal transition: {current_status.value} -> {target_status.value}"
            )
        # Business rule: cannot complete a job with outstanding parts
        if target_status == JobStatusEnum.COMPLETE:
            pending = [
                p for p in (self.part_requirements or [])
                if p.stock_status not in {
                    StockStatusEnum.RECEIVED,
                    StockStatusEnum.FITTED,
                    StockStatusEnum.IN_STOCK,
                    StockStatusEnum.NOT_REQUIRED,
                }
            ]
            if pending:
                raise InvalidJobTransition(
                    f"Cannot complete job: {len(pending)} part(s) still pending/on order"
                )
            # Business rule: cannot complete with unmeasured required items
            unmeasured = [
                s for s in (self.survey_items or [])
                if s.requires_measurement
                and s.measurement_result == MeasurementResultEnum.NOT_MEASURED
            ]
            if unmeasured:
                raise InvalidJobTransition(
                    f"Cannot complete job: {len(unmeasured)} required measurement(s) not recorded"
                )
        # Business rule: if costing sheet exists, must have matched lines before BUILD
        if target_status == JobStatusEnum.BUILD:
            if self.costing_sheet is not None and self.costing_sheet.lines:
                has_matched = any(
                    line.match_status == MatchStatusEnum.MATCHED
                    for line in self.costing_sheet.lines
                )
                if not has_matched:
                    raise InvalidJobTransition(
                        "Cannot move to BUILD: costing sheet has no matched lines"
                    )
        self.status = target_status

    def is_waiting_on_parts(self) -> bool:
        if self.status not in {JobStatusEnum.OFFICE, JobStatusEnum.BUILD}:
            return False
        return any(
            p.stock_status not in {
                StockStatusEnum.RECEIVED,
                StockStatusEnum.FITTED,
                StockStatusEnum.IN_STOCK,
            }
            for p in (self.part_requirements or [])
        )

    def is_waiting_on_machining(self) -> bool:
        if self.status not in {JobStatusEnum.OFFICE, JobStatusEnum.BUILD}:
            return False
        return any(
            (s.decision == DecisionEnum.MACHINING and not getattr(s, "is_resolved", False))
            for s in (self.survey_items or [])
        )

    def bottleneck_type(self) -> str:
        parts = self.is_waiting_on_parts()
        machining = self.is_waiting_on_machining()
        if parts and machining:
            return "Both"
        if parts:
            return "Parts"
        if machining:
            return "Machining"
        return ""


@event.listens_for(Job.status, "set", retval=True)
def _guard_job_status_set(_target, value, oldvalue, _initiator):
    if oldvalue in (None, NO_VALUE):
        return value
    old_status = _coerce_job_status(oldvalue)
    new_status = _coerce_job_status(value)
    if old_status is None or new_status is None or old_status == new_status:
        return value

    allowed = JOB_STATUS_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise InvalidJobTransition(
            f"Illegal direct status write: {old_status.value} -> {new_status.value}"
        )
    return value


class SurveyItem(db.Model):
    __tablename__ = "survey_items"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    section = db.Column(db.String(64), index=True)
    pos = db.Column(db.Integer, index=True)
    part_no = db.Column(db.String(64))
    name = db.Column(db.String(128))
    qty = db.Column(db.Integer, default=1)

    # Flags
    always_replace = db.Column(db.Boolean, default=False)  # 100% replacement
    in_kit = db.Column(db.Boolean, default=False)  # supplied as part of a kit

    # NEW: behaviour flags copied from TemplateItem
    big_ticket = db.Column(db.Boolean, default=False)       # menu / upsell item
    requires_test = db.Column(db.Boolean, default=False)    # needs test before order

    requires_measurement = db.Column(
        db.Boolean,
        default=False,
    )  # measurement needed

    # NEW: kit behaviour used by BOM kit logic
    kit_name = db.Column(db.String(128))        # label that groups lines into a kit
    kit_master = db.Column(db.Boolean, default=False)  # is this the “boxed” kit line?

    # Survey data
    condition = db.Column(db.String(32))
    decision = db.Column(db.Enum(DecisionEnum, values_callable=_enum_names, name="decisionenum"))
    notes = db.Column(db.Text)

    # Measurements (actual recorded for this job)
    measurement_value = db.Column(db.String(32))
    measurement_unit = db.Column(db.String(16))
    spec_min = db.Column(db.String(32))
    spec_max = db.Column(db.String(32))
    measurement_result = db.Column(
        db.Enum(MeasurementResultEnum, values_callable=_enum_names, name="measurementresultenum"),
        default=MeasurementResultEnum.NOT_MEASURED,
    )
    torque_value = db.Column(db.Float)
    torque_unit = db.Column(db.String(16), default="Nm")
    torque_sequence = db.Column(db.Integer)
    torque_confirmed = db.Column(db.Boolean, default=False)
    is_resolved = db.Column(db.Boolean, default=False, nullable=False)


class PartRequirement(db.Model):
    """
    BOM / parts list line per job.
    Generated from SurveyItem when decision == REPLACE (or always_replace),
    then owned/edited by Office.
    """

    __tablename__ = "part_requirements"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Link back to the survey line that created this BOM line
    survey_item_id = db.Column(
        db.Integer,
        db.ForeignKey("survey_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    survey_item = db.relationship(
        "SurveyItem",
        backref="part_requirement",
        uselist=False,
    )

    # Copy of the survey/template meta at time of BOM generation
    section = db.Column(db.String(64), index=True)  # TA / MAN group
    pos = db.Column(db.Integer, index=True)  # positional index within section
    part_no = db.Column(db.String(120))
    name = db.Column(db.String(255))

    # How many we actually need to order/use
    qty_required = db.Column(db.Integer, default=1)

    # BOM / stock status for this job/line
    stock_status = db.Column(
        db.Enum(StockStatusEnum, values_callable=_enum_names, name="stockstatusenum"),
        nullable=False,
        default=StockStatusEnum.TO_ORDER,
        index=True,
    )

    supplier = db.Column(db.String(120))
    po_number = db.Column(db.String(120))
    notes = db.Column(db.Text)
    backorder_reason = db.Column(db.Text)
    qty_received = db.Column(db.Integer, default=0)
    received_at = db.Column(db.DateTime, nullable=True)
    received_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Approval metadata (Office review before issuing to Stores)
    approved = db.Column(db.Boolean, default=False, nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    # QuickBooks expense tracking
    qb_expense_id = db.Column(db.String(128), nullable=True, index=True)
    qb_bill_id = db.Column(db.String(128), nullable=True)
    qb_last_sync_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    received_by = db.relationship("User", foreign_keys=[received_by_id])


class Attachment(db.Model):
    __tablename__ = "attachments"
    __table_args__ = (
        db.UniqueConstraint("job_id", "file_hash", name="uq_attachments_job_file_hash"),
    )

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = db.Column(db.String(255))
    original_filename = db.Column(db.String(255))
    file_path = db.Column(db.String(255))
    file_type = db.Column(db.String(64))
    file_hash = db.Column(db.String(64), index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_id])


# ─────────────────────────────────────────
# Templates
# ─────────────────────────────────────────


class Template(db.Model):
    __tablename__ = "templates"
    __table_args__ = (
        db.UniqueConstraint("organization_id", "name", name="uq_templates_org_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(128), nullable=False)
    engine_type = db.Column(db.String(128))

    # Lock flag – when True, only Admin can edit this template
    is_locked = db.Column(db.Boolean, nullable=False, default=False)

    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    items = db.relationship(
        "TemplateItem",
        backref="template",
        cascade="all, delete-orphan",
    )

    # Logical grouping of template lines (measured items, kits, big ticket, etc.)
    groups = db.relationship(
        "TemplateGroup",
        backref="template",
        cascade="all, delete-orphan",
    )

    # 🔹 All jobs that use this template as their Job Pack spec
    jobs = db.relationship(
        "Job",
        back_populates="template",
    )

    # Office costing templates attached to this engine template
    costing_templates = db.relationship(
        "CostingTemplateProfile",
        back_populates="template",
        cascade="all, delete-orphan",
    )

    epicor_settings = db.relationship(
        "EpicorSetting",
        back_populates="template",
        cascade="all, delete-orphan",
    )

    # NEW: optional JSON schema describing pre-survey checkboxes
    pre_survey_schema = db.Column(db.Text, nullable=True)

    sections = db.relationship(
        "TemplateSection",
        back_populates="template",
        cascade="all, delete-orphan",
    )
    organization = db.relationship("Organization", backref="templates", lazy=True)


class TemplateWizardState(db.Model):
    __tablename__ = "template_wizard_states"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status = db.Column(db.String(32), nullable=False, default="draft")
    current_step = db.Column(db.Integer, nullable=False, default=1)
    step_data = db.Column(db.JSON, nullable=True)
    step_status = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    template = db.relationship("Template", backref=db.backref("wizard_state", uselist=False))


class TemplatePart(db.Model):
    __tablename__ = "template_parts"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    part_no = db.Column(db.String(128), nullable=False)
    normalized_part_no = db.Column(db.String(128), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    template = db.relationship("Template", backref=db.backref("canonical_parts", cascade="all, delete-orphan"))


class TemplateOccurrence(db.Model):
    __tablename__ = "template_occurrences"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_part_id = db.Column(
        db.Integer,
        db.ForeignKey("template_parts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_item_id = db.Column(
        db.Integer,
        db.ForeignKey("template_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    section = db.Column(db.String(128), nullable=True)
    pos = db.Column(db.Integer, nullable=True)
    qty = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    part = db.relationship("TemplatePart", backref=db.backref("occurrences", cascade="all, delete-orphan"))

class TemplateItem(db.Model):
    __tablename__ = "template_items"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    section = db.Column(db.String(64))
    pos = db.Column(db.Integer)
    part_no = db.Column(db.String(64))
    name = db.Column(db.String(128))
    qty = db.Column(db.Integer, default=1)

    # Flags at template level
    always_replace = db.Column(db.Boolean, default=False)  # 100% replacement
    in_kit = db.Column(db.Boolean, default=False)          # part comes inside a kit

    # NEW: behaviour flags
    big_ticket = db.Column(db.Boolean, default=False)      # menu / upsell item
    requires_test = db.Column(db.Boolean, default=False)   # needs test before decision

    requires_measurement = db.Column(
        db.Boolean,
        default=False,
    )  # needs measurement row
    requires_torque = db.Column(db.Boolean, default=False)
    requires_build_measure = db.Column(db.Boolean, default=False)
    requires_photo = db.Column(db.Boolean, default=False)

    # Measurement spec (one spec per template line)
    measurement_label = db.Column(db.String(255))  # e.g. "Big end bore"
    measurement_unit = db.Column(db.String(32))    # e.g. "mm", "µm"
    measurement_min = db.Column(db.Float)          # lower limit
    measurement_max = db.Column(db.Float)          # upper limit
    torque_value = db.Column(db.Float)
    torque_unit = db.Column(db.String(16), default="Nm")
    torque_sequence = db.Column(db.Integer)
    assembly_notes = db.Column(db.Text)

    # Supersedes rules: JSON string of part numbers this line replaces (for kits/assemblies)
    supersedes = db.Column(db.Text, nullable=True)
    bundles = db.Column(db.Text, nullable=True)

    # Many-to-many groups (big ticket, measured set, kit, etc.)
    groups = db.relationship(
        "TemplateGroup",
        secondary="template_item_groups",
        back_populates="items",
        lazy="joined",
    )

    # One-to-one stores overlay
    store_item = db.relationship(
        "StoreItem",
        backref="template_item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    organization = db.relationship("Organization", backref="template_items", lazy=True)


class TemplateSection(db.Model):
    __tablename__ = "template_sections"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(128), nullable=False)
    display_order = db.Column(db.Integer, nullable=True)

    template = db.relationship("Template", back_populates="sections")
    illustration_links = db.relationship(
        "TemplateSectionIllustrationLink",
        back_populates="section",
        cascade="all, delete-orphan",
    )


class TemplateGroup(db.Model):
    """
    Logical grouping of template lines inside a template.

    Examples:
      - "Measured items – critical"
      - "Big ticket items"
      - "KIT 200123 – gasket set"
      - "Electricals for test"
    """

    __tablename__ = "template_groups"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer,
        db.ForeignKey("templates.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Short internal reference (used to avoid accidental duplicates per template)
    code = db.Column(db.String(64), nullable=False)

    # Nice display label for the UI
    label = db.Column(db.String(255), nullable=False)

    # Category / behaviour hint:
    # 'measure', 'big_ticket', 'kit', 'test_electrical', 'other', etc.
    type = db.Column(db.String(32), nullable=False, default="other")

    # Optional: parent kit / assembly part number
    parent_part_no = db.Column(db.String(64))

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # All template items that belong to this group
    items = db.relationship(
        "TemplateItem",
        secondary="template_item_groups",
        back_populates="groups",
    )


class TemplateItemGroup(db.Model):
    """
    Join table: many TemplateItems ↔ many TemplateGroups.
    """

    __tablename__ = "template_item_groups"

    template_item_id = db.Column(
        db.Integer,
        db.ForeignKey("template_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    template_group_id = db.Column(
        db.Integer,
        db.ForeignKey("template_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )



class StoreItem(db.Model):
    """
    Lite stores overlay: one row per TemplateItem.

    Uses the template as the full parts catalogue, and just tracks
    bin + stock against each template line.
    """

    __tablename__ = "store_items"
    __table_args__ = (
        db.UniqueConstraint("organization_id", "barcode", name="uq_store_items_org_barcode"),
    )

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # One-to-one with TemplateItem
    template_item_id = db.Column(
        db.Integer,
        db.ForeignKey("template_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Convenience copy so we can filter by engine later if we want
    engine_type = db.Column(db.String(128))

    bin_location = db.Column(db.String(64))
    barcode = db.Column(db.String(64), nullable=True)
    qty_in_stock = db.Column(db.Integer, default=0)
    min_stock = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    organization = db.relationship("Organization", backref="store_items", lazy=True)


# ─────────────────────────────────────────
# Pick lists (Stores inbox)
# ─────────────────────────────────────────


class PickList(db.Model):
    __tablename__ = "pick_lists"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job = db.relationship("Job", back_populates="pick_lists")

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_by = db.relationship(
        "User",
        backref="pick_lists_created",
    )

    status = db.Column(
        db.Enum(PickListStatusEnum, values_callable=_enum_names, name="pickliststatusenum"),
        default=PickListStatusEnum.NEW,
        nullable=False,
        index=True,
    )
    organization = db.relationship("Organization", backref="pick_lists", lazy=True)


class PickListItem(db.Model):
    __tablename__ = "pick_list_items"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    pick_list_id = db.Column(
        db.Integer,
        db.ForeignKey("pick_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pick_list = db.relationship(
        "PickList",
        backref=db.backref(
            "items",
            cascade="all, delete-orphan",
            lazy="joined",
        ),
    )

    part_no = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(255))
    bin_location = db.Column(db.String(64))

    qty_required = db.Column(db.Integer, default=0, nullable=False)
    stock_at_issue = db.Column(db.Integer, default=0, nullable=False)

    picked = db.Column(db.Boolean, default=False, nullable=False)
    issued_qty = db.Column(db.Integer, default=0, nullable=False)
    returned_qty = db.Column(db.Integer, default=0, nullable=False)
    organization = db.relationship("Organization", backref="pick_list_items", lazy=True)


# Keep tenant ownership aligned with authoritative parents.
@event.listens_for(StoreItem, "before_insert")
@event.listens_for(StoreItem, "before_update")
def _enforce_store_item_org(_mapper, _connection, target):
    if not target.template_item_id:
        raise ValueError("StoreItem requires template_item_id.")
    template_item = target.template_item or db.session.get(TemplateItem, target.template_item_id)
    if not template_item:
        raise ValueError("StoreItem template_item not found.")
    if target.organization_id is None:
        target.organization_id = template_item.organization_id
    if target.organization_id != template_item.organization_id:
        raise ValueError("StoreItem organization_id must match template_item.organization_id.")


@event.listens_for(PickList, "before_insert")
@event.listens_for(PickList, "before_update")
def _enforce_picklist_org(_mapper, _connection, target):
    if not target.job_id:
        raise ValueError("PickList requires job_id.")
    job = target.job or db.session.get(Job, target.job_id)
    if not job:
        raise ValueError("PickList job not found.")
    if target.organization_id is None:
        target.organization_id = job.organization_id
    if target.organization_id != job.organization_id:
        raise ValueError("PickList organization_id must match job.organization_id.")


@event.listens_for(PickListItem, "before_insert")
@event.listens_for(PickListItem, "before_update")
def _enforce_picklist_item_org(_mapper, _connection, target):
    if not target.pick_list_id:
        raise ValueError("PickListItem requires pick_list_id.")
    picklist = target.pick_list or db.session.get(PickList, target.pick_list_id)
    if not picklist:
        raise ValueError("PickListItem pick_list not found.")
    if target.organization_id is None:
        target.organization_id = picklist.organization_id
    if target.organization_id != picklist.organization_id:
        raise ValueError("PickListItem organization_id must match pick_list.organization_id.")


# ─────────────────────────────────────────
# Stores foundations – EngineType & Part catalogue
# (used by both BOM and future Stores module)
# ─────────────────────────────────────────

# Association table for many-to-many relation:
# one part can belong to several engine types, one engine type has many parts.
engine_type_parts = db.Table(
    "engine_type_parts",
    db.Column(
        "engine_type_id",
        db.Integer,
        db.ForeignKey("engine_types.id"),
        primary_key=True,
    ),
    db.Column(
        "part_id",
        db.Integer,
        db.ForeignKey("parts.id"),
        primary_key=True,
    ),
)


class EngineTypeModel(db.Model):
    # renamed to EngineTypeModel to avoid clashing with Job.engine_type string
    """
    Master record for an engine family/type used in Stores / catalogue.

    This is separate from Job.engine_type string so we don't break your existing data.
    You can gradually wire Jobs/Templates to this later.
    """

    __tablename__ = "engine_types"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(128), unique=True, nullable=False)  # e.g. MAN_D0836_LF
    name = db.Column(db.String(255), nullable=False)  # e.g. MAN D0836 LF Engine

    parts = db.relationship(
        "Part",
        secondary=engine_type_parts,
        back_populates="engine_types",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<EngineTypeModel code={self.code!r}>"


class Part(db.Model):
    """
    Master part catalogue record across engine types.

    Populated from Template/TemplateItem when an engine template is synced
    into the Stores catalogue.
    """

    __tablename__ = "parts"

    id = db.Column(db.Integer, primary_key=True)
    part_no = db.Column(db.String(128), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    unit = db.Column(db.String(32), nullable=True)

    section = db.Column(db.String(64), nullable=True)
    pos = db.Column(db.Integer, nullable=True)
    qty_per_engine = db.Column(db.Integer, nullable=True)

    # From template flags
    is_always_required = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )  # 100% item
    is_in_kit = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )  # supplied as part of a kit

    # Raw OEM / template metadata if we want to keep more detail
    oem_meta = db.Column(db.JSON, nullable=True)

    engine_types = db.relationship(
        "EngineTypeModel",
        secondary=engine_type_parts,
        back_populates="parts",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<Part part_no={self.part_no!r} name={self.name!r}>"
    
from datetime import datetime

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    # Optional links to a job and user
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    # Simple action name, e.g. "status_change", "survey_completed", "attachment_uploaded"
    action = db.Column(db.String(64), nullable=False)

    # Short human-readable summary
    message = db.Column(db.String(255), nullable=False)

    # Optional blob for extra details (JSON as string, free-text, etc.)
    details = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    # Optional relationships (handy later, not required for now)
    job = db.relationship("Job", backref="audit_logs", lazy=True)
    user = db.relationship("User", backref="audit_logs", lazy=True)

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action!r} job_id={self.job_id} user_id={self.user_id}>" 


class MeasurementAuditLog(db.Model):
    __tablename__ = "measurement_audit_logs"

    __table_args__ = (
        db.Index("ix_measurement_audit_logs_survey_item_timestamp", "survey_item_id", "timestamp"),
    )

    id = db.Column(db.Integer, primary_key=True)
    survey_item_id = db.Column(
        db.Integer,
        db.ForeignKey("survey_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    field_name = db.Column(db.String(64), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    change_reason = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    survey_item = db.relationship("SurveyItem", backref="measurement_audit_logs", lazy=True)
    user = db.relationship("User", backref="measurement_audit_logs", lazy=True)

    def __repr__(self) -> str:
        return f"<MeasurementAuditLog survey_item_id={self.survey_item_id} field={self.field_name!r}>"


class JobReportRevisionLog(db.Model):
    __tablename__ = "job_report_revisions"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    job = db.relationship("Job", back_populates="revisions")
    user = db.relationship("User", backref="report_revisions", lazy=True)

    def __repr__(self) -> str:
        return f"<JobReportRevisionLog job_id={self.job_id} rev={self.revision} reason={self.reason!r}>"


class ErrorLog(db.Model):
    __tablename__ = "error_logs"

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(255), nullable=True)
    message = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    user = db.relationship("User", backref="error_logs", lazy=True)

    def __repr__(self) -> str:
        return f"<ErrorLog id={self.id} path={self.path!r} user_id={self.user_id}>"


class AppLog(db.Model):
    __tablename__ = "app_logs"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    request_id = db.Column(db.String(64), nullable=True, index=True)
    level = db.Column(db.String(32), nullable=False, default="critical")
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    job = db.relationship("Job", backref="app_logs", lazy=True)
    user = db.relationship("User", backref="app_logs", lazy=True)

    def __repr__(self) -> str:
        return f"<AppLog id={self.id} job_id={self.job_id} level={self.level!r}>"


class JobLog(db.Model):
    __tablename__ = "job_logs"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    action_type = db.Column(db.String(64), nullable=False)  # e.g., status_change, decision_made, nc_opened, nc_closed, release_signed
    message = db.Column(db.String(255), nullable=False)
    details = db.Column(db.JSON, nullable=True)

    job = db.relationship("Job", backref="job_logs", lazy=True)
    user = db.relationship("User", backref="job_logs", lazy=True)

    def __repr__(self) -> str:
        return f"<JobLog id={self.id} action={self.action_type!r} job_id={self.job_id} user_id={self.user_id}>"


class PreSurveyResult(db.Model):
    __tablename__ = "pre_survey_results"

    id = db.Column(db.Integer, primary_key=True)

    # One-to-one with Job
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    job = db.relationship(
        "Job",
        backref=db.backref("pre_survey_result", uselist=False),
    )

    # JSON string of checkbox answers, e.g. {"alternator_present": true, ...}
    data = db.Column(db.Text, nullable=True)

    # Free text notes
    notes = db.Column(db.Text, nullable=True)

    # Path to the saved thumbnail image (relative to UPLOAD_FOLDER)
    thumbnail_path = db.Column(db.String(255), nullable=True)

    # When the pre-survey was actually completed
    completed_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<PreSurveyResult id={self.id} job_id={self.job_id}>"


# ─────────────────────────────────────────
# Epicor integration settings
# ─────────────────────────────────────────


class EpicorSetting(db.Model):
    __tablename__ = "epicor_settings"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)

    base_url = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(128), nullable=True)
    plant = db.Column(db.String(128), nullable=True)
    environment = db.Column(
        db.Enum(EpicorEnvironmentEnum, values_callable=_enum_values, name="epicorenvironmentenum"),
        default=EpicorEnvironmentEnum.TEST,
    )

    auth_method = db.Column(
        db.Enum(EpicorAuthMethodEnum, values_callable=_enum_values, name="epicorauthmethodenum"),
        default=EpicorAuthMethodEnum.API_KEY,
        nullable=False,
    )
    api_key_env_var = db.Column(db.String(128), nullable=True)
    oauth_client_id = db.Column(db.String(255), nullable=True)
    oauth_tenant_id = db.Column(db.String(255), nullable=True)
    oauth_scope = db.Column(db.String(255), nullable=True)

    baq_part_cost = db.Column(db.String(128), nullable=True)
    baq_stock = db.Column(db.String(128), nullable=True)
    baq_po_status = db.Column(db.String(128), nullable=True)

    write_mode = db.Column(
        db.Enum(EpicorWriteModeEnum, values_callable=_enum_values, name="epicorwritemodeenum"),
        default=EpicorWriteModeEnum.NONE,
    )

    last_tested_at = db.Column(db.DateTime, nullable=True)
    last_test_status = db.Column(db.String(32), nullable=True)
    last_test_message = db.Column(db.Text, nullable=True)
    last_sample_at = db.Column(db.DateTime, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    template = db.relationship("Template", back_populates="epicor_settings")

    def api_key(self) -> str | None:
        """Fetch API key from the configured env var (non-persistent)."""
        import os

        if not self.api_key_env_var:
            return None
        return os.environ.get(self.api_key_env_var)


# ─────────────────────────────────────────
# QuickBooks integration models
# ─────────────────────────────────────────


class QuickBooksConnection(db.Model):
    """
    Stores QB OAuth credentials per organization.
    One active connection per org at a time.
    """
    __tablename__ = "quickbooks_connections"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # QB Company/Realm
    realm_id = db.Column(db.String(128), nullable=False)
    company_name = db.Column(db.String(255), nullable=True)

    # OAuth2 tokens (encrypted)
    access_token_encrypted = db.Column(db.Text, nullable=False)
    refresh_token_encrypted = db.Column(db.Text, nullable=False)
    token_expires_at = db.Column(db.DateTime, nullable=False)
    refresh_token_expires_at = db.Column(db.DateTime, nullable=True)

    # Connection settings
    environment = db.Column(
        db.Enum(QuickBooksEnvironmentEnum, values_callable=_enum_values, name="qbenvironmentenum"),
        default=QuickBooksEnvironmentEnum.SANDBOX,
        nullable=False,
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    # Sync configuration
    default_income_account_id = db.Column(db.String(64), nullable=True)
    default_expense_account_id = db.Column(db.String(64), nullable=True)
    auto_create_customers = db.Column(db.Boolean, default=True, nullable=False)
    invoice_prefix = db.Column(db.String(32), nullable=True)

    # Audit
    connected_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    connected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_sync_at = db.Column(db.DateTime, nullable=True)
    last_test_at = db.Column(db.DateTime, nullable=True)
    last_test_status = db.Column(db.String(32), nullable=True)
    last_test_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    organization = db.relationship("Organization", backref=db.backref("qb_connection", uselist=False))
    connected_by = db.relationship("User", foreign_keys=[connected_by_id])


class QuickBooksSyncLog(db.Model):
    """
    Tracks all sync attempts for audit and debugging.
    """
    __tablename__ = "quickbooks_sync_logs"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # What was synced
    sync_type = db.Column(
        db.Enum(QBSyncTypeEnum, values_callable=_enum_values, name="qbsynctypeenum"),
        nullable=False,
    )
    entity_type = db.Column(db.String(32), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False, index=True)

    # QB reference
    qb_id = db.Column(db.String(128), nullable=True)
    qb_doc_number = db.Column(db.String(64), nullable=True)

    # Status
    status = db.Column(db.String(32), nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    error_code = db.Column(db.String(64), nullable=True)

    # Who triggered it
    synced_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Debug data
    request_payload = db.Column(db.JSON, nullable=True)
    response_payload = db.Column(db.JSON, nullable=True)

    synced_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    organization = db.relationship("Organization")
    synced_by = db.relationship("User")


class QuickBooksCustomerMap(db.Model):
    """
    Maps RemanAssist customer names to QB Customer IDs.
    Prevents duplicate customer creation.
    """
    __tablename__ = "quickbooks_customer_maps"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Local reference
    customer_name = db.Column(db.String(255), nullable=False)
    customer_name_normalized = db.Column(db.String(255), nullable=False, index=True)

    # QB reference
    qb_customer_id = db.Column(db.String(64), nullable=False)
    qb_display_name = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("organization_id", "customer_name_normalized", name="uq_qb_customer_org_name"),
    )


# ─────────────────────────────────────────
# Illustration / exploded views
# ─────────────────────────────────────────


class IllustrationPage(db.Model):
    __tablename__ = "illustration_pages"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=True)
    engine_tag = db.Column(db.String(128), nullable=True)
    image_path = db.Column(db.String(255), nullable=False)
    natural_w = db.Column(db.Integer, nullable=True)
    natural_h = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="draft")  # draft/published/archived

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    published_at = db.Column(db.DateTime, nullable=True)

    display_config_json = db.Column(db.JSON, nullable=True)

    created_by = db.relationship("User")
    parts = db.relationship(
        "IllustrationPartRow",
        back_populates="page",
        cascade="all, delete-orphan",
    )
    pos_labels = db.relationship(
        "IllustrationPosLabel",
        back_populates="page",
        cascade="all, delete-orphan",
    )
    hotspots = db.relationship(
        "IllustrationHotspot",
        back_populates="page",
        cascade="all, delete-orphan",
    )
    section_links = db.relationship(
        "TemplateSectionIllustrationLink",
        back_populates="page",
        cascade="all, delete-orphan",
    )


class IllustrationPartRow(db.Model):
    __tablename__ = "illustration_part_rows"

    id = db.Column(db.Integer, primary_key=True)
    illustration_page_id = db.Column(
        db.Integer,
        db.ForeignKey("illustration_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pos = db.Column(db.Integer, nullable=False)
    part_no = db.Column(db.String(120), nullable=True)
    qty = db.Column(db.Integer, nullable=False, default=1)
    designation = db.Column(db.String(255), nullable=True)

    page = db.relationship("IllustrationPage", back_populates="parts")


class IllustrationPosLabel(db.Model):
    __tablename__ = "illustration_pos_labels"

    id = db.Column(db.Integer, primary_key=True)
    illustration_page_id = db.Column(
        db.Integer,
        db.ForeignKey("illustration_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pos = db.Column(db.Integer, nullable=False)
    x_norm = db.Column(db.Float, nullable=False)
    y_norm = db.Column(db.Float, nullable=False)

    page = db.relationship("IllustrationPage", back_populates="pos_labels")


class IllustrationHotspot(db.Model):
    __tablename__ = "illustration_hotspots"

    id = db.Column(db.Integer, primary_key=True)
    illustration_page_id = db.Column(
        db.Integer,
        db.ForeignKey("illustration_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pos = db.Column(db.Integer, nullable=False)
    shape_json = db.Column(db.JSON, nullable=False)

    page = db.relationship("IllustrationPage", back_populates="hotspots")


class TemplateMeasurementSpec(db.Model):
    __tablename__ = "template_measurement_specs"

    id = db.Column(db.Integer, primary_key=True)
    template_item_id = db.Column(
        db.Integer,
        db.ForeignKey("template_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instance_index = db.Column(db.Integer, nullable=False, default=1)
    label = db.Column(db.String(255), nullable=True)
    unit = db.Column(db.String(32), nullable=True)
    min_value = db.Column(db.Float, nullable=True)
    max_value = db.Column(db.Float, nullable=True)

    template_item = db.relationship("TemplateItem")

class TemplateSectionIllustrationLink(db.Model):
    __tablename__ = "template_section_illustrations"

    id = db.Column(db.Integer, primary_key=True)
    template_section_id = db.Column(
        db.Integer,
        db.ForeignKey("template_sections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    illustration_page_id = db.Column(
        db.Integer,
        db.ForeignKey("illustration_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_order = db.Column(db.Integer, nullable=True)

    section = db.relationship("TemplateSection", back_populates="illustration_links")
    page = db.relationship("IllustrationPage", back_populates="section_links")


# ─────────────────────────────────────────
# Costing / office sheet models
# ─────────────────────────────────────────


class JobCostingUpload(db.Model):
    __tablename__ = "job_costing_uploads"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = db.Column(db.Integer, nullable=False, default=1)

    file_path = db.Column(db.String(512), nullable=False)
    original_filename = db.Column(db.String(255), nullable=True)
    sheet_name = db.Column(db.String(128), nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    parsed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    job = db.relationship("Job", backref="costing_uploads", lazy=True)
    uploaded_by = db.relationship("User")


class CostingTemplateProfile(db.Model):
    __tablename__ = "costing_template_profiles"

    id = db.Column(db.Integer, primary_key=True)
    engine_template_id = db.Column(
        db.Integer,
        db.ForeignKey("templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    name = db.Column(db.String(255), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    xlsx_template_path = db.Column(db.String(512), nullable=True)
    sheet_name = db.Column(db.String(128), nullable=True)
    table_start_row = db.Column(db.Integer, nullable=True)
    required_columns_json = db.Column(db.JSON, nullable=True)
    header_cell_map_json = db.Column(db.JSON, nullable=True)
    row_match_keys_json = db.Column(db.JSON, nullable=True)
    programme_rules_json = db.Column(db.JSON, nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    template = db.relationship("Template", back_populates="costing_templates")
    created_by = db.relationship("User")
    template_lines = db.relationship(
        "CostingTemplateLine",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class CostingTemplateLine(db.Model):
    __tablename__ = "costing_template_lines"

    id = db.Column(db.Integer, primary_key=True)
    costing_template_profile_id = db.Column(
        db.Integer,
        db.ForeignKey("costing_template_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )

    line_no = db.Column(db.Integer, nullable=True)
    group_no = db.Column(db.String(64), nullable=True)
    figure = db.Column(db.String(64), nullable=True)
    item_no = db.Column(db.String(64), nullable=True)

    oem_part_no = db.Column(db.String(120), nullable=True)
    system_part_number = db.Column(db.String(120), nullable=True)
    part_description = db.Column(db.String(255), nullable=True)

    default_class = db.Column(
        db.Enum(LineClassEnum, values_callable=_enum_values, name="lineclassenum"),
        default=LineClassEnum.STANDARD,
    )
    default_intended_supplier = db.Column(db.String(128), nullable=True)
    default_latest_supplier = db.Column(db.String(128), nullable=True)
    default_latest_cost = db.Column(db.Numeric(12, 2), nullable=True)
    default_menu_sell_price = db.Column(db.Numeric(12, 2), nullable=True)

    is_menu = db.Column(db.Boolean, default=False, nullable=False)
    is_kit = db.Column(db.Boolean, default=False, nullable=False)
    is_consumable = db.Column(db.Boolean, default=False, nullable=False)

    default_qty_on_stock = db.Column(db.Integer, default=0)
    default_qty_on_order = db.Column(db.Integer, default=0)

    is_active = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    profile = db.relationship("CostingTemplateProfile", back_populates="template_lines")


class CostingSheet(db.Model):
    __tablename__ = "costing_sheets"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer,
        db.ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    job_costing_upload_id = db.Column(
        db.Integer,
        db.ForeignKey("job_costing_uploads.id", ondelete="SET NULL"),
        nullable=True,
    )
    costing_template_profile_id = db.Column(
        db.Integer,
        db.ForeignKey("costing_template_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    template_version_snapshot = db.Column(db.Integer, nullable=True)

    stage = db.Column(
        db.Enum(CostingStageEnum, values_callable=_enum_values, name="costingstageenum"),
        default=CostingStageEnum.AWAITING_SAS,
        nullable=False,
    )

    # Header values (copied from job/office sheet)
    issue = db.Column(db.String(64), nullable=True)
    auth = db.Column(db.String(64), nullable=True)
    job_no = db.Column(db.String(64), nullable=True)
    sn = db.Column(db.String(128), nullable=True)
    engine_no = db.Column(db.String(128), nullable=True)
    engine_desc = db.Column(db.String(255), nullable=True)
    date = db.Column(db.DateTime, nullable=True)

    # Totals
    parts_replacement_cost = db.Column(db.Numeric(12, 2), default=0)
    emergent_work_cost = db.Column(db.Numeric(12, 2), default=0)
    menu_price_add = db.Column(db.Numeric(12, 2), default=0)
    cost_booked = db.Column(db.Numeric(12, 2), default=0)

    warning_text = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    locked_at = db.Column(db.DateTime, nullable=True)

    job = db.relationship("Job", back_populates="costing_sheet")
    job_costing_upload = db.relationship("JobCostingUpload")
    template_profile = db.relationship("CostingTemplateProfile")
    lines = db.relationship(
        "CostingLine",
        back_populates="sheet",
        cascade="all, delete-orphan",
    )

    def transition_stage_to(self, new_stage: CostingStageEnum) -> None:
        current = self.stage
        if current == new_stage:
            return
        allowed = COSTING_STAGE_TRANSITIONS.get(current, set())
        if new_stage not in allowed:
            raise InvalidCostingTransition(
                f"Illegal costing transition: {current.value} -> {new_stage.value}"
            )
        self.stage = new_stage


class CostingLine(db.Model):
    __tablename__ = "costing_lines"

    id = db.Column(db.Integer, primary_key=True)
    costing_sheet_id = db.Column(
        db.Integer,
        db.ForeignKey("costing_sheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    part_requirement_id = db.Column(
        db.Integer,
        db.ForeignKey("part_requirements.id", ondelete="SET NULL"),
        nullable=True,
    )

    line_no = db.Column(db.Integer, nullable=True)
    group_no = db.Column(db.String(64), nullable=True)
    figure = db.Column(db.String(64), nullable=True)
    item_no = db.Column(db.String(64), nullable=True)

    oem_part_no = db.Column(db.String(120), nullable=True)
    system_part_number = db.Column(db.String(120), nullable=True)
    part_description = db.Column(db.String(255), nullable=True)

    line_class = db.Column(
        db.Enum(LineClassEnum, values_callable=_enum_values, name="lineclassenum"),
        default=LineClassEnum.STANDARD,
    )
    notes = db.Column(db.Text, nullable=True)
    is_kit = db.Column(db.Boolean, default=False, nullable=False)
    is_menu = db.Column(db.Boolean, default=False, nullable=False)
    is_consumable = db.Column(db.Boolean, default=False, nullable=False)

    intended_supplier = db.Column(db.String(128), nullable=True)
    latest_supplier = db.Column(db.String(128), nullable=True)
    latest_cost = db.Column(db.Numeric(12, 2), nullable=True)
    price_cost = db.Column(db.Numeric(12, 2), nullable=True)
    menu_sell_price_unit = db.Column(db.Numeric(12, 2), nullable=True)
    rbb_value = db.Column(db.Numeric(12, 2), nullable=True)

    qty_on_stock = db.Column(db.Integer, default=0)
    qty_on_order = db.Column(db.Integer, default=0)
    qty_required = db.Column(db.Integer, default=0)

    po_number = db.Column(db.String(120), nullable=True)
    unit_cost_confirmed = db.Column(db.Numeric(12, 2), nullable=True)
    line_cost = db.Column(db.Numeric(12, 2), nullable=True)
    procurement_status = db.Column(
        db.Enum(ProcurementStatusEnum, values_callable=_enum_values, name="procurementstatusenum"),
        default=ProcurementStatusEnum.NOT_COSTED,
    )

    emergent_qty_required = db.Column(db.Integer, default=0)
    emergent_line_cost = db.Column(db.Numeric(12, 2), nullable=True)
    emergent_reason = db.Column(db.Text, nullable=True)

    match_status = db.Column(
        db.Enum(MatchStatusEnum, values_callable=_enum_values, name="matchstatusenum"),
        default=MatchStatusEnum.UNMATCHED_SHEET,
    )

    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    sheet = db.relationship("CostingSheet", back_populates="lines")
    part_requirement = db.relationship("PartRequirement", backref="costing_lines")


@event.listens_for(Attachment, "after_delete")
def _delete_attachment_file(_mapper, _connection, target):
    try:
        from file_utils import delete_upload_file

        rel_path = target.file_path or target.filename
        delete_upload_file(rel_path)
    except Exception:
        pass


@event.listens_for(JobCostingUpload, "after_delete")
def _delete_costing_upload_file(_mapper, _connection, target):
    try:
        from file_utils import delete_upload_file

        delete_upload_file(target.file_path)
    except Exception:
        pass


@event.listens_for(IllustrationPage, "after_delete")
def _delete_illustration_image(_mapper, _connection, target):
    try:
        from file_utils import delete_upload_file

        delete_upload_file(target.image_path)
    except Exception:
        pass


@event.listens_for(Job, "after_delete")
def _delete_job_uploads(_mapper, _connection, target):
    try:
        from file_utils import delete_job_upload_dir

        delete_job_upload_dir(target.id)
    except Exception:
        pass
