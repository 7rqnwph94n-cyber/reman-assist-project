from models import (
    db,
    Job,
    SurveyItem,
    TemplateItem,
    PartRequirement,
    StockStatusEnum,
    DecisionEnum,
)


def prune_good_parts(job_id: int) -> None:
    """Remove BOM lines whose survey decision is REUSE (and not always-replace)."""
    parts = PartRequirement.query.filter_by(job_id=job_id).all()
    survey_items = {si.id: si for si in SurveyItem.query.filter_by(job_id=job_id).all()}
    to_delete = []
    for p in parts:
        si = survey_items.get(getattr(p, "survey_item_id", None))
        if si and not si.always_replace and si.decision == DecisionEnum.REUSE:
            to_delete.append(p.id)
    if to_delete:
        PartRequirement.query.filter(PartRequirement.id.in_(to_delete)).delete(synchronize_session=False)
        db.session.flush()


def apply_supersedes(job_id: int) -> None:
    """If a kit/assembly line supersedes other part numbers, drop those from BOM."""
    job = db.session.get(Job, job_id)
    if not job or not job.template_id:
        return

    tmpl_items = TemplateItem.query.filter_by(template_id=job.template_id).all()
    supersede_map = {}
    bundle_map = {}
    for ti in tmpl_items:
        if not ti.supersedes:
            continue
        try:
            targets = [p.strip().lower() for p in ti.supersedes.split(",") if p.strip()]
        except Exception:
            targets = []
        if targets:
            key = (ti.part_no or "").strip().lower()
            supersede_map[key] = targets
        if ti.bundles:
            try:
                btargets = [p.strip().lower() for p in ti.bundles.split(",") if p.strip()]
            except Exception:
                btargets = []
            if btargets:
                key = (ti.part_no or "").strip().lower()
                bundle_map[key] = btargets

    if not supersede_map:
        supersede_map = {}

    survey_items = SurveyItem.query.filter_by(job_id=job_id).all()
    survey_by_part = {
        (si.part_no or "").strip().lower(): si for si in survey_items if si.part_no
    }

    # Build case-insensitive lookup of BOM rows
    pr_all = PartRequirement.query.filter_by(job_id=job_id).all()
    pr_by_part_lower = {}
    for pr in pr_all:
        key = (pr.part_no or "").strip().lower()
        if key:
            pr_by_part_lower.setdefault(key, []).append(pr)

    to_delete = []
    to_add = []
    for kit_part_no, targets in supersede_map.items():
        if not kit_part_no:
            continue
        kit_si = survey_by_part.get(kit_part_no)
        if not kit_si:
            continue
        if not (kit_si.always_replace or kit_si.decision in (DecisionEnum.REPLACE, DecisionEnum.SCRAP)):
            continue
        for tgt in targets:
            matches = pr_by_part_lower.get(tgt)
            if matches:
                to_delete.extend([p.id for p in matches])

    for kit_part_no, targets in bundle_map.items():
        if not kit_part_no:
            continue
        kit_si = survey_by_part.get(kit_part_no)
        if not kit_si:
            continue
        if not (kit_si.always_replace or kit_si.decision in (DecisionEnum.REPLACE, DecisionEnum.SCRAP)):
            continue
        for tgt in targets:
            existing = pr_by_part_lower.get(tgt)
            if existing:
                continue
            src_si = survey_by_part.get(tgt)
            if src_si:
                pr = PartRequirement(
                    job_id=job_id,
                    survey_item_id=src_si.id,
                    section=src_si.section,
                    pos=src_si.pos,
                    part_no=src_si.part_no,
                    name=src_si.name,
                    qty_required=src_si.qty or 1,
                    stock_status=StockStatusEnum.TO_ORDER,
                )
                to_add.append(pr)

    if to_delete:
        PartRequirement.query.filter(PartRequirement.id.in_(to_delete)).delete(synchronize_session=False)
        db.session.flush()
    if to_add:
        db.session.add_all(to_add)
        db.session.flush()
