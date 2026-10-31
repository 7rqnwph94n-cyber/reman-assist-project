# Template Editor - Design Analysis
## Comprehensive Design Study for Product Managers

**Document Purpose**: Analyze the design patterns, user experience, and architecture of the template editor system without referencing specific code implementations.

**Target Audience**: Product managers, UX designers, and technical leads building similar systems

**Analysis Date**: February 2026

---

## Table of Contents

1. [User Experience Flow](#1-user-experience-flow)
2. [Data Model Conceptual Design](#2-data-model-conceptual-design)
3. [UI/UX Patterns That Work Well](#3-uiux-patterns-that-work-well)
4. [Technical Approaches That Work](#4-technical-approaches-that-work)
5. [Pain Points & Limitations](#5-pain-points--limitations)
6. [Improvement Recommendations](#6-improvement-recommendations)

---

## 1. User Experience Flow

### 1.1 Entry Points

The system provides **two distinct pathways** for template management:

**Path A: Template Wizard** (Guided Multi-Step Flow)
- Designed for initial template creation
- Step-locked progression (must complete Step 1 before Step 2)
- Suitable for users importing from external sources (PDFs, spreadsheets)

**Path B: Direct Template Editor** (Power User Flow)
- Single comprehensive form with all fields visible
- Faster for experienced users making targeted edits
- No step progression; all data accessible simultaneously

### 1.2 Template Wizard Journey

**Step 1: Import Assets**

**Purpose**: Populate initial parts list and section structure

**User Actions**:
- Choose import method:
  - **CSV/Excel Upload**: Upload spreadsheet with parts list
  - **PDF Extraction**: Upload manufacturer's parts catalog PDF, system auto-extracts parts/sections
  - **Image Upload**: Upload folder of section diagrams (matched by filename pattern)
- Configure import options:
  - "Replace existing items" (destructive) vs. "Append to existing"
  - For PDF: select manufacturer profile (auto-detect or manual)
- Execute import

**Validation/Feedback**:
- File type validation (accepts .csv, .xlsx, .pdf, .jpg, .png)
- Size limits enforced (prevents timeout)
- Import summary displayed: "450 rows created, 5 skipped (missing part number)"
- **Safety mechanism**: Destructive imports require typing "WIPE" + checkbox confirmation
- Blocks import if active jobs reference this template

**Outcome**: Template populated with parts list organized by sections

---

**Step 2: Categorize + Rules**

**Purpose**: Configure part behavior, create kit groupings, set replacement rules

**User Actions**:
- Edit parts inline in table:
  - Part number, description, quantity
  - Section assignment
  - Position/sequence number
- Set behavioral flags per part:
  - "Always replace" (forces replacement in every job)
  - "Big ticket item" (high-value part requiring special approval)
  - "Requires testing" (triggers test workflow before purchase decision)
  - "Requires measurement" (enables measurement entry in inspection)
- Create kit groupings:
  - Define kit name (e.g., "Gasket Set A")
  - Assign parts to kit
- Configure replacement rules:
  - **Supersedes**: "If you order Part A, remove Parts B, C, D from BOM" (kit consolidation)
  - **Bundles**: "If you order Part A, automatically add Parts E, F" (assembly kits)

**Validation/Feedback**:
- Part number uniqueness checked within template
- Warnings if kit references non-existent parts
- Auto-save on every edit (no explicit Save button)

**Outcome**: Parts categorized, kits defined, intelligent BOM rules configured

---

**Step 3: Exploded View (Illustrations)**

**Purpose**: Link section diagrams to template, define interactive hotspots

**User Actions**:
- Review sections created in Step 1
- For each section:
  - Upload diagram image (exploded view drawing)
  - Define position (POS) labels: coordinate markers on image linking to part numbers
  - Create interactive hotspots: clickable regions on diagram
- Drag coordinates on image to place POS labels (visual editor)

**Validation/Feedback**:
- Section status indicator: "POS labels complete" or "Pending"
- Image preview with labeled positions

**Outcome**: Sections have visual diagrams with interactive part references

---

**Step 4: Assembly Log**

**Purpose**: Flag parts requiring assembly documentation

**User Actions**:
- Review parts list in table
- For each part, mark if it requires:
  - **Torque specification** (bolt torque, sequence)
  - **Build measurement** (assembly clearance check)
  - **Photo documentation** (during assembly)
- Collapse/expand sections to navigate large parts lists

**Validation/Feedback**:
- Checklist completion count per section
- Warning if conflicting flags (e.g., "always replace" + "requires test")

**Outcome**: Assembly workflow requirements defined per part

---

**Step 5: Measurements & Limits**

**Purpose**: Define measurement specifications for inspected parts

**User Actions**:
- View parts flagged with "requires measurement" from Step 2
- For each part:
  - Define measurement label (e.g., "Shaft Diameter", "Bearing Clearance")
  - Set unit (inches, mm, mil, psi)
  - Set min/max specification limits
- **Multi-instance handling**:
  - For parts with qty > 1, system expands into individual rows (e.g., qty=3 becomes 3 measurement rows)
  - "Apply to All" button copies first row values to remaining instances
- Configure measurement instances individually if needed

**Validation/Feedback**:
- Unit conversion hints (mm ↔ inches)
- Warning if min > max
- Visual indicator: measurement count per part

**Outcome**: Measurement specifications defined, ready for job inspection workflows

---

**Step 6: Torque (Incomplete)**

**Purpose**: Define torque sequences and values

**Current State**: Step is visible in navigation but functionally incomplete

**Observed Limitations**:
- Minimal UI implementation
- Torque data stored in database but not fully editable in wizard
- Users uncertain of purpose or how to use

**Expected User Actions** (based on partial implementation):
- Define torque values per bolt/fastener
- Set tightening sequence (order of operations)
- Specify torque units (Nm, lb-ft)

---

### 1.3 Direct Template Editor Journey

**Single-Page Editing Experience**:
- All parts displayed in large table (20-650 rows typical)
- Inline editing of all fields:
  - Part details (number, description, quantity)
  - Section assignment
  - Behavioral flags (checkboxes)
  - Kit assignment (dropdown)
- Search bar filters parts list (client-side)
- Add/delete rows inline
- Save triggered on every edit (no explicit Save button)

**When Used**:
- Quick fixes to existing templates
- Targeted edits (change one measurement spec, add one part)
- Experienced users who know exactly what to change

---

### 1.4 Validation & Feedback Mechanisms

**Proactive Warnings**:
- Import conflicts: "5 existing sections not in uploaded list were left unchanged"
- Active jobs: "Cannot delete template: 12 active jobs depend on it"
- Missing data: "Part ABC has qty=3 but only 1 measurement spec defined"

**Blocking Errors**:
- Duplicate part numbers within template
- Invalid file types on upload
- Missing required fields (part number, description)

**Status Indicators**:
- Wizard step completion: ✓ green checkmark when step complete
- Next step disabled until current step marked complete
- Template lock icon if locked (Admin-only edit)

**User Confirmation Required**:
- Destructive operations: Type "WIPE" to confirm replacing all existing items
- Template locking: "Lock template? Active jobs will become read-only."
- Deletion: "Delete template? This cannot be undone."

---

## 2. Data Model Conceptual Design

### 2.1 Core Entities

```
┌─────────────────────────────────────────────────────────┐
│                       TEMPLATE                          │
│  - Name (unique per organization)                       │
│  - Engine type classification                           │
│  - Version number (increments on edit)                  │
│  - Lock status (boolean)                                │
│  - Created by, Updated timestamps                       │
└─────────────────────────────────────────────────────────┘
      ↓ has many
┌─────────────────────────────────────────────────────────┐
│                   TEMPLATE SECTION                      │
│  - Section name (e.g., "TA 01 - Turbocharger")          │
│  - Display order (sequence)                             │
│  - Linked illustrations (optional)                      │
└─────────────────────────────────────────────────────────┘
      ↓ contains
┌─────────────────────────────────────────────────────────┐
│                   TEMPLATE ITEM (Part)                  │
│  - Position/sequence within section                     │
│  - Part number, description, quantity                   │
│  - Behavioral flags:                                    │
│    • always_replace (boolean)                           │
│    • big_ticket (boolean)                               │
│    • requires_test, requires_measurement (boolean)      │
│    • requires_torque, requires_photo (boolean)          │
│  - Measurement spec (label, unit, min, max)             │
│  - Replacement rules (supersedes[], bundles[])          │
└─────────────────────────────────────────────────────────┘
      ↓ belongs to (many-to-many)
┌─────────────────────────────────────────────────────────┐
│                   TEMPLATE GROUP (Kit)                  │
│  - Group code (unique identifier)                       │
│  - Group label (display name)                           │
│  - Group type (kit, measured_items, big_ticket, etc.)   │
└─────────────────────────────────────────────────────────┘
```

**Additional Supporting Entities**:

```
CANONICAL PARTS INDEX
  ├── TemplatePart (deduplicated master list)
  │    - Normalized part number
  │    - Part name
  └── TemplateOccurrence (tracks where each part appears)
       - Reference to TemplatePart
       - Reference to TemplateItem
       - Section, position, quantity (copied for fast lookup)

MEASUREMENT SPECIFICATION
  ├── Instance index (for multi-instance parts)
  ├── Label, unit, min value, max value
  └── Links to TemplateItem

ILLUSTRATION SYSTEM
  ├── IllustrationPage (diagram image)
  │    - Image path, dimensions
  │    - Natural width/height (for scaling)
  ├── IllustrationPartRow (parts list on diagram)
  ├── IllustrationPosLabel (position coordinate markers)
  └── IllustrationHotspot (clickable regions)

WIZARD STATE TRACKING
  ├── Current step (integer)
  ├── Step completion status (JSON: {step1: true, step2: false})
  ├── Step data cache (JSON: import summaries, errors, warnings)
  └── Last updated timestamp
```

### 2.2 Key Relationships

**Template → Template Item**: One-to-Many
- A template has 20-650 items (typical)
- Each item belongs to exactly one template
- Cascade delete: Deleting template removes all items

**Template Item → Template Group**: Many-to-Many
- A part can belong to multiple groups (e.g., "Kit A" + "Big Ticket Items")
- A group contains multiple parts
- Join table stores relationships

**Template Section → Illustration**: One-to-Many
- A section can have multiple diagram pages (e.g., multi-page manual)
- Each illustration belongs to one section
- Optional relationship (sections can exist without diagrams)

**Template Item → Measurement Spec**: One-to-Many
- A part with qty=1 has 0 or 1 measurement specs
- A part with qty=N can have up to N measurement specs (one per instance)
- Each spec belongs to exactly one template item

**Template → Job**: One-to-Many (outside template system)
- A template is a blueprint for many jobs
- Jobs reference template ID
- Template cannot be deleted if active jobs exist

### 2.3 Key Attributes Explained

**Behavioral Flags** (stored as booleans on Template Item):

| Flag | Purpose | Impact on Job Workflow |
|------|---------|------------------------|
| `always_replace` | Part is 100% replaced in every job | Forces "replace" decision in survey, always appears in BOM |
| `big_ticket` | High-value part requiring approval | Surfaced separately in costing, may require customer approval |
| `requires_test` | Part must be tested before decision | Triggers test workflow before technician decides keep/replace |
| `requires_measurement` | Part needs dimensional inspection | Enables measurement entry fields in survey form |
| `requires_torque` | Fastener needs torque spec | Triggers torque sequence tracking in assembly |
| `requires_photo` | Part needs photo documentation | Prompts technician to upload photo during inspection |

**Replacement Rules** (stored as JSON arrays):

- **Supersedes** (array of part numbers):
  - If technician selects Part A for replacement, automatically remove Parts B, C, D from BOM
  - Use case: Kit replaces individual components (Gasket Set → individual gaskets)

- **Bundles** (array of part numbers):
  - If technician selects Part A for replacement, automatically add Parts E, F to BOM
  - Use case: Assembly kits (Pump rebuild kit → bearings + seals + gaskets)

### 2.4 Versioning & Locking

**Version Control**:
- Template has integer `version` field
- Increments on every save operation
- Old versions **NOT retained** (just the number increases)
- Used for tracking: "This job used template v3, now template is v7"

**Lock Mechanism**:
- Boolean `is_locked` flag on Template
- When locked:
  - Only Admin users can edit
  - Technicians/Estimators have read-only access
  - Prevents accidental changes to production templates
- When to lock:
  - Template is production-ready and in active use
  - Multiple jobs depend on it
  - Changes would invalidate in-progress work

**Lock Limitation**:
- All-or-nothing: locks entire template
- Cannot lock specific sections (e.g., lock measurements but allow new parts)
- To make changes: Admin must unlock → edit → re-lock

### 2.5 Canonical Parts Index (Behind-the-Scenes Optimization)

**Purpose**: Deduplicate parts across the template

**How It Works**:
1. Template has 650 items, but many are duplicates (e.g., same bolt appearing in 14 places)
2. System builds canonical index:
   - Normalizes part numbers (removes spaces, dashes, standardizes format)
   - Groups items by normalized part number
   - Creates master "TemplatePart" record (one per unique part)
   - Creates "TemplateOccurrence" records tracking each place part appears
3. Result: 650 items → 120 canonical parts

**Use Cases**:
- Costing: Lookup price once per canonical part, apply to all occurrences
- BOM optimization: Aggregate quantities (Part ABC appears 5x with qty=2 each → total qty=10)
- Parts catalog sync: Match canonical parts to supplier catalogs

**User Visibility**: **None** (runs in background, users unaware)

---

## 3. UI/UX Patterns That Work Well

### 3.1 Multi-Lane Import Strategy

**Pattern**: Provide three parallel import pathways instead of forcing single method

**Lanes**:
1. **CSV/Excel Upload**: For shops with parts lists in spreadsheets
2. **PDF Extraction**: For shops with only manufacturer PDF catalogs
3. **Image Upload**: For shops with diagram images but no digital parts list

**Why It Works**:
- Accommodates diverse source document types
- Reduces friction: users don't need to convert formats first
- Graceful degradation: if PDF extraction fails, fallback to CSV

**Implementation Details**:
- All lanes produce same output (Template Items + Sections)
- Flexible column mapping: "part_no" ≈ "part number" ≈ "partnumber" ≈ "PartNo"
- Handles missing data: skips rows with blank part numbers, fills defaults for missing quantities

### 3.2 Step-Locked Wizard Progression

**Pattern**: Users must complete Step N before proceeding to Step N+1

**Visual Indicators**:
- Step pills at top of page (numbered 1-6)
- Current step highlighted
- Completed steps show ✓ green checkmark
- Incomplete steps are dimmed/disabled

**Why It Works**:
- Prevents incomplete setup (can't configure measurements before parts exist)
- Reduces cognitive load: focus on one task at a time
- Clear progress indicator builds confidence

**Trade-off**: Power users find it restrictive (hence Direct Editor exists)

### 3.3 Inline Table Editing

**Pattern**: Single large table with all fields editable in place (no modal dialogs)

**Interaction Style**:
- Click cell → becomes input field
- Dropdowns for flags (checkboxes in cell)
- Text inputs for part number, description, quantity
- Save triggered automatically on blur (no Save button)

**Why It Works**:
- Familiar spreadsheet-like UX
- Fast data entry (tab between cells)
- No context switching (everything on one page)

**Limitation**: Becomes unwieldy for very large templates (500+ rows)

### 3.4 Progressive Disclosure

**Pattern**: Show advanced options only when relevant

**Examples**:
- Measurement fields only appear when "requires_measurement" flag is checked
- Replacement rules (supersedes/bundles) shown in expandable panel per part
- Illustration configuration only visible for sections (not individual parts)

**Why It Works**:
- Reduces visual clutter
- Guides users to relevant fields
- Power features available but not overwhelming

### 3.5 Destructive Operation Safeguards

**Pattern**: Require explicit confirmation for destructive actions

**Mechanisms**:
- **Type-to-confirm**: User must type "WIPE" to replace existing parts
- **Checkbox confirmation**: "I understand this will delete 450 existing parts"
- **Blocking checks**: Prevent deletion if active jobs depend on template

**Why It Works**:
- Prevents accidental data loss
- Slows down user to ensure they understand consequences
- Provides escape hatch ("Are you sure?")

### 3.6 "Apply to All" Helper

**Pattern**: Copy values from first row to all similar rows

**Use Case**: Part with qty=10 requires same measurement spec for all 10 instances

**Flow**:
1. System expands part into 10 measurement rows
2. User fills first row: "Shaft Diameter | 2.000" | 1.998 | 2.002 | inches"
3. User clicks "Apply to All"
4. Values copied to rows 2-10

**Why It Works**:
- Reduces repetitive data entry (10x time savings)
- Maintains consistency (no typos across rows)
- Still allows per-instance customization if needed

### 3.7 Section-Based Organization

**Pattern**: Group parts by logical assemblies (sections)

**Visual Structure**:
- Section headers as visual dividers in parts table
- Collapse/expand sections to navigate large lists
- Section-level illustration display (diagram appears below section header)

**Why It Works**:
- Matches mental model (engine → sections → parts)
- Easier navigation (find impeller parts in "Impeller Assembly" section)
- Reduces scrolling (collapse unused sections)

### 3.8 Reusable Component Approach

**Pattern**: Same template editing form used in both wizard and standalone editor

**Benefits**:
- Consistency: editing experience identical in both flows
- Maintainability: single component to update
- Flexibility: users can switch between wizard and direct editor mid-workflow

**Implementation**: "return_to_wizard" flag allows editor to redirect back to wizard after save

---

## 4. Technical Approaches That Work

### 4.1 Flexible Data Import Pipeline

**Approach**: Build tolerance for messy, inconsistent source data

**Techniques**:
1. **Fuzzy Column Matching**
   - Normalize headers: lowercase, remove spaces/underscores
   - Match variations: "part_no" = "part number" = "partnumber" = "PartNo"
   - Fallback: allow user manual column mapping if auto-match fails

2. **Robust Parsing**
   - Handle qty as integer or string ("3" vs 3 vs "3 ea")
   - Extract part numbers from messy text ("P/N: ABC-123" → "ABC-123")
   - Skip blank rows without crashing

3. **Partial Success**
   - Import continues even if some rows fail
   - Return summary: "450 created, 5 skipped (missing part number)"
   - User can review skipped rows and re-import

**Why It Works**: Real-world PDFs and spreadsheets are messy. System adapts instead of rejecting.

### 4.2 Canonical Parts Deduplication

**Approach**: Automatically build deduplicated master parts list from raw data

**Algorithm**:
1. Normalize part numbers (remove spaces, dashes, uppercase)
2. Group template items by normalized part number
3. Create one "TemplatePart" per unique normalized part number
4. Create "TemplateOccurrence" for each item (tracks where it appears)
5. Store aggregated data: total qty across occurrences, sections where used

**Benefits**:
- BOM generation faster (aggregate quantities in single query)
- Costing simpler (lookup price once, apply to all occurrences)
- Parts catalog sync easier (match canonical parts to supplier database)

**Trade-off**: Adds complexity (two tables instead of one), but benefits compound over time

### 4.3 State Machine for Wizard Progress

**Approach**: Track wizard completion state in structured JSON

**State Schema**:
```json
{
  "current_step": 2,
  "step_status": {
    "step1": {
      "complete": true,
      "errors": [],
      "warnings": ["5 rows skipped due to missing part number"],
      "summary": {
        "rows_created": 450,
        "rows_skipped": 5,
        "sections_created": 8
      }
    },
    "step2": {
      "complete": false,
      "errors": ["Part ABC assigned to non-existent kit XYZ"]
    }
  },
  "last_updated": "2026-02-01T14:30:00Z"
}
```

**Benefits**:
- Resumable workflows (user can leave and return)
- Clear audit trail (see what happened in each step)
- Enables conditional logic (skip Step 3 if no illustrations uploaded)

**Why It Works**: Wizard can span multiple sessions; state persistence essential

### 4.4 Transactional Import Operations

**Approach**: Wrap destructive imports in database transactions

**Flow**:
1. Start transaction
2. If "replace_existing" flag: DELETE all existing Template Items
3. INSERT new Template Items
4. If any error: ROLLBACK (restore old data)
5. If success: COMMIT
6. Build canonical index (separate transaction)

**Benefits**:
- All-or-nothing: either import succeeds completely or nothing changes
- No partial states (half-deleted, half-imported)
- Safe to retry on failure

**Limitation**: Large imports (1000+ rows) can lock table briefly

### 4.5 Measurement Instance Expansion

**Approach**: Expand multi-quantity parts into individual measurement rows

**Rationale**:
- Part with qty=5 may have different measurements per instance
- E.g., 5 piston rings → each has different wear, needs individual measurement

**Implementation**:
1. Query template items where qty > 1 and requires_measurement = true
2. Expand each into qty rows with instance_index (1, 2, 3, ...)
3. Display as table rows for user to fill
4. Save each row as separate Measurement Spec record

**Trade-off**: Creates large forms (100 parts with avg qty=3 → 300 measurement rows)

### 4.6 Server-Side Auto-Save

**Approach**: No explicit Save button; every edit triggers background save

**Implementation**:
- Frontend: onBlur event on each input field → POST to API
- Backend: Updates single database record
- Response: 200 OK or error message
- Frontend displays toast notification: "Saved" or "Error: {message}"

**Benefits**:
- Users can't forget to save (no lost work)
- Immediate feedback on validation errors
- Reduces cognitive load (no "Save Changes" button to hunt for)

**Limitation**: Can create many small database transactions; requires good indexing

### 4.7 PDF Profile System

**Approach**: Define manufacturer-specific parsing rules in JSON profiles

**Profile Structure**:
```json
{
  "name": "Caterpillar",
  "section_pattern": "^\\d{3}-\\d{4}\\s+[A-Z\\s]+AS$",
  "table_columns": {
    "pos": "REF NOTE NO",
    "part_no": "PARTNUMBER",
    "name": "PARTNAME",
    "qty": "QTY"
  },
  "image_extraction": {
    "mode": "section_header",
    "min_width": 200,
    "min_height": 200
  }
}
```

**Benefits**:
- Supports multiple manufacturers without code changes (just add profile JSON)
- Auto-detection: system tries each profile, picks best match
- Fallback: if auto-detect fails, user manually selects profile

**Limitation**: Requires deep knowledge of each manufacturer's PDF format; brittle if format changes

---

## 5. Pain Points & Limitations

### 5.1 UX Friction: Dense Tables

**Problem**: Large templates (500+ rows) create massive scrolling tables

**User Impact**:
- Horizontal scroll required (10+ columns wide)
- No column hide/show configuration
- Search works but doesn't highlight results in context
- Mobile/tablet usage nearly impossible (too narrow)

**Root Cause**: Single-page table approach doesn't scale beyond ~100 rows

**Workaround**: Users resort to exporting to Excel for bulk editing

### 5.2 Destructive Operations Without Preview

**Problem**: "Replace existing" import has no diff preview

**User Impact**:
- Cannot see what will be deleted/changed before committing
- If import fails midway, partial data may be saved
- Must manually verify results after import

**Example Scenario**:
1. User uploads CSV to add 50 new parts
2. Accidentally checks "Replace existing" (should be "Append")
3. Clicks Import
4. 450 existing parts deleted, 50 new parts added
5. No undo; must restore from backup or re-import

**Mitigation**: Requires typing "WIPE" helps but doesn't show consequences

### 5.3 PDF Extraction Opacity

**Problem**: PDF import is black-box; users don't understand failure modes

**User Impact**:
- "Auto" profile selection fails silently (picks wrong profile, garbage data)
- No visibility into which profile was used
- Error messages vague: "Failed to extract table" (why? how to fix?)
- Requires external module (`pdf-parts-extractor`) with separate installation

**Root Cause**: PDF parsing is complex; abstraction hides too much

**Workaround**: Users often give up and manually transcribe PDF to CSV

### 5.4 Kit Management Fragmentation

**Problem**: Kit definition scattered across multiple UI locations

**Current State**:
- Kit name created via text input on template edit page
- Parts assigned to kit via dropdown on each part row
- Kit relationships (which parts belong together) not visualized
- No dedicated "Kit Management" page

**User Impact**:
- Difficult to see all parts in a kit at once
- Error-prone: easy to forget to assign a part to kit
- No validation: can assign part to non-existent kit (saves silently)

**Example Confusion**:
User wants to create "Gasket Set A" containing 8 gaskets:
1. Create kit name: "Gasket Set A"
2. Scroll through 450 parts, find each of 8 gaskets, set dropdown to "Gasket Set A"
3. Miss 1 gasket → kit incomplete, no warning

**Better Approach**: Dedicated UI showing kit as parent with child parts

### 5.5 Step 6 (Torque) Incomplete

**Problem**: Torque step visible but non-functional

**User Impact**:
- Users see Step 6 in navigation, assume it's required
- Click through, find minimal UI, unsure what to do
- Torque data stored in database but not editable via wizard
- Feels half-baked; users lose confidence in product

**Root Cause**: Feature partially implemented then abandoned

**Recommendation**: Either complete feature or hide step until ready

### 5.6 No Bulk Actions

**Problem**: Cannot bulk-edit multiple parts at once

**Missing Capabilities**:
- Select 20 parts → tag all as "big ticket"
- Select 50 parts → assign all to same kit
- Select parts by section → delete all at once
- Find-and-replace part numbers (e.g., update supplier numbering)

**User Impact**:
- Repetitive clicking (tag 20 parts = 20 individual clicks)
- Time-consuming for large templates
- Tedious to make sweeping changes (e.g., change all qty=1 to qty=2)

**Workaround**: Export to Excel, bulk edit, re-import (loses other data)

### 5.7 Measurement Workflow Duplication

**Problem**: Measurement specs editable in two places

**Locations**:
1. Wizard Step 5: Measurement configuration form
2. Separate "Measurements" page (outside wizard)

**User Impact**:
- Confusion: "Where should I edit measurements?"
- No sync warnings: edit in one place, other place shows stale data until refresh
- Inconsistent UX: different layouts for same data

**Root Cause**: Measurements added to wizard after standalone page existed

**Recommendation**: Unify into single editor; remove duplicate

### 5.8 Pre-Survey Isolation

**Problem**: Pre-survey checklist configuration separate from wizard flow

**Current State**:
- Pre-survey is Step 0 (before inspection)
- Configured on separate "Pre-Survey Form" page (not in wizard)
- No guidance on typical pre-survey questions for an engine type
- No template: users must create from scratch

**User Impact**:
- Users forget to configure pre-survey (it's optional and hidden)
- Inconsistent pre-surveys across templates (no standardization)
- No best practices captured

**Example**:
Template for MAN D0836 engine created without pre-survey.
Technician starts job, no pre-survey checklist → manual notes on paper → defeats purpose of digital workflow.

**Better Approach**: Integrate pre-survey config into wizard Step 1 with pre-built templates

### 5.9 No Validation or Dry-Run

**Problem**: Cannot test template before jobs depend on it

**Missing Features**:
- Preview: see what survey form looks like before template goes live
- Validation warnings:
  - Part flagged "always_replace" AND "requires_test" (conflict?)
  - Part has qty=3 but only 1 measurement spec (incomplete?)
  - Kit references part that doesn't exist
- Dry-run: simulate job creation with this template (no database writes)

**User Impact**:
- Bad templates propagate to jobs
- Discover issues only when technician complains: "Measurement fields are wrong"
- Must edit template while jobs in progress (risky)

**Example**:
Template has part "Bearing XYZ" with qty=4 and requires_measurement=true.
Admin forgets to add measurement specs in Step 5.
Technician opens job → sees "Bearing XYZ" requires measurement but no fields to enter values.
Admin must unlock template, add specs, re-lock → disrupts in-progress jobs.

### 5.10 Canonical Parts Invisible

**Problem**: Backend tracks canonical parts but users never see them

**Current State**:
- System deduplicates parts into canonical index
- No UI to view canonical parts list
- No UI to review occurrences (where each canonical part appears)
- Quantities aggregated in background (users don't see total qty across occurrences)

**User Impact**:
- Mental gap: "Why does BOM show qty=14 but template item says qty=2?"
- Confusion when syncing to external systems (Epicor, stores)
- No insight into part usage patterns (e.g., "Bolt ABC used in 9 different sections")

**Example**:
Part "Bolt M10x50" appears:
- Section A: qty=4
- Section B: qty=6
- Section C: qty=4
Total: qty=14

Template shows 3 separate rows. BOM shows 1 row with qty=14.
User: "Where did qty=14 come from?"

**Better Approach**: Show canonical parts view with occurrence drill-down

### 5.11 Costing Integration Disconnect

**Problem**: Costing template upload separate from main template editor

**Current State**:
- Main template: parts list with flags, measurements, kits
- Costing template: Excel upload with part costs, menu prices, suppliers
- No validation that costing lines match template items
- Match status tracked in database but not visible in template editor

**User Impact**:
- Costing sheet can drift out of sync with template
- Parts added to template but missing in costing → BOM generation fails
- No warnings: "10 parts in template not found in costing catalog"

**Root Cause**: Costing module built separately; integration incomplete

**Recommendation**: Show costing status per part in template editor (e.g., "Cost: $45.00" or "⚠ Not in catalog")

### 5.12 Lock Feature Too Coarse

**Problem**: Template-level lock is all-or-nothing

**Current Behavior**:
- Lock template → entire template read-only (except for Admin)
- Cannot lock specific sections (e.g., lock measurements but allow adding new parts)
- Must unlock entire template to make any change
- Active jobs prevent unlocking (must wait until all jobs complete)

**User Impact**:
- Inflexible: can't hotfix measurement spec while jobs in progress
- Risky: unlocking template allows any changes (including destructive)
- Blocks urgent edits (must create new template as workaround)

**Example**:
Technician discovers measurement spec for "Shaft Diameter" has wrong max value (2.002" should be 2.005").
Template is locked, 5 active jobs.
Admin must: wait for jobs to complete OR unlock template (risky) OR create duplicate template with fix.

**Better Approach**: Granular locking (lock items, lock measurements, lock sections independently)

---

## 6. Improvement Recommendations

### 6.1 If Rebuilding from Scratch

#### **Start with Single Editor, Not Wizard**

**Rationale**:
- Wizard adds complexity (state tracking, step locking, navigation)
- Most edits are targeted (change 1-5 parts), not full import
- Power users prefer direct access to all fields

**Recommended Flow**:
1. Single-page editor as primary interface (table-based)
2. Add "Import Wizard" as optional guided flow (not default)
3. Wizard for initial setup only; after that, use editor

**Benefits**:
- Simpler codebase (one editor component vs. two)
- Faster iteration (no step state management)
- Users discover features organically (not forced progression)

---

#### **Unify Measurement Editing**

**Current Problem**: Measurements editable in two places

**Proposed Solution**:
- Single "Measurements" tab in template editor
- Show measurements as collapsible sections within parts table:
  ```
  Part ABC | Bearing
  └─ Measurement: Bore Diameter | 2.000±0.002 | inches
  ```
- Or: dedicated sub-page with filter-by-section

**Benefits**:
- No duplication
- Clear single source of truth
- Easier to validate (all measurement specs in one view)

---

#### **Make Kits First-Class**

**Current Problem**: Kits are just labels; no dedicated UI

**Proposed Solution**:
1. **Kit Management Page**:
   - List all kits
   - For each kit: show member parts in tree view
   - Add/remove parts via drag-and-drop or checkboxes
2. **Kit Definition Wizard**:
   - Step 1: Kit name, kit type (assembly, replacement, menu)
   - Step 2: Select member parts (checkboxes on parts list)
   - Step 3: Define kit rules (supersedes, bundles)

**Visual Mockup**:
```
Kit: Gasket Set A
├── Part 1: Cylinder head gasket (qty=1)
├── Part 2: Valve cover gasket (qty=1)
└── Part 3: Oil pan gasket (qty=1)

Rules:
  - If kit selected, remove individual gaskets from BOM
  - Bundle: Add gasket sealant (Part 99)
```

**Benefits**:
- Visualize kit structure at a glance
- Validate: all kit members exist
- Easier to edit (no hunting through 450-row table)

---

#### **Add Validation & Preview**

**Current Problem**: No way to test template before jobs use it

**Proposed Features**:

1. **Live Preview**:
   - "Preview Survey Form" button
   - Shows exactly what technician will see
   - Includes: sections, parts, measurement fields, flags
   - Updates live as template is edited

2. **Validation Checks** (run before Save):
   - Conflicts: part flagged "always_replace" + "requires_test" (warn user)
   - Incomplete: part with qty>1 has fewer measurement specs than qty (warn)
   - Orphans: kit references part that doesn't exist (error, block save)
   - Duplicates: same part number in multiple sections (warn if unintentional)

3. **Dry-Run Mode**:
   - "Simulate Job" button
   - Creates temporary job (not saved to DB)
   - User walks through inspection workflow
   - Identifies UX issues before template goes live

**Benefits**:
- Catch errors before propagation
- Builds user confidence ("I know this works")
- Reduces support requests ("Survey form is broken")

---

#### **Simplify PDF Integration**

**Current Problem**: PDF extraction is opaque and brittle

**Proposed Approach**:

1. **Option A: Simplify to Text Extraction Only**
   - Extract plain text from PDF
   - User maps columns manually (drag headers to columns)
   - No profile system (too complex)
   - Trade-off: More manual work, but transparent

2. **Option B: Improve Profile Transparency**
   - Show which profile was selected: "Using Caterpillar profile"
   - Allow user to override: "Not working? Try MAN profile"
   - Show extraction preview before import: "Found 450 rows, 8 sections"
   - Provide download link for profile JSON (power users can customize)

3. **Option C: Hybrid Approach**
   - Default: Text extraction + manual mapping
   - Advanced: Profile-based (opt-in for power users)
   - Best of both worlds: simple for most, powerful for experts

**Benefits**:
- Reduces support burden (fewer "PDF import failed" tickets)
- Increases user confidence (transparency)
- Still supports automated extraction for those who need it

---

#### **Implement Versioning & Rollback**

**Current Problem**: No version history; edits are irreversible

**Proposed System**:

1. **Version History**:
   - Save snapshot of template on every edit
   - Store: version number, edited by, edited at, change summary
   - UI: "Template History" page showing all versions

2. **Rollback**:
   - "Restore Version" button
   - Creates new version (doesn't delete current)
   - Warning: "3 active jobs use current version. Restoring will create conflicts."

3. **Diff View**:
   - Compare two versions side-by-side
   - Highlight changes: added parts (green), removed parts (red), modified (yellow)

**Benefits**:
- Safety net: mistakes are reversible
- Audit trail: see who changed what and when
- Debugging: "Version 5 worked, version 6 broke → what changed?"

---

#### **Add Bulk Editing**

**Current Problem**: One-by-one editing tedious for large templates

**Proposed Features**:

1. **Multi-Select**:
   - Checkboxes on each row
   - Select multiple parts
   - Bulk actions: Delete, Tag, Assign to kit, Set flag

2. **Find & Replace**:
   - Search: part_no contains "ABC"
   - Replace with: "XYZ"
   - Confirm: "Replace 14 occurrences?"

3. **Spreadsheet Import/Export**:
   - Export to Excel (all fields editable)
   - Bulk edit in Excel
   - Re-import with merge (only update changed rows)

**Benefits**:
- 10x faster for large templates
- Reduces errors (set flag once for 20 parts vs. 20 individual clicks)
- Improves user satisfaction (less tedium)

---

### 6.2 Modern UX Patterns to Adopt

#### **Infinite Scroll with Virtualization**

**Problem Solved**: Large tables (500+ rows) cause slow rendering

**Approach**:
- Render only visible rows (e.g., 50 rows at a time)
- As user scrolls, load next batch dynamically
- Total DOM elements stays low (fast performance)

**Libraries**: React Virtualized, TanStack Virtual

---

#### **Inline Search with Highlighting**

**Problem Solved**: Search filters table but doesn't highlight matches

**Approach**:
- Search highlights matching text in yellow
- Auto-scrolls to first match
- "Next" / "Previous" buttons to navigate matches
- Shows count: "3 of 12 matches"

**Example**:
User searches "bearing" → all rows with "bearing" in description highlighted, scrolls to first match.

---

#### **Drag-and-Drop Reordering**

**Problem Solved**: Changing part order (position within section) requires manual number editing

**Approach**:
- Drag part rows to reorder
- Position numbers auto-update
- Visual feedback (drop zone indicator)

**Libraries**: React DnD, dnd-kit

---

#### **Toast Notifications Instead of Alerts**

**Problem Solved**: Browser alerts are jarring, block workflow

**Approach**:
- Non-blocking toast messages (bottom-right corner)
- Auto-dismiss after 5 seconds
- Color-coded: green (success), red (error), yellow (warning)

**Example**:
Save → "✓ Template saved" toast appears, fades out after 5 seconds.

---

#### **Keyboard Shortcuts**

**Problem Solved**: Mouse-only interaction is slow

**Proposed Shortcuts**:
- `Ctrl+S` - Save template
- `Ctrl+F` - Focus search box
- `Ctrl+K` - Quick command palette (search actions)
- `Tab` / `Shift+Tab` - Navigate between cells
- `Enter` - Edit cell, save on blur

---

#### **Contextual Help Tooltips**

**Problem Solved**: Users unsure what flags/fields mean

**Approach**:
- Hover over flag → tooltip: "Always Replace: Part is replaced in every job, regardless of condition"
- Inline help icons: `?` next to complex fields
- Link to docs: "Learn more about measurement specs"

---

### 6.3 Features That Would Add Most Value

#### **Pre-Built Template Library**

**Proposal**: Curated library of common engine types

**Includes**:
- MAN D0836, D2866
- CAT 3304, 3512
- Cummins 6BT, N14
- Detroit Series 60

**How It Works**:
1. User creates new template
2. Option: "Start from library template" (dropdown)
3. System clones library template
4. User customizes for their shop

**Benefits**:
- 80% time savings (don't start from scratch)
- Best practices built-in (pre-configured flags, kits)
- Consistency across shops (industry standardization)

---

#### **Template Marketplace (Community)**

**Proposal**: Users share templates with each other

**Features**:
- Upload template to marketplace (public or private)
- Search/browse by engine type, manufacturer
- Rate templates (5-star system)
- Download count, last updated
- Comments/reviews

**Monetization** (optional):
- Premium templates ($10-50 each)
- Revenue share: 70% to creator, 30% to platform

**Benefits**:
- Network effect: platform gets more valuable as users contribute
- Reduces setup friction (new users start with templates)
- Monetization opportunity

---

#### **Automated Supersedes Detection**

**Proposal**: AI-powered kit/supersedes rule suggestion

**How It Works**:
1. User imports parts list
2. System analyzes part numbers and descriptions
3. Identifies potential kits (e.g., "Gasket Set" + 8 individual gaskets)
4. Suggests supersedes rules: "Did you mean: Gasket Set → {part1, part2, ...}?"
5. User confirms or rejects

**Underlying Tech**:
- String similarity (part descriptions containing "gasket")
- Pattern matching (kit part numbers often share prefix)
- Machine learning (trained on existing templates)

**Benefits**:
- Saves manual kit configuration
- Reduces errors (auto-detects related parts)
- Teaches users: "Oh, I should create a kit for these!"

---

#### **Mobile-Optimized View**

**Proposal**: Dedicated mobile interface for tablet use

**Features**:
- Card-based layout (not table)
- Swipe to navigate between parts
- Large touch targets (buttons 44px min)
- Simplified: show only essential fields, hide advanced

**Use Case**: Estimator on shop floor with tablet reviewing template while looking at physical parts.

**Benefits**:
- Field usability (tablets on shop floor)
- Faster adoption (no laptop required)
- Improves accuracy (review template where parts are)

---

#### **Changelog & Notifications**

**Proposal**: Track template changes and notify affected users

**Features**:
1. **Changelog**:
   - Every edit logged: "Admin added part ABC (qty=2) to Section 5"
   - Visible on template detail page
   - Filter by date, user, action type

2. **Notifications**:
   - When template changes, notify users with active jobs
   - Email/in-app: "Template XYZ updated. 3 of your jobs use this template."
   - Option to review changes or continue with old version

**Benefits**:
- Transparency: users see what changed
- Coordination: team aware of edits
- Prevents surprises: "Why did my survey form change?"

---

## Conclusion

### Summary: What Works

The template editor demonstrates several strong design decisions:

1. **Flexibility**: Multi-lane import (CSV, PDF, images) accommodates diverse workflows
2. **Progressive Disclosure**: Advanced features available but not overwhelming
3. **Safety**: Destructive operations require explicit confirmation
4. **Reusability**: Single editor component serves both wizard and standalone flows

### Summary: What Needs Improvement

Key pain points that limit usability:

1. **Scalability**: Dense tables break down beyond 100-200 rows
2. **Validation**: No preview or dry-run before template goes live
3. **Kit Management**: Fragmented UI makes kit creation error-prone
4. **Measurement Duplication**: Two places to edit same data
5. **PDF Opacity**: Extraction failures are opaque and frustrating

### Recommendations for Future Builders

If designing a similar system:

1. **Start Simple**: Single-page editor, add wizard later only if data import is complex
2. **Validate Early**: Show previews, run checks, let users test before production
3. **Unify Editing**: One place per entity (measurements in one tab, not two)
4. **Bulk Operations**: Multi-select, find-replace, spreadsheet import/export
5. **Transparent Automation**: If system does magic (PDF extraction, canonical parts), show users what happened

**Final Insight**: The best template editor is one that users barely notice—it captures their expertise quickly, prevents errors proactively, and gets out of their way so they can focus on the work, not the tool.

---

**End of Design Analysis**

*Document Version: 1.0*
*Analysis Date: February 2, 2026*
