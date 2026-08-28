<div align="center">

# PEER — Project Execution and Evaluation Report

**A project controls dashboard for industrial engineering projects: schedule tracking,
S-curve analytics, and AI-generated insights, built on Django.**

[Features](#features) · [Quick start](#quick-start) · [AI insights](#ai-insights) · [Data](#data--privacy) · [Architecture](#architecture)

</div>

---

## What this is

PEER is a full-stack portal for tracking capital and maintenance projects — the kind of
work a plant or facility engineering team runs continuously: replace a pump, upgrade a
substation, extend a fire water main. Each project has scope, personnel, prerequisites,
regulatory approvals, a schedule of activities, and equipment specifications.

On top of that operational data sits an **analytics layer** (planned-vs-actual S-curves,
schedule variance, cost tracking, a ranked "what needs attention" list) and an **AI
insights layer** that reads the computed analytics and writes a plain-language summary,
risks, and recommended actions.

It started as a Streamlit prototype, was rebuilt as a Django CRUD app, and was extended
with the analytics and AI layers described here.

> **No real project data is used anywhere in this repository.** See
> [Data & privacy](#data--privacy).

---

## Features

### Operations
- Full CRUD for project sheets — administrative details, personnel, prerequisites,
  regulatory approvals, scheduled activities, equipment specifications
- CSV export of raw project data and of the computed analytics separately

### Analytics (deterministic — no AI involved)
- **Dual S-curves per project** — target (planned) vs. current (actual) cumulative
  progress, weighted by activity duration, with the actual curve correctly truncated
  at today
- **Schedule variance & SPI** — how far ahead or behind baseline, expressed in points
  and as a schedule performance index
- **Blended portfolio S-curve** — every project's curves averaged onto one chart for a
  single-glance portfolio view
- **Ranked critical-activity list** — a transparent, capped scoring formula (lateness,
  criticality, shortfall against baseline) surfaces what actually needs attention,
  not just what's oldest
- **Completion forecasting** — extrapolates a likely finish date from the current
  schedule performance index
- **Cost-vs-progress tracking** — flags projects where spend is outpacing physical
  progress
- **Open blocker detection** — surfaces prerequisites and approvals currently holding
  a project up

Every number above is plain Python arithmetic against the database, in
[`portal/analytics.py`](portal/analytics.py) — no model, no API call, fully unit
tested. See [How the analytics work](#how-the-analytics-work).

### AI insights
- Per-project and portfolio-level narrative: a summary, ranked risks, and recommended
  actions, written from the already-computed analytics
- **Three-tier reliability**: live model call → short-lived cache → deterministic
  rule-based fallback if the AI is unavailable for any reason. The page never errors
  and never shows an empty state.
- The AI **never performs any calculation** — every figure it references was computed
  by the analytics layer first and handed to it as fact. See
  [How the AI insights work](#how-the-ai-insights-work).

### Design
- No CDN, no web fonts, no charting library — everything runs offline, including the
  S-curve charts (hand-rolled inline SVG)
- Built to run on a non-technical user's Windows laptop with minimal setup

---

## Quick start

Requires **Python 3.10+**. Django is the only hard dependency.

```bash
git clone https://github.com/tzarcrept/peer-portal.git
cd peer-portal

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

python manage.py migrate
python manage.py seed_synthetic_data   # loads 18 synthetic demo projects
python manage.py runserver
```

Open **http://127.0.0.1:8000/**.

### Using the app

| Page | What you'll find |
|---|---|
| **Portfolio dashboard** (`/`) | KPIs across every project, a blended S-curve, projects ranked worst-variance-first, a category breakdown |
| **Project analytics** (`/analytics/`) | Target-vs-current S-curve for one project, schedule/cost KPIs, ranked critical activities, AI insight panel |
| **Project repository** (`/repository/`) | The full logged detail sheet for one project |
| **Add / edit project** (`/project/new/`) | Data entry — scope, personnel, prerequisites, approvals, schedule, equipment |
| **Analytics CSV** (`/download-analytics-csv/`) | The computed metrics, one row per project — for further analysis in Excel/BI tools |
| **Full data CSV** (`/download-csv/`) | Raw sheet contents, flattened |
| **Django admin** (`/admin/`) | Run `python manage.py createsuperuser` first |

Click **Regenerate insights** on any analytics page to force a fresh AI narrative
(bypassing the cache).

### Run the tests

```bash
python manage.py test
```

44 tests covering the analytics maths, every AI failure mode (network down, timeout,
malformed response, safety block), and every view including empty-database and
unknown-project edge cases. A few tracebacks print during the run — those are tests
deliberately simulating failures and asserting the fallback engages correctly. A clean
run ends in `OK`.

---

## AI insights

### How the AI insights work

The insights panel is powered by **Google's Gemini API**, but is designed so the
feature is entirely optional:

```
analytics.py     computes the facts    →  deterministic, tested, always available
ai_insights.py    writes about them     →  optional narrative layer on top
```

Every percentage, slip-day count, SPI value, and currency figure shown in an insight is
computed in `analytics.py` first and passed to the model as an established fact in a
JSON bundle. The system prompt explicitly instructs the model **not to calculate or
invent anything** — only to interpret and prioritise what it's given. This matters for
two reasons: language models are unreliable at arithmetic, and every figure on screen
needs to trace back to a rule that can be explained, not to "the model said so."

**Enabling it:**

```bash
export PEER_AI_API_KEY=your-gemini-key-here   # Windows: set PEER_AI_API_KEY=...
```

Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — no
billing setup required. Without a key, the app runs entirely on the fallback below.

### How insights work *without* AI

This is the important part for reliability: **the app never depends on the AI being
available.** If there's no API key, or the call times out, errors, gets rate-limited, or
returns something unparseable, `ai_insights.py` falls back to a **rule-based narrative
generator** — plain Python functions (`_rule_based_project`, `_rule_based_portfolio`)
that read the exact same computed-facts bundle and assemble a summary, risks, and
actions using string templates.

This is not a second AI or a disguised model call — it's closer to a mail-merge: take
numbers that `analytics.py` already computed (e.g. `overdue_days = (today -
planned_finish).days`, a literal date subtraction) and drop them into a fixed sentence
shape (`f"{name} is {days} days overdue"`). Same inputs always produce the exact same
output. It exists specifically so the dashboard **never shows an error or an empty
state**, regardless of AI availability.

The insight panel always labels which tier produced what you're looking at
("AI-generated" vs. "Rule-based (AI unavailable)"), so this is never hidden from the
user.

---

## How the analytics work

**S-curves.** Progress is modelled as weighted activity completion, where each
activity's weight is its planned duration in days — a 30-day activity represents more
of the project than a 2-day one. The target curve ramps each activity linearly from
planned start to planned finish; the current curve does the same using actual dates and
recorded percent-complete, and is truncated at today since there's no such thing as
future actual progress.

**Critical-activity ranking.** A transparent, additive score: capped lateness (both
overdue days and late-start days, capped at 90 days each), criticality rating (1–5,
weighted heavily), and shortfall against the activity's own baseline. The 90-day cap is
deliberate — without it, raw lateness drowns out everything else, so a criticality-2
activity that's been late for a year would always outrank a criticality-5 activity late
by three months. Full reasoning is in the module docstring in
[`portal/analytics.py`](portal/analytics.py).

**Cost tracking.** Compares percent of budget spent against percent physical progress;
flags when spend is running materially ahead of progress.

**Forecasting.** Extrapolates a likely completion date by stretching remaining planned
duration by the inverse of the current schedule performance index.

---

## Data & privacy

**This repository contains no real project data, and never has.**

The dataset shipped with this project — 18 projects, personnel, contractors, budgets,
equipment tags, dates — is entirely **synthetic**, generated by
[`portal/management/commands/seed_synthetic_data.py`](portal/management/commands/seed_synthetic_data.py)
using a fixed random seed. No project name, person, contractor, site, tag number, or
figure in the dataset corresponds to any real organisation, facility, or individual.

This project was originally developed against real internal data during an internship.
**Before this code was made public:**

- The original data file was deleted and replaced entirely with the synthetic generator
- Every reference to the originating organisation's name was removed from code,
  templates, and configuration
- Regulatory approval categories were rewritten to describe **what they regulate**
  (e.g. "Pressure Vessel Certification", "Environmental Clearance") rather than naming
  the originating jurisdiction's specific statutory bodies
- Real personnel names, employee IDs, and project identifiers were removed and replaced
  by the synthetic generator

What *was* kept is generic, textbook industrial-engineering vocabulary — terms like
P&ID, HAZOP, MOC (Management of Change), and standard equipment categories (centrifugal
pump, heat exchanger, etc.) — which are industry-standard terminology, not
organisation-specific or proprietary.

The synthetic seeder generates all dates **relative to the current date**, so the demo
data stays realistic-looking (a mix of finished, running, and upcoming work) no matter
when you run it, and is reproducible via a fixed seed so the same dataset appears every
time.

```bash
python manage.py seed_synthetic_data           # wipe and reload the synthetic dataset
python manage.py seed_synthetic_data --append   # add to existing projects instead
```

---

## Architecture

```
peer_portal/              Django project configuration
  settings.py              All AI/deployment config, read from environment variables

portal/
  models.py                 6 related models: Project, Official, Prerequisite,
                            Approval, Event, Equipment
  analytics.py               Deterministic metrics engine — every number on screen
                            is computed here
  ai_insights.py             AI narrative layer with 3-tier fallback (see above)
  constants.py               Dropdown vocabularies + every analytics threshold,
                            single source of truth
  views.py                   Dashboards, CRUD, CSV exports, insight-refresh endpoint
  reconstruct.py             Model querysets <-> form row shapes
  tests.py                   44 tests: analytics maths, AI failure modes, all views
  templatetags/               Presentation-only formatting filters
  management/commands/
    seed_synthetic_data.py   Synthetic dataset generator (see Data & privacy)
  static/portal/
    style.css                 Control-room/instrument visual design
    charts.js                  Hand-rolled inline-SVG S-curve renderer, no library
    form.js, insight.js
  templates/portal/
```

---

## Known limitations

- **No authentication.** Every page is open to anyone who can reach the server — this
  is built for local/demo use, not shared deployment. Adding `login_required` and a
  permission model would be the first change before hosting this anywhere shared.
- **No true critical-path modelling.** The schema has no activity-dependency
  relationships, so the "critical activity" ranking scores each activity independently
  rather than computing a real critical path through a dependency network.
- **Dates are stored as text**, not `DateField`, because real project sheets
  legitimately contain values like "N/A" for approvals that haven't happened yet.
  `analytics.py` parses defensively and ignores anything unparseable.
- **SQLite** is fine at this scale but isn't built for concurrent multi-user writes.

---

## License

[MIT](LICENSE) — use, fork, and adapt freely.
