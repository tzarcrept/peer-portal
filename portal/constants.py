"""
All fixed dropdown lists and constants used across the portal.

Vocabulary note: everything here is generic industrial-project terminology
(standard engineering practice, not specific to any single operator, site or
jurisdiction). Approval categories are described by what they regulate rather
than by the name of any particular statutory body, so the portal can be pointed
at any plant or region without carrying another organisation's internal terms.
"""

# Placeholder used for dropdowns that must NOT default to a real value
PLACEHOLDER = "-- Select --"

# Pre-defined equipment categories (generic rotating / static / instrumentation)
STANDARD_CATEGORIES = [
    "Centrifugal Pump",
    "Positive Displacement Pump",
    "Fan",
    "Blower",
    "Compressor",
    "Turbine",
    "Heat Exchanger",
    "Condenser",
    "Drum",
    "Tank",
    "Vessel",
    "Piping Spool",
    "Valve",
    "Instrumentation",
    "Electrical Panel",
]

# Pre-defined Project Prerequisite types
PREREQUISITE_TYPES = [
    "P&ID",
    "Engineering Drawings",
    "Datasheets",
    "Material Availability",
    "Tie-in Point",
    "Management of Change",
    "Hazard Study Recommendations",
    "Service Contract",
    "Other (Custom)",
]
PREREQUISITE_STATUSES = [
    "Available", "Pending", "In Progress", "Not Available", "Not Applicable", "Yes", "No",
]
# Prerequisite statuses that mean "this is actively holding the project up"
PREREQUISITE_BLOCKING_STATUSES = ("Pending", "Not Available", "No")

# Fixed regulatory approval matrix rows -- described by scope of regulation,
# deliberately not named after any specific national or local authority.
APPROVAL_TYPES = [
    "Environmental Clearance",
    "Pressure Vessel Certification",
    "Electrical Safety Inspectorate",
    "Site Safety Clearance",
    "Workplace Safety Inspectorate",
    "Hazardous Materials Authority",
    "Right-of-Way / External Access",
    "Local Authority Permit",
]
APPROVAL_STATUSES = ["Available", "Pending", "Not Available", "Not Applicable"]
APPROVAL_DATE_ENABLED_STATUSES = ("Available", "Pending")
# Approval statuses that mean "this is actively holding the project up"
APPROVAL_BLOCKING_STATUSES = ("Pending", "Not Available")

# Project Major Event statuses
EVENT_STATUSES = ["Planned", "In Progress", "Completed", "Delayed", "Cancelled"]
EVENT_DONE_STATUSES = ("Completed",)
EVENT_EXCLUDED_STATUSES = ("Cancelled",)

# Project categories used for portfolio grouping on the dashboard
PROJECT_CATEGORIES = [
    "Reliability Improvement",
    "Capacity Enhancement",
    "Safety Compliance",
    "Environmental Compliance",
    "Energy Efficiency",
    "Asset Replacement",
    "Debottlenecking",
    "Digital / Instrumentation",
]

NATURE_OF_PROJECT = ["Critical", "Major", "Minor", "Routine"]

# ---- Analytics thresholds (single source of truth, used by analytics.py) ----
# Schedule variance (actual % complete minus planned % complete, in points).
# The deadband stops sub-point rounding noise from being reported as a real slip:
# a project 0.2 points off its baseline is on plan, not "behind".
SCHEDULE_VARIANCE_DEADBAND = 2.0
SCHEDULE_VARIANCE_AT_RISK = -5.0    # below this -> "At Risk"
SCHEDULE_VARIANCE_CRITICAL = -15.0  # below this -> "Critical"
# Criticality rating (1-5) at or above which an activity is treated as high-impact
HIGH_CRITICALITY_THRESHOLD = 4
# Cost: actual expenditure ratio exceeding progress ratio by this much -> overrun flag
COST_OVERRUN_TOLERANCE = 0.10
