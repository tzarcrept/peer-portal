"""
Generates the synthetic demonstration dataset.

Why synthetic
-------------
This portal was originally built against a real operator's project data, which cannot
be redistributed. Everything below is invented: project names, sites, personnel,
contractors, tag numbers, budgets and dates contain no real-world information. The
*schema* and the engineering vocabulary are generic industry-standard terms.

Design goals
------------
1. Reproducible.   A fixed RNG seed means the same dataset every run, so screenshots,
                   demos and any numbers quoted elsewhere stay consistent.
2. Always current. Every date is generated relative to today, so the dashboard shows a
                   live-looking mix of finished, running and upcoming work whenever it
                   is run, rather than going stale.
3. Analytically interesting. Projects are built from explicit performance archetypes
                   (see ARCHETYPES) so the dashboard has genuinely different situations
                   to surface: recoveries, stalls, cost overruns and clean runs. A
                   dataset where everything is on track would demonstrate nothing.

Usage
-----
    python manage.py seed_synthetic_data           # wipe and reseed
    python manage.py seed_synthetic_data --append  # keep existing projects
"""

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from portal.models import Approval, Equipment, Event, Official, Prerequisite, Project

SEED = 20240815

# ---- Performance archetypes -------------------------------------------------
# factor      : actual progress achieved as a multiple of planned progress at today
#               (1.0 = exactly on plan, 0.5 = half the expected work done)
# blockers    : how many prerequisites/approvals to leave in a blocking state
# cost_factor : spend as a multiple of physical progress (>1 = burning fast)
ARCHETYPES = {
    "on_track":       {"factor": 1.00, "blockers": 0, "cost_factor": 1.00},
    "ahead":          {"factor": 1.12, "blockers": 0, "cost_factor": 0.92},
    "slightly_behind": {"factor": 0.92, "blockers": 1, "cost_factor": 1.05},
    "at_risk":        {"factor": 0.72, "blockers": 2, "cost_factor": 1.20},
    "critical":       {"factor": 0.45, "blockers": 3, "cost_factor": 1.45},
    "stalled":        {"factor": 0.28, "blockers": 4, "cost_factor": 1.15},
    "complete":       {"factor": 1.00, "blockers": 0, "cost_factor": 0.98},
}

# name, archetype, months since start, total months, category, nature, site
PROJECTS = [
    ("Cooling Water Pump Replacement",      "on_track",        6, 12, "Asset Replacement",        "Major",    "Utilities Block A"),
    ("Boiler Feed Line Reinstatement",      "at_risk",         8, 14, "Reliability Improvement",  "Critical", "Steam Generation Area"),
    ("Effluent Treatment Capacity Upgrade", "critical",       10, 16, "Environmental Compliance", "Critical", "Effluent Plant"),
    ("Instrument Air Dryer Installation",   "ahead",           4,  9, "Reliability Improvement",  "Major",    "Utilities Block B"),
    ("Fire Water Ring Main Extension",      "slightly_behind", 7, 13, "Safety Compliance",        "Critical", "Plant Perimeter"),
    ("Heat Exchanger Retubing Campaign",    "complete",       14, 11, "Asset Replacement",        "Major",    "Process Unit 12"),
    ("Flare Header Debottlenecking",        "at_risk",         9, 15, "Debottlenecking",          "Critical", "Flare Area"),
    ("Condensate Recovery System",          "on_track",        5, 11, "Energy Efficiency",        "Major",    "Steam Generation Area"),
    ("Substation Switchgear Modernisation", "stalled",        11, 18, "Asset Replacement",        "Critical", "Electrical Substation 3"),
    ("Tank Farm Level Instrumentation",     "slightly_behind", 6, 10, "Digital / Instrumentation", "Major",   "Tank Farm North"),
    ("Compressor Overhaul Programme",       "on_track",        3,  8, "Reliability Improvement",  "Major",    "Process Unit 7"),
    ("Chemical Dosing Skid Installation",   "ahead",           2,  7, "Capacity Enhancement",     "Minor",    "Utilities Block A"),
    ("Nitrogen Generation Unit",            "at_risk",         8, 14, "Capacity Enhancement",     "Major",    "Utilities Block C"),
    ("Pipe Rack Structural Rehabilitation", "critical",       12, 17, "Asset Replacement",        "Major",    "Central Pipe Rack"),
    ("Emergency Shutdown System Upgrade",   "on_track",        4, 12, "Safety Compliance",        "Critical", "Control Room"),
    ("Waste Heat Recovery Retrofit",        "complete",       16, 13, "Energy Efficiency",        "Major",    "Process Unit 12"),
    ("Cooling Tower Fill Replacement",      "slightly_behind", 5,  9, "Asset Replacement",        "Minor",    "Cooling Tower Bay 2"),
    ("Storm Water Drainage Rerouting",      "stalled",         9, 15, "Environmental Compliance", "Minor",    "Plant Perimeter"),
]

# Standard activity spine every project follows, with relative weight and criticality.
ACTIVITY_TEMPLATE = [
    ("Scope Freeze and Basic Engineering", 2.0, 3),
    ("Detailed Engineering and Drawings",  3.0, 4),
    ("Procurement and Purchase Orders",    3.0, 4),
    ("Long Lead Item Delivery",            3.5, 5),
    ("Site Mobilisation",                  1.0, 2),
    ("Civil and Structural Works",         2.5, 3),
    ("Mechanical Erection",                3.0, 5),
    ("Piping and Fabrication",             2.5, 4),
    ("Electrical and Instrumentation",     2.5, 4),
    ("Pre-Commissioning Checks",           1.5, 4),
    ("Commissioning and Handover",         1.5, 5),
]

FIRST_NAMES = ["Arun", "Meera", "Rohan", "Kavita", "Sanjay", "Priya", "Vikram", "Neha",
               "Anil", "Divya", "Rajesh", "Sunita", "Karan", "Anita", "Manoj", "Pooja"]
LAST_NAMES = ["Sharma", "Nair", "Iyer", "Deshmukh", "Bose", "Kulkarni", "Reddy", "Menon",
              "Chauhan", "Pillai", "Bhatt", "Rao", "Joshi", "Verma"]
DESIGNATIONS = ["Project Manager", "Lead Engineer", "Site Engineer", "Planning Engineer",
                "Commissioning Engineer", "Safety Officer", "Procurement Lead"]
DEPARTMENTS = ["Projects", "Maintenance", "Operations", "Engineering Services",
               "Health and Safety", "Procurement", "Quality Assurance"]
CONTRACTORS = ["Meridian Engineering Services", "Delta Industrial Contractors",
               "Northline Fabrication", "Apex Mechanical Works", "Ironbridge Projects",
               "Sterling Plant Services", "Vantage Constructors"]

EQUIPMENT_POOL = [
    ("Centrifugal Pump",   "PMP", [("Flow Rate", "{} m3/hr"), ("Head", "{} m"), ("Rating", "{} kW"), ("MOC", "SS316")]),
    ("Heat Exchanger",     "HEX", [("Duty", "{} kW"), ("Surface Area", "{} m2"), ("MOC", "CS / SS304")]),
    ("Drum",               "DRM", [("Capacity", "{} m3"), ("Design Pressure", "{} barg"), ("MOC", "CS")]),
    ("Tank",               "TNK", [("Capacity", "{} m3"), ("Diameter", "{} m"), ("MOC", "CS")]),
    ("Valve",              "VLV", [("Size", "{} inch"), ("Class", "150#"), ("Type", "Gate")]),
    ("Instrumentation",    "INS", [("Range", "0-{} barg"), ("Signal", "4-20 mA"), ("Protocol", "HART")]),
    ("Electrical Panel",   "PNL", [("Rating", "{} kW"), ("Voltage", "415 V"), ("IP Rating", "IP55")]),
    ("Compressor",         "CMP", [("Capacity", "{} Nm3/hr"), ("Discharge Pressure", "{} barg"), ("Rating", "{} kW")]),
    ("Piping Spool",       "SPL", [("Size", "{} inch"), ("Schedule", "Sch 40"), ("MOC", "CS A106 Gr B")]),
    ("Blower",             "BLW", [("Capacity", "{} Nm3/hr"), ("Rating", "{} kW")]),
]

PREREQ_POOL = [
    "P&ID", "Engineering Drawings", "Datasheets", "Material Availability",
    "Tie-in Point", "Management of Change", "Hazard Study Recommendations", "Service Contract",
]
APPROVAL_POOL = [
    "Environmental Clearance", "Pressure Vessel Certification", "Electrical Safety Inspectorate",
    "Site Safety Clearance", "Workplace Safety Inspectorate", "Hazardous Materials Authority",
    "Right-of-Way / External Access", "Local Authority Permit",
]


def ramp(current, start, finish):
    if finish <= start:
        return 1.0 if current >= finish else 0.0
    if current <= start:
        return 0.0
    if current >= finish:
        return 1.0
    return (current - start).days / (finish - start).days


class Command(BaseCommand):
    help = "Populate the database with the synthetic demonstration dataset."

    def add_arguments(self, parser):
        parser.add_argument("--append", action="store_true",
                            help="Keep existing projects instead of wiping first.")

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(SEED)
        today = date.today()

        if not options["append"]:
            deleted = Project.objects.count()
            Project.objects.all().delete()
            if deleted:
                self.stdout.write(self.style.WARNING(f"Removed {deleted} existing project(s)."))

        created = 0
        for spec in PROJECTS:
            name = spec[0]
            if Project.objects.filter(name=name).exists():
                self.stdout.write(f"  skip (exists): {name}")
                continue
            self._build_project(rng, today, *spec)
            created += 1
            self.stdout.write(f"  + {name}")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {created} synthetic project(s). All data is fictional."
        ))

    # ------------------------------------------------------------------
    def _build_project(self, rng, today, name, archetype_key, months_elapsed,
                       total_months, category, nature, site):
        arch = ARCHETYPES[archetype_key]
        start = today - timedelta(days=int(months_elapsed * 30.4))
        total_days = int(total_months * 30.4)
        planned_end = start + timedelta(days=total_days)

        budget = rng.choice([850, 1200, 1750, 2400, 3100, 4500, 6200, 8000]) * 1000

        project = Project.objects.create(
            name=name,
            reg_no=f"PRJ-{rng.randint(1000, 9999)}",
            reg_date=(start - timedelta(days=rng.randint(10, 40))).isoformat(),
            ar_no=f"AR-{rng.randint(100, 999)}-{start.year}",
            budget=str(budget),
            contractor=rng.choice(CONTRACTORS),
            start_date=start.isoformat(),
            completion_date=planned_end.isoformat(),
            target_etc=planned_end.isoformat(),
            area_unit=site,
            project_category=category,
            nature_of_project=nature,
            projected_savings=str(rng.choice([120, 180, 260, 340, 500]) * 1000),
            irr=f"{rng.randint(11, 26)}%",
        )

        events = self._build_events(rng, project, today, start, total_days, arch, archetype_key)

        # Spend is derived from realised progress so the cost figures agree with the
        # schedule figures rather than being independently random.
        total_weight = sum(e["weight"] for e in events) or 1
        progress = sum(e["weight"] * e["fraction"] for e in events) / total_weight
        spent = int(budget * min(1.0, progress * arch["cost_factor"]))
        project.actual_expenditure = str(spent)
        project.save(update_fields=["actual_expenditure"])

        self._build_officials(rng, project)
        self._build_prerequisites(rng, project, arch["blockers"])
        self._build_approvals(rng, project, arch["blockers"], start)
        self._build_equipment(rng, project)

    # ------------------------------------------------------------------
    def _build_events(self, rng, project, today, start, total_days, arch, archetype_key):
        template = ACTIVITY_TEMPLATE
        weight_total = sum(t[1] for t in template)

        rows, cursor = [], start
        for title, weight, criticality in template:
            span = max(3, int(total_days * (weight / weight_total)))
            planned_start = cursor
            planned_finish = planned_start + timedelta(days=span)
            cursor = planned_finish
            rows.append({
                "title": title, "weight": weight, "criticality": criticality,
                "planned_start": planned_start, "planned_finish": planned_finish,
                "span": span,
            })

        factor = arch["factor"]
        built = []
        for row in rows:
            planned_fraction = ramp(today, row["planned_start"], row["planned_finish"])

            if archetype_key == "complete":
                fraction = 1.0
            else:
                fraction = min(1.0, planned_fraction * factor)

            # Small per-activity jitter so the curve isn't unnaturally smooth, while
            # keeping the project's overall performance at its archetype level.
            if 0.0 < fraction < 1.0:
                fraction = min(1.0, max(0.0, fraction + rng.uniform(-0.08, 0.08)))

            actual_start, actual_finish, progress_pct = "", "", 0

            if fraction >= 0.999:
                status = "Completed"
                progress_pct = 100
                slip = int(row["span"] * (1 / max(factor, 0.3) - 1))
                slip = max(0, min(slip, row["span"] * 2))
                a_start = row["planned_start"] + timedelta(days=rng.randint(0, 4))
                a_finish = min(row["planned_finish"] + timedelta(days=slip), today)
                if a_finish < a_start:
                    a_finish = a_start
                actual_start, actual_finish = a_start.isoformat(), a_finish.isoformat()
            elif fraction <= 0.001:
                status = "Planned"
            else:
                a_start = row["planned_start"] + timedelta(days=rng.randint(0, 6))
                if a_start > today:
                    a_start = today - timedelta(days=1)
                actual_start = a_start.isoformat()
                progress_pct = int(round(fraction * 100))
                status = "Delayed" if today > row["planned_finish"] else "In Progress"

            remarks = ""
            if status == "Delayed":
                remarks = rng.choice([
                    "Awaiting material clearance at site.",
                    "Contractor manpower below planned deployment.",
                    "Sequenced behind an upstream activity.",
                    "Rework identified during inspection.",
                ])

            Event.objects.create(
                project=project,
                event_name=row["title"],
                planned_start=row["planned_start"].isoformat(),
                planned_finish=row["planned_finish"].isoformat(),
                duration=row["span"],
                actual_start=actual_start,
                actual_finish=actual_finish,
                criticality_rating=row["criticality"],
                status=status,
                progress_pct=progress_pct,
                remarks=remarks,
            )
            built.append({"weight": row["span"], "fraction": fraction})
        return built

    # ------------------------------------------------------------------
    def _build_officials(self, rng, project):
        for _ in range(rng.randint(2, 4)):
            Official.objects.create(
                project=project,
                name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                designation=rng.choice(DESIGNATIONS),
                department=rng.choice(DEPARTMENTS),
                employee_id=str(rng.randint(100000, 999999)),
            )

    def _build_prerequisites(self, rng, project, blockers):
        chosen = rng.sample(PREREQ_POOL, rng.randint(5, len(PREREQ_POOL)))
        blocking_left = blockers
        for prereq in chosen:
            if blocking_left > 0 and rng.random() < 0.55:
                status = rng.choice(["Pending", "Not Available"])
                remarks = rng.choice([
                    "Vendor submission awaited.",
                    "Under review with engineering.",
                    "Held pending upstream clarification.",
                ])
                blocking_left -= 1
            else:
                status = rng.choice(["Available", "Available", "In Progress", "Not Applicable"])
                remarks = ""
            Prerequisite.objects.create(project=project, type=prereq, status=status, remarks=remarks)

    def _build_approvals(self, rng, project, blockers, start):
        blocking_left = max(0, blockers - 1)
        for approval in APPROVAL_POOL:
            roll = rng.random()
            if blocking_left > 0 and roll < 0.30:
                status, blocking_left = "Pending", blocking_left - 1
                date_val = (start + timedelta(days=rng.randint(30, 200))).isoformat()
            elif roll < 0.50:
                status = "Available"
                date_val = (start + timedelta(days=rng.randint(5, 120))).isoformat()
            else:
                status, date_val = "Not Applicable", "N/A"
            Approval.objects.create(project=project, approval_type=approval,
                                    status=status, date=date_val)

    def _build_equipment(self, rng, project):
        for index, (category, prefix, params) in enumerate(
                rng.sample(EQUIPMENT_POOL, rng.randint(3, 6)), start=1):
            tag = f"{prefix}-{rng.randint(1000, 9999)}"
            custom = {}
            for label, template in params:
                custom[label] = template.format(*[rng.randint(5, 400)
                                                  for _ in range(template.count("{}"))])
            Equipment.objects.create(
                project=project, tag=tag, category=category,
                count=rng.randint(1, 3), custom_params=custom,
            )
