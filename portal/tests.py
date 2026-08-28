"""
Test suite for the PEER portal.

Priorities, in order:

  1. The analytics maths is correct. These are the numbers a reviewer would check
     with a calculator, so they are pinned against hand-worked expected values
     rather than against whatever the code happens to currently return.
  2. The AI layer cannot break a page. Every failure mode of the model call is
     simulated and asserted to fall back cleanly rather than raise.
  3. Every view renders, including the awkward states: no projects at all,
     a project with no dates, and an unknown project name.

Run with:  python manage.py test
"""

from datetime import date, timedelta
from unittest import mock

from django.test import Client, TestCase

from . import ai_insights, analytics
from .models import Approval, Equipment, Event, Prerequisite, Project


def make_event(project, name, p_start, p_finish, **kwargs):
    return Event.objects.create(
        project=project,
        event_name=name,
        planned_start=p_start.isoformat() if p_start else "",
        planned_finish=p_finish.isoformat() if p_finish else "",
        duration=(p_finish - p_start).days if p_start and p_finish else 1,
        **kwargs,
    )


# ==================== parsing ====================

class ParsingTests(TestCase):
    def test_parses_supported_date_formats(self):
        expected = date(2025, 3, 9)
        for text in ["2025-03-09", "09-03-2025", "09/03/2025", "2025/03/09", "09.03.2025"]:
            self.assertEqual(analytics.parse_date(text), expected, msg=text)

    def test_returns_none_for_non_dates(self):
        for text in ["", None, "N/A", "NA", "-", "TBD", "sometime next quarter", "30.11.18.4"]:
            self.assertIsNone(analytics.parse_date(text), msg=repr(text))

    def test_parses_currency_shaped_numbers(self):
        self.assertEqual(analytics.parse_number("340000"), 340000.0)
        self.assertEqual(analytics.parse_number("  3,40,000 "), 340000.0)
        self.assertEqual(analytics.parse_number("Rs 1,250.50"), 1250.50)

    def test_returns_none_for_non_numbers(self):
        for text in ["", None, "N/A", "NIL", "-", "to be advised"]:
            self.assertIsNone(analytics.parse_number(text), msg=repr(text))


# ==================== S-curve maths ====================

class SCurveTests(TestCase):
    def setUp(self):
        self.today = date(2026, 1, 1)
        self.project = Project.objects.create(name="Curve Test")

    def test_two_equal_activities_halfway_gives_fifty_percent_planned(self):
        """Two 100-day activities back to back; at the join, plan says exactly 50%."""
        start = self.today - timedelta(days=100)
        make_event(self.project, "A", start, self.today, status="Completed",
                   actual_start=start.isoformat(), actual_finish=self.today.isoformat())
        make_event(self.project, "B", self.today, self.today + timedelta(days=100), status="Planned")

        curves = analytics.build_s_curves(list(self.project.events.all()), today=self.today)
        self.assertAlmostEqual(curves["planned_today"], 50.0, places=1)
        self.assertAlmostEqual(curves["actual_today"], 50.0, places=1)
        self.assertAlmostEqual(curves["variance"], 0.0, places=1)
        self.assertAlmostEqual(curves["spi"], 1.0, places=2)

    def test_weighting_is_by_duration_not_activity_count(self):
        """A completed 10-day task next to a pending 90-day task is 10%, not 50%."""
        start = self.today - timedelta(days=10)
        make_event(self.project, "Short", start, self.today, status="Completed",
                   actual_start=start.isoformat(), actual_finish=self.today.isoformat())
        make_event(self.project, "Long", self.today, self.today + timedelta(days=90), status="Planned")

        curves = analytics.build_s_curves(list(self.project.events.all()), today=self.today)
        self.assertAlmostEqual(curves["actual_today"], 10.0, places=1)

    def test_actual_curve_is_truncated_at_today(self):
        start = self.today - timedelta(days=50)
        make_event(self.project, "Running", start, self.today + timedelta(days=50),
                   status="In Progress", actual_start=start.isoformat(), progress_pct=40)

        curves = analytics.build_s_curves(list(self.project.events.all()), today=self.today)
        future = [p for p in curves["points"] if p["date"] > self.today.isoformat()]
        self.assertTrue(future, "expected sample points after today")
        self.assertTrue(all(p["actual"] is None for p in future))
        self.assertTrue(all(p["planned"] is not None for p in curves["points"]))

    def test_both_curves_are_monotonic_and_bounded(self):
        cursor = self.today - timedelta(days=180)
        for index in range(6):
            finish = cursor + timedelta(days=30)
            make_event(self.project, f"Act {index}", cursor, finish,
                       status="Completed" if index < 3 else "Planned",
                       actual_start=cursor.isoformat() if index < 3 else "",
                       actual_finish=finish.isoformat() if index < 3 else "")
            cursor = finish

        curves = analytics.build_s_curves(list(self.project.events.all()), today=self.today)
        planned = [p["planned"] for p in curves["points"]]
        actual = [p["actual"] for p in curves["points"] if p["actual"] is not None]

        self.assertEqual(planned, sorted(planned))
        self.assertEqual(actual, sorted(actual))
        self.assertGreaterEqual(min(planned), 0.0)
        self.assertLessEqual(max(planned), 100.0)
        self.assertAlmostEqual(planned[-1], 100.0, places=1)

    def test_cancelled_activities_do_not_depress_progress(self):
        start = self.today - timedelta(days=30)
        make_event(self.project, "Done", start, self.today, status="Completed",
                   actual_start=start.isoformat(), actual_finish=self.today.isoformat())
        make_event(self.project, "Dropped", start, self.today, status="Cancelled")

        curves = analytics.build_s_curves(list(self.project.events.all()), today=self.today)
        self.assertAlmostEqual(curves["actual_today"], 100.0, places=1)

    def test_project_with_no_usable_dates_reports_no_data(self):
        Event.objects.create(project=self.project, event_name="Undated", status="Planned")
        curves = analytics.build_s_curves(list(self.project.events.all()), today=self.today)
        self.assertFalse(curves["has_data"])
        self.assertEqual(curves["points"], [])

    def test_no_events_at_all_reports_no_data(self):
        curves = analytics.build_s_curves([], today=self.today)
        self.assertFalse(curves["has_data"])


# ==================== health, ranking, cost ====================

class ClassificationTests(TestCase):
    def test_deadband_stops_rounding_noise_reading_as_a_slip(self):
        self.assertEqual(analytics.classify_health(-0.3)["label"], "On Track")
        self.assertEqual(analytics.classify_health(0.0)["label"], "On Track")

    def test_bands(self):
        self.assertEqual(analytics.classify_health(-3.0)["label"], "Slightly Behind")
        self.assertEqual(analytics.classify_health(-9.0)["label"], "At Risk")
        self.assertEqual(analytics.classify_health(-30.0)["label"], "Critical")
        self.assertEqual(analytics.classify_health(8.0)["label"], "Ahead of Plan")
        self.assertEqual(analytics.classify_health(None)["label"], "No Baseline")


class RankingTests(TestCase):
    def setUp(self):
        self.today = date(2026, 1, 1)
        self.project = Project.objects.create(name="Ranking Test")

    def test_criticality_can_outrank_a_much_older_slip(self):
        """The 90-day cap is what makes this possible; without it, age always wins."""
        old_start = self.today - timedelta(days=400)
        make_event(self.project, "Old low-criticality", old_start,
                   old_start + timedelta(days=30), status="Delayed",
                   criticality_rating=1, actual_start=old_start.isoformat(), progress_pct=50)

        recent_start = self.today - timedelta(days=120)
        make_event(self.project, "Recent high-criticality", recent_start,
                   recent_start + timedelta(days=30), status="Delayed",
                   criticality_rating=5, actual_start=recent_start.isoformat(), progress_pct=50)

        ranked = analytics.rank_critical_activities(
            list(self.project.events.all()), today=self.today)
        self.assertEqual(ranked[0]["name"], "Recent high-criticality")

    def test_completed_activities_are_excluded(self):
        start = self.today - timedelta(days=60)
        make_event(self.project, "Finished", start, self.today - timedelta(days=30),
                   status="Completed", actual_start=start.isoformat(),
                   actual_finish=(self.today - timedelta(days=30)).isoformat())
        ranked = analytics.rank_critical_activities(
            list(self.project.events.all()), today=self.today)
        self.assertEqual(ranked, [])

    def test_not_started_activity_is_flagged_with_a_reason(self):
        start = self.today - timedelta(days=45)
        make_event(self.project, "Never began", start, self.today + timedelta(days=45),
                   status="Planned", criticality_rating=3)
        ranked = analytics.rank_critical_activities(
            list(self.project.events.all()), today=self.today)
        self.assertEqual(ranked[0]["late_start_days"], 45)
        self.assertTrue(any("not started" in r for r in ranked[0]["reasons"]))


class CostTests(TestCase):
    def test_flags_spend_running_ahead_of_progress(self):
        project = Project.objects.create(name="Cost", budget="1000000",
                                         actual_expenditure="700000")
        summary = analytics.cost_summary(project, progress_pct=30.0)
        self.assertEqual(summary["burn_pct"], 70.0)
        self.assertEqual(summary["overrun_points"], 40.0)
        self.assertTrue(summary["flag"])

    def test_does_not_flag_spend_tracking_progress(self):
        project = Project.objects.create(name="Cost OK", budget="1000000",
                                         actual_expenditure="320000")
        self.assertFalse(analytics.cost_summary(project, progress_pct=30.0)["flag"])

    def test_missing_budget_is_handled(self):
        project = Project.objects.create(name="No budget", budget="N/A",
                                         actual_expenditure="")
        summary = analytics.cost_summary(project, progress_pct=50.0)
        self.assertFalse(summary["has_data"])
        self.assertIsNone(summary["burn_pct"])


class BlockerTests(TestCase):
    def test_only_blocking_statuses_are_reported(self):
        project = Project.objects.create(name="Blockers")
        Prerequisite.objects.create(project=project, type="P&ID", status="Available")
        Prerequisite.objects.create(project=project, type="Datasheets", status="Pending")
        Approval.objects.create(project=project, approval_type="Environmental Clearance",
                                status="Not Available")
        Approval.objects.create(project=project, approval_type="Local Authority Permit",
                                status="Not Applicable")

        blockers = analytics.find_blockers(project)
        self.assertEqual(len(blockers), 2)
        self.assertEqual({b["name"] for b in blockers},
                         {"Datasheets", "Environmental Clearance"})


# ==================== AI layer resilience ====================

class AIFallbackTests(TestCase):
    """The insight panel must survive every model failure mode."""

    def setUp(self):
        self.today = date(2026, 1, 1)
        self.project = Project.objects.create(
            name="AI Test", budget="1000000", actual_expenditure="600000",
            completion_date=(self.today + timedelta(days=90)).isoformat())
        start = self.today - timedelta(days=120)
        make_event(self.project, "Slipping activity", start, self.today - timedelta(days=30),
                   status="Delayed", criticality_rating=5,
                   actual_start=start.isoformat(), progress_pct=40)
        self.analysis = analytics.analyse_project(self.project, today=self.today)

    def assert_usable(self, insight):
        self.assertIn(insight["source"], {"ai", "rules"})
        self.assertTrue(insight["summary"].strip())
        self.assertIsInstance(insight["risks"], list)
        self.assertIsInstance(insight["actions"], list)

    def test_falls_back_when_no_api_key_is_configured(self):
        with self.settings(AI_API_KEY="", AI_CACHE_SECONDS=0):
            insight = ai_insights.project_insight(self.analysis)
        self.assertEqual(insight["source"], "rules")
        self.assert_usable(insight)
        self.assertIn("AI Test", insight["summary"])

    def test_fallback_narrative_cites_the_real_computed_figures(self):
        with self.settings(AI_API_KEY="", AI_CACHE_SECONDS=0):
            insight = ai_insights.project_insight(self.analysis)
        self.assertIn("Slipping activity", " ".join(
            r["title"] + r["detail"] for r in insight["risks"] + insight["actions"]))

    def test_survives_network_error(self):
        with self.settings(AI_API_KEY="k", AI_CACHE_SECONDS=0), \
             mock.patch("portal.ai_insights.urllib.request.urlopen",
                        side_effect=OSError("network down")):
            insight = ai_insights.project_insight(self.analysis)
        self.assertEqual(insight["source"], "rules")
        self.assert_usable(insight)

    def test_survives_timeout(self):
        with self.settings(AI_API_KEY="k", AI_CACHE_SECONDS=0), \
             mock.patch("portal.ai_insights.urllib.request.urlopen",
                        side_effect=TimeoutError()):
            insight = ai_insights.project_insight(self.analysis)
        self.assertEqual(insight["source"], "rules")
        self.assert_usable(insight)

    def test_survives_malformed_json_from_model(self):
        with self.settings(AI_API_KEY="k", AI_CACHE_SECONDS=0), \
             mock.patch("portal.ai_insights._call_model",
                        return_value=(None, "Could not parse the AI response.")):
            insight = ai_insights.project_insight(self.analysis)
        self.assertEqual(insight["source"], "rules")
        self.assert_usable(insight)

    def test_survives_unexpected_exception_anywhere_in_the_layer(self):
        with self.settings(AI_API_KEY="k", AI_CACHE_SECONDS=0), \
             mock.patch("portal.ai_insights._call_model",
                        side_effect=RuntimeError("boom")):
            insight = ai_insights.project_insight(self.analysis)
        self.assert_usable(insight)

    def test_accepts_a_well_formed_model_response(self):
        payload = {
            "summary": "Behind plan.",
            "risks": [{"title": "R", "detail": "d"}],
            "actions": [{"title": "A", "detail": "d"}],
        }
        with self.settings(AI_API_KEY="k", AI_CACHE_SECONDS=0), \
             mock.patch("portal.ai_insights._call_model", return_value=(payload, None)):
            insight = ai_insights.project_insight(self.analysis)
        self.assertEqual(insight["source"], "ai")
        self.assertEqual(insight["summary"], "Behind plan.")

    def test_strips_markdown_fences_from_model_output(self):
        raw = '```json\n{"summary": "S", "risks": [], "actions": []}\n```'
        parsed = ai_insights._parse_json_response(raw)
        self.assertEqual(parsed["summary"], "S")

    def test_recovers_json_embedded_in_prose(self):
        raw = 'Sure, here you go: {"summary": "S", "risks": [], "actions": []} Hope that helps.'
        parsed = ai_insights._parse_json_response(raw)
        self.assertEqual(parsed["summary"], "S")

    def test_rejects_response_with_no_summary(self):
        self.assertIsNone(ai_insights._parse_json_response('{"risks": []}'))
        self.assertIsNone(ai_insights._parse_json_response("not json at all"))


# ==================== views ====================

class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = date.today()
        cls.project = Project.objects.create(
            name="View Test Project", budget="500000", actual_expenditure="200000",
            project_category="Reliability Improvement", nature_of_project="Major",
            start_date=(today - timedelta(days=60)).isoformat(),
            completion_date=(today + timedelta(days=60)).isoformat())
        make_event(cls.project, "Design", today - timedelta(days=60), today - timedelta(days=20),
                   status="Completed", criticality_rating=4,
                   actual_start=(today - timedelta(days=60)).isoformat(),
                   actual_finish=(today - timedelta(days=20)).isoformat())
        make_event(cls.project, "Build", today - timedelta(days=20), today + timedelta(days=40),
                   status="In Progress", criticality_rating=5,
                   actual_start=(today - timedelta(days=20)).isoformat(), progress_pct=35)
        Prerequisite.objects.create(project=cls.project, type="Datasheets", status="Pending")
        Approval.objects.create(project=cls.project, approval_type="Site Safety Clearance",
                                status="Available", date=today.isoformat())
        Equipment.objects.create(project=cls.project, tag="PMP-1001",
                                 category="Centrifugal Pump", count=2,
                                 custom_params={"Flow Rate": "40 m3/hr"})

    def setUp(self):
        self.client = Client()

    def test_all_pages_render(self):
        for url in ["/", "/analytics/", "/repository/", "/project/new/",
                    f"/analytics/{self.project.name}/",
                    f"/project/{self.project.name}/edit/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_dashboard_shows_the_project(self):
        body = self.client.get("/").content.decode()
        self.assertIn("View Test Project", body)
        self.assertIn("Schedule variance", body)

    def test_project_analytics_includes_curve_payload(self):
        body = self.client.get(f"/analytics/{self.project.name}/").content.decode()
        self.assertIn("curve-data", body)
        self.assertIn("Target vs current", body)

    def test_unknown_project_falls_back_to_first_rather_than_erroring(self):
        response = self.client.get("/analytics/", {"project": "does not exist"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View Test Project")

    def test_empty_database_renders_guidance_not_a_crash(self):
        Project.objects.all().delete()
        for url in ["/", "/analytics/", "/repository/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "seed_synthetic_data")

    def test_csv_exports(self):
        raw = self.client.get("/download-csv/")
        self.assertEqual(raw.status_code, 200)
        self.assertIn("attachment", raw["Content-Disposition"])

        derived = self.client.get("/download-analytics-csv/")
        body = derived.content.decode()
        self.assertIn("schedule_variance_points", body)
        self.assertIn("View Test Project", body)

    def test_insight_refresh_returns_json(self):
        response = self.client.post(f"/insight/{self.project.name}/refresh/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["insight"]["summary"])

    def test_insight_refresh_for_unknown_project_is_a_clean_404(self):
        response = self.client.post("/insight/nope/refresh/")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["ok"])

    def test_create_project_round_trip(self):
        response = self.client.post("/project/new/", {
            "proj_name": "Created By Test",
            "budget": "123456",
            "start_date": "2026-01-01",
            "comp_date": "2026-12-31",
            "events_json": '[{"event_name": "Kickoff", "planned_start": "2026-01-01",'
                           ' "planned_finish": "2026-02-01", "duration": 31,'
                           ' "status": "Completed", "criticality_rating": 3,'
                           ' "progress_pct": 0, "actual_start": "2026-01-01",'
                           ' "actual_finish": "2026-01-28", "remarks": ""}]',
            "equipment_json": "[]", "prereqs_json": "[]",
            "officials_json": "[]", "approvals_json": "{}",
        })
        self.assertEqual(response.status_code, 302)
        created = Project.objects.get(name="Created By Test")
        event = created.events.first()
        # Status Completed must force progress to 100 regardless of what was posted,
        # so the actual curve can never contradict the status column.
        self.assertEqual(event.progress_pct, 100)

    def test_duplicate_project_name_is_rejected(self):
        response = self.client.post("/project/new/", {
            "proj_name": "View Test Project",
            "equipment_json": "[]", "prereqs_json": "[]", "officials_json": "[]",
            "events_json": "[]", "approvals_json": "{}",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    def test_delete_project(self):
        response = self.client.post(f"/project/{self.project.name}/delete/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Project.objects.filter(name=self.project.name).exists())


class SeedCommandTests(TestCase):
    def test_seeding_produces_an_analytically_varied_portfolio(self):
        from django.core.management import call_command
        from io import StringIO

        call_command("seed_synthetic_data", stdout=StringIO())
        projects = list(Project.objects.prefetch_related(
            "events", "prerequisites", "approvals", "equipment_items"))
        self.assertGreaterEqual(len(projects), 15)

        portfolio = analytics.analyse_portfolio(projects)
        labels = {row["health"]["label"] for row in portfolio["rows"]}
        # A dataset where everything is On Track would demonstrate nothing.
        self.assertIn("Critical", labels)
        self.assertIn("On Track", labels)
        self.assertGreater(portfolio["total_blockers"], 0)
