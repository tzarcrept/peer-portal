from django.contrib import admin

from .models import Approval, Equipment, Event, Official, Prerequisite, Project


class OfficialInline(admin.TabularInline):
    model = Official
    extra = 0


class PrerequisiteInline(admin.TabularInline):
    model = Prerequisite
    extra = 0


class ApprovalInline(admin.TabularInline):
    model = Approval
    extra = 0


class EventInline(admin.TabularInline):
    model = Event
    extra = 0


class EquipmentInline(admin.TabularInline):
    model = Equipment
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "project_category", "nature_of_project", "start_date", "completion_date")
    search_fields = ("name", "project_category", "area_unit", "contractor")
    inlines = [OfficialInline, PrerequisiteInline, ApprovalInline, EventInline, EquipmentInline]
