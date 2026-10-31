# InspectForge - Technical Specification
## Digital Inspection & Job Pack Platform for Industrial Equipment Overhaul

**Version:** 1.0
**Date:** February 2026
**Industry:** Industrial Equipment Overhaul & Repair
**Target Market:** Pump shops, compressor rebuilders, hydraulic repair, gearbox specialists

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Requirements Document](#2-requirements-document)
3. [Database Schema Design](#3-database-schema-design)
4. [API Endpoint Specifications](#4-api-endpoint-specifications)
5. [Component Architecture](#5-component-architecture)
6. [Recommended Tech Stack](#6-recommended-tech-stack)
7. [Feature Specifications](#7-feature-specifications)
8. [Implementation Phases](#8-implementation-phases)
9. [Terminology Translation](#9-terminology-translation)
10. [Differentiation Notes](#10-differentiation-notes)

---

## 1. Product Overview

### 1.1 Target Market

**Primary Market**: Industrial equipment overhaul and repair facilities specializing in:
- Centrifugal and positive displacement pumps
- Reciprocating and rotary compressors
- Hydraulic cylinders and systems
- Industrial gearboxes and reducers
- Turbines and blowers
- Mixers and agitators

**Company Size**: 5-100 employees, processing 50-500 jobs annually

**Current Pain Points**:
- Paper-based inspection forms scattered across shop floor
- Inconsistent inspection criteria between technicians
- Manual BOM compilation from handwritten notes
- No standardized work instructions per equipment type
- Quote preparation takes days (manual spreadsheet compilation)
- Lost institutional knowledge when experienced technicians leave
- No digital record of "as-found" vs. "as-built" condition

### 1.2 Core Value Proposition

**InspectForge transforms equipment overhaul shops from paper-based chaos to digital precision.**

**Key Benefits**:
1. **Standardized Inspections**: Digital checklists tailored to equipment type (pump, compressor, gearbox)
2. **Instant BOMs**: Auto-generate parts lists from inspection decisions
3. **Fast Quoting**: Real-time cost calculations as parts are selected
4. **Knowledge Preservation**: Templates capture best practices for each equipment model
5. **Quality Proof**: Complete digital job pack (photos, measurements, test results) for customer
6. **Efficiency Gains**: 60% faster inspection documentation, 80% faster quote generation

**Competitive Advantage**:
- Equipment-agnostic (not locked to one industry)
- Template library grows with your experience
- Mobile-friendly (technicians on shop floor with tablets)
- Modern SaaS pricing (no upfront investment)

### 1.3 Key Differences from Motor-Focused Approach

**RemanAssist** (motor remanufacturing) vs. **InspectForge** (equipment overhaul):

| Aspect | RemanAssist (Motors) | InspectForge (Equipment) |
|--------|---------------------|--------------------------|
| **Scope** | Diesel/gas engines only | Any industrial equipment |
| **Structure** | Fixed sections (crankshaft, pistons, etc.) | Flexible assemblies per equipment type |
| **Terminology** | Engine-specific (clearances, torque) | Equipment-neutral (component, assembly) |
| **Templates** | Engine models (CAT 3512, MAN D0836) | Equipment types + models |
| **Measurements** | Heavy focus (bore, clearance, torque) | Optional, equipment-dependent |
| **Testing** | Compression test, leak-down | Equipment-specific (pump performance, pressure test) |
| **Complexity** | High (500+ parts per engine) | Variable (20-200 parts per job) |
| **Customer** | Motor remanufacturers only | Broad equipment repair market |

**Why This is a Separate Product**:
- Different buyer personas (equipment shop vs. motor shop)
- Different terminology prevents market confusion
- Broader market opportunity (equipment repair > motor reman)
- Simpler MVP (less complex than motor-specific logic)
- Easier to sell/demonstrate (generic concepts)

---

## 2. Requirements Document

### 2.1 User Roles and Permissions

**Role Hierarchy**:

| Role | Capabilities | Typical User |
|------|--------------|--------------|
| **Technician** | Complete inspections, upload photos, enter test results | Shop floor technician, inspector |
| **Estimator** | Create jobs, build quotes, approve parts lists, generate customer proposals | Sales estimator, service manager |
| **Procurement** | Manage parts sourcing, track POs, update stock levels | Purchasing agent, inventory clerk |
| **Admin** | Manage users, create templates, configure equipment types, system settings | Shop owner, operations manager |

**Permission Matrix**:

| Action | Technician | Estimator | Procurement | Admin |
|--------|-----------|-----------|-------------|-------|
| Create job | ❌ | ✅ | ❌ | ✅ |
| Assign job | ❌ | ✅ | ❌ | ✅ |
| Complete inspection | ✅ (assigned only) | ✅ | ❌ | ✅ |
| Edit BOM | ❌ | ✅ | ❌ | ✅ |
| Create quote | ❌ | ✅ | ❌ | ✅ |
| Approve quote | ❌ | ✅ | ❌ | ✅ |
| Manage procurement | ❌ | ❌ | ✅ | ✅ |
| Create templates | ❌ | ❌ | ❌ | ✅ |
| Manage users | ❌ | ❌ | ❌ | ✅ |

### 2.2 Core User Stories

**Epic 1: Job Management**
- As an **Estimator**, I want to create a new job from a customer request so that we can track work
- As an **Estimator**, I want to assign a job to a technician so they know what to inspect
- As an **Estimator**, I want to see all jobs at a glance so I can track workload
- As an **Admin**, I want to view job history so I can identify repeat customers and equipment

**Epic 2: Inspection Workflow**
- As a **Technician**, I want to select an equipment template so I have a checklist to follow
- As a **Technician**, I want to mark each component as keep/replace/repair so I document findings
- As a **Technician**, I want to upload photos of damage so estimator can review condition
- As a **Technician**, I want to enter measurements and test results so they're captured digitally
- As a **Technician**, I want to submit inspection when complete so estimator can quote

**Epic 3: Quoting & BOM**
- As an **Estimator**, I want to see auto-generated BOM from inspection so I don't manually compile
- As an **Estimator**, I want to add/remove parts so I can adjust the scope
- As an **Estimator**, I want to enter part costs so I can calculate total
- As an **Estimator**, I want to add labor hours so quote includes all costs
- As an **Estimator**, I want to export quote PDF so I can send to customer
- As an **Estimator**, I want to mark quote as approved so job moves to work phase

**Epic 4: Templates & Knowledge Base**
- As an **Admin**, I want to create equipment templates so inspections are standardized
- As an **Admin**, I want to define typical components per equipment type so checklists are pre-populated
- As an **Admin**, I want to clone existing templates so I don't start from scratch
- As an **Admin**, I want to mark templates as "standard" so they appear in quick-create

**Epic 5: Procurement & Parts Tracking**
- As **Procurement**, I want to see all parts needed across jobs so I can bulk order
- As **Procurement**, I want to mark parts as ordered/received so estimators know status
- As **Procurement**, I want to track PO numbers so I can reference orders
- As **Procurement**, I want stock alerts so I know what to reorder

**Epic 6: Reporting & Analytics**
- As an **Estimator**, I want to generate job pack PDF so customer gets complete documentation
- As an **Admin**, I want to see jobs per month so I can track volume
- As an **Admin**, I want to see average quote value so I can measure growth
- As an **Admin**, I want to export data so I can analyze in Excel

### 2.3 Feature Requirements (MVP Only)

**Must Have (MVP)**:
1. User authentication (username/password, roles)
2. Job creation (customer, equipment type, serial number)
3. Job assignment to technician
4. Equipment templates (CRUD)
5. Inspection form (component list, keep/replace decisions)
6. Photo upload (per job, per component)
7. Auto-generated BOM from inspection
8. Manual BOM editing (add/remove parts)
9. Quote calculation (parts + labor)
10. Quote PDF export
11. Job dashboard (list view, filters)
12. Job status workflow (received → inspection → quoting → approved → work → complete)

**Should Have (Post-MVP)**:
- Measurement entry with specs
- Performance test results
- Template marketplace (share templates)
- Customer portal (view job status)
- Inventory management
- Email notifications
- Mobile app (native iOS/Android)
- Barcode scanning

**Could Have (Future)**:
- ERP integration (QuickBooks, SAP)
- Supplier catalogs (auto-pricing)
- Scheduling/calendar
- Time tracking
- Equipment history (all jobs for serial number)
- Predictive failure analysis (ML)

**Won't Have (Out of Scope)**:
- Accounting/invoicing (use QuickBooks)
- CRM (use existing tools)
- Shop floor MES (manufacturing execution)
- 3D CAD viewer

---

## 3. Database Schema Design

### 3.1 Core Tables Overview (18 Tables)

**Organizations & Users**:
- `organizations` - Multi-tenant container
- `users` - User accounts with roles

**Job Management**:
- `jobs` - Master job record
- `job_status_history` - Status change audit trail

**Equipment & Templates**:
- `equipment_types` - Equipment categories (pump, compressor, gearbox)
- `equipment_templates` - Reusable inspection templates
- `template_assemblies` - Assembly groupings within template
- `template_components` - Component checklist within assembly

**Inspection**:
- `inspection_items` - Actual inspection line items per job
- `measurements` - Measurement entries (optional)
- `test_results` - Performance test results (optional)

**Parts & BOM**:
- `bom_items` - Bill of materials (generated + manual)
- `parts_catalog` - Master parts reference

**Quoting**:
- `quotes` - Quote header with totals
- `quote_line_items` - Quote detail (parts + labor)

**Media & Audit**:
- `attachments` - Photos and documents
- `audit_logs` - Action history

**Procurement** (Post-MVP):
- `purchase_orders` - PO tracking

### 3.2 Detailed Schema

#### Organizations & Users

**`organizations`**
```sql
CREATE TABLE organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    subscription_tier VARCHAR(50) DEFAULT 'trial',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**`users`**
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL, -- technician, estimator, procurement, admin
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    is_active BOOLEAN DEFAULT true,
    force_password_reset BOOLEAN DEFAULT false,
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(organization_id, email)
);
```

#### Job Management

**`jobs`**
```sql
CREATE TABLE jobs (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id),
    job_number VARCHAR(50) UNIQUE NOT NULL,

    -- Customer info
    customer_name VARCHAR(255) NOT NULL,
    customer_contact VARCHAR(255),
    customer_po VARCHAR(100),

    -- Equipment info
    equipment_type_id INTEGER REFERENCES equipment_types(id),
    manufacturer VARCHAR(200),
    model VARCHAR(200),
    serial_number VARCHAR(200),
    equipment_tag VARCHAR(100), -- Customer's asset tag

    -- Job workflow
    status VARCHAR(50) NOT NULL DEFAULT 'received',
    -- Status enum: received, inspection, quoting, approved, in_work, testing, complete, on_hold
    assigned_to_id INTEGER REFERENCES users(id),
    created_by_id INTEGER REFERENCES users(id),

    -- Template reference
    template_id INTEGER REFERENCES equipment_templates(id),

    -- Timestamps
    received_date DATE,
    target_completion_date DATE,
    completed_date DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_jobs_org ON jobs(organization_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_assigned ON jobs(assigned_to_id);
```

**`job_status_history`**
```sql
CREATE TABLE job_status_history (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    from_status VARCHAR(50),
    to_status VARCHAR(50) NOT NULL,
    changed_by_id INTEGER REFERENCES users(id),
    changed_at TIMESTAMP DEFAULT NOW(),
    notes TEXT
);
```

#### Equipment & Templates

**`equipment_types`**
```sql
CREATE TABLE equipment_types (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id),
    name VARCHAR(200) NOT NULL, -- "Centrifugal Pump", "Reciprocating Compressor"
    category VARCHAR(100), -- pump, compressor, gearbox, hydraulic, turbine
    icon VARCHAR(50), -- UI icon reference
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(organization_id, name)
);
```

**`equipment_templates`**
```sql
CREATE TABLE equipment_templates (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id),
    name VARCHAR(255) NOT NULL, -- "Goulds 3196 Pump", "Ingersoll Rand Compressor"
    equipment_type_id INTEGER REFERENCES equipment_types(id),
    manufacturer VARCHAR(200),
    model_family VARCHAR(200),
    description TEXT,
    is_locked BOOLEAN DEFAULT false, -- Admin-only edit when locked
    is_standard BOOLEAN DEFAULT false, -- Appears in quick-create
    version INTEGER DEFAULT 1,
    created_by_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(organization_id, name)
);
```

**`template_assemblies`**
```sql
CREATE TABLE template_assemblies (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES equipment_templates(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL, -- "Impeller Assembly", "Bearing Housing"
    assembly_code VARCHAR(50), -- "IMP", "BRG", "SEAL"
    display_order INTEGER DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**`template_components`**
```sql
CREATE TABLE template_components (
    id SERIAL PRIMARY KEY,
    template_id INTEGER REFERENCES equipment_templates(id) ON DELETE CASCADE,
    assembly_id INTEGER REFERENCES template_assemblies(id) ON DELETE SET NULL,

    -- Component identification
    item_number VARCHAR(50), -- Position in assembly (1, 2, 3...)
    part_number VARCHAR(200), -- OEM part number
    description VARCHAR(500) NOT NULL,
    quantity INTEGER DEFAULT 1,

    -- Inspection flags
    is_critical BOOLEAN DEFAULT false, -- High-importance component
    always_replace BOOLEAN DEFAULT false, -- Always replaced (wear item)
    requires_measurement BOOLEAN DEFAULT false,
    requires_testing BOOLEAN DEFAULT false,

    -- Reference data
    specifications TEXT, -- JSON: {"bore": "4.5in", "material": "316SS"}
    notes TEXT,

    created_at TIMESTAMP DEFAULT NOW()
);
```

#### Inspection

**`inspection_items`**
```sql
CREATE TABLE inspection_items (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    template_component_id INTEGER REFERENCES template_components(id),

    -- Component identification (copied from template)
    assembly_name VARCHAR(255),
    item_number VARCHAR(50),
    part_number VARCHAR(200),
    description VARCHAR(500) NOT NULL,
    quantity INTEGER DEFAULT 1,

    -- Inspection findings
    decision VARCHAR(50) NOT NULL DEFAULT 'pending',
    -- Decision enum: keep, replace, repair, upgrade, pending
    condition_rating INTEGER, -- 1-5 scale (1=poor, 5=excellent)
    condition_notes TEXT,

    -- Repair details (if decision=repair)
    repair_description TEXT,
    repair_estimated_hours DECIMAL(5,2),

    -- Flags
    is_critical BOOLEAN DEFAULT false,
    is_resolved BOOLEAN DEFAULT false,

    -- Audit
    inspected_by_id INTEGER REFERENCES users(id),
    inspected_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_inspection_job ON inspection_items(job_id);
CREATE INDEX idx_inspection_decision ON inspection_items(decision);
```

**`measurements`**
```sql
CREATE TABLE measurements (
    id SERIAL PRIMARY KEY,
    inspection_item_id INTEGER REFERENCES inspection_items(id) ON DELETE CASCADE,

    label VARCHAR(200) NOT NULL, -- "Shaft Diameter", "Bearing Clearance"
    value_measured DECIMAL(10,4),
    value_min_spec DECIMAL(10,4),
    value_max_spec DECIMAL(10,4),
    unit VARCHAR(20), -- in, mm, mil, psi, bar
    result VARCHAR(50), -- within_spec, out_of_spec, not_measured

    measured_by_id INTEGER REFERENCES users(id),
    measured_at TIMESTAMP DEFAULT NOW()
);
```

**`test_results`**
```sql
CREATE TABLE test_results (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,

    test_type VARCHAR(100) NOT NULL, -- "Pressure Test", "Flow Test", "Vibration Test"
    test_procedure TEXT,

    -- Results
    pass_fail VARCHAR(20), -- pass, fail, conditional
    measured_value DECIMAL(10,4),
    spec_value DECIMAL(10,4),
    unit VARCHAR(20),

    notes TEXT,
    tested_by_id INTEGER REFERENCES users(id),
    tested_at TIMESTAMP DEFAULT NOW()
);
```

#### Parts & BOM

**`parts_catalog`**
```sql
CREATE TABLE parts_catalog (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id),

    part_number VARCHAR(200) UNIQUE NOT NULL,
    description VARCHAR(500),
    manufacturer VARCHAR(200),
    supplier VARCHAR(200),
    unit_cost DECIMAL(10,2),
    unit_of_measure VARCHAR(20), -- ea, ft, lb, gal

    -- Categorization
    category VARCHAR(100), -- bearing, seal, gasket, fastener
    is_stocked BOOLEAN DEFAULT false,
    stock_quantity INTEGER DEFAULT 0,

    last_cost_update TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**`bom_items`**
```sql
CREATE TABLE bom_items (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    inspection_item_id INTEGER REFERENCES inspection_items(id) ON DELETE SET NULL,

    -- Part identification
    part_number VARCHAR(200),
    description VARCHAR(500) NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_of_measure VARCHAR(20),

    -- Source
    source VARCHAR(50), -- auto_generated, manual_add

    -- Procurement
    supplier VARCHAR(200),
    unit_cost DECIMAL(10,2),
    total_cost DECIMAL(10,2), -- quantity × unit_cost

    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_bom_job ON bom_items(job_id);
```

#### Quoting

**`quotes`**
```sql
CREATE TABLE quotes (
    id SERIAL PRIMARY KEY,
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,

    quote_number VARCHAR(50) UNIQUE NOT NULL,
    version INTEGER DEFAULT 1, -- Quote revision

    -- Totals
    parts_total DECIMAL(10,2) DEFAULT 0,
    labor_hours DECIMAL(6,2) DEFAULT 0,
    labor_rate DECIMAL(6,2) DEFAULT 0,
    labor_total DECIMAL(10,2) DEFAULT 0,
    markup_percent DECIMAL(5,2) DEFAULT 0,
    markup_amount DECIMAL(10,2) DEFAULT 0,
    quote_total DECIMAL(10,2) DEFAULT 0,

    -- Status
    status VARCHAR(50) DEFAULT 'draft', -- draft, sent, approved, rejected

    -- Validity
    valid_until DATE,

    -- Approval
    approved_by_id INTEGER REFERENCES users(id),
    approved_at TIMESTAMP,

    -- Customer communication
    sent_to_customer_at TIMESTAMP,
    customer_response_at TIMESTAMP,

    notes TEXT,
    created_by_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**`quote_line_items`**
```sql
CREATE TABLE quote_line_items (
    id SERIAL PRIMARY KEY,
    quote_id INTEGER REFERENCES quotes(id) ON DELETE CASCADE,
    bom_item_id INTEGER REFERENCES bom_items(id) ON DELETE SET NULL,

    line_type VARCHAR(50) NOT NULL, -- part, labor, subcontract, misc

    -- Line details
    item_number INTEGER, -- Line sequence
    description VARCHAR(500) NOT NULL,
    quantity DECIMAL(10,2) NOT NULL DEFAULT 1,
    unit_price DECIMAL(10,2) NOT NULL DEFAULT 0,
    line_total DECIMAL(10,2) NOT NULL DEFAULT 0,

    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### Media & Audit

**`attachments`**
```sql
CREATE TABLE attachments (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id),
    job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
    inspection_item_id INTEGER REFERENCES inspection_items(id) ON DELETE SET NULL,

    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_type VARCHAR(50), -- image/jpeg, application/pdf
    file_size INTEGER, -- bytes

    caption TEXT,
    uploaded_by_id INTEGER REFERENCES users(id),
    uploaded_at TIMESTAMP DEFAULT NOW()
);
```

**`audit_logs`**
```sql
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER REFERENCES organizations(id),
    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id),

    action VARCHAR(100) NOT NULL, -- created_job, updated_inspection, approved_quote
    entity_type VARCHAR(50), -- job, inspection, quote
    entity_id INTEGER,

    details TEXT, -- JSON: old/new values
    ip_address VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_org ON audit_logs(organization_id);
CREATE INDEX idx_audit_job ON audit_logs(job_id);
CREATE INDEX idx_audit_created ON audit_logs(created_at);
```

### 3.3 Key Relationships

```
Organization (1) ──┬─→ (many) User
                   ├─→ (many) Job
                   ├─→ (many) EquipmentTemplate
                   └─→ (many) EquipmentType

Job (1) ──┬─→ (many) InspectionItem ──→ (0..1) BOMItem
          ├─→ (many) BOMItem
          ├─→ (1) Quote ──→ (many) QuoteLineItem
          ├─→ (many) Attachment
          ├─→ (many) TestResult
          └─→ (1) EquipmentTemplate

EquipmentTemplate (1) ──┬─→ (many) TemplateAssembly
                         └─→ (many) TemplateComponent ──→ (0..1) TemplateAssembly

InspectionItem (1) ──→ (many) Measurement
```

## 4. API Endpoint Specifications

### 4.1 API Design Philosophy

**RESTful JSON API** with the following principles:
- Resource-based URLs (`/api/v1/jobs`, `/api/v1/templates`)
- HTTP verbs for actions (GET, POST, PUT, DELETE)
- JSON request/response bodies
- JWT authentication (Bearer tokens)
- Consistent error format
- Pagination on list endpoints (25 per page default)
- Filter/search query parameters

**Base URL**: `https://api.inspectforge.com/v1`

### 4.2 Authentication Endpoints

**POST /api/v1/auth/login**
- Purpose: User login, returns JWT token
- Request:
  ```json
  {
    "email": "tech@acmepump.com",
    "password": "secure123"
  }
  ```
- Response:
  ```json
  {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "user": {
      "id": 1,
      "email": "tech@acmepump.com",
      "first_name": "John",
      "last_name": "Doe",
      "role": "technician",
      "organization": {
        "id": 1,
        "name": "Acme Pump Repair",
        "slug": "acme-pump"
      }
    },
    "expires_at": "2026-02-03T12:00:00Z"
  }
  ```

**POST /api/v1/auth/logout**
- Purpose: Invalidate current token
- Headers: `Authorization: Bearer {token}`
- Response: `204 No Content`

**POST /api/v1/auth/refresh**
- Purpose: Refresh expiring token
- Returns: New JWT token with extended expiration

### 4.3 Job Endpoints

**GET /api/v1/jobs**
- Purpose: List all jobs (paginated, filtered)
- Query params: `?status=inspection&assigned_to=5&page=1&per_page=25&search=pump`
- Response:
  ```json
  {
    "jobs": [
      {
        "id": 123,
        "job_number": "JOB-2026-0123",
        "customer_name": "ABC Manufacturing",
        "equipment_type": "Centrifugal Pump",
        "manufacturer": "Goulds",
        "model": "3196",
        "serial_number": "12345-ABC",
        "status": "inspection",
        "assigned_to": {
          "id": 5,
          "name": "John Doe"
        },
        "created_at": "2026-02-01T10:00:00Z",
        "target_completion_date": "2026-02-15"
      }
    ],
    "pagination": {
      "page": 1,
      "per_page": 25,
      "total": 156,
      "total_pages": 7
    }
  }
  ```

**GET /api/v1/jobs/{id}**
- Purpose: Get single job details
- Response: Full job object with relationships

**POST /api/v1/jobs**
- Purpose: Create new job
- Request:
  ```json
  {
    "customer_name": "ABC Manufacturing",
    "customer_contact": "Jane Smith",
    "equipment_type_id": 3,
    "manufacturer": "Goulds",
    "model": "3196 MTX",
    "serial_number": "12345-ABC",
    "equipment_tag": "PUMP-101",
    "template_id": 7,
    "assigned_to_id": 5,
    "received_date": "2026-02-01",
    "target_completion_date": "2026-02-15"
  }
  ```
- Response: `201 Created` with job object

**PUT /api/v1/jobs/{id}**
- Purpose: Update job
- Request: Partial job object
- Response: Updated job object

**POST /api/v1/jobs/{id}/status**
- Purpose: Change job status
- Request:
  ```json
  {
    "status": "quoting",
    "notes": "Inspection complete, ready for quote"
  }
  ```
- Response: Updated job with new status

### 4.4 Inspection Endpoints

**POST /api/v1/jobs/{id}/inspection/seed**
- Purpose: Populate inspection items from template
- Request:
  ```json
  {
    "template_id": 7
  }
  ```
- Response: `201 Created` with array of inspection_items

**GET /api/v1/jobs/{id}/inspection**
- Purpose: Get all inspection items for job
- Response:
  ```json
  {
    "inspection_items": [
      {
        "id": 456,
        "assembly_name": "Impeller Assembly",
        "item_number": "1",
        "description": "Impeller (cast iron)",
        "part_number": "IMP-3196-12",
        "quantity": 1,
        "decision": "replace",
        "condition_rating": 2,
        "condition_notes": "Heavy wear on vanes, pitting on shroud",
        "is_critical": true,
        "inspected_at": "2026-02-01T14:30:00Z"
      }
    ]
  }
  ```

**PUT /api/v1/inspection-items/{id}**
- Purpose: Update single inspection item
- Request:
  ```json
  {
    "decision": "replace",
    "condition_rating": 2,
    "condition_notes": "Heavy wear on vanes"
  }
  ```
- Response: Updated inspection_item

**POST /api/v1/inspection-items/{id}/measurements**
- Purpose: Add measurement to inspection item
- Request:
  ```json
  {
    "label": "Shaft Diameter",
    "value_measured": 1.995,
    "value_min_spec": 1.998,
    "value_max_spec": 2.002,
    "unit": "in"
  }
  ```
- Response: Created measurement object

### 4.5 BOM Endpoints

**POST /api/v1/jobs/{id}/bom/generate**
- Purpose: Auto-generate BOM from inspection decisions
- Response: `201 Created` with array of bom_items

**GET /api/v1/jobs/{id}/bom**
- Purpose: Get BOM for job
- Response:
  ```json
  {
    "bom_items": [
      {
        "id": 789,
        "part_number": "IMP-3196-12",
        "description": "Impeller (cast iron)",
        "quantity": 1,
        "unit_cost": 450.00,
        "total_cost": 450.00,
        "source": "auto_generated",
        "supplier": "Goulds Direct"
      }
    ],
    "totals": {
      "parts_count": 12,
      "total_cost": 2850.00
    }
  }
  ```

**POST /api/v1/jobs/{id}/bom**
- Purpose: Manually add BOM item
- Request:
  ```json
  {
    "part_number": "GSKT-001",
    "description": "Casing gasket",
    "quantity": 1,
    "unit_cost": 15.00,
    "supplier": "McMaster-Carr"
  }
  ```

**DELETE /api/v1/bom-items/{id}**
- Purpose: Remove BOM item

### 4.6 Quote Endpoints

**POST /api/v1/jobs/{id}/quotes**
- Purpose: Create quote from BOM
- Request:
  ```json
  {
    "labor_hours": 24,
    "labor_rate": 95.00,
    "markup_percent": 15,
    "valid_until": "2026-03-01"
  }
  ```
- Response: Created quote object with totals

**GET /api/v1/quotes/{id}**
- Purpose: Get quote details
- Response: Full quote with line items

**PUT /api/v1/quotes/{id}**
- Purpose: Update quote (revise)
- Response: Updated quote (increments version)

**POST /api/v1/quotes/{id}/approve**
- Purpose: Approve quote, move job to "approved" status
- Response: Approved quote

**GET /api/v1/quotes/{id}/pdf**
- Purpose: Generate quote PDF
- Response: PDF file (application/pdf)

### 4.7 Template Endpoints

**GET /api/v1/templates**
- Purpose: List equipment templates
- Query params: `?equipment_type_id=3&is_standard=true`
- Response: Array of templates

**GET /api/v1/templates/{id}**
- Purpose: Get template with components
- Response:
  ```json
  {
    "id": 7,
    "name": "Goulds 3196 Pump Standard",
    "equipment_type": "Centrifugal Pump",
    "manufacturer": "Goulds",
    "assemblies": [
      {
        "id": 20,
        "name": "Impeller Assembly",
        "components": [
          {
            "id": 100,
            "item_number": "1",
            "part_number": "IMP-3196-12",
            "description": "Impeller (cast iron)",
            "quantity": 1,
            "is_critical": true
          }
        ]
      }
    ]
  }
  ```

**POST /api/v1/templates**
- Purpose: Create new template (Admin only)
- Request: Template object with assemblies and components
- Response: `201 Created`

**POST /api/v1/templates/{id}/clone**
- Purpose: Clone existing template
- Response: New template (copy)

### 4.8 Attachment Endpoints

**POST /api/v1/jobs/{id}/attachments**
- Purpose: Upload photo or document
- Request: Multipart form data with file
- Headers: `Content-Type: multipart/form-data`
- Response:
  ```json
  {
    "id": 999,
    "file_name": "impeller_damage.jpg",
    "file_path": "/uploads/jobs/123/impeller_damage.jpg",
    "file_type": "image/jpeg",
    "file_size": 245678,
    "uploaded_at": "2026-02-01T15:00:00Z"
  }
  ```

**DELETE /api/v1/attachments/{id}**
- Purpose: Delete attachment

### 4.9 User & Admin Endpoints

**GET /api/v1/users**
- Purpose: List users (Admin only)
- Response: Array of users

**POST /api/v1/users**
- Purpose: Create user (Admin only)
- Request:
  ```json
  {
    "email": "newtech@acmepump.com",
    "first_name": "Jane",
    "last_name": "Smith",
    "role": "technician",
    "password": "temp123"
  }
  ```

**GET /api/v1/equipment-types**
- Purpose: List equipment types
- Response: Array of equipment types

### 4.10 Error Format

All errors return consistent JSON:
```json
{
  "error": {
    "code": "validation_error",
    "message": "Validation failed",
    "details": {
      "customer_name": ["This field is required"],
      "serial_number": ["Must be unique"]
    }
  }
}
```

HTTP Status Codes:
- `200 OK` - Success
- `201 Created` - Resource created
- `204 No Content` - Success with no body
- `400 Bad Request` - Validation error
- `401 Unauthorized` - Not authenticated
- `403 Forbidden` - Not authorized (wrong role)
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

---

## 5. Component Architecture

### 5.1 Frontend Technology Choice

**Recommended**: React 18+ with TypeScript

**Rationale**:
- Component reusability (inspection form, BOM editor)
- Strong ecosystem (React Query, React Router, Tailwind)
- TypeScript adds type safety for complex data structures
- Easier to hire React developers than other frameworks
- Better mobile support (React Native potential)

**Alternative Considered**: Vue.js (simpler learning curve, but smaller talent pool)

### 5.2 Component Hierarchy

```
App
├── AuthProvider (context: current user, org)
├── Router
│   ├── PublicRoutes
│   │   └── LoginPage
│   └── PrivateRoutes (requires auth)
│       ├── DashboardLayout
│       │   ├── TopNav (logo, search, user menu)
│       │   ├── Sidebar (navigation links)
│       │   └── MainContent (router outlet)
│       │       ├── DashboardPage
│       │       │   ├── KPICards (jobs count, quote value)
│       │       │   └── JobsTable (list with filters)
│       │       ├── JobDetailPage
│       │       │   ├── JobHeader (customer, equipment, status)
│       │       │   ├── StatusStepper (workflow visualization)
│       │       │   └── TabPanel
│       │       │       ├── InspectionTab
│       │       │       │   ├── AssemblyAccordion
│       │       │       │   │   └── InspectionItemRow
│       │       │       │   │       ├── DecisionDropdown
│       │       │       │   │       ├── ConditionRating
│       │       │       │   │       ├── MeasurementForm
│       │       │       │   │       └── PhotoUpload
│       │       │       │   └── SubmitInspectionButton
│       │       │       ├── BOMTab
│       │       │       │   ├── BOMTable (editable)
│       │       │       │   ├── AddPartButton
│       │       │       │   └── GenerateBOMButton
│       │       │       ├── QuoteTab
│       │       │       │   ├── QuoteForm (labor, markup)
│       │       │       │   ├── QuoteLineItemsTable
│       │       │       │   ├── QuoteTotals
│       │       │       │   └── ApproveQuoteButton
│       │       │       └── AttachmentsTab
│       │       │           └── AttachmentGrid
│       │       ├── TemplatesPage
│       │       │   ├── TemplateList
│       │       │   └── CreateTemplateButton
│       │       ├── TemplateEditorPage
│       │       │   ├── TemplateBasicInfo
│       │       │   ├── AssemblyManager
│       │       │   └── ComponentManager
│       │       └── SettingsPage
│       │           ├── UserManagement
│       │           └── EquipmentTypeManager
└── NotificationProvider (toast notifications)
```

### 5.3 Key Shared Components

**1. InspectionItemRow**
- Props: `item`, `onUpdate`, `onPhotoUpload`
- State: `decision`, `conditionRating`, `notes`
- Features:
  - Dropdown for decision (keep/replace/repair/upgrade)
  - Star rating for condition (1-5)
  - Expandable section for measurements
  - Photo upload button

**2. BOMTable**
- Props: `bomItems`, `editable`, `onAdd`, `onRemove`, `onUpdate`
- Features:
  - Editable cells (part number, quantity, cost)
  - Add row button
  - Delete row button
  - Total cost calculation footer

**3. QuotePDF**
- Props: `quote`, `job`, `bomItems`
- Generates PDF using react-pdf or html2pdf
- Includes: Company logo, quote number, line items, totals

**4. FileUpload**
- Props: `onUpload`, `accept` (file types), `maxSize`
- Features: Drag-and-drop zone, preview thumbnails, progress bar

**5. StatusStepper**
- Props: `currentStatus`, `steps`
- Visual workflow: received → inspection → quoting → approved → work → complete
- Highlights current step, checkmarks completed

### 5.4 State Management

**React Query** for server state:
- Automatic caching
- Background refetching
- Optimistic updates
- Pagination

Example:
```typescript
const { data: job, isLoading } = useQuery({
  queryKey: ['jobs', jobId],
  queryFn: () => api.getJob(jobId)
});

const updateInspectionMutation = useMutation({
  mutationFn: api.updateInspectionItem,
  onSuccess: () => {
    queryClient.invalidateQueries(['jobs', jobId]);
  }
});
```

**Context API** for global state:
- `AuthContext`: Current user, org, permissions
- `NotificationContext`: Toast messages

**Local State** (useState):
- Form inputs
- UI toggles (accordion open/closed)

### 5.5 Routing Structure

```
/login
/dashboard
/jobs
/jobs/new
/jobs/:id
/jobs/:id/inspection
/jobs/:id/bom
/jobs/:id/quote
/jobs/:id/attachments
/templates
/templates/new
/templates/:id/edit
/settings/users
/settings/equipment-types
```

---

## 6. Recommended Tech Stack

### 6.1 Frontend

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **React** | 18.3+ | UI framework | Component reusability, large ecosystem |
| **TypeScript** | 5.0+ | Type safety | Prevents bugs, better IDE support |
| **Vite** | 5.0+ | Build tool | Fast dev server, instant HMR |
| **React Router** | 6.22+ | Routing | Industry standard, type-safe |
| **React Query** | 5.0+ | Server state | Caching, background sync, pagination |
| **Tailwind CSS** | 3.4+ | Styling | Utility-first, fast development |
| **shadcn/ui** | Latest | Component library | Accessible, customizable components |
| **React Hook Form** | 7.50+ | Forms | Performance, validation |
| **Zod** | 3.22+ | Schema validation | Type-safe validation |
| **Axios** | 1.6+ | HTTP client | Interceptors, request/response handling |

### 6.2 Backend

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Node.js** | 20 LTS | Runtime | JavaScript full-stack, large talent pool |
| **Express** | 4.18+ | Web framework | Simple, flexible, well-documented |
| **TypeScript** | 5.0+ | Type safety | Shared types with frontend |
| **Prisma** | 5.10+ | ORM | Type-safe queries, migrations |
| **PostgreSQL** | 15+ | Database | ACID, JSON support, full-text search |
| **JWT** | jsonwebtoken 9.0+ | Authentication | Stateless, mobile-friendly |
| **bcrypt** | 5.1+ | Password hashing | Industry standard |
| **Multer** | 1.4+ | File upload | Multipart form handling |
| **PDFKit** | 0.14+ | PDF generation | Quote PDFs |

**Alternative Backend**: Python (Flask) + SQLAlchemy (closer to RemanAssist patterns)

### 6.3 Infrastructure

| Service | Purpose | Why |
|---------|---------|-----|
| **Vercel** or **Railway** | Frontend hosting | Easy deployment, CDN, preview URLs |
| **Render** or **Railway** | Backend hosting | Managed PostgreSQL, auto-deploy from Git |
| **AWS S3** or **Cloudflare R2** | File storage | Scalable, cheap for attachments |
| **Sentry** | Error tracking | Real-time error alerts |
| **PostHog** | Analytics | Product analytics, feature flags |

### 6.4 Development Tools

| Tool | Purpose |
|------|---------|
| **ESLint** | Code linting |
| **Prettier** | Code formatting |
| **Vitest** | Unit testing |
| **Playwright** | E2E testing |
| **Docker** | Local dev environment |
| **GitHub Actions** | CI/CD |

## 7. Feature Specifications

### 7.1 Job Creation

**Purpose**: Create new job from customer request

**User Flow** (Estimator):
1. Click "New Job" button on dashboard
2. Fill form:
   - Customer name (required)
   - Customer contact (optional)
   - Customer PO number (optional)
   - Equipment type dropdown (required) - e.g., "Centrifugal Pump"
   - Manufacturer (text input)
   - Model (text input)
   - Serial number (required)
   - Equipment tag (optional) - customer's asset ID
   - Received date (date picker)
   - Target completion date (date picker)
   - Select template (optional) - filtered by equipment type
   - Assign to technician (dropdown)
3. Click "Create Job"
4. System generates job number (JOB-2026-0001)
5. Redirect to job detail page

**Technical Approach**:
- Form validation: Zod schema
- Unique job number: Auto-increment with year prefix
- Template selection: Filtered API call `/api/v1/templates?equipment_type_id=3`
- On create: POST `/api/v1/jobs`
- Status: Auto-set to "received"

**Data Requirements**:
- `jobs` table insert
- `job_status_history` table insert (initial status)
- `audit_logs` table insert (action: "created_job")

### 7.2 Inspection Workflow

**Purpose**: Technician documents equipment condition

**User Flow** (Technician):
1. Open job from "My Jobs" list
2. Click "Start Inspection" button
   - If template selected: System populates inspection_items from template
   - If no template: Technician adds items manually
3. For each inspection item:
   - View: Assembly, item number, description, part number
   - Select decision: Keep / Replace / Repair / Upgrade
   - Rate condition: 1-5 stars
   - Enter notes: Free text
   - Add measurements (optional):
     - Label, measured value, spec range, unit
     - System calculates within_spec / out_of_spec
   - Upload photos:
     - Drag-and-drop or click to browse
     - Supports JPG, PNG, PDF
     - Max 10MB per file
     - Thumbnail preview
4. Expand next assembly accordion, repeat
5. Click "Submit Inspection"
6. System changes job status to "quoting"
7. Notification sent to estimator

**Technical Approach**:
- Accordion component for assemblies (collapse/expand)
- Inspection item rows: Inline editing
- Decision dropdown: onChange triggers PUT `/api/v1/inspection-items/{id}`
- Photo upload: POST `/api/v1/jobs/{id}/attachments` with multipart form
- Optimistic updates: React Query mutations
- Auto-save: Debounced (save 2 seconds after last edit)

**Data Requirements**:
- `inspection_items` table updates
- `measurements` table inserts
- `attachments` table inserts
- `job_status_history` table insert (status change to "quoting")

### 7.3 BOM Generation

**Purpose**: Auto-create parts list from inspection decisions

**User Flow** (Estimator):
1. Navigate to job "BOM" tab
2. Click "Generate BOM from Inspection"
3. System:
   - Scans inspection_items where decision = "replace"
   - Creates bom_items for each
   - Looks up part_number in parts_catalog for cost
   - Calculates totals
4. Display BOM table:
   - Part number, description, quantity, unit cost, total cost
   - Editable: Quantity, unit cost, supplier
   - Actions: Add row, delete row
5. Estimator reviews, adjusts quantities/costs
6. Click "Save BOM"

**Technical Approach**:
- Algorithm (backend):
  ```
  1. Query inspection_items WHERE job_id = X AND decision = 'replace'
  2. For each item:
     - Create bom_item
     - Copy part_number, description, quantity
     - Lookup part_number in parts_catalog
     - Set unit_cost = catalog.unit_cost (if found)
     - Set source = 'auto_generated'
  3. Return bom_items array
  ```
- Frontend: React Query mutation
- Editable table: React Hook Form with field array
- Add row: Appends empty bom_item
- Delete row: Confirmation modal, then DELETE `/api/v1/bom-items/{id}`

**Data Requirements**:
- `bom_items` table inserts
- Join with `parts_catalog` for pricing

### 7.4 Quote Creation

**Purpose**: Build customer quote with parts and labor

**User Flow** (Estimator):
1. Navigate to job "Quote" tab
2. System displays:
   - BOM line items (from bom_items)
   - Parts total (sum of bom_items)
3. Estimator enters:
   - Labor hours (number input)
   - Labor rate ($/hour)
   - Markup percentage (%)
   - Valid until date (date picker)
4. System calculates:
   - Labor total = hours × rate
   - Subtotal = parts total + labor total
   - Markup amount = subtotal × markup %
   - Quote total = subtotal + markup
5. Estimator reviews quote
6. Click "Generate Quote PDF"
   - Opens PDF in new tab
   - Header: Company logo, quote number, date
   - Customer info
   - Equipment info
   - Line items table (parts + labor)
   - Totals section
   - Footer: Valid until, terms & conditions
7. Estimator emails PDF to customer
8. Click "Mark as Sent"
9. When customer approves, click "Approve Quote"
   - Job status changes to "approved"
   - Job moves to work phase

**Technical Approach**:
- Form: React Hook Form
- Real-time calculation: Watch form fields, update totals
- PDF generation (backend):
  - Use PDFKit (Node.js) or ReportLab (Python)
  - Template: Company letterhead
  - Data: Query job, bom_items, quote
  - Return: PDF binary (Content-Type: application/pdf)
- Approve button: POST `/api/v1/quotes/{id}/approve`
  - Updates quote.status = 'approved'
  - Updates job.status = 'approved'
  - Inserts job_status_history

**Data Requirements**:
- `quotes` table insert
- `quote_line_items` table inserts (copy from bom_items)
- `jobs` table update (status)
- `job_status_history` table insert

### 7.5 Template Management

**Purpose**: Create reusable inspection checklists

**User Flow** (Admin):
1. Navigate to "Templates" page
2. Click "Create Template"
3. Enter basic info:
   - Name (e.g., "Goulds 3196 Pump - Standard")
   - Equipment type (dropdown)
   - Manufacturer (text)
   - Model family (text)
   - Description (textarea)
4. Click "Next"
5. Add assemblies:
   - Assembly name (e.g., "Impeller Assembly")
   - Assembly code (e.g., "IMP")
   - Click "Add Assembly"
   - Repeat for each assembly
6. Click "Next"
7. Add components:
   - Select assembly (dropdown)
   - Item number (e.g., "1")
   - Part number (e.g., "IMP-3196-12")
   - Description (e.g., "Impeller (cast iron)")
   - Quantity (default 1)
   - Flags:
     - Is critical? (checkbox)
     - Always replace? (checkbox)
     - Requires measurement? (checkbox)
   - Click "Add Component"
   - Repeat for each component
8. Click "Save Template"
9. Template now available for job creation

**Technical Approach**:
- Multi-step wizard: React component with step state
- Form persistence: Save draft to localStorage (auto-save)
- API calls:
  - POST `/api/v1/templates` (creates template record)
  - POST `/api/v1/templates/{id}/assemblies` (creates assemblies)
  - POST `/api/v1/templates/{id}/components` (creates components)
- Batch operation: Frontend collects all data, sends in single transaction

**Data Requirements**:
- `equipment_templates` table insert
- `template_assemblies` table inserts
- `template_components` table inserts

---

## 8. Implementation Phases

### 8.1 Phase 1: Foundation (Weeks 1-2)

**Goals**:
- Set up development environment
- Database schema
- Authentication
- Basic job CRUD

**Tasks**:
- [ ] Initialize project repos (frontend, backend)
- [ ] Set up PostgreSQL database
- [ ] Run Prisma migrations (schema)
- [ ] Implement JWT authentication
- [ ] Build login page
- [ ] Build dashboard layout (nav, sidebar)
- [ ] Implement user roles & permissions
- [ ] Create job list API endpoint
- [ ] Create job detail API endpoint
- [ ] Build job list page
- [ ] Build job creation form
- [ ] Build job detail page (basic)

**Deliverable**: Users can log in, create jobs, view job list

### 8.2 Phase 2: Inspection Workflow (Weeks 3-4)

**Goals**:
- Inspection form
- Photo upload
- Decision tracking

**Tasks**:
- [ ] Build inspection API endpoints
- [ ] Create inspection item seeding (from template)
- [ ] Build inspection form UI
  - [ ] Assembly accordion
  - [ ] Inspection item rows
  - [ ] Decision dropdown
  - [ ] Condition rating stars
- [ ] Implement photo upload
  - [ ] Multer file handling (backend)
  - [ ] Drag-and-drop component (frontend)
  - [ ] Thumbnail display
- [ ] Build measurement entry form (optional)
- [ ] Implement job status transitions
- [ ] Add "Submit Inspection" action

**Deliverable**: Technicians can complete inspections, upload photos

### 8.3 Phase 3: BOM & Quoting (Weeks 5-6)

**Goals**:
- Auto-generate BOM
- Quote builder
- PDF export

**Tasks**:
- [ ] Build BOM generation algorithm (backend)
- [ ] Create BOM API endpoints
- [ ] Build BOM table UI (editable)
- [ ] Implement add/remove rows
- [ ] Build quote API endpoints
- [ ] Build quote form UI
- [ ] Implement real-time calculation
- [ ] Build PDF generation (backend)
  - [ ] Quote PDF template
  - [ ] Company logo placeholder
- [ ] Add "Generate PDF" button
- [ ] Implement quote approval workflow

**Deliverable**: Estimators can generate BOM, create quotes, export PDF

### 8.4 Phase 4: Templates (Weeks 7-8)

**Goals**:
- Template CRUD
- Template wizard
- Seeding jobs from templates

**Tasks**:
- [ ] Build template API endpoints
- [ ] Create equipment types management
- [ ] Build template list page
- [ ] Build template wizard UI
  - [ ] Step 1: Basic info
  - [ ] Step 2: Assemblies
  - [ ] Step 3: Components
- [ ] Implement template cloning
- [ ] Add "Select template" to job creation
- [ ] Implement inspection seeding from template
- [ ] Build template preview

**Deliverable**: Admins can create templates, jobs use templates

### 8.5 Phase 5: Polish & Testing (Weeks 9-10)

**Goals**:
- Error handling
- Loading states
- Responsive design
- Testing

**Tasks**:
- [ ] Add error boundaries (frontend)
- [ ] Implement toast notifications
- [ ] Add loading skeletons
- [ ] Responsive CSS (mobile, tablet)
- [ ] Write unit tests (Vitest)
  - [ ] BOM generation algorithm
  - [ ] Quote calculation
  - [ ] Auth middleware
- [ ] Write E2E tests (Playwright)
  - [ ] Login flow
  - [ ] Job creation flow
  - [ ] Inspection flow
  - [ ] Quote generation flow
- [ ] Accessibility audit (WCAG)
- [ ] Performance optimization
  - [ ] Code splitting
  - [ ] Image optimization
  - [ ] Database indexes

**Deliverable**: Production-ready MVP

### 8.6 Phase 6: Deployment & Launch (Weeks 11-12)

**Goals**:
- Deploy to production
- Onboard first customers
- Monitor and fix issues

**Tasks**:
- [ ] Set up production infrastructure
  - [ ] Backend hosting (Render/Railway)
  - [ ] Frontend hosting (Vercel)
  - [ ] Database (Render PostgreSQL)
  - [ ] File storage (AWS S3 / Cloudflare R2)
- [ ] Configure environment variables
- [ ] Set up CI/CD (GitHub Actions)
- [ ] Configure error tracking (Sentry)
- [ ] Set up analytics (PostHog)
- [ ] Write documentation
  - [ ] User guide
  - [ ] Admin guide
  - [ ] API docs
- [ ] Onboard first 3-5 customers
- [ ] Collect feedback
- [ ] Fix critical bugs
- [ ] Plan post-MVP features

**Deliverable**: Live production app with paying customers

---

## 9. Terminology Translation

### 9.1 Motor (RemanAssist) → Equipment (InspectForge)

| RemanAssist (Motor) | InspectForge (Equipment) | Rationale |
|---------------------|--------------------------|-----------|
| **Engine** | **Equipment** | Generic term covers pumps, compressors, gearboxes |
| **Engine Type** (e.g., "MAN D0836") | **Equipment Type** (e.g., "Centrifugal Pump") | More generic classification |
| **Section** (e.g., "TA0101 - Turbocharger") | **Assembly** (e.g., "Impeller Assembly") | Clearer hierarchy: equipment → assembly → component |
| **Survey Item** | **Inspection Item** | "Inspection" is standard industry term |
| **Part Requirement** | **BOM Item** | BOM is universal manufacturing term |
| **Job Pack** | **Job** | Simpler, job is already comprehensive |
| **Template** | **Equipment Template** | More descriptive |
| **Always Replace** | **Always Replace** | Same (wear items exist in all industries) |
| **Kit Components** | **Assembly** | Kit logic not needed (less complex products) |
| **Measurement** | **Measurement** | Same (universal concept) |
| **Torque Specification** | **Test Result** | Generic testing (not just torque) |
| **Pre-Survey** | **Initial Assessment** | More professional terminology |
| **Release / Approval** | **Approval** | Simpler workflow |

### 9.2 Industry-Specific Language

**Pump Shop**:
- "Impeller", "Volute", "Casing", "Wear Ring", "Mechanical Seal"
- Performance test: "Flow rate at X head"

**Compressor Shop**:
- "Cylinder", "Piston", "Valve Plate", "Crankshaft", "Unloader"
- Performance test: "CFM at X PSI"

**Gearbox Shop**:
- "Gear Set", "Input Shaft", "Output Shaft", "Bearing", "Seal"
- Performance test: "Backlash", "Runout"

**Hydraulic Shop**:
- "Cylinder Rod", "Piston", "Seal Kit", "Barrel", "Gland"
- Performance test: "Leak test at X PSI"

**InspectForge uses equipment-neutral terms by default**, with customization per template.

### 9.3 UI Copy Guidelines

**Button Labels**:
- "Start Inspection" (not "Begin Survey")
- "Generate BOM" (not "Create Parts List")
- "Create Quote" (not "Build Estimate")
- "Approve & Release" (not "Sign Off")

**Status Labels**:
- "Received" (equipment arrived)
- "Inspection" (being inspected)
- "Quoting" (building quote)
- "Approved" (customer approved)
- "In Work" (being repaired/rebuilt)
- "Testing" (performance testing)
- "Complete" (ready to ship)

**Email Templates**:
- Subject: "Quote #{number} for {equipment} Overhaul"
- Body: "We've completed the inspection of your {equipment} (S/N: {serial}). Please review the attached quote."

---

## 10. Differentiation Notes

### 10.1 Why InspectForge is NOT Just "Generic RemanAssist"

**1. Broader Market**
- RemanAssist: Motor remanufacturing shops only (~500 in US)
- InspectForge: Equipment overhaul shops (~5,000+ in US)
- Market size: 10x larger

**2. Simpler Product Logic**
- RemanAssist: Complex kit suppression, supersedes rules
- InspectForge: Straightforward keep/replace decisions
- Easier to build, sell, support

**3. Different Buyer Persona**
- RemanAssist: Motor shop manager (deep technical knowledge)
- InspectForge: Equipment shop owner (business-focused)
- Sales message: Efficiency & customer satisfaction (not technical precision)

**4. Flexible Equipment Types**
- RemanAssist: Fixed engine structure (crankshaft, pistons, etc.)
- InspectForge: User defines assemblies per equipment type
- Customizable to any equipment

**5. Faster MVP**
- RemanAssist: 18+ months to build (complex domain)
- InspectForge: 12 weeks to MVP (simpler scope)
- Lower development risk

### 10.2 How InspectForge Differs from Competitors

**vs. Paper/Excel** (current state):
- InspectForge: Digital forms, auto-BOM, instant quotes
- Paper: Manual transcription, error-prone, slow

**vs. Generic Field Service Software** (e.g., ServiceTitan):
- InspectForge: Built for overhaul shops (inspection-first workflow)
- ServiceTitan: Built for HVAC/plumbing (dispatch-first workflow)
- InspectForge has templates, BOM generation, quote builder

**vs. ERP Systems** (e.g., QuickBooks, SAP):
- InspectForge: Lightweight, overhaul-specific
- ERP: Heavy, generic accounting/inventory
- InspectForge integrates WITH ERP (doesn't replace)

**vs. Maintenance Management** (e.g., Fiix, Limble):
- InspectForge: For repair shops (external customers)
- CMMS: For asset owners (internal maintenance)
- Different workflow entirely

### 10.3 Positioning Statement

> **InspectForge is the digital inspection and quoting platform built specifically for industrial equipment overhaul shops.**
>
> We help pump shops, compressor rebuilders, and hydraulic repair facilities transition from paper-based chaos to digital precision—standardizing inspections, automating BOMs, and delivering professional quotes in minutes, not days.

**Target Customer**: 10-50 person equipment repair shops processing 100-300 jobs per year, currently using paper forms and Excel spreadsheets.

**Price Point**: $200-500/month SaaS (per shop, unlimited users)

**Go-to-Market**: Content marketing (SEO for "pump shop software"), trade shows (fluid power expos), direct outreach to equipment repair associations.

---

## Conclusion

InspectForge is a **clean room design** for industrial equipment overhaul, inspired by successful patterns from motor remanufacturing software but purpose-built for a broader market.

**Key Success Factors**:
1. **Equipment-agnostic**: Works for pumps, compressors, gearboxes, hydraulics
2. **Simple to use**: Technicians can learn in 15 minutes
3. **Fast ROI**: Shops save 10+ hours per week on paperwork
4. **Professional output**: Customers receive polished quote PDFs with photos
5. **Grows with you**: Template library expands as shop builds expertise

**Next Steps**:
1. Validate market with 10 customer discovery interviews
2. Build database + authentication (Week 1-2)
3. Ship MVP to first 3 pilot customers (Week 12)
4. Iterate based on feedback
5. Scale to 50 customers by end of Year 1

---

**End of Technical Specification**

*Document Version: 1.0*
*Last Updated: February 2, 2026*
