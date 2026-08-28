"""
AI insights layer.

This module turns the already-computed facts from analytics.py into readable
narrative: an executive summary, ranked risks, and recommended actions.

--------------------------------------------------------------------------------
Design rule: the AI never calculates anything
--------------------------------------------------------------------------------
Every number the narrative refers to -- percentages, slip days, SPI, costs -- is
computed in analytics.py and passed in as fact. The model is asked only to
interpret and prioritise, never to derive. This matters for two reasons:

  1. Correctness. Language models are unreliable arithmetic engines. Anything a
     reviewer could check with a calculator is computed in Python.
  2. Defensibility. Every figure on screen traces back to a rule in analytics.py
     that can be explained. "The model said so" is never the reason for a number.

--------------------------------------------------------------------------------
Reliability
--------------------------------------------------------------------------------
The insights panel is designed so that it cannot break the page. There are three
tiers, and the portal silently walks down them:

  1. Live model call succeeds and returns valid JSON  -> AI narrative.
  2. Cached narrative from an earlier call            -> AI narrative (cached).
  3. Anything else -- no API key, network down, timeout, HTTP error, malformed
     JSON, unexpected schema, or any unhandled exception whatsoever
                                                      -> rule-based narrative.

Tier 3 is written from the identical fact bundle by _rule_based_insight() below,
so it always says something true and specific about the project rather than
showing an error. Every public function in this module is wrapped so that no
exception can propagate into a view.
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a project controls analyst reviewing execution data for \
industrial engineering projects. You will be given a JSON bundle of ALREADY CALCULATED \
metrics for one project or portfolio.

Rules you must follow:
- Do NOT calculate, re-derive, estimate or invent any number. Use only the figures \
given to you, quoted exactly as provided.
- Do NOT speculate about causes that are not evidenced in the data. If the data shows \
an activity is late, say it is late; do not invent a reason why.
- Be specific and name the actual activities, blockers and projects from the data.
- Write for a busy engineering manager: direct, concrete, no filler, no hedging \
language, no restating the obvious.

Respond with ONLY a JSON object, no preamble and no markdown code fences, in exactly \
this shape:
{
  "summary": "2-4 sentences on where this stands and why",
  "risks": [{"title": "short label", "detail": "1-2 sentences citing the data"}],
  "actions": [{"title": "short imperative action", "detail": "1-2 sentences on what to do and why now"}]
}
Provide 2-4 risks and 2-4 actions, ordered most important first."""


# ==================== public entry points ====================

def project_insight(analysis, force_refresh=False):
    """Narrative insight for a single project. Never raises."""
    try:
        facts = _project_facts(analysis)
        return _insight(facts, kind="project", force_refresh=force_refresh)
    except Exception:
        logger.exception("project_insight failed; falling back")
        try:
            return _rule_based_insight(_project_facts(analysis), kind="project")
        except Exception:
            return _empty_insight()


def portfolio_insight(portfolio, force_refresh=False):
    """Narrative insight across all projects. Never raises."""
    try:
        facts = _portfolio_facts(portfolio)
        return _insight(facts, kind="portfolio", force_refresh=force_refresh)
    except Exception:
        logger.exception("portfolio_insight failed; falling back")
        try:
            return _rule_based_insight(_portfolio_facts(portfolio), kind="portfolio")
        except Exception:
            return _empty_insight()


def ai_is_configured():
    return bool(getattr(settings, "AI_API_KEY", ""))


# ==================== orchestration ====================

def _insight(facts, kind, force_refresh=False):
    """Walk the three reliability tiers described in the module docstring."""
    cache_key = _cache_key(facts, kind)
    cache_seconds = int(getattr(settings, "AI_CACHE_SECONDS", 0) or 0)

    if cache_seconds and not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            cached = dict(cached)
            cached["cached"] = True
            return cached

    if not ai_is_configured():
        result = _rule_based_insight(facts, kind)
        result["reason"] = "No API key configured (set PEER_AI_API_KEY to enable AI narrative)."
        return result

    parsed, error = _call_model(facts, kind)
    if parsed is None:
        result = _rule_based_insight(facts, kind)
        result["reason"] = error or "AI service unavailable."
        return result

    result = {
        "source": "ai",
        "source_label": "AI-generated",
        "summary": parsed["summary"],
        "risks": parsed["risks"],
        "actions": parsed["actions"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cached": False,
        "reason": "",
    }
    if cache_seconds:
        try:
            cache.set(cache_key, result, cache_seconds)
        except Exception:
            logger.exception("Failed to cache AI insight (non-fatal)")
    return result


def _cache_key(facts, kind):
    blob = json.dumps(facts, sort_keys=True, default=str).encode("utf-8")
    return f"peer:insight:{kind}:{hashlib.sha256(blob).hexdigest()[:32]}"


# ==================== model call ====================

def _call_model(facts, kind):
    """Call the Gemini API. Returns (parsed_dict, None) or (None, error_message).

    Uses Google's generativelanguage.googleapis.com REST endpoint directly (no SDK
    dependency, consistent with the rest of this module). Catches every failure mode
    explicitly so the caller only has to check for None.
    """
    model = getattr(settings, "AI_MODEL", "gemini-2.5-flash")
    url_template = getattr(
        settings, "AI_API_URL",
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    )
    url = url_template.format(model=model)

    payload = {
        "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{
            "role": "user",
            "parts": [{
                "text": (
                    f"Here is the calculated {kind} data. Return only the JSON object.\n\n"
                    + json.dumps(facts, indent=2, default=str)
                ),
            }],
        }],
        "generationConfig": {
            "maxOutputTokens": int(getattr(settings, "AI_MAX_TOKENS", 1200)),
            "temperature": 0.4,
            # Ask Gemini to emit raw JSON directly rather than relying on prompt
            # instructions alone -- this is a real API feature, not a convention,
            # so it materially cuts down on markdown-fenced or prose-wrapped output.
            "responseMimeType": "application/json",
        },
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.AI_API_KEY,
        },
        method="POST",
    )

    timeout = float(getattr(settings, "AI_TIMEOUT_SECONDS", 20))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:300]
        except Exception:
            pass
        logger.warning("Gemini HTTP %s: %s", exc.code, detail)
        if exc.code in (401, 403):
            return None, "AI service rejected the API key (check PEER_AI_API_KEY)."
        if exc.code == 429:
            return None, "AI service rate limit or quota exceeded."
        return None, f"AI service returned HTTP {exc.code}."
    except urllib.error.URLError as exc:
        logger.warning("AI network error: %s", exc.reason)
        return None, "Could not reach the AI service (network unavailable)."
    except TimeoutError:
        return None, f"AI service timed out after {timeout:.0f}s."
    except json.JSONDecodeError:
        return None, "AI service returned a non-JSON response."
    except Exception as exc:
        logger.exception("Unexpected AI transport failure")
        return None, f"Unexpected AI error: {type(exc).__name__}."

    # Gemini reports safety blocks and other non-content stops via promptFeedback /
    # finishReason rather than an HTTP error, so an empty candidates list is a normal
    # response shape here and needs its own message rather than falling through to
    # the generic "empty response" case below.
    if not body.get("candidates"):
        block_reason = (body.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            return None, f"AI service blocked the request ({block_reason})."
        return None, "AI service returned no candidates."

    text = _extract_text(body)
    if not text:
        finish_reason = body["candidates"][0].get("finishReason", "")
        if finish_reason and finish_reason != "STOP":
            return None, f"AI response was cut off ({finish_reason})."
        return None, "AI service returned an empty response."

    parsed = _parse_json_response(text)
    if parsed is None:
        return None, "Could not parse the AI response."
    return parsed, None


def _extract_text(body):
    """Pull the text out of a Gemini generateContent response.

    Shape: {"candidates": [{"content": {"parts": [{"text": "..."}]}}]}
    """
    try:
        parts = body["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    except (KeyError, IndexError, TypeError):
        return ""


def _parse_json_response(text):
    """Parse and validate the model's JSON, tolerating stray fences or prose.

    Returns a dict guaranteed to have string `summary` and well-formed `risks` /
    `actions` lists, or None if the response can't be salvaged.
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("```")[1] if "```" in candidate[3:] else candidate[3:]
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
        candidate = candidate.strip()

    data = None
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                return None
    if not isinstance(data, dict):
        return None

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None

    def clean_items(raw):
        items = []
        if isinstance(raw, list):
            for entry in raw[:4]:
                if isinstance(entry, dict):
                    title = str(entry.get("title", "")).strip()
                    detail = str(entry.get("detail", "")).strip()
                elif isinstance(entry, str):
                    title, detail = entry.strip(), ""
                else:
                    continue
                if title or detail:
                    items.append({"title": title or "Note", "detail": detail})
        return items

    return {
        "summary": summary.strip(),
        "risks": clean_items(data.get("risks")),
        "actions": clean_items(data.get("actions")),
    }


# ==================== fact bundles ====================

def _project_facts(analysis):
    """Compact, model-friendly view of one project's computed analytics."""
    curves = analysis["curves"]
    cost = analysis["cost"]
    return {
        "project_name": analysis["name"],
        "as_of_date": analysis["today"],
        "schedule": {
            "planned_percent_complete": curves["planned_today"],
            "actual_percent_complete": curves["actual_today"],
            "variance_points": curves["variance"],
            "schedule_performance_index": curves["spi"],
            "health": analysis["health"]["label"],
        },
        "forecast": analysis["forecast"],
        "activity_counts": analysis["activity_status_counts"],
        "activities_needing_attention": [
            {
                "name": a["name"],
                "status": a["status"],
                "criticality_out_of_5": a["criticality"],
                "planned_finish": a["planned_finish"],
                "days_overdue": a["overdue_days"],
                "days_late_starting": a["late_start_days"],
                "percent_behind_own_baseline": a["shortfall"],
                "why_flagged": a["reasons"],
            }
            for a in analysis["top_critical"]
        ],
        "blockers": analysis["blockers"],
        "cost": {
            "budget": cost["budget"],
            "spent": cost["spent"],
            "percent_of_budget_spent": cost["burn_pct"],
            "spend_ahead_of_progress_by_points": cost["overrun_points"],
            "overrun_flag": cost["flag"],
        } if cost["has_data"] else None,
        "equipment_units": analysis["equipment_units"],
    }


def _portfolio_facts(portfolio):
    return {
        "as_of_date": portfolio["today"],
        "project_count": portfolio["project_count"],
        "average_planned_percent": portfolio["avg_planned"],
        "average_actual_percent": portfolio["avg_actual"],
        "average_variance_points": portfolio["avg_variance"],
        "projects_at_risk_or_critical": portfolio["at_risk_count"],
        "health_breakdown": portfolio["health_counts"],
        "total_budget": portfolio["total_budget"],
        "total_spent": portfolio["total_spent"],
        "percent_of_budget_spent": portfolio["burn_pct"],
        "total_open_blockers": portfolio["total_blockers"],
        "projects": [
            {
                "name": r["name"],
                "category": r["category"],
                "planned_percent": r["planned_pct"],
                "actual_percent": r["actual_pct"],
                "variance_points": r["variance"],
                "health": r["health"]["label"],
                "open_blockers": r["blocker_count"],
                "late_activities": r["critical_count"],
                "cost_overrun_flag": r["cost_flag"],
            }
            for r in portfolio["rows"]
        ],
    }


# ==================== deterministic fallback narrative ====================

def _rule_based_insight(facts, kind):
    """Write the narrative from the same facts, with no model involved.

    This is the guaranteed floor: it always produces specific, accurate prose about
    the actual data, so the panel never shows an error or an empty state.
    """
    builder = _rule_based_project if kind == "project" else _rule_based_portfolio
    summary, risks, actions = builder(facts)
    return {
        "source": "rules",
        "source_label": "Rule-based (AI unavailable)",
        "summary": summary,
        "risks": risks[:4],
        "actions": actions[:4],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cached": False,
        "reason": "",
    }


def _rule_based_project(facts):
    schedule = facts["schedule"]
    name = facts["project_name"]
    actual = schedule["actual_percent_complete"]
    planned = schedule["planned_percent_complete"]
    variance = schedule["variance_points"]
    health = schedule["health"]

    if variance < 0:
        direction = f"running {abs(variance):.1f} points behind its baseline"
    elif variance > 0:
        direction = f"running {variance:.1f} points ahead of its baseline"
    else:
        direction = "exactly on its baseline"

    summary = (
        f"{name} is {actual:.1f}% complete against a planned {planned:.1f}%, "
        f"{direction}, and is currently classified {health}."
    )
    forecast = facts.get("forecast")
    if forecast and forecast.get("is_late"):
        summary += (
            f" At the current rate the finish date extrapolates to "
            f"{forecast['forecast_completion']}, about {forecast['slip_days']} days "
            f"past the planned {forecast['planned_completion']}."
        )

    risks, actions = [], []

    for activity in facts["activities_needing_attention"][:3]:
        if activity["days_overdue"] > 0:
            risks.append({
                "title": f"{activity['name']} is {activity['days_overdue']} days overdue",
                "detail": (
                    f"Planned to finish {activity['planned_finish']}, still marked "
                    f"{activity['status']} with a criticality of "
                    f"{activity['criticality_out_of_5']}/5."
                ),
            })
        elif activity["days_late_starting"] > 0:
            risks.append({
                "title": f"{activity['name']} has not started",
                "detail": (
                    f"{activity['days_late_starting']} days past its planned start, "
                    f"criticality {activity['criticality_out_of_5']}/5."
                ),
            })

    blockers = facts.get("blockers") or []
    if blockers:
        names = ", ".join(b["name"] for b in blockers[:3])
        risks.append({
            "title": f"{len(blockers)} open blocker(s)",
            "detail": f"Currently outstanding: {names}.",
        })
        actions.append({
            "title": "Clear the open prerequisites and approvals",
            "detail": f"Chase {names} -- downstream activities cannot close until these land.",
        })

    cost = facts.get("cost")
    if cost and cost.get("overrun_flag"):
        risks.append({
            "title": "Spend is outpacing progress",
            "detail": (
                f"{cost['percent_of_budget_spent']:.1f}% of budget consumed against "
                f"{schedule['actual_percent_complete']:.1f}% physical progress, a gap of "
                f"{cost['spend_ahead_of_progress_by_points']:.1f} points."
            ),
        })
        actions.append({
            "title": "Review commitments against remaining scope",
            "detail": "Confirm the remaining work can be delivered inside the unspent balance.",
        })

    top = facts["activities_needing_attention"][:2]
    if top:
        actions.insert(0, {
            "title": f"Prioritise {top[0]['name']}",
            "detail": (
                "Highest-ranked activity by the criticality and slippage scoring: "
                + "; ".join(top[0]["why_flagged"]) + "."
            ),
        })
    if variance < -5:
        actions.append({
            "title": "Re-baseline or recover the schedule",
            "detail": (
                f"A {abs(variance):.1f}-point gap will not close on its own; either add "
                "resource to the ranked activities above or formally revise the plan."
            ),
        })

    if not risks:
        risks.append({
            "title": "No material schedule risk detected",
            "detail": "No overdue activities, no late starts and no open blockers.",
        })
    if not actions:
        actions.append({
            "title": "Maintain current cadence",
            "detail": "Progress is tracking to plan; keep reporting against the baseline.",
        })
    return summary, risks, actions


def _rule_based_portfolio(facts):
    count = facts["project_count"]
    at_risk = facts["projects_at_risk_or_critical"]
    avg_variance = facts["average_variance_points"]

    summary = (
        f"{count} project(s) tracked. Average progress is "
        f"{facts['average_actual_percent']:.1f}% against a planned "
        f"{facts['average_planned_percent']:.1f}%, an average variance of "
        f"{avg_variance:.1f} points. {at_risk} project(s) are At Risk or Critical."
    )
    if facts.get("percent_of_budget_spent") is not None:
        summary += f" {facts['percent_of_budget_spent']:.1f}% of total budget has been committed."

    risks, actions = [], []
    worst = [p for p in facts["projects"] if p["variance_points"] < 0][:3]
    for project in worst:
        risks.append({
            "title": f"{project['name']} is {abs(project['variance_points']):.1f} points behind",
            "detail": (
                f"{project['actual_percent']:.1f}% actual against "
                f"{project['planned_percent']:.1f}% planned, {project['open_blockers']} open "
                f"blocker(s) and {project['late_activities']} late activity(ies)."
            ),
        })

    if facts["total_open_blockers"]:
        actions.append({
            "title": f"Work down the {facts['total_open_blockers']} open blockers",
            "detail": "Prerequisites and approvals are the most common cross-project constraint.",
        })
    if worst:
        actions.append({
            "title": f"Escalate {worst[0]['name']} first",
            "detail": "It carries the largest negative schedule variance in the portfolio.",
        })

    overruns = [p for p in facts["projects"] if p["cost_overrun_flag"]]
    if overruns:
        risks.append({
            "title": f"{len(overruns)} project(s) spending ahead of progress",
            "detail": "Affected: " + ", ".join(p["name"] for p in overruns[:3]) + ".",
        })

    if not risks:
        risks.append({
            "title": "Portfolio is tracking to plan",
            "detail": "No project is materially behind its baseline.",
        })
    if not actions:
        actions.append({
            "title": "Hold current review cadence",
            "detail": "No portfolio-level intervention indicated by the current data.",
        })
    return summary, risks, actions


def _empty_insight():
    """Absolute last resort -- only reachable if fact assembly itself fails."""
    return {
        "source": "rules",
        "source_label": "Unavailable",
        "summary": "Insight could not be generated for this project.",
        "risks": [],
        "actions": [],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cached": False,
        "reason": "Analytics data was incomplete.",
    }
