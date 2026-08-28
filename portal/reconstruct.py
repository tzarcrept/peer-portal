"""
Converts model querysets into the row-list shape the Add/Edit form (and its JavaScript)
expect, and provides blank default rows for a brand-new project.
"""

from . import constants


# ==================== DEFAULT (BLANK) ROWS ====================

def default_equipment_row():
    return {"category_sel": constants.PLACEHOLDER, "category_custom": "", "tag": "", "count": 1,
            "params": [{"label": "", "val": ""}]}


def default_prerequisite_row():
    return {"type_sel": constants.PLACEHOLDER, "type_custom": "",
            "status": constants.PREREQUISITE_STATUSES[0], "remarks": ""}


def default_event_row():
    return {"event_name": "", "planned_start": "", "planned_finish": "", "duration": 1,
            "actual_start": "", "actual_finish": "", "criticality_rating": 1,
            "status": constants.PLACEHOLDER, "progress_pct": 0, "remarks": ""}


def default_official_row():
    return {"name": "", "designation": "", "department": "", "employee_id": ""}


def default_approval_rows_list():
    return [{"type": a_type, "status": constants.PLACEHOLDER, "date": ""} for a_type in constants.APPROVAL_TYPES]


# ==================== FROM SAVED MODEL QUERYSETS (edit mode) ====================

def equipment_rows_from_queryset(equipment_qs):
    rows = []
    for item in equipment_qs:
        if item.category in constants.STANDARD_CATEGORIES:
            category_sel, category_custom = item.category, ""
        else:
            category_sel, category_custom = "Other (Custom)", item.category
        params = [{"label": k, "val": v} for k, v in item.custom_params.items()]
        if not params:
            params = [{"label": "", "val": ""}]
        rows.append({
            "category_sel": category_sel,
            "category_custom": category_custom,
            "tag": item.tag,
            "count": item.count,
            "params": params,
        })
    return rows if rows else [default_equipment_row()]


def prereq_rows_from_queryset(prereq_qs):
    rows = []
    for p in prereq_qs:
        if p.type in constants.PREREQUISITE_TYPES:
            type_sel, type_custom = p.type, ""
        else:
            type_sel, type_custom = "Other (Custom)", p.type
        rows.append({
            "type_sel": type_sel,
            "type_custom": type_custom,
            "status": p.status,
            "remarks": p.remarks,
        })
    return rows if rows else [default_prerequisite_row()]


def approval_rows_from_queryset(approval_qs):
    by_type = {a.approval_type: a for a in approval_qs}
    rows = []
    for a_type in constants.APPROVAL_TYPES:
        approval = by_type.get(a_type)
        if approval is None:
            rows.append({"type": a_type, "status": constants.PLACEHOLDER, "date": ""})
            continue
        status = approval.status if approval.status in constants.APPROVAL_STATUSES else constants.PLACEHOLDER
        date_val = "" if approval.date in (None, "N/A") else approval.date
        rows.append({"type": a_type, "status": status, "date": date_val})
    return rows


def event_rows_from_queryset(event_qs):
    rows = []
    for e in event_qs:
        rating = min(max(e.criticality_rating or 1, 1), 5)
        progress = min(max(int(getattr(e, "progress_pct", 0) or 0), 0), 100)
        rows.append({
            "event_name": e.event_name,
            "planned_start": e.planned_start,
            "planned_finish": e.planned_finish,
            "duration": e.duration or 1,
            "actual_start": e.actual_start,
            "actual_finish": e.actual_finish,
            "criticality_rating": rating,
            "status": e.status if e.status in constants.EVENT_STATUSES else constants.PLACEHOLDER,
            "progress_pct": progress,
            "remarks": e.remarks,
        })
    return rows if rows else [default_event_row()]


def official_rows_from_queryset(official_qs):
    rows = [
        {"name": o.name, "designation": o.designation, "department": o.department, "employee_id": o.employee_id}
        for o in official_qs
    ]
    return rows if rows else [default_official_row()]


# ==================== FROM SUBMITTED (BUT REJECTED) FORM DATA ====================

def approval_rows_from_submitted_dict(approval_rows):
    """Used when re-showing the form after a validation error, so the user's
    approval selections aren't lost."""
    rows = []
    for a_type in constants.APPROVAL_TYPES:
        details = approval_rows.get(a_type, {})
        status = details.get("status", constants.PLACEHOLDER)
        rows.append({
            "type": a_type,
            "status": status if status in constants.APPROVAL_STATUSES else constants.PLACEHOLDER,
            "date": details.get("date", ""),
        })
    return rows
