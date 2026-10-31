# RemanAssist - Comprehensive Architectural Review

**Version:** 1.1 Gold Standard
**Review Date:** February 2026
**Reviewer:** Architectural Analysis Agent
**Purpose:** Complete system documentation for new developers and stakeholders

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Database Schema](#2-database-schema)
3. [Tech Stack](#3-tech-stack)
4. [Core Features & Workflows](#4-core-features--workflows)
5. [Business Logic](#5-business-logic)
6. [File/Folder Structure](#6-filefolder-structure)
7. [UI/UX Patterns](#7-uiux-patterns)
8. [API Design](#8-api-design)
9. [Key Insights](#9-key-insights)
10. [Motor-Specific Elements](#10-motor-specific-elements)

---

## 1. Architecture Overview

### 1.1 Architectural Pattern

**Flask Monolithic Architecture** with clear separation of concerns:

- **Pattern**: Factory pattern with blueprint-based modular routing
- **Framework**: Flask 3.0.3 (Python web framework)
- **ORM**: SQLAlchemy 2.0.31 with Flask-SQLAlchemy integration
- **Templating**: Server-side rendering with Jinja2
- **Authentication**: Flask-Login session-based authentication
- **Database**: SQLite (development), PostgreSQL (production)

### 1.2 System Design Principles

**Multitenancy Architecture**:
- Hard multitenancy via `organization_id` foreign key on all tables
- Organization slug-based access control
- User belongs to single organization with role-based permissions
- All queries automatically scoped to user's organization via `get_org_filter()`

**Blueprint Organization**:
The application is organized into 7 functional blueprints:

| Blueprint | Purpose | Routes | Lines of Code |
|-----------|---------|--------|---------------|
| `jobs` | Job Pack lifecycle management | 17 | 1,658 |
| `survey` | Technician inspection workflow | 2 | 651 |
| `parts` | BOM editing & procurement | 3 | 813 |
| `stores` | Inventory & pick lists | 6 | 747 |
| `costing` | Office costing sheet management | 8 | 732 |
| `auth` | User authentication & management | ~10 | ~300 |
| `epicor` | ERP integration (minimal) | - | - |

**Service Layer Pattern**:
Business logic is separated from route handlers into dedicated service modules in `services/`:
- `bom.py` - BOM generation algorithms
- `costing.py` - Costing calculations
- `job_services.py` - Job lifecycle management
- `measurement_service.py` - Measurement validation & unit conversion
- `job_pack_report.py` - Report generation
- Plus 7 additional service modules

### 1.3 Application Flow

```
User Request → Flask Router → Blueprint Route Handler
    ↓
Authorization Check (decorators: @login_required, @roles_required)
    ↓
Service Layer (business logic)
    ↓
SQLAlchemy ORM → Database
    ↓
Jinja2 Template Rendering → HTML Response
```

---

## 2. Database Schema

### 2.1 Complete Table Inventory (28 Tables)

#### Organizations & Users

**`organizations`**
- **Purpose**: Multitenancy container
- **Key Fields**: `id`, `name`, `slug` (unique), `created_at`
- **Relationships**: Has many Users, Jobs, Templates

**`users`**
- **Purpose**: User accounts with role-based access
- **Key Fields**: `id`, `organization_id`, `username` (unique per org), `password_hash`, `role` (enum), `force_password_reset`, `created_at`
- **Roles**: Technician, Office, Stores, Admin
- **Relationships**: Belongs to Organization; has many Jobs (created_by, assigned_to)

#### Job Management

**`jobs`** (Master record)
- **Purpose**: Represents a single remanufacturing project
- **Key Fields**:
  - `id`, `organization_id`
  - `job_number` (unique per org, e.g., "JOB-2024-001")
  - `job_pack_id` (unique identifier for job pack)
  - `customer_name`, `engine_type`, `serial_number`
  - `status` (enum): pre_survey → survey → office → build → complete (+ hold)
  - `template_id` (FK to templates)
  - `assigned_to_id` (FK to users - Technician)
  - `created_by_id` (FK to users)
  - `survey_version`, `parts_version`, `report_revision` (versioning)
  - `release_signed_by_id`, `release_signed_at` (approval workflow)
- **Relationships**:
  - Belongs to Template, Organization, Users (assigned_to, created_by, release_signed_by)
  - Has many SurveyItems, PartRequirements, Attachments, AuditLogs, PickLists
  - Has one CostingSheet, PreSurveyResult

**`survey_items`** (Inspection line items)
- **Purpose**: Individual parts inspected during survey
- **Key Fields**:
  - `id`, `job_id`
  - `section` (grouping code, e.g., "TA0101")
  - `pos` (position/item number)
  - `part_no`, `name`, `qty`
  - `condition` (wear description)
  - `decision` (enum): reuse, replace, scrap, inspect, new, machining
  - `measurement_*` (label, result, value, unit, min, max, status)
  - `torque_*` (value, unit, sequence, notes)
  - `is_resolved` (boolean)
- **Limit**: ~500 items per job (configurable)
- **Relationships**: Belongs to Job; has one PartRequirement (optional)

**`part_requirements`** (BOM lines)
- **Purpose**: Parts needed for job (generated from survey decisions)
- **Key Fields**:
  - `id`, `job_id`, `survey_item_id`
  - `section`, `pos`, `part_no`, `name`, `qty_required`
  - `stock_status` (enum): pending, in_stock, to_order, ordered, received, fitted
  - `supplier`, `po_number`, `notes`
  - `approved`, `approved_by_id`, `approved_at`
  - `received_qty`, `received_at`
- **Relationships**: Belongs to Job, SurveyItem (optional); has many CostingLines

#### Template System

**`templates`** (Reusable job specifications)
- **Purpose**: Master specification for engine types
- **Key Fields**:
  - `id`, `organization_id`
  - `name` (unique per org, e.g., "MAN D0836 Standard")
  - `engine_type`
  - `is_locked` (Admin-only edit when true)
  - `version`, `created_at`, `updated_at`
  - `pre_survey_schema` (JSON - checkbox configuration)
- **Relationships**:
  - Belongs to Organization
  - Has many TemplateItems, TemplateSections, TemplateGroups
  - Has one EpicorSetting, CostingTemplateProfile

**`template_items`** (Template line items)
- **Purpose**: Parts catalog for template
- **Key Fields**:
  - `id`, `template_id`, `organization_id`
  - `section`, `pos`, `part_no`, `name`, `qty`
  - Flags: `always_replace`, `in_kit`, `big_ticket`, `requires_test`, `requires_measurement`, `requires_torque`
  - `measurement_*` (label, unit, min, max)
  - `torque_*` (label, unit, sequence, notes)
  - `supersedes` (JSON - kit replacement rules)
  - `bundles` (JSON - component grouping)
  - `assembly_notes`
- **Typical Count**: 80-150 items per template
- **Relationships**:
  - Belongs to Template
  - Has many TemplateGroups (M:M via template_item_groups)
  - Has one StoreItem (optional)

**`template_sections`**
- **Purpose**: Section headers for organizing template
- **Key Fields**: `id`, `template_id`, `name`, `display_order`
- **Relationships**: Has many IllustrationPages (M:M)

**`template_groups`**
- **Purpose**: Logical groupings (measured items, big ticket items, kits, electrical tests)
- **Key Fields**: `id`, `template_id`, `code`, `label`, `type`, `parent_part_no`
- **Relationships**: Has many TemplateItems (M:M)

**`template_parts`** (Canonical parts catalog)
- **Purpose**: Normalized parts master per template
- **Key Fields**: `id`, `template_id`, `part_no` (normalized), `name`

**`template_occurrences`**
- **Purpose**: Track part occurrences across template
- **Key Fields**: `id`, `template_id`, `template_part_id`, `template_item_id`, `section`, `pos`, `qty`

**`template_measurement_specs`**
- **Purpose**: Measurement specifications per template item instance
- **Key Fields**: `id`, `template_item_id`, `instance_index`, `label`, `unit`, `min_value`, `max_value`

#### Stores & Inventory

**`store_items`** (Stock overlay)
- **Purpose**: Inventory levels per template item
- **Key Fields**:
  - `id`, `template_item_id` (unique)
  - `engine_type`, `bin_location`, `barcode` (unique)
  - `qty_in_stock`, `min_stock`
  - `notes`, `created_at`, `updated_at`
- **Relationships**: Belongs to TemplateItem

**`engine_types`**
- **Purpose**: Engine family master data
- **Key Fields**: `id`, `code` (unique), `name`

**`parts`**
- **Purpose**: Global parts catalog
- **Key Fields**: `id`, `part_no` (unique), `name`, `unit`, `section`, `pos`, `qty_per_engine`, flags, `oem_meta`

**`engine_type_parts`** (Join table)
- **Purpose**: Many-to-many relationship between engine types and parts

**`pick_lists`**
- **Purpose**: Stores issue list for job
- **Key Fields**: `id`, `job_id`, `created_at`, `created_by_id`, `status` (enum: new/picked/complete/cancelled)
- **Relationships**: Belongs to Job; has many PickListItems

**`pick_list_items`**
- **Purpose**: Individual lines on pick list
- **Key Fields**: `id`, `pick_list_id`, `part_no`, `name`, `bin_location`, `qty_required`, `stock_at_issue`, `picked`, `issued_qty`, `returned_qty`

#### Costing (Office Sheet)

**`costing_sheets`**
- **Purpose**: Master costing sheet per job
- **Key Fields**:
  - `id`, `job_id` (unique), `job_costing_upload_id`, `template_profile_id`
  - `stage` (enum): awaiting_sas, costing_in_progress, awaiting_po, engine_in_build, complete
  - `issue`, `auth`, `job_no`, `sn`, `engine_no`, `engine_desc`
  - `parts_cost`, `emergent_cost`, `menu_price`, `booked_cost`
  - `warning_text`, `created_at`, `locked_at`
- **Relationships**: Has many CostingLines

**`costing_lines`**
- **Purpose**: Individual costing line per part
- **Key Fields**:
  - `id`, `sheet_id`, `part_requirement_id`
  - `line_no`, `group_no`, `figure`, `item_no`
  - `oem_part_no`, `system_part_no`, `description`
  - `line_class` (enum): replace_100, as_required, menu_item, kit_part, consumable
  - `intended_supplier`, `latest_supplier`, `latest_cost`
  - `price_cost`, `menu_sell_price`, `rbb_value`
  - `qty_*` (stock, order, booked)
  - `po_number`, `procurement_status` (enum)
  - `emergent_*` (work, cost)
  - `match_status` (enum): matched, unmatched_bom, unmatched_sheet, ambiguous
  - `notes`

**`costing_template_profiles`**
- **Purpose**: Office costing templates (XLSX parsing config)
- **Key Fields**: `id`, `template_id`, `name`, `version`, `is_active`, `xlsx_template_path`, `sheet_name`, `table_start_row`, `required_columns_json`, `header_cell_map_json`, `row_match_keys_json`, `programme_rules_json`

**`costing_template_lines`**
- **Purpose**: Template line defaults for costing
- **Key Fields**: `id`, `profile_id`, `line_no`, `group_no`, `figure`, `item_no`, `oem_part_no`, `system_part_no`, `description`, `line_class`, `supplier`, `cost`, `menu_sell_price`, flags

**`job_costing_uploads`**
- **Purpose**: Excel upload tracking
- **Key Fields**: `id`, `job_id`, `version`, `file_path`, `original_filename`, `sheet_name`, `uploaded_by_id`, `uploaded_at`, `parsed_at`, `notes`

#### Attachments & Media

**`attachments`**
- **Purpose**: Job attachments (photos, documents)
- **Key Fields**: `id`, `job_id`, `filename`, `original_filename`, `file_path`, `file_type`, `file_hash` (unique per job - deduplication), `uploaded_by_id`, `uploaded_at`

**`illustration_pages`**
- **Purpose**: Exploded view diagrams
- **Key Fields**: `id`, `title`, `engine_tag`, `image_path`, `natural_w`, `natural_h`, `status`, `display_config_json`, `created_by_id`, `created_at`, `published_at`

**`illustration_part_rows`**
- **Purpose**: Part references on illustration
- **Key Fields**: `id`, `page_id`, `pos`, `part_no`, `qty`, `designation`

**`illustration_pos_labels`**
- **Purpose**: Position labels overlay on illustration
- **Key Fields**: `id`, `page_id`, `pos`, `x_norm`, `y_norm` (normalized coordinates)

**`illustration_hotspots`**
- **Purpose**: Interactive hotspots on illustration
- **Key Fields**: `id`, `page_id`, `pos`, `shape_json` (polygon coordinates)

**`template_section_illustrations`** (Join table)
- **Purpose**: Link illustrations to template sections
- **Key Fields**: `id`, `section_id`, `page_id`, `display_order`

#### Audit & Logging

**`audit_logs`**
- **Purpose**: General audit trail
- **Key Fields**: `id`, `job_id`, `user_id`, `action`, `message`, `details`, `created_at`

**`job_logs`**
- **Purpose**: Detailed job events
- **Key Fields**: `id`, `job_id`, `user_id`, `timestamp`, `action_type`, `message`, `details` (JSON)

**`measurement_audit_logs`**
- **Purpose**: Measurement change tracking
- **Key Fields**: `id`, `survey_item_id`, `user_id`, `field_name`, `old_value`, `new_value`, `change_reason`, `timestamp`

**`job_report_revisions`**
- **Purpose**: Report version history
- **Key Fields**: `id`, `job_id`, `revision`, `reason`, `user_id`, `created_at`

**`error_logs`**
- **Purpose**: Error tracking
- **Key Fields**: `id`, `path`, `message`, `user_id`, `created_at`

**`app_logs`**
- **Purpose**: Application-level logs
- **Key Fields**: `id`, `job_id`, `user_id`, `request_id`, `level`, `message`, `created_at`

#### Other Tables

**`pre_survey_results`**
- **Purpose**: Pre-survey checkpoint data (checkboxes, thumbnail, notes)

**`epicor_settings`**
- **Purpose**: ERP integration configuration per template

**`template_wizard_states`**
- **Purpose**: Template wizard progress tracking

### 2.2 Key Relationships

```
Organization (1) ──┬─→ (many) User
                   ├─→ (many) Job
                   ├─→ (many) Template
                   └─→ (many) TemplateItem

Job (1) ──┬─→ (many) SurveyItem ──→ (0..1) PartRequirement
          ├─→ (many) PartRequirement ──→ (many) CostingLine
          ├─→ (1) CostingSheet ──→ (many) CostingLine
          ├─→ (many) Attachment
          ├─→ (many) AuditLog
          ├─→ (many) PickList ──→ (many) PickListItem
          ├─→ (0..1) PreSurveyResult
          ├─→ (1) Template [via template_id]
          └─→ (0..1) Release User [approval signature]

Template (1) ──┬─→ (many) TemplateItem ──→ (many) TemplateGroup [M:M]
               ├─→ (many) TemplateSection ──→ (many) IllustrationPage [M:M]
               ├─→ (many) CostingTemplateProfile
               └─→ (1) EpicorSetting

TemplateItem (1) ──→ (0..1) StoreItem [inventory overlay]
```

### 2.3 Enums & Constants

**Role Enum**: `Technician`, `Office`, `Stores`, `Admin`

**Job Status Enum**: `pre_survey`, `survey`, `office`, `build`, `hold`, `complete`

**Decision Enum**: `reuse`, `replace`, `scrap`, `inspect`, `new`, `machining`

**Stock Status Enum**: `pending`, `in_stock`, `to_order`, `ordered`, `received`, `backorder`, `fitted`, `not_required`

**Measurement Result Enum**: `within_spec`, `out_of_spec`, `not_measured`

**Pick List Status Enum**: `new`, `picked`, `complete`, `cancelled`

**Costing Stage Enum**: `awaiting_sas`, `costing_in_progress`, `awaiting_po`, `engine_in_build`, `complete`

**Line Class Enum**: `replace_100`, `as_required`, `menu_item`, `kit_part`, `consumable`, `standard`

**Procurement Status Enum**: `not_costed`, `costed`, `po_raised`, `ordered`, `received`, `issued`

**Match Status Enum**: `matched`, `unmatched_bom`, `unmatched_sheet`, `ambiguous`

### 2.4 Indexes & Constraints

**Unique Constraints**:
- `users.username` (unique per organization)
- `jobs.job_number` (unique per organization)
- `jobs.job_pack_id` (globally unique)
- `templates.name` (unique per organization)
- `store_items.barcode` (globally unique)
- `parts.part_no` (globally unique)
- `attachments.file_hash` (unique per job - deduplication)

**Indexes** (from migration `8a1b2c3d4e5f`):
- `jobs.job_number`, `jobs.status`, `jobs.template_id`, `jobs.assigned_to_id`
- `survey_items.job_id`, `survey_items.decision`
- `part_requirements.job_id`, `part_requirements.stock_status`
- `measurement_audit_logs.survey_item_id`, `measurement_audit_logs.timestamp`

### 2.5 Data Flow Example

**Job Creation → Survey → BOM → Costing → Build**

```
1. Job Created (status=pre_survey)
   - Record created in `jobs` table
   - Template reference stored (`template_id`)
   - Assigned to Technician (`assigned_to_id`)

2. Pre-Survey (optional)
   - Record created in `pre_survey_results`
   - Photos uploaded to `attachments`

3. Survey Populated (status=survey)
   - Template items copied to `survey_items`
   - Technician inspects each item
   - Sets `decision` (reuse/replace/scrap)
   - Enters measurements, torque values
   - Uploads photos to `attachments`

4. BOM Generated (status=office)
   - Service scans `survey_items` where decision=REPLACE
   - Creates `part_requirements` rows
   - Applies kit suppression logic
   - Applies supersedes rules

5. Costing Sheet Created
   - `costing_sheet` record created
   - BOM lines copied to `costing_lines`
   - Office uploads Excel, parses into `job_costing_uploads`
   - Lines matched between BOM and Excel
   - Procurement status tracked

6. Pick List Generated (status=build)
   - `pick_list` created with items from BOM
   - Stores picks items, updates `stock_at_issue`, `issued_qty`
   - Stock levels in `store_items` updated

7. Job Released (status=complete)
   - Admin signs release (`release_signed_by_id`, `release_signed_at`)
   - Report generated (PDF)
   - ZIP export created
```

---

## 3. Tech Stack

### 3.1 Backend (Python)

| Component | Version | Purpose |
|-----------|---------|---------|
| **Flask** | 3.0.3 | Web framework |
| **SQLAlchemy** | 2.0.31 | ORM |
| **Flask-SQLAlchemy** | 3.1.1 | Flask integration for SQLAlchemy |
| **Flask-Migrate** | 4.0.7 | Database migrations (Alembic wrapper) |
| **Flask-Login** | 0.6.3 | Session management |
| **Flask-WTF** | 1.2.1 | CSRF protection, form handling |
| **Werkzeug** | 3.0.3 | WSGI utilities, password hashing |
| **psycopg2-binary** | 2.9.9 | PostgreSQL driver |
| **pandas** | 2.2.2 | Data analysis (BOM compilation, costing calculations) |
| **openpyxl** | 3.1.4 | Excel reading/writing |
| **PyPDF** | 1.24.10 | PDF parsing |
| **PyMuPDF** | - | PDF parsing (fitz library) |
| **WeasyPrint** | 67.0 | HTML→PDF conversion |
| **ReportLab** | 4.4.4 | PDF generation |
| **Pillow** | 12.0.0 | Image processing |
| **bcrypt** | 5.0.0 | Password hashing |
| **PyJWT** | 2.10.1 | JWT tokens |
| **cryptography** | 46.0.3 | Encryption utilities |
| **redis** | 5.0.7 | Distributed rate-limiting (production) |
| **python-dotenv** | 1.2.1 | Environment variable loading |
| **requests** | 2.32.5 | HTTP client (Epicor integration) |
| **tenacity** | 9.1.2 | Retry logic |
| **GitPython** | 3.1.45 | Version control integration |
| **Click** | 8.3.0 | CLI framework |
| **Jinja2** | 3.1.6 | Template engine |

**Total Dependencies**: 60 packages in `requirements.txt`

### 3.2 Frontend

**Templating**: Jinja2 3.1.6
- Server-side rendering
- No SPA framework (React/Vue/Angular)
- 56 HTML template files (~2MB total)

**CSS**:
- Plain CSS (no preprocessors)
- `style.css` (79KB - main stylesheet)
- `components.css` (component library)
- `mobile.css`, `tablet.css` (responsive breakpoints)
- `theme.css` (color scheme)
- Total: ~150KB CSS

**JavaScript**:
- Vanilla JavaScript (no external libraries)
- Inline event handlers in templates
- No bundler (webpack/vite)

### 3.3 Database

**Development**: SQLite 3
- File-based (`instance/app.db`)
- Simple setup, no external service
- Current size: ~7GB (production data imported for testing)

**Production**: PostgreSQL
- Driver: `psycopg2-binary 2.9.9`
- Migrations: Alembic (via Flask-Migrate)
- 21 migration versions

**Migrations**:
- Alembic configuration in `migrations/`
- Version control for schema changes
- Example migrations:
  - `cb31edff9cc9` - Initial schema
  - `462e693b8825` - Add torque fields
  - `ca2e176c395f` - Add machining decision
  - `a1b2c3d4e5f6` - Hard multitenancy (org_slug)
  - `8a1b2c3d4e5f` - Add indexes

### 3.4 Infrastructure & DevOps

**WSGI Server**: `wsgi.py` for gunicorn/uwsgi (production)

**Environment Configuration**:
- `.env` files (python-dotenv)
- Separate configs: Development, Testing, Production
- Config file: `config.py`

**Redis** (optional, production):
- Login rate-limiting
- Distributed locking
- Not used in development (falls back to in-memory)

**Deployment**:
- Systemd service file (`deploy/systemd_reman.service`)
- Gunicorn config (`deploy/gunicorn_config.py`)
- Docker Compose (`deploy/docker-compose.yml`)

### 3.5 Testing

**pytest**: Unit testing framework
- Configuration: `pytest.ini`
- Fixtures: `conftest.py`
- Test files: `tests/test_*.py` (26 test modules)

**Playwright**: E2E testing
- Browser automation
- Test directory: `e2e/tests/`
- Dependencies: `requirements-e2e.txt`

**Load Testing**:
- Custom stress test scripts (`tests/stress_test.py`)
- 250+ concurrent job creation simulation

### 3.6 Development Tools

**CLI Commands** (Click-based):
```bash
flask create-admin          # Create admin user
flask db upgrade            # Run migrations
flask seed-data             # Generate test data
flask export-templates      # Export templates to JSON
flask import-templates      # Import templates from JSON
```

**Scripts** (`scripts/`):
- `run_dev.sh` - Development server
- `run_prod.sh` - Production server (gunicorn)
- `backup_sqlite.py` - Database backup
- `restore_sqlite.py` - Database restore
- `upgrade_legacy_db.py` - Migration helper
- `admin_reset_password.py` - Password reset utility
- Plus 16 more operational scripts

---

## 4. Core Features & Workflows

### 4.1 Job/Project Management

**Main Routes**: `/dashboard`, `/jobs/*`

**Features**:
- Create job pack from template
- Assign technician to job
- Track job status through lifecycle
- Multi-version support (survey, parts, report revisions)
- Release/approval workflow with digital signature
- Job locking (read-only for completed jobs)

**Workflow**:
```
1. User (Office/Admin) creates new job
   → Selects template
   → Enters customer name, engine details, serial number
   → Assigns to technician

2. System creates Job record
   → Status = "pre_survey"
   → Generates unique job_number (e.g., "JOB-2024-001")
   → Generates unique job_pack_id (UUID)

3. Optional Pre-Survey
   → Technician completes checklist
   → Uploads thumbnail photo
   → Status changes to "survey"

4. Survey Phase
   → Template items copied to survey_items
   → Technician inspects, makes decisions
   → Status remains "survey" until submitted

5. Office Phase
   → BOM automatically generated
   → Costing sheet created
   → Status = "office"

6. Build Phase
   → Pick lists created
   → Parts issued from stores
   → Status = "build"

7. Completion & Release
   → Admin reviews and signs
   → Status = "complete"
   → Job becomes read-only
```

**Key Functions** (in `services/job_services.py`):
- `create_job()` - Creates job with template reference
- `change_job_status()` - State machine transitions with validation
- `get_dashboard_jobs()` - Role-filtered job list for dashboard
- `is_job_locked()` - Determines if job is read-only

**Dashboard Views** (role-specific):
- **Technician**: Assigned jobs in survey phase
- **Office**: Jobs in office/costing phase
- **Stores**: Jobs with active pick lists
- **Admin**: All jobs with filtering

### 4.2 Inspection Workflow (Survey)

**Routes**: `/jobs/<id>/pre_survey`, `/jobs/<id>/survey`

**Features**:
- Pre-survey checkpoint with configurable questions
- Section-based survey form (engine-specific layout)
- Decision per line item (6 options)
- Measurement entry with validation
- Torque value tracking with sequence numbers
- Wear condition assessment
- Photo/attachment upload
- Real-time validation and warnings

**Survey Form Structure**:
```
For each section (e.g., "TA0101 - Turbocharger Assembly"):
  For each survey item:
    - Position number
    - Part number, name, quantity
    - Condition text field (wear description)
    - Decision dropdown:
      • Reuse (part is acceptable)
      • Replace (part needs replacement)
      • Scrap (part is damaged beyond repair)
      • Inspect (requires further inspection)
      • New (new part being installed)
      • Machining (part needs machining)
    - Measurement fields (if requires_measurement):
      • Label (e.g., "Big-end bearing clearance")
      • Unit (mm or inches)
      • Min/Max spec
      • Actual value
      • Result indicator (within_spec, out_of_spec, not_measured)
    - Torque fields (if requires_torque):
      • Value, unit (Nm or lb-ft)
      • Sequence number
      • Notes
    - Attachments (photos specific to this item)
```

**Complex Logic**:

1. **Kit Suppression**:
   - If a kit master line (e.g., "Gasket Set") is marked REPLACE
   - All sibling kit members (individual gaskets) are suppressed from BOM
   - Only the kit master appears in BOM

2. **Measurement Validation**:
   - Unit conversion (mm ↔ inches, Nm ↔ lb-ft)
   - Clearance ceiling checks (max 2" or 50mm for clearances)
   - Comparison to spec range (min/max)
   - Audit trail on every measurement change

3. **Illustration Overlays**:
   - Exploded diagrams displayed per section
   - Interactive hotspots highlight parts
   - Position labels link diagram to part list

**Key Functions** (in `survey/routes.py`):
- `seed_survey()` - Copies template items to survey_items
- `validate_measurement()` - Unit conversion and spec checking
- `audit_measurement_change()` - Logs changes to measurement_audit_logs

### 4.3 Template System

**Routes**: `/templates/*`, `/admin/templates/<id>/costing/catalogue`

**Features**:
- Create/edit templates for engine types
- Lock templates (Admin-only edit when locked)
- Reusable sections with descriptions
- Measurement specifications per item
- Supersedes rules (kit replacements, bundles)
- Pre-survey schema configuration (JSON)
- Template wizard (multi-step UI builder)
- Template versioning

**Template Structure**:
```
Template (e.g., "MAN D0836 Standard")
├── Basic Info
│   ├── Name: "MAN D0836 Standard"
│   ├── Engine Type: "MAN D0836"
│   ├── Version: 3
│   └── Locked: true
├── Template Sections (e.g., 8 sections)
│   ├── "TA0101 - Cylinderblock"
│   ├── "TA0201 - Crankshaft Assembly"
│   ├── "TA0301 - Pistons & Connecting Rods"
│   └── ...
├── Template Items (e.g., 120 items)
│   ├── Item 1: Cylinderblock (always_replace=false, big_ticket=true)
│   ├── Item 2: Main bearing set (always_replace=true, in_kit=true)
│   ├── Item 3: Crankshaft (requires_measurement=true)
│   └── ...
├── Template Groups
│   ├── "Measured Items" (14 items)
│   ├── "Big Ticket Items" (6 items)
│   ├── "Kit Components" (32 items)
│   └── "Electrical Tests" (8 items)
└── Illustrations
    ├── Section 1 → Illustration 1 (exploded view)
    └── ...
```

**Key Flags on Template Items**:
- `always_replace`: Part is always replaced (appears in BOM regardless of survey decision)
- `in_kit`: Part is member of a kit (subject to kit suppression logic)
- `big_ticket`: High-value item requiring special attention
- `requires_test`: Electrical/functional testing required
- `requires_measurement`: Dimensional inspection required
- `requires_torque`: Torque specification tracking required

**Template Wizard Workflow**:
```
Step 1: Basic Info
  → Name, engine type, description

Step 2: Add Sections
  → Create section headers (e.g., "TA0101 - Cylinderblock")

Step 3: Add Template Items
  → Import from CSV or add manually
  → Set section, pos, part_no, name, qty
  → Set flags (always_replace, in_kit, etc.)

Step 4: Configure Measurement Specs
  → For items with requires_measurement=true
  → Define label, unit, min, max

Step 5: Define Groups
  → Create logical groupings
  → Assign items to groups (M:M)

Step 6: Set Up Pre-Survey
  → Configure checkbox questions (JSON schema)

Step 7: Review & Publish
  → Lock template (optional)
  → Template ready for job creation
```

### 4.4 BOM Generation

**Service**: `services/bom.py`, `services/bom_services.py`

**Algorithm**:
```
1. Clear existing PartRequirement rows for job

2. Iterate through survey_items:
   For each item:
     - If decision == REPLACE OR always_replace == true:
       → Create PartRequirement
       → Set qty_required = survey_item.qty
       → Set stock_status = "to_order"
       → Add to candidate_lines list

3. Group candidate_lines by kit_name

4. Kit Suppression:
   For each kit group:
     - Find kit_master line (template_item.kit_master == true)
     - If kit_master in candidate_lines (i.e., decision == REPLACE):
       → Keep ONLY the kit_master in BOM
       → Remove all sibling kit members from BOM
     - Else:
       → Keep all individual kit members in BOM

5. Apply Supersedes Rules:
   For each PartRequirement:
     - Check template_item.supersedes (JSON array)
     - If current part_no is in supersedes list:
       → Replace with parent SKU (e.g., kit replaces components)

6. Commit PartRequirement rows to database

7. Return summary (total parts, total qty)
```

**Example**:
- Template has "Gasket Set" (kit_master=true) and 8 individual gaskets (in_kit=true, same kit_name)
- If technician marks "Gasket Set" as REPLACE:
  - BOM contains: 1x "Gasket Set"
  - BOM does NOT contain: 8 individual gaskets (suppressed)
- If technician marks "Gasket Set" as REUSE but "Valve Cover Gasket" as REPLACE:
  - BOM contains: 1x "Valve Cover Gasket"
  - BOM does NOT contain: "Gasket Set" or other individual gaskets

**Key Functions**:
- `generate_bom_for_job()` - Main BOM creation (called when survey submitted)
- `regenerate_bom_for_job()` - Idempotent refresh (can be called multiple times)
- `apply_supersedes()` - Kit/component folding logic

### 4.5 PDF Export & Reporting

**Routes**: `/jobs/<id>/report`, `/jobs/<id>/report.pdf`, `/jobs/<id>/export.zip`

**Capabilities**:
- HTML report generation (responsive layout)
- PDF rendering (WeasyPrint HTML→PDF)
- ZIP pack export (report + attachments + metadata)
- Image embedding with configurable limits
- Report versioning (revision tracking)

**Report Structure**:
```
Job Pack Report
├── Cover Page
│   ├── Job number, customer, engine type, serial number
│   ├── Job status, assigned technician
│   └── Signature (if released)
├── Pre-Survey Results (if exists)
│   ├── Checklist responses
│   └── Thumbnail photo
├── Survey Items (by section)
│   ├── Section header with illustration
│   ├── Table of items:
│   │   ├── Pos, Part No, Name, Qty
│   │   ├── Condition, Decision
│   │   ├── Measurements (if any)
│   │   └── Torque values (if any)
│   └── Section attachments
├── BOM (Parts List)
│   ├── Table of required parts:
│   │   ├── Pos, Part No, Name, Qty
│   │   ├── Stock Status, Supplier
│   │   └── PO Number
│   └── Total parts count
├── Costing Summary (if office completed)
│   ├── Parts cost
│   ├── Emergent work cost
│   ├── Menu price
│   └── Booked cost
├── Attachments
│   ├── Photos (first 50, configurable)
│   └── Documents list
└── Metadata
    ├── Created by, created date
    ├── Survey version, parts version
    ├── Report revision
    └── Generated timestamp
```

**PDF Generation Methods**:
1. **WeasyPrint** (primary):
   - Renders HTML template to PDF
   - Preserves CSS styling
   - Handles page breaks, headers, footers
   - Image embedding

2. **Playwright** (fallback, if WeasyPrint fails):
   - Headless browser rendering
   - Better complex CSS support
   - Slower but more reliable for edge cases

**Key Functions** (in `services/job_pack_report.py`):
- `build_job_pack_context()` - Prepare template context (data for report)
- `build_job_pack_pdf()` - WeasyPrint rendering
- `build_job_pack_zip()` - Archive creation with metadata

### 4.6 User Authentication & Authorization

**Routes**: `/auth/login`, `/auth/logout`, `/auth/change_password`, `/admin/users/*`

**Features**:
- Username/password authentication
- Password hashing (bcrypt)
- 4-tier role-based access control
- Force password reset on first login
- Login rate-limiting (brute-force protection)
- Organization-scoped access (multitenancy)
- CSRF protection (all forms)

**Role Hierarchy**:

| Role | Permissions |
|------|-------------|
| **Technician** | View assigned jobs, complete surveys, upload attachments |
| **Office** | Create jobs, view all jobs, edit BOM, manage costing, release jobs (limited) |
| **Stores** | Manage inventory, create/fulfill pick lists, update stock levels |
| **Admin** | All permissions + user management, template locking, system config |

**Rate Limiting**:
- User-level: 6 failed attempts → 900 second lockout (15 minutes)
- IP-level: 20 failed attempts → 900 second lockout
- Window: 900 seconds (15 minutes)
- Storage: Redis (production) or in-memory (development)

**Security Decorators** (in `auth_utils.py`):
```python
@login_required
- Ensures user is authenticated
- Redirects to login if not

@roles_required(role1, role2, ...)
- Ensures user has one of the specified roles
- Returns 403 Forbidden if not

@job_access_required(role=None)
- Ensures user has access to specific job
- Checks role if specified
- Checks organization scoping
- Returns 404 if job not found or no access
```

**Organization Scoping**:
```python
def get_org_filter():
    """Return SQLAlchemy filter for current user's organization"""
    return Model.organization_id == current_user.organization_id

# Used in all queries:
jobs = Job.query.filter(get_org_filter()).all()
```

### 4.7 File Upload/Storage

**Service**: `file_utils.py`

**Features**:
- Secure filename handling (sanitization)
- File size limits (20MB single file, 50MB total per job)
- File type validation (whitelist)
- File hash tracking (deduplication within job)
- Automatic cleanup (SQLAlchemy event listener on delete)
- Organized folder structure

**Allowed File Types**:
- Images: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, `.svg`
- Documents: `.pdf`, `.xlsx`, `.csv`

**Folder Structure**:
```
uploads/
├── jobs/
│   ├── {job_id}/
│   │   ├── attachments/
│   │   │   ├── photo1.jpg
│   │   │   ├── photo2.jpg
│   │   │   └── ...
│   │   └── reports/
│   │       ├── job_pack_v1.pdf
│   │       └── job_pack_v2.pdf
│   └── ...
├── illustrations/
│   ├── {template_id}/
│   │   ├── section1_diagram.png
│   │   └── section2_diagram.png
│   └── ...
└── temp/
    └── {session_id}/
        └── upload_xyz.tmp
```

**Deduplication**:
- Hash calculated on upload (SHA-256)
- Stored in `attachments.file_hash`
- Unique constraint: `(job_id, file_hash)`
- Prevents duplicate uploads within same job

### 4.8 Stores & Inventory

**Routes**: `/stores/*`, `/stores/picklists/<id>`

**Features**:
- Master parts catalog per engine type
- Bin location tracking
- Barcode label generation
- Min/max stock level alerts
- Pick list workflow (Create → Pick → Issue)
- Stock movement tracking

**Stock Management Workflow**:
```
1. Setup (Admin/Stores)
   → Define engine types
   → Create parts catalog
   → Link parts to engine types
   → Assign bin locations
   → Set min/max stock levels

2. Stock Overlay (per Template Item)
   → Create StoreItem linked to TemplateItem
   → Set bin_location (e.g., "A12-B3")
   → Generate barcode (unique)
   → Set qty_in_stock, min_stock

3. Pick List Creation (Office)
   → Job enters "build" status
   → System creates PickList
   → Copies PartRequirements to PickListItems
   → Sets stock_at_issue (snapshot of current stock)

4. Picking (Stores)
   → Stores opens pick list
   → For each item:
     - Scans barcode or manually finds bin
     - Picks qty_required
     - Marks as picked
   → Pick list status changes to "picked"

5. Issuing (Stores)
   → Reviews picked items
   → Sets issued_qty (may differ from qty_required if stock shortage)
   → Issues to job
   → Updates stock levels (qty_in_stock -= issued_qty)
   → Pick list status changes to "complete"

6. Returns (if applicable)
   → Sets returned_qty
   → Updates stock levels (qty_in_stock += returned_qty)
```

**Key Functions** (in `stores/routes.py`):
- `create_pick_list()` - Generate pick list from BOM
- `update_pick_list_status()` - State transitions
- `issue_stock()` - Deduct from inventory
- `update_stock_levels()` - Manual adjustments

---

## 5. Business Logic

### 5.1 Measurement Calculation & Validation

**Service**: `services/measurement_service.py`

**Unit Conversions**:
```
Metric ↔ Imperial:
- 1 inch = 25.4 mm
- 1 Nm = 0.7376 lb-ft

Conversion applied when:
- Template spec is in one unit
- Measurement entered in different unit
- Display unit preference differs
```

**Validation Logic**:
```python
def validate_and_format_measurement(raw_value, spec_min, spec_max, unit, label):
    """
    1. Parse raw input to Decimal (handle various formats)
    2. Check if label contains "clearance" or "tolerance"
       → Apply ceiling check (max 2" or 50mm)
    3. Convert to spec unit if needed
    4. Compare value to spec range
       → within_spec: min <= value <= max
       → out_of_spec: value < min OR value > max
       → not_measured: value is None/empty
    5. Return formatted value + result status
    6. If field was updated, create MeasurementAuditLog entry
    """
```

**Clearance Ceiling Check**:
- Purpose: Prevent data entry errors for clearances/tolerances
- Rule: If label contains "clearance" or "tolerance", value must be ≤ 2" (50mm)
- Rationale: Clearances >2" are unrealistic and likely typos

**Audit Trail**:
Every measurement change is logged:
```
MeasurementAuditLog:
- survey_item_id
- user_id
- field_name (e.g., "measurement_value")
- old_value, new_value
- change_reason (optional comment)
- timestamp
```

### 5.2 Wear Analysis

**Implicit Approach**:
- No explicit wear scoring algorithm
- Wear assessment is qualitative (technician judgment)
- `condition` field captures wear description (free text)
- `decision` enum captures action (reuse/replace/scrap)

**Decision Factors** (technician considers):
- Visual inspection (condition text)
- Measurement results (within/out of spec)
- OEM guidelines (big_ticket items)
- Cost considerations (menu items)
- Customer requirements

**No Automated Decision**:
- System does NOT auto-decide reuse vs. replace
- Technician has full control over decision
- System only validates measurements against specs

### 5.3 BOM Compilation

**Algorithm** (see 4.4 for full details):

**Input**:
- List of `survey_items` with decisions
- Template metadata (always_replace flags, kit definitions, supersedes rules)

**Processing Steps**:
1. Filter survey items: decision==REPLACE OR always_replace==true
2. Create PartRequirement rows
3. Apply kit suppression (if kit master is REPLACE, suppress kit members)
4. Apply supersedes rules (replace component SKUs with kit SKU)
5. Deduplicate (if same part appears in multiple sections)

**Output**:
- List of `part_requirements` (BOM)
- Summary statistics (total parts, total qty)

**Idempotency**:
- BOM can be regenerated multiple times
- Always clears and rebuilds from scratch
- Safe to call after survey edits

**Example Supersedes Rule**:
```json
{
  "template_item_id": 123,
  "part_no": "GSK-12345",
  "supersedes": ["GSK-001", "GSK-002", "GSK-003"],
  "description": "Full gasket set replaces individual gaskets"
}

Result:
- If technician marks GSK-001 as REPLACE
- BOM shows: GSK-12345 (full set) instead of GSK-001
```

### 5.4 Cost Calculations

**Service**: `services/costing.py`

**Costing Sheet Structure**:
```
CostingSheet (master):
- parts_cost: Sum of all parts (qty × latest_cost)
- emergent_cost: Additional unexpected work
- menu_price: Sum of menu items (qty × menu_sell_price)
- booked_cost: Final cost booked to customer

CostingLine (detail):
- line_class: replace_100, as_required, menu_item, kit_part, consumable
- qty_stock: Quantity in stock (no cost)
- qty_order: Quantity to order (apply cost)
- qty_booked: Quantity charged to customer
- latest_cost: Unit cost from supplier
- menu_sell_price: Standard menu price
```

**Calculation Flow**:
```
1. Ensure costing sheet exists for job

2. Load template profile (if exists)
   → Pre-populate costing_lines from costing_template_lines
   → Apply programme rules (e.g., "All turbo parts: multiply cost by 1.2")

3. OR: Upload Excel file
   → Parse Excel using openpyxl
   → Match header columns to required fields
   → Create job_costing_upload record
   → Parse rows into costing_lines

4. Match BOM to Costing Sheet
   → For each PartRequirement:
     - Find matching CostingLine by part_no
     - If match:
       → Set match_status = "matched"
       → Link part_requirement_id
     - If no match:
       → Create new CostingLine
       → Set match_status = "unmatched_bom"
   → For each CostingLine with no PartRequirement:
     → Set match_status = "unmatched_sheet"

5. Calculate Totals
   → parts_cost = sum(qty_order × latest_cost) for line_class=replace_100
   → emergent_cost = sum(emergent_work_cost)
   → menu_price = sum(qty_booked × menu_sell_price) for line_class=menu_item
   → booked_cost = parts_cost + emergent_cost

6. Procurement Status Tracking
   → not_costed: Line exists but no cost
   → costed: Cost entered
   → po_raised: PO number assigned
   → ordered: Order placed with supplier
   → received: Part received in stores
   → issued: Part issued to job
```

**Programme Rules** (JSON configuration in costing_template_profile):
```json
{
  "rules": [
    {
      "condition": "section == 'TA02'",
      "action": "multiply_cost",
      "factor": 1.2,
      "description": "20% markup on turbocharger parts"
    },
    {
      "condition": "line_class == 'menu_item'",
      "action": "set_menu_sell_price",
      "value": "lookup",
      "description": "Use standard menu price"
    }
  ]
}
```

### 5.5 Template Wizard Flow

**State Tracking**: `TemplateWizardState` model
- Tracks current step (1-7)
- Stores intermediate data (JSON)
- Allows resume/save progress

**Multi-Step Process**:

**Step 1: Basic Info**
- Input: name, engine_type, description
- Validation: Unique name per organization
- Action: Create Template record

**Step 2: Add Sections**
- Input: Section headers (e.g., "TA0101 - Cylinderblock")
- Action: Create TemplateSection records

**Step 3: Add Template Items**
- Input: CSV upload OR manual entry
- Fields: section, pos, part_no, name, qty, flags
- Validation: Unique (section, pos) per template
- Action: Create TemplateItem records

**Step 4: Configure Measurement Specs**
- Filter: Items with requires_measurement=true
- Input: label, unit, min, max (per item instance)
- Action: Create TemplateMeasurementSpec records

**Step 5: Define Groups**
- Input: Group name, type, member selection
- Action: Create TemplateGroup records, link to items (M:M)

**Step 6: Set Up Pre-Survey**
- Input: JSON schema for checkbox questions
- Format:
  ```json
  {
    "questions": [
      {"id": "q1", "text": "Is engine serial number visible?", "required": true},
      {"id": "q2", "text": "Are all accessories present?", "required": false}
    ]
  }
  ```
- Action: Store in template.pre_survey_schema

**Step 7: Review & Publish**
- Display: Summary of template (items, sections, groups)
- Option: Lock template (Admin-only edit)
- Action: Set is_locked=true (optional), template ready for use

---

## 6. File/Folder Structure

### 6.1 Root Directory

```
reman_app_v1.1_gold_standard/
├── app.py                          [1,019 lines] Flask factory, CLI commands
├── models.py                       [1,648 lines] SQLAlchemy models (28 tables)
├── config.py                       [~200 lines] Config classes (dev/test/prod)
├── constants.py                    [~50 lines] Magic numbers, enums
├── auth_utils.py                   [~150 lines] Auth decorators
├── wsgi.py                         [~20 lines] WSGI entrypoint for production
├── requirements.txt                [60 dependencies] Production deps
├── requirements-test.txt           [~10 dependencies] Testing deps
├── requirements-e2e.txt            [~5 dependencies] Playwright E2E
├── pytest.ini                      pytest configuration
├── conftest.py                     Test fixtures
├── Makefile                        Dev/ops targets
├── README.md                       Main documentation
├── QUICKSTART.md                   Quick setup guide
├── TECHNICAL_DEBT.md               Known issues & TODOs
├── PRODUCTION_READINESS.md         Production checklist
├── .env.example                    Environment template
├── .env.sample                     Environment sample
├── .gitignore                      Git exclusions
├── .dockerignore                   Docker exclusions
└── app.db                          SQLite database (dev, git-ignored)
```

### 6.2 Blueprints (Feature Modules)

```
auth/
└── routes.py                       [~300 lines] Login, password, user mgmt

jobs/
└── routes.py                       [1,658 lines] Job lifecycle, dashboard, reporting
    - Routes: /dashboard, /jobs/*, /kpi, /reports/*

survey/
└── routes.py                       [651 lines] Survey form, measurements
    - Routes: /jobs/<id>/survey, /jobs/<id>/pre_survey

parts/
└── routes.py                       [813 lines] BOM editor, procurement
    - Routes: /jobs/<id>/parts, /jobs/<id>/parts/procurement

stores/
└── routes.py                       [747 lines] Inventory, pick lists
    - Routes: /stores/*, /stores/picklists/*

costing/
└── routes.py                       [732 lines] Costing sheet, Excel upload
    - Routes: /jobs/<id>/costing, /admin/templates/<id>/costing/catalogue

epicor/
├── routes.py                       [minimal] ERP endpoints
├── baq_queries.py                  BAQ query definitions
└── rest_client.py                  REST API client

illustrations/
└── routes.py                       [~400 lines] Illustration wizard
    - Routes: /illustrations/*, /admin/illustrations/*
```

### 6.3 Services (Business Logic)

```
services/
├── __init__.py
├── bom.py                          [~250 lines] BOM generation, kit suppression
├── bom_services.py                 [~200 lines] Supersedes, bundle logic
├── costing.py                      [~350 lines] Costing calculations, Excel parsing
├── epicor.py                       [~150 lines] ERP integration
├── file_utils.py                   [~180 lines] Upload handling, validation
├── job_pack_export.py              [~200 lines] ZIP export with metadata
├── job_pack_report.py              [~300 lines] Report context building
├── job_pack_revision.py            [~100 lines] Report versioning
├── job_services.py                 [~320 lines] Job lifecycle, status changes
├── measurement_service.py          [~220 lines] Measurement validation, conversion
├── pdf_import.py                   [~150 lines] PDF parsing (in development)
├── pdf_renderer.py                 [~180 lines] PDF generation (WeasyPrint)
└── seed_data.py                    [~400 lines] Test data generation
```

### 6.4 Templates (Jinja2 HTML)

```
templates/                          [56 files, ~2MB total]
├── base.html                       Master layout with nav, flash messages
├── dashboard.html                  [~15KB] Job listing, KPI cards
├── login.html                      Login form
├── create_job.html                 Job creation form
├── job_pre_survey.html             Pre-survey checkpoint
├── job_survey.html                 [66KB] Large survey form with sections
├── job_pack.html                   Job pack editor
├── parts.html                      [53KB] BOM table editor
├── parts_procurement.html          Procurement tracking sheet
├── costing_sheet.html              [~12KB] Costing UI
├── stores.html                     [32KB] Inventory management
├── pick_list.html                  Pick list detail
├── template_wizard.html            [30KB] Multi-step template builder
├── system_status.html              System health dashboard
├── kpi_dashboard.html              KPI metrics
├── _macros/                        [45+ macro files]
│   ├── _attachment_macros.html    Upload/download UI
│   ├── _template_editor_form.html Template item editor
│   ├── _picklist_macros.html      Pick list rows
│   ├── _stores_macros.html        Stock tables
│   ├── _job_meta_card.html        Job header card
│   ├── _export_macros.html        Export buttons
│   └── ... (39 more macros)
└── reports/
    └── job_pack_report.html        PDF report layout
```

### 6.5 Static Assets

```
static/                             [~976KB total]
├── style.css                       [79KB] Main stylesheet
├── components.css                  [~12KB] Component library
├── mobile.css                      [~8KB] Mobile responsive (375px+)
├── tablet.css                      [~6KB] Tablet responsive (768px+)
├── theme.css                       [~4KB] Color scheme
├── css/
│   └── report.css                  [~5KB] PDF-specific styling
├── logo.png                        [~50KB] Application logo
├── IMG_5640.jpg                    [~800KB] Sample image
└── (other images, icons)
```

### 6.6 Database Migrations

```
migrations/
├── alembic.ini                     Alembic configuration
├── env.py                          Migration environment
├── script.py.mako                  Migration template
└── versions/                       [21 migration files]
    ├── cb31edff9cc9_initial.py                         Initial schema
    ├── 462e693b8825_add_surveyitem_torque_fields.py   Add torque tracking
    ├── ca2e176c395f_add_machining_decision.py         Add machining option
    ├── 1a2b3c4d5e6f_picklist_state.py                 Add picklist workflow
    ├── 8a1b2c3d4e5f_job_indexes.py                    Performance indexes
    ├── aa7c9b1d2e3f_add_attachment_file_hash.py       Deduplication
    ├── 7a002b9dbc0e_add_job_pack_and_nc.py            Job pack ID
    ├── fe8d2c9a3b11_fix_missing_report_revision.py    Versioning fix
    ├── merge_*.py                                      Merge migrations
    ├── 6f2c1a0b9d7e_add_templateitem_assembly.py      Assembly fields
    ├── 9e0f1a2b3c4d_add_template_canonical.py         Canonical parts
    ├── cc_epicor_settings.py                          ERP config
    ├── af25d3f4c9ab_add_force_password_reset.py       Password policy
    ├── ee4d7c2a9b10_add_versions_indexes.py           Version indexes
    ├── 8c9d0e1f2a3b_add_illustrations.py              Illustration system
    ├── zz_add_supersedes_template_item.py             Supersedes logic
    └── a1b2c3d4e5f6_hard_multitenancy_org_slug.py     Multitenancy
```

### 6.7 Testing

```
tests/                              [26 test files, ~5000 lines total]
├── conftest.py                     Shared fixtures (app, db, users)
├── test_auth.py                    Authentication tests
├── test_job_flow.py                End-to-end job workflow
├── test_measurements.py            Measurement validation tests
├── test_bom.py                     BOM generation tests
├── test_costing.py                 Costing calculations tests
├── test_survey.py                  Survey form tests
├── test_permissions.py             Role-based access tests
├── test_templates.py               Template CRUD tests
├── test_stores.py                  Inventory tests
├── test_file_upload.py             Upload validation tests
├── test_pdf_export.py              PDF generation tests
├── test_api_endpoints.py           Route tests
├── test_models.py                  Model relationship tests
├── security_test.py                [moved to tests/] Penetration tests
├── stress_test.py                  [moved to tests/] Load tests (250+ jobs)
└── ... (11 more test modules)

e2e/                                Playwright E2E tests
└── tests/
    ├── test_job_creation.py        Full job creation flow
    ├── test_survey_workflow.py     Survey completion flow
    ├── test_login.py               Authentication flow
    └── ... (4 more E2E tests)
```

### 6.8 Deployment & Operations

```
deploy/
├── docker-compose.yml              Multi-container setup
├── gunicorn_config.py              Gunicorn WSGI config
├── systemd_reman.service           Systemd service file
└── ... (2 more deploy files)

scripts/                            [~25 operational scripts]
├── run_dev.sh                      Development server
├── run_prod.sh                     Production server (gunicorn)
├── backup_sqlite.py                Database backup
├── restore_sqlite.py               Database restore
├── upgrade_legacy_db.py            Migration helper
├── admin_reset_password.py         Password reset utility
├── check_pdf_extractor.sh          PDF extractor health check
└── ... (18 more scripts)

dev_tools/                          Development utilities
load/                               Load testing tools
docs/                               Documentation
logs/                               Log directory (git-ignored)
uploads/                            User uploads (git-ignored)
instance/                           Instance folder (git-ignored)
```

### 6.9 New: PDF Parts Extractor

```
pdf-parts-extractor/                [In development - see summary context]
├── setup.py                        Package installation
├── README.md                       Package documentation
├── profiles/                       Manufacturer-specific profiles
│   ├── caterpillar.json           CAT parts catalog format
│   ├── man.json                   MAN diesel format
│   ├── steyr.json                 Steyr Motors format
│   └── kubota.json                Kubota bilingual format
└── pdf_parts_extractor/
    ├── __init__.py
    ├── profiles.py                 [152 lines] Profile discovery, auto-detect
    ├── section_detector.py         [181 lines] Section header detection
    ├── image_extractor.py          [250 lines] Section image extraction
    ├── table_parser.py             [260 lines] Parts table parsing
    └── extract.py                  [pending] Main entry point
```

---

## 7. UI/UX Patterns

### 7.1 Frontend Architecture

**Server-Side Rendering**:
- No SPA framework (React/Vue/Angular)
- Jinja2 templates generate HTML on server
- Full page reloads on navigation
- Progressive enhancement approach

**JavaScript Approach**:
- Vanilla JavaScript (no external libraries)
- Inline event handlers in templates
- No bundler (webpack/vite)
- Minimal client-side logic

**CSS Strategy**:
- Plain CSS (no preprocessors)
- Component-based organization
- Mobile-first responsive design
- CSS Grid and Flexbox for layouts

### 7.2 Component Library

**Key UI Components**:

1. **Job Meta Card** (`_job_meta_card.html`)
   - Displays: Job number, customer, engine type, status
   - Colored status badge
   - Assigned technician
   - Actions menu (view, edit, export)

2. **Status Steps** (inline in templates)
   - Visual workflow: pre_survey → survey → office → build → complete
   - Current step highlighted
   - Completed steps checked
   - Click to jump to phase (if permitted)

3. **Attachment Manager** (`_attachment_macros.html`)
   - Drag-and-drop upload zone
   - File type validation (client-side)
   - Thumbnail previews
   - Download/delete actions

4. **Measurement Input** (inline in `job_survey.html`)
   - Input field with unit dropdown
   - Min/Max spec display
   - Real-time validation indicator (green/red)
   - Audit icon (click to view change history)

5. **Pick List Row** (`_picklist_macros.html`)
   - Part info (part_no, name)
   - Bin location (clickable)
   - Quantity required vs. issued
   - Checkbox for picked status

6. **Stock Table** (`_stores_macros.html`)
   - Part catalog with stock levels
   - Color-coded: green (in stock), yellow (low), red (out)
   - Barcode display
   - Quick-edit qty

### 7.3 Navigation Patterns

**Top Navigation Bar**:
```
[Logo] RemanAssist    [Search Box]    [User: John Doe ▼] [Logout]
                                      Role: Office
```

**Sidebar** (context-dependent):
```
Job JOB-2024-001
━━━━━━━━━━━━━━━━━━━━
✓ Pre-Survey
✓ Survey
→ Office
  Build
  Complete
━━━━━━━━━━━━━━━━━━━━
[View Survey]
[Edit BOM]
[Costing Sheet]
[Export Report]
```

**Breadcrumbs**:
```
Dashboard > Jobs > JOB-2024-001 > Survey
```

### 7.4 Responsive Breakpoints

**Mobile** (`mobile.css`): 375px - 767px
- Single column layout
- Collapsed navigation (hamburger menu)
- Stacked forms
- Touch-friendly buttons (min 44px height)

**Tablet** (`tablet.css`): 768px - 1023px
- Two column layout
- Sidebar navigation
- Grid tables

**Desktop** (`style.css`): 1024px+
- Three column layout (sidebar, main, details)
- Full tables with all columns
- Hover states

### 7.5 Forms

**Form Structure**:
```html
<form method="POST" action="/jobs/123/survey">
  {{ csrf_token }}  <!-- CSRF protection -->

  <fieldset>
    <legend>Section: TA0101 - Cylinderblock</legend>

    <!-- Table of items -->
    <table>
      <thead>
        <tr><th>Pos</th><th>Part No</th><th>Name</th>...</tr>
      </thead>
      <tbody>
        {% for item in items %}
        <tr>
          <td>{{ item.pos }}</td>
          <td>{{ item.part_no }}</td>
          <td>{{ item.name }}</td>
          <td>
            <select name="decision_{{ item.id }}">
              <option value="reuse">Reuse</option>
              <option value="replace">Replace</option>
              ...
            </select>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </fieldset>

  <button type="submit">Save Survey</button>
</form>
```

**Form Validation**:
- Server-side validation (primary)
- Flash messages for errors (red banner)
- Success messages (green banner)
- Field-level error messages (inline)
- Client-side validation (optional, HTML5 attributes)

**Large Form Handling**:
- Custom `LargeFormRequest` class (in `app.py`)
- Supports up to 50MB POST data
- Handles 500+ survey items per form

### 7.6 Main Screens/Views

**Dashboard** (`dashboard.html`):
- Role-specific job list
- KPI cards (total jobs, jobs in progress, completed this month)
- Filters: Status, assigned technician, date range
- Search box (job number, customer name)
- Pagination (25 per page)

**Job Survey** (`job_survey.html`):
- Large form (66KB template)
- Sections accordion (expandable/collapsible)
- Inline measurement inputs
- Attachment upload per section
- Autosave (optional, not implemented in current version)

**BOM Editor** (`parts.html`):
- Editable table (53KB template)
- Add/remove rows
- Stock status dropdown per row
- Bulk actions (approve all, export)
- Real-time total calculation

**Costing Sheet** (`costing_sheet.html`):
- Two-panel layout (BOM vs. Excel upload)
- Match status indicators (color-coded)
- Cost calculation summary
- Procurement status tracking

**Stores Dashboard** (`stores.html`):
- Stock table with filters (32KB template)
- Pick list queue
- Low stock alerts (red highlight)
- Barcode scanner integration (optional)

### 7.7 State Management

**No Client-Side State**:
- All state stored on server (database)
- Forms are stateless (each submit is independent)
- Flash messages stored in session (Flask flash())

**Session Storage**:
- `current_user` (Flask-Login)
- Flash messages (errors, success)
- CSRF tokens (Flask-WTF)

**No Local Storage** (browser):
- No client-side caching
- No offline mode (requires server connection)

---

## 8. API Design

### 8.1 No RESTful API

**Important**: RemanAssist does NOT have a separate RESTful JSON API.

- All endpoints return HTML (Jinja2 templates)
- No `/api/*` routes
- Form submissions use POST with redirects
- Some AJAX endpoints return JSON (limited)

### 8.2 Route Inventory

**Jobs Blueprint** (`/jobs/*`):

| Method | Route | Purpose | Returns |
|--------|-------|---------|---------|
| GET | `/dashboard` | Main dashboard | HTML |
| GET | `/jobs` | Job list | HTML |
| GET | `/jobs/create` | Job creation form | HTML |
| POST | `/jobs/create` | Create job | Redirect |
| GET | `/jobs/<id>` | Job detail | HTML |
| GET | `/jobs/<id>/pre_survey` | Pre-survey form | HTML |
| POST | `/jobs/<id>/pre_survey` | Submit pre-survey | Redirect |
| GET | `/jobs/<id>/pack` | Job pack editor | HTML |
| POST | `/jobs/<id>/bom/regenerate` | Regenerate BOM | Redirect |
| GET | `/jobs/<id>/report` | HTML report | HTML |
| GET | `/jobs/<id>/report.pdf` | PDF report | PDF file |
| GET | `/jobs/<id>/export.zip` | ZIP export | ZIP file |
| GET | `/jobs/<id>/build` | Build phase UI | HTML |
| GET | `/jobs/<id>/attachments` | Attachments manager | HTML |
| POST | `/jobs/<id>/release` | Release/approve job | Redirect |
| GET | `/reports/job_flow` | Job flow report | HTML |
| GET | `/reports/job_flow.csv` | Export CSV | CSV file |
| GET | `/kpi` | KPI dashboard | HTML |
| GET | `/admin/system` | System status | HTML |

**Survey Blueprint** (`/survey/*`):

| Method | Route | Purpose | Returns |
|--------|-------|---------|---------|
| POST | `/jobs/<id>/survey/seed` | Populate from template | Redirect |
| GET | `/jobs/<id>/survey` | Survey form | HTML |
| POST | `/jobs/<id>/survey` | Submit survey | Redirect |

**Parts Blueprint** (`/parts/*`):

| Method | Route | Purpose | Returns |
|--------|-------|---------|---------|
| GET | `/jobs/<id>/parts` | BOM editor | HTML |
| POST | `/jobs/<id>/parts` | Update BOM | Redirect |
| GET | `/jobs/<id>/parts/procurement` | Procurement sheet | HTML |
| POST | `/jobs/<id>/parts/procurement` | Update procurement | Redirect |
| GET | `/jobs/<id>/parts/export` | Export parts list | CSV file |

**Stores Blueprint** (`/stores/*`):

| Method | Route | Purpose | Returns |
|--------|-------|---------|---------|
| GET | `/stores` | Stores dashboard | HTML |
| GET | `/stores/template/<id>` | Stock for template | HTML |
| POST | `/stores/template/<id>` | Update stock | Redirect |
| POST | `/admin/stores/update` | Update stock (admin) | Redirect |
| POST | `/stores/barcodes/update` | Update barcodes | Redirect |
| POST | `/stores/barcodes/import` | Bulk import barcodes | Redirect |
| GET | `/stores/picklists/<id>` | Pick list detail | HTML |
| POST | `/stores/picklists/<id>/status` | Change picklist status | Redirect |

**Costing Blueprint** (`/costing/*`):

| Method | Route | Purpose | Returns |
|--------|-------|---------|---------|
| GET | `/jobs/<id>/costing` | Costing sheet | HTML |
| POST | `/jobs/<id>/costing` | Update costing | Redirect |
| POST | `/jobs/<id>/costing/upload` | Upload Excel | Redirect |
| POST | `/jobs/<id>/costing/use_upload` | Apply Excel upload | Redirect |
| GET | `/jobs/<id>/costing/uploads/<id>` | View upload | HTML |
| GET | `/jobs/<id>/costing.json` | Export JSON | JSON file |
| POST | `/jobs/<id>/costing/bind` | Bind BOM to costing | Redirect |
| GET | `/jobs/<id>/costing/export` | Export costing | XLSX file |
| GET | `/jobs/<id>/costing/export_dmt` | Export DMT format | CSV file |
| GET | `/admin/templates/<id>/costing/catalogue` | Costing template editor | HTML |

**Auth Blueprint** (`/auth/*`):

| Method | Route | Purpose | Returns |
|--------|-------|---------|---------|
| GET | `/auth/login` | Login form | HTML |
| POST | `/auth/login` | Login submit | Redirect |
| GET | `/auth/logout` | Logout | Redirect |
| GET | `/auth/change_password` | Password change form | HTML |
| POST | `/auth/change_password` | Submit password change | Redirect |
| GET | `/admin/users` | User list | HTML |
| POST | `/admin/users/create` | Create user | Redirect |
| POST | `/admin/users/<id>/delete` | Delete user | Redirect |

### 8.3 Request/Response Patterns

**Standard GET Request**:
```
Request:
  GET /jobs/123 HTTP/1.1
  Cookie: session=abc123

Response:
  200 OK
  Content-Type: text/html
  <html>...</html>
```

**Standard POST Request** (form submission):
```
Request:
  POST /jobs/123/survey HTTP/1.1
  Content-Type: application/x-www-form-urlencoded
  Cookie: session=abc123

  csrf_token=xyz789&decision_1=replace&decision_2=reuse&...

Response:
  302 Found
  Location: /jobs/123?message=Survey+saved
```

**AJAX Request** (rare):
```
Request:
  GET /jobs/123/parts/status-summary HTTP/1.1
  X-Requested-With: XMLHttpRequest
  Cookie: session=abc123

Response:
  200 OK
  Content-Type: application/json

  {
    "total_parts": 45,
    "in_stock": 30,
    "to_order": 15
  }
```

### 8.4 Authentication Approach

**Session-Based**:
- Flask-Login manages sessions
- Session cookie (`session=...`)
- No JWT tokens in headers (except for optional Epicor integration)

**No API Keys**:
- No API key authentication
- No OAuth (except optional Epicor integration)

**CSRF Protection**:
- All POST/PUT/DELETE require CSRF token
- Token embedded in forms (`{{ csrf_token }}`)
- Validated on submission (Flask-WTF)

---

## 9. Key Insights

### 9.1 What Works Really Well

1. **Clear Separation of Concerns**
   - Services layer isolates complex business logic from route handlers
   - Models are pure data structures (no business logic)
   - Easy to test and maintain

2. **Comprehensive Multitenancy**
   - Hard org-scoping prevents cross-tenant data leaks
   - `get_org_filter()` applied consistently across all queries
   - Production-ready for SaaS deployment

3. **Audit Trail Excellence**
   - Three-tier logging: AuditLog, JobLog, MeasurementAuditLog
   - Every critical action tracked with user/timestamp
   - Regulatory compliance potential (ISO, etc.)

4. **Idempotent BOM Generation**
   - Can regenerate BOM multiple times safely
   - Always clears and rebuilds from scratch
   - No stale data issues

5. **Sophisticated Product Structure Logic**
   - Kit suppression handles complex product relationships
   - Supersedes rules enable flexible product substitution
   - Bundles handle component kits elegantly

6. **Role-Based Access Control**
   - Fine-grained permissions (4 roles)
   - Job-level access control
   - Organization-scoped queries

7. **Production-Ready Configuration**
   - Separate dev/test/prod configs
   - Environment variable management (.env)
   - Security best practices (CSRF, bcrypt, rate-limiting)

8. **Comprehensive Testing**
   - Unit tests (pytest)
   - E2E tests (Playwright)
   - Load tests (250+ concurrent jobs)
   - Security tests (penetration testing)

9. **Measurement Validation System**
   - Unit conversion (mm ↔ inches, Nm ↔ lb-ft)
   - Clearance ceiling checks (prevents data entry errors)
   - Audit trail on every change
   - Real-time spec comparison

10. **Large Form Handling**
    - Custom `LargeFormRequest` class supports 50MB+ forms
    - 500-item survey capacity
    - Deduplication prevents duplicate attachments

### 9.2 Complexity Hotspots

1. **Job Survey Form** (`job_survey.html` - 66KB)
   - Massive template with complex state management
   - 500+ items, each with measurements, torque, attachments
   - Performance issues on large templates (DOM size)

2. **BOM Generation Logic** (`services/bom.py`)
   - Kit suppression algorithm is intricate
   - Supersedes rules add complexity
   - Difficult to debug when rules conflict

3. **Costing Sheet** (`costing/routes.py`)
   - Excel upload parsing is brittle
   - Template binding logic complex
   - Cost calculation spread across multiple functions

4. **Template Wizard** (`template_wizard.html` - 30KB)
   - Multi-step wizard with JSON state tracking
   - Complex validation across steps
   - User can get stuck if steps out of order

5. **Epicor Integration** (`epicor/`)
   - REST client + BAQ queries incomplete
   - Authentication handling complex (API key vs. OAuth)
   - Error handling insufficient

6. **Illustration System** (`illustrations/`)
   - Interactive hotspots require manual coordinate entry
   - Position labels need normalization (x_norm, y_norm)
   - Part mapping is manual and error-prone

7. **Report Rendering** (`services/pdf_renderer.py`)
   - WeasyPrint vs. Playwright fallback logic
   - Image embedding limits (memory issues)
   - Page break handling unreliable

8. **Measurement Audit Trail** (`measurement_audit_logs`)
   - Tracking changes across multiple fields is complex
   - Querying audit history requires joins
   - No diff view UI (planned)

### 9.3 What's Messy or Needs Improvement

**Critical**:
1. **N+1 Query Issues**
   - Dashboard loads jobs without eager loading (templates, users)
   - Survey form loads items without relationships (measurements, torque)
   - Fix: Use `selectinload()` or `joinedload()`

2. **Background Task Queue Missing**
   - PDF/ZIP generation blocks HTTP request
   - Excel parsing can timeout on large files
   - Fix: Celery or RQ for async tasks

3. **State Machine Validation**
   - Job status transitions not strictly enforced
   - Can manually set status without checks
   - Fix: Implement explicit state machine

**High**:
1. **Full-Text Search**
   - Job search is basic SQL LIKE (slow on large datasets)
   - No indexing on text fields
   - Fix: Elasticsearch or PostgreSQL full-text search

2. **API Layer Missing**
   - No RESTful API (mobile app potential blocked)
   - All logic tied to HTML templates
   - Fix: Build `/api/*` endpoints with JSON responses

3. **Pagination Missing**
   - Lists >100 rows cause performance issues
   - All jobs loaded on dashboard (memory heavy)
   - Fix: Add pagination (25 per page)

4. **Conditional App Setup**
   - Some initialization logic in route handlers
   - Should be in `create_app()` factory
   - Fix: Move to app factory

**Medium**:
1. **Illustration Editor**
   - No WYSIWYG tool (manual coordinate entry)
   - Error-prone and time-consuming
   - Fix: Build visual editor (drag-and-drop hotspots)

2. **Mobile UX**
   - Responsive CSS exists but not optimized
   - Forms too large for mobile screens
   - Fix: Mobile-first redesign

3. **Offline Mode**
   - Technicians need connectivity for survey
   - Fix: Service worker for offline caching

4. **Notification System**
   - No email/SMS on status changes
   - Manual polling required
   - Fix: Email integration (SendGrid, SES)

**Low**:
1. **Dark Mode**
   - Only light theme exists
   - Fix: CSS variables for theming

2. **Accessibility**
   - No WCAG compliance testing
   - Fix: Accessibility audit

3. **Internationalization**
   - Localization module exists but not fully used
   - Fix: Full i18n for UI strings

### 9.4 Most Complex Part

**BOM Generation with Kit Suppression + Supersedes**

This is the most algorithmically complex part of the system:

1. Iterate survey items, filter by decision
2. Create candidate PartRequirement rows
3. Group by kit_name
4. For each kit, check if kit_master is REPLACE
   - If yes: suppress all kit members, keep only kit_master
   - If no: keep all individual kit members
5. Apply supersedes rules (replace component SKUs with kit SKU)
6. Deduplicate (same part in multiple sections)
7. Commit to database

**Why Complex**:
- Multiple conditional branches
- JSON-based supersedes rules (flexible but hard to validate)
- Kit suppression is recursive (kits can contain kits)
- Difficult to debug when rules conflict
- No visual representation of logic

**Most Clever Solution**:

**File Hash Deduplication** (`attachments.file_hash`)

Simple but elegant:
- SHA-256 hash calculated on upload
- Unique constraint: `(job_id, file_hash)`
- Database enforces deduplication
- User uploads same file twice → second upload rejected (friendly message)
- Saves storage space
- No manual tracking required

### 9.5 Performance Considerations

**SQLite Bottleneck**:
- Current database: ~7GB (production data imported)
- SQLite is single-threaded (write lock blocks reads)
- Production should use PostgreSQL

**Report Rendering Slow**:
- WeasyPrint can take 10-30 seconds for 50-page reports
- Blocking HTTP request (user waits)
- Fix: Background job queue + polling UI

**Large Survey Form**:
- 500-item survey = 66KB HTML + 2-3MB POST data
- DOM rendering slow in browser
- Fix: Pagination or infinite scroll

**Query N+1**:
- Dashboard loads 100 jobs + 100 queries for templates + 100 queries for users
- Fix: Eager loading with `selectinload()`

**CSV/Excel Exports**:
- In-memory construction (memory-heavy for 10k+ rows)
- Fix: Streaming exports (yield rows)

---

## 10. Motor-Specific Elements

### 10.1 Motor Remanufacturing Domain

**Core Concept**: Disassemble engine → Inspect all parts → Replace worn parts → Reassemble

**Workflow**:
1. Engine arrives from customer
2. Technician disassembles engine
3. For each part: Inspect, measure, decide (reuse/replace/scrap)
4. Office procures replacement parts
5. Technician reassembles engine with new/reused parts
6. Test engine, deliver to customer

### 10.2 Motor-Specific Terminology

**Engine Type**: Model/series of engine (e.g., "MAN D0836 LE", "CAT 3512", "Kubota V3800")

**Section Codes**:
- `TA` prefix: Turbocharger assembly
- `MAN` prefix: Manifold assembly
- `CYL` prefix: Cylinder block
- `CRK` prefix: Crankshaft assembly
- `PIS` prefix: Pistons & connecting rods

**Big Ticket Items**: High-value components (cylinder block, crankshaft, turbocharger)
- Require special attention
- Often sent for external machining
- Cost >$1000 each

**Kit Components**: Parts sold as a set (gasket kits, bearing sets, seal kits)
- Cheaper to buy as kit than individually
- Kit suppression logic prevents ordering duplicates

**Measurements** (motor-specific):
- Big-end bearing clearance (mm or inches)
- Crankshaft journal diameter (mm)
- Cylinder bore diameter (mm)
- Piston ring gap (mm)
- Valve seat width (mm)

**Torque Specifications**:
- Main bearing cap bolts (Nm or lb-ft)
- Connecting rod bolts (Nm)
- Cylinder head bolts (Nm, sequence matters)

**Decisions**:
- **Reuse**: Part within spec, no visible wear
- **Replace**: Part worn beyond spec
- **Scrap**: Part damaged, cannot be reused
- **Machining**: Part can be machined to restore spec (cylinder rebore, crankshaft grind)
- **Inspect**: Requires further inspection (NDT, magnaflux)

### 10.3 What Would Change for Different Industry

**If RemanAssist were adapted for, say, transmission remanufacturing**:

**Same (generic)**:
- Job/project management
- User authentication & roles
- File upload/storage
- Audit trail
- BOM generation (conceptually)
- Costing calculations

**Different (motor-specific)**:
1. **Terminology**:
   - "Engine" → "Transmission"
   - "Section codes" (TA, CYL, etc.) → Industry-specific codes
   - "Big-end bearing clearance" → Transmission-specific measurements

2. **Measurement Specs**:
   - Motor: Clearances, diameters, torque
   - Transmission: Clutch pack clearance, gear backlash, shaft runout

3. **Template Structure**:
   - Motor: Sections = engine assemblies (turbo, crankshaft, etc.)
   - Transmission: Sections = gear sets, clutch packs, valve bodies

4. **Product Logic**:
   - Kit suppression might work differently
   - Supersedes rules would be industry-specific

5. **Illustrations**:
   - Motor: Exploded engine diagrams
   - Transmission: Exploded transmission diagrams

6. **Pre-Survey**:
   - Motor: "Is serial number visible?", "Turbo present?"
   - Transmission: "Gear ratio?", "Torque converter included?"

**Abstraction Potential**:
With moderate refactoring, RemanAssist could become a generic remanufacturing platform:
- Move terminology to config/database (not hardcoded)
- Template-based measurement specs (already done!)
- Configurable section codes
- Industry-specific pre-survey schemas (JSON, already done!)
- Generic "assembly" → "sub-assembly" → "part" hierarchy

**Estimated Effort**: 2-3 months to genericize for any remanufacturing industry

---

## Conclusion

RemanAssist is a **mature, production-ready monolithic Flask application** for motor remanufacturing management. It demonstrates:

- **Strong architecture**: Clear separation (blueprints, services, models)
- **Complex business logic**: Kit suppression, supersedes, measurement validation
- **Multitenancy**: Hard org-scoping for SaaS deployment
- **Comprehensive audit**: Full traceability of decisions and changes
- **Production-ready**: Migrations, testing, security, rate-limiting

**Strengths**:
- Well-structured codebase (services layer)
- Sophisticated product logic (kits, supersedes)
- Role-based access control
- Comprehensive testing

**Areas for Improvement**:
- N+1 queries (performance)
- Background task queue (async processing)
- RESTful API (mobile app potential)
- Mobile UX optimization

**Motor-Specific**: The application is deeply rooted in motor remanufacturing terminology and workflows, but with moderate refactoring could be genericized for any remanufacturing industry (transmissions, pumps, gearboxes, etc.).

---

**End of Architectural Review**
