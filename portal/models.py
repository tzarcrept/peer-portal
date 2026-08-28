"""
Database schema for the portal. Each section of a project sheet becomes its own
table, linked back to Project by a foreign key.

Dates are kept as plain CharFields (not DateField) rather than proper date types.
This matches how project sheets are filled in practice, where some date-like fields
legitimately hold non-date text (e.g. "N/A" for an approval that hasn't happened,
or free-text values in Target/ETC). A real DateField would reject those.
portal/analytics.py parses these defensively -- anything unparseable is simply
ignored by the analytics rather than raising.
"""

from django.db import models


class Project(models.Model):
    name = models.CharField(max_length=255, unique=True)

    # ---- Administrative Details ----
    reg_no = models.CharField(max_length=255, blank=True, default="")
    reg_date = models.CharField(max_length=20, blank=True, default="")
    ar_no = models.CharField(max_length=255, blank=True, default="")
    budget = models.CharField(max_length=255, blank=True, default="")
    actual_expenditure = models.CharField(max_length=255, blank=True, default="")
    contractor = models.CharField(max_length=255, blank=True, default="")
    start_date = models.CharField(max_length=20, blank=True, default="")
    completion_date = models.CharField(max_length=20, blank=True, default="")
    target_etc = models.CharField(max_length=255, blank=True, default="")
    area_unit = models.CharField(max_length=255, blank=True, default="")
    project_category = models.CharField(max_length=255, blank=True, default="")
    nature_of_project = models.CharField(max_length=255, blank=True, default="")
    projected_savings = models.CharField(max_length=255, blank=True, default="")
    irr = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Official(models.Model):
    project = models.ForeignKey(Project, related_name="officials", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    designation = models.CharField(max_length=255, blank=True, default="")
    department = models.CharField(max_length=255, blank=True, default="")
    employee_id = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} ({self.project.name})"


class Prerequisite(models.Model):
    project = models.ForeignKey(Project, related_name="prerequisites", on_delete=models.CASCADE)
    type = models.CharField(max_length=255)
    status = models.CharField(max_length=50)
    remarks = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.type} ({self.project.name})"


class Approval(models.Model):
    project = models.ForeignKey(Project, related_name="approvals", on_delete=models.CASCADE)
    approval_type = models.CharField(max_length=100)
    status = models.CharField(max_length=50, default="Not Applicable")
    date = models.CharField(max_length=20, blank=True, default="N/A")

    class Meta:
        ordering = ["id"]
        unique_together = ("project", "approval_type")

    def __str__(self):
        return f"{self.approval_type} ({self.project.name})"


class Event(models.Model):
    """A scheduled activity / milestone. These rows drive both S-curves."""

    project = models.ForeignKey(Project, related_name="events", on_delete=models.CASCADE)
    event_name = models.CharField(max_length=255)
    planned_start = models.CharField(max_length=20, blank=True, default="")
    planned_finish = models.CharField(max_length=20, blank=True, default="")
    duration = models.IntegerField(default=1)
    actual_start = models.CharField(max_length=20, blank=True, default="")
    actual_finish = models.CharField(max_length=20, blank=True, default="")
    criticality_rating = models.IntegerField(default=1)
    status = models.CharField(max_length=50, default="Planned")
    # Percent complete for activities that are underway. Completed activities are
    # treated as 100 regardless of this value; Planned activities as 0. Only
    # In Progress / Delayed rows actually read it. Needed for a meaningful
    # actual (current) S-curve -- without it, work in flight registers as zero.
    progress_pct = models.IntegerField(default=0)
    remarks = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.event_name} ({self.project.name})"


class Equipment(models.Model):
    project = models.ForeignKey(Project, related_name="equipment_items", on_delete=models.CASCADE)
    tag = models.CharField(max_length=255, verbose_name="Tag Number / Name")
    category = models.CharField(max_length=255)
    count = models.IntegerField(default=1)
    # Everything that isn't Category/Count -- the free-form spec key/value pairs
    # (e.g. "Flow rate": "7", "MOC": "SS316") -- kept as JSON rather than a separate
    # table, since these are always read/written as a single unit, never queried
    # individually.
    custom_params = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]
        unique_together = ("project", "tag")

    def __str__(self):
        return f"{self.tag} ({self.project.name})"
