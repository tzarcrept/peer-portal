import csv
import json
from urllib.parse import quote

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import ai_insights, analytics, constants
from . import reconstruct as rc
from .models import Approval, Equipment, Event, Official, Prerequisite, Project


# ==================== VIEW: Portfolio Dashboard ====================

def dashboard(request):
    """Portfolio-level overview: KPIs, health mix, ranked project table, AI insight.

    All figures come from analytics.analyse_portfolio(). The AI panel is additive --
    if it falls back to rule-based narrative, everything else on the page is identical.
    """
    projects = list(Project.objects.prefetch_related(
        "events", "prerequisites", "approvals", "equipment_items"
    ).order_by("name"))

    portfolio = analytics.analyse_portfolio(projects)
    insight = ai_insights.portfolio_insight(portfolio) if projects else None

    # Blended portfolio S-curve: mean planned/actual across projects, resampled onto a
    # shared monthly axis so the curves are comparable rather than jagged.
    portfolio_curve = _blended_curve(projects)

    category_rows = sorted(
        (
            {"category": name, "count": data["count"],
             "avg_variance": data["avg_variance"], "budget": data["budget"]}
            for name, data in portfolio["by_category"].items()
        ),
        key=lambda r: r["avg_variance"],
    )

    return render(request, "portal/dashboard.html", {
        "portfolio": portfolio,
        "insight": insight,
        "portfolio_curve": portfolio_curve,
        "category_rows": category_rows,
        "ai_configured": ai_insights.ai_is_configured(),
        "has_projects": bool(projects),
    })


def _blended_curve(projects):
    """Average the planned and actual curves of every project onto one axis.

    Each project's curve is sampled on its own dates, so they are first interpolated
    onto a common set of dates (the union of all sample dates, thinned to ~40 points)
    before averaging. Projects contribute equally.
    """
    from datetime import date

    series = []
    for project in projects:
        curves = analytics.build_s_curves(list(project.events.all()))
        if curves["has_data"]:
            series.append(curves)
    if not series:
        return {"has_data": False, "points": []}

    all_dates = sorted({p["date"] for c in series for p in c["points"]})
    if len(all_dates) > 40:
        stride = len(all_dates) // 40 + 1
        thinned = all_dates[::stride]
        if all_dates[-1] not in thinned:
            thinned.append(all_dates[-1])
        all_dates = thinned

    today = date.today().isoformat()
    points = []
    for sample in all_dates:
        planned_vals, actual_vals = [], []
        for curve in series:
            planned_vals.append(_interpolate(curve["points"], sample, "planned"))
            if sample <= today:
                actual_vals.append(_interpolate(curve["points"], sample, "actual"))
        planned = sum(planned_vals) / len(planned_vals) if planned_vals else 0.0
        actual = sum(actual_vals) / len(actual_vals) if actual_vals else None
        points.append({
            "date": sample,
            "planned": round(planned, 2),
            "actual": round(actual, 2) if actual is not None else None,
        })

    return {"has_data": True, "points": points, "today": today}


def _interpolate(points, target_date, key):
    """Value of `key` at `target_date`, holding flat outside the series' own range."""
    previous = 0.0
    for point in points:
        value = point.get(key)
        if value is None:
            value = previous
        if point["date"] >= target_date:
            return value
        previous = value
    return previous


# ==================== VIEW: Project Analytics ====================

def project_dashboard(request, project_name=None):
    """Per-project analytics: both S-curves, KPIs, ranked critical activities, insight."""
    project_names = list(Project.objects.order_by("name").values_list("name", flat=True))

    selected = project_name or request.GET.get("project")
    if selected not in project_names:
        selected = project_names[0] if project_names else None

    context = {"project_names": project_names, "selected_proj": selected,
               "ai_configured": ai_insights.ai_is_configured()}

    if selected:
        project = Project.objects.prefetch_related(
            "events", "prerequisites", "approvals", "equipment_items"
        ).get(name=selected)
        analysis = analytics.analyse_project(project)
        context.update({
            "analysis": analysis,
            "curves": analysis["curves"],
            "insight": ai_insights.project_insight(analysis),
            "equipment_rows": sorted(
                analysis["equipment_by_category"].items(), key=lambda kv: -kv[1]
            ),
        })

    return render(request, "portal/project_dashboard.html", context)


@require_POST
def refresh_insight(request, project_name):
    """Force a fresh model call, bypassing the cache. Always returns JSON, never 500s."""
    try:
        if project_name == "__portfolio__":
            projects = list(Project.objects.prefetch_related(
                "events", "prerequisites", "approvals", "equipment_items"))
            insight = ai_insights.portfolio_insight(
                analytics.analyse_portfolio(projects), force_refresh=True)
        else:
            project = Project.objects.prefetch_related(
                "events", "prerequisites", "approvals", "equipment_items"
            ).get(name=project_name)
            insight = ai_insights.project_insight(
                analytics.analyse_project(project), force_refresh=True)
        return JsonResponse({"ok": True, "insight": insight})
    except Project.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Project not found."}, status=404)
    except Exception as exc:  # noqa: BLE001 -- endpoint must never surface a 500
        return JsonResponse({"ok": False, "error": f"{type(exc).__name__}"}, status=200)


# ==================== VIEW: Project Repository ====================

def repository(request):
    """Full detail sheet for one project."""
    project_names = list(Project.objects.order_by("name").values_list("name", flat=True))

    selected_proj = request.GET.get("project")
    if selected_proj not in project_names:
        selected_proj = project_names[0] if project_names else None

    context = {"project_names": project_names, "selected_proj": selected_proj}

    if selected_proj:
        project = Project.objects.get(name=selected_proj)
        equipment_items = list(project.equipment_items.all())
        total_units = sum(item.count for item in equipment_items)

        additional_fields = [
            ("Registration No.", project.reg_no),
            ("Registration Date", project.reg_date),
            ("AR No.", project.ar_no),
            ("Actual Expenditure", project.actual_expenditure),
            ("Target / ETC", project.target_etc),
            ("Area / Unit", project.area_unit),
            ("Project Category", project.project_category),
            ("Nature of Project", project.nature_of_project),
            ("Projected Savings", project.projected_savings),
            ("IRR", project.irr),
        ]
        additional_fields = [(label, value if value else "N/A") for label, value in additional_fields]

        category_groups = {}
        for item in equipment_items:
            specs = {"Category": item.category, "Count": item.count, **item.custom_params}
            category_groups.setdefault(item.category, []).append({"tag": item.tag, "specs": specs})

        approvals_by_type = {a.approval_type: a for a in project.approvals.all()}
        approvals = {
            a_type: {
                "status": approvals_by_type[a_type].status if a_type in approvals_by_type else "N/A",
                "date": approvals_by_type[a_type].date if a_type in approvals_by_type else "N/A",
            }
            for a_type in constants.APPROVAL_TYPES
        }

        context.update({
            "meta": project,
            "total_units": total_units,
            "additional_fields": additional_fields,
            "officials": project.officials.all(),
            "prerequisites": project.prerequisites.all(),
            "approvals": approvals,
            "events": project.events.all(),
            "equipment_category_groups": category_groups,
            "has_equipment": bool(equipment_items),
        })

    return render(request, "portal/repository.html", context)


@require_POST
def delete_project(request, project_name):
    deleted, _ = Project.objects.filter(name=project_name).delete()
    if deleted:
        messages.success(request, f"Project '{project_name}' deleted.")
    else:
        messages.error(request, f"Project '{project_name}' not found.")
    return redirect("repository")


# ==================== EXPORTS ====================

def download_csv(request):
    """Raw export: every project and everything under it, one row per project."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="peer_project_data.csv"'

    rows = [_flatten_project(project) for project in Project.objects.order_by("name")]
    if not rows:
        return response

    fieldnames = sorted({key for row in rows for key in row.keys()})
    writer = csv.DictWriter(response, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return response


def download_analytics_csv(request):
    """Analytics export: the computed metrics, one row per project.

    This is the file you would hand to someone doing further analysis in Excel or
    a BI tool -- it contains the derived figures, not the raw sheet contents.
    """
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="peer_analytics.csv"'

    projects = list(Project.objects.prefetch_related(
        "events", "prerequisites", "approvals", "equipment_items").order_by("name"))
    portfolio = analytics.analyse_portfolio(projects)

    writer = csv.writer(response)
    writer.writerow([
        "project", "category", "nature", "area_unit", "planned_pct_complete",
        "actual_pct_complete", "schedule_variance_points", "spi", "health",
        "open_blockers", "late_activities", "budget", "spent", "cost_overrun_flag",
        "planned_completion", "forecast_completion", "forecast_slip_days",
    ])
    for row in portfolio["rows"]:
        forecast = row["forecast"] or {}
        writer.writerow([
            row["name"], row["category"], row["nature"], row["area_unit"],
            row["planned_pct"], row["actual_pct"], row["variance"],
            row["spi"] if row["spi"] is not None else "",
            row["health"]["label"], row["blocker_count"], row["critical_count"],
            row["budget"] if row["budget"] is not None else "",
            row["spent"] if row["spent"] is not None else "",
            "YES" if row["cost_flag"] else "NO",
            forecast.get("planned_completion", ""),
            forecast.get("forecast_completion", ""),
            forecast.get("slip_days", ""),
        ])
    return response


def _flatten_project(project):
    """Flattens one Project and all its related rows into a single flat dict."""
    out = {"name": project.name}
    for field in ["reg_no", "reg_date", "ar_no", "budget", "actual_expenditure", "contractor",
                  "start_date", "completion_date", "target_etc", "area_unit", "project_category",
                  "nature_of_project", "projected_savings", "irr"]:
        out[field] = getattr(project, field)

    for i, o in enumerate(project.officials.all()):
        out[f"official_{i}_name"] = o.name
        out[f"official_{i}_designation"] = o.designation
        out[f"official_{i}_department"] = o.department
        out[f"official_{i}_employee_id"] = o.employee_id

    for i, p in enumerate(project.prerequisites.all()):
        out[f"prerequisite_{i}_type"] = p.type
        out[f"prerequisite_{i}_status"] = p.status
        out[f"prerequisite_{i}_remarks"] = p.remarks

    for a in project.approvals.all():
        key = a.approval_type.replace(" ", "_").replace("/", "-")
        out[f"approval_{key}_status"] = a.status
        out[f"approval_{key}_date"] = a.date

    for i, e in enumerate(project.events.all()):
        out[f"event_{i}_name"] = e.event_name
        out[f"event_{i}_planned_start"] = e.planned_start
        out[f"event_{i}_planned_finish"] = e.planned_finish
        out[f"event_{i}_duration"] = e.duration
        out[f"event_{i}_actual_start"] = e.actual_start
        out[f"event_{i}_actual_finish"] = e.actual_finish
        out[f"event_{i}_criticality_rating"] = e.criticality_rating
        out[f"event_{i}_progress_pct"] = e.progress_pct
        out[f"event_{i}_status"] = e.status
        out[f"event_{i}_remarks"] = e.remarks

    for eq in project.equipment_items.all():
        prefix = f"equipment_{eq.tag}"
        out[f"{prefix}_category"] = eq.category
        out[f"{prefix}_count"] = eq.count
        for key, val in eq.custom_params.items():
            out[f"{prefix}_{key}"] = val

    return out


# ==================== VIEW: Add / Edit Project ====================

def project_form(request, project_name=None):
    """GET -> blank or pre-filled form. POST -> validate and save."""
    editing = project_name is not None

    if request.method == "POST":
        return _handle_save(request, project_name)

    if editing:
        try:
            project = Project.objects.get(name=project_name)
        except Project.DoesNotExist:
            messages.error(request, f"Project '{project_name}' not found.")
            return redirect("repository")

        initial = {
            "proj_name": project.name,
            "reg_no": project.reg_no,
            "reg_date": project.reg_date,
            "ar_no": project.ar_no,
            "budget": _clean(project.budget),
            "actual_expenditure": project.actual_expenditure,
            "contractor": _clean(project.contractor),
            "start_date": project.start_date,
            "comp_date": project.completion_date,
            "target_etc": project.target_etc,
            "area_unit": project.area_unit,
            "project_category": project.project_category,
            "nature_of_project": project.nature_of_project,
            "projected_savings": project.projected_savings,
            "irr": project.irr,
        }
        equipment_rows = rc.equipment_rows_from_queryset(project.equipment_items.all())
        prereq_rows = rc.prereq_rows_from_queryset(project.prerequisites.all())
        approval_rows_list = rc.approval_rows_from_queryset(project.approvals.all())
        event_rows = rc.event_rows_from_queryset(project.events.all())
        official_rows = rc.official_rows_from_queryset(project.officials.all())
    else:
        initial = _blank_meta()
        equipment_rows = [rc.default_equipment_row()]
        prereq_rows = [rc.default_prerequisite_row()]
        approval_rows_list = rc.default_approval_rows_list()
        event_rows = [rc.default_event_row()]
        official_rows = [rc.default_official_row()]

    context = _build_context(editing, project_name, initial, equipment_rows, prereq_rows,
                             approval_rows_list, event_rows, official_rows)
    return render(request, "portal/project_form.html", context)


def _clean(value):
    return "" if value in (None, "N/A") else value


def _blank_meta():
    return {
        "proj_name": "", "reg_no": "", "reg_date": "", "ar_no": "", "budget": "",
        "actual_expenditure": "", "contractor": "", "start_date": "", "comp_date": "",
        "target_etc": "", "area_unit": "", "project_category": "", "nature_of_project": "",
        "projected_savings": "", "irr": "",
    }


def _build_context(editing, original_name, initial, equipment_rows, prereq_rows,
                   approval_rows_list, event_rows, official_rows):
    return {
        "editing": editing,
        "original_name": original_name or "",
        "initial": initial,
        "equipment_rows": equipment_rows,
        "prereq_rows": prereq_rows,
        "approval_rows_list": approval_rows_list,
        "event_rows": event_rows,
        "official_rows": official_rows,
        "standard_categories": constants.STANDARD_CATEGORIES,
        "prerequisite_types": constants.PREREQUISITE_TYPES,
        "prerequisite_statuses": constants.PREREQUISITE_STATUSES,
        "approval_types": constants.APPROVAL_TYPES,
        "approval_statuses": constants.APPROVAL_STATUSES,
        "event_statuses": constants.EVENT_STATUSES,
        "project_categories": constants.PROJECT_CATEGORIES,
        "nature_choices": constants.NATURE_OF_PROJECT,
        "placeholder": constants.PLACEHOLDER,
    }


@transaction.atomic
def _handle_save(request, project_name):
    editing = project_name is not None

    proj_name = request.POST.get("proj_name", "").strip()
    reg_no = request.POST.get("reg_no", "").strip()
    reg_date = request.POST.get("reg_date", "").strip()
    ar_no = request.POST.get("ar_no", "").strip()
    budget = request.POST.get("budget", "").strip()
    actual_expenditure = request.POST.get("actual_expenditure", "").strip()
    contractor = request.POST.get("contractor", "").strip()
    start_date = request.POST.get("start_date", "").strip()
    comp_date = request.POST.get("comp_date", "").strip()
    target_etc = request.POST.get("target_etc", "").strip()
    area_unit = request.POST.get("area_unit", "").strip()
    project_category = request.POST.get("project_category", "").strip()
    nature_of_project = request.POST.get("nature_of_project", "").strip()
    projected_savings = request.POST.get("projected_savings", "").strip()
    irr = request.POST.get("irr", "").strip()

    equipment_rows = _safe_json_list(request.POST.get("equipment_json"))
    prereq_rows = _safe_json_list(request.POST.get("prereqs_json"))
    official_rows = _safe_json_list(request.POST.get("officials_json"))
    event_rows = _safe_json_list(request.POST.get("events_json"))
    approval_rows = _safe_json_dict(request.POST.get("approvals_json"))

    # ---- Equipment ----
    final_equipment = []
    equipment_error = None
    seen_tags = set()
    for eq in equipment_rows:
        tag = (eq.get("tag") or "").strip()
        if not tag:
            continue
        if tag in seen_tags:
            equipment_error = f"Tag Number / Name '{tag}' is used more than once. Tags must be unique within a project."
            break
        seen_tags.add(tag)

        category_sel = eq.get("category_sel", constants.PLACEHOLDER)
        if category_sel == constants.PLACEHOLDER:
            equipment_error = f"Please select an Equipment Category for Tag Number / Name '{tag}'."
            break
        if category_sel == "Other (Custom)":
            custom = (eq.get("category_custom") or "").strip()
            resolved_cat = custom if custom else "Uncategorized"
        else:
            resolved_cat = category_sel
        try:
            count = int(eq.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        custom_params = {}
        for p in eq.get("params", []):
            label = (p.get("label") or "").strip()
            if label:
                custom_params[label] = p.get("val", "")
        final_equipment.append({"tag": tag, "category": resolved_cat, "count": count,
                                "custom_params": custom_params})

    # ---- Officials ----
    final_officials = []
    for o in official_rows:
        name = (o.get("name") or "").strip()
        if name:
            final_officials.append({
                "name": name,
                "designation": o.get("designation", ""),
                "department": o.get("department", ""),
                "employee_id": o.get("employee_id", ""),
            })

    # ---- Prerequisites ----
    final_prereqs = []
    for p in prereq_rows:
        type_sel = p.get("type_sel", constants.PLACEHOLDER)
        if type_sel == constants.PLACEHOLDER:
            continue
        if type_sel == "Other (Custom)":
            custom = (p.get("type_custom") or "").strip()
            resolved_type = custom if custom else "Uncategorized"
        else:
            resolved_type = type_sel
        final_prereqs.append({
            "type": resolved_type,
            "status": p.get("status", constants.PREREQUISITE_STATUSES[0]),
            "remarks": p.get("remarks", ""),
        })

    # ---- Approvals: fixed matrix, always saved in full ----
    final_approvals = []
    for a_type in constants.APPROVAL_TYPES:
        details = approval_rows.get(a_type, {})
        status = details.get("status", constants.PLACEHOLDER)
        if status == constants.PLACEHOLDER:
            status = "Not Applicable"
        date_val = details.get("date") or "N/A" if status in constants.APPROVAL_DATE_ENABLED_STATUSES else "N/A"
        final_approvals.append({"approval_type": a_type, "status": status, "date": date_val})

    # ---- Events ----
    final_events = []
    for ev in event_rows:
        name = (ev.get("event_name") or "").strip()
        if not name:
            continue
        status = ev.get("status", constants.PLACEHOLDER)
        if status == constants.PLACEHOLDER:
            status = "Planned"
        try:
            rating = min(max(int(ev.get("criticality_rating") or 1), 1), 5)
        except (TypeError, ValueError):
            rating = 1
        try:
            duration = int(ev.get("duration") or 1)
        except (TypeError, ValueError):
            duration = 1
        try:
            progress = min(max(int(ev.get("progress_pct") or 0), 0), 100)
        except (TypeError, ValueError):
            progress = 0
        # Keep progress consistent with status so the actual S-curve can't contradict
        # the status column the user is looking at.
        if status == "Completed":
            progress = 100
        elif status == "Planned":
            progress = 0
        final_events.append({
            "event_name": name,
            "planned_start": ev.get("planned_start", ""),
            "duration": duration,
            "planned_finish": ev.get("planned_finish", ""),
            "criticality_rating": rating,
            "actual_start": ev.get("actual_start", ""),
            "actual_finish": ev.get("actual_finish", ""),
            "status": status,
            "progress_pct": progress,
            "remarks": ev.get("remarks", ""),
        })

    error_message = None
    if not proj_name:
        error_message = "Submission failed: Project Name is mandatory."
    elif equipment_error:
        error_message = f"Submission failed: {equipment_error}"
    elif not editing and Project.objects.filter(name=proj_name).exists():
        error_message = f"A project named '{proj_name}' already exists. Choose a different name, or edit the existing one instead."
    elif editing and proj_name != project_name and Project.objects.filter(name=proj_name).exists():
        error_message = f"A project named '{proj_name}' already exists. Choose a different name."

    if error_message:
        messages.error(request, error_message)
        initial = {
            "proj_name": proj_name, "reg_no": reg_no, "reg_date": reg_date, "ar_no": ar_no,
            "budget": budget, "actual_expenditure": actual_expenditure, "contractor": contractor,
            "start_date": start_date, "comp_date": comp_date, "target_etc": target_etc,
            "area_unit": area_unit, "project_category": project_category,
            "nature_of_project": nature_of_project, "projected_savings": projected_savings, "irr": irr,
        }
        context = _build_context(
            editing, project_name, initial,
            equipment_rows or [rc.default_equipment_row()],
            prereq_rows or [rc.default_prerequisite_row()],
            rc.approval_rows_from_submitted_dict(approval_rows),
            event_rows or [rc.default_event_row()],
            official_rows or [rc.default_official_row()],
        )
        return render(request, "portal/project_form.html", context)

    # ---- All good: write to the database ----
    project = Project.objects.get(name=project_name) if editing else Project()

    project.name = proj_name
    project.reg_no = reg_no
    project.reg_date = reg_date
    project.ar_no = ar_no
    project.budget = budget if budget else "N/A"
    project.actual_expenditure = actual_expenditure
    project.contractor = contractor if contractor else "N/A"
    project.start_date = start_date
    project.completion_date = comp_date
    project.target_etc = target_etc
    project.area_unit = area_unit
    project.project_category = project_category
    project.nature_of_project = nature_of_project
    project.projected_savings = projected_savings
    project.irr = irr
    project.save()

    # Replace every related row on each save. Wrapped in @transaction.atomic above,
    # so a failure partway through rolls back rather than half-saving the project.
    project.officials.all().delete()
    Official.objects.bulk_create([Official(project=project, **o) for o in final_officials])

    project.prerequisites.all().delete()
    Prerequisite.objects.bulk_create([Prerequisite(project=project, **p) for p in final_prereqs])

    project.approvals.all().delete()
    Approval.objects.bulk_create([Approval(project=project, **a) for a in final_approvals])

    project.events.all().delete()
    Event.objects.bulk_create([Event(project=project, **e) for e in final_events])

    project.equipment_items.all().delete()
    Equipment.objects.bulk_create([Equipment(project=project, **e) for e in final_equipment])

    messages.success(request, f"Project sheet '{proj_name}' logged successfully!")
    return redirect(f"{reverse('repository')}?project={quote(proj_name)}")


def _safe_json_list(raw):
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _safe_json_dict(raw):
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}
