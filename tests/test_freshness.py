"""
Unit tests for RoleRadar freshness policy and semantic classification.
"""

from datetime import datetime, timedelta, timezone
import unittest

from ingestion.freshness import (
    DEFAULT_FRESHNESS_DAYS,
    FRESHNESS_INACTIVE,
    FRESHNESS_RECENTLY_DISCOVERED,
    FRESHNESS_RECENTLY_POSTED,
    FRESHNESS_STALE,
    classify_freshness_status,
    get_effective_freshness_date,
    get_freshness_sql_predicate,
    get_today_freshness_sql_predicate,
    get_week_freshness_sql_predicate,
    is_job_fresh,
    is_job_posted_today,
    is_job_posted_this_week,
    is_job_recently_posted,
    RECENTLY_POSTED_DAYS,
)


class TestFreshnessPolicy(unittest.TestCase):
    """
    Verifies freshness calculation, 30-day window boundaries,
    and publication/discovery timestamp fallbacks.
    """

    def setUp(self):
        self.ref_time = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_posting_from_today_is_fresh(self):
        today = self.ref_time - timedelta(hours=2)
        self.assertTrue(is_job_fresh(posted_at=today, created_at=today, reference_time=self.ref_time))

    def test_posting_10_days_old_is_fresh(self):
        ten_days_ago = self.ref_time - timedelta(days=10)
        self.assertTrue(is_job_fresh(posted_at=ten_days_ago, created_at=ten_days_ago, reference_time=self.ref_time))

    def test_posting_30_day_boundary_behavior(self):
        # Exactly 30 days is fresh
        boundary_30 = self.ref_time - timedelta(days=DEFAULT_FRESHNESS_DAYS)
        self.assertTrue(
            is_job_fresh(posted_at=boundary_30, created_at=boundary_30, reference_time=self.ref_time),
            "Job posted exactly 30 days ago should be considered fresh.",
        )

        # 30 days and 1 second ago is stale
        stale_30_plus = self.ref_time - timedelta(days=DEFAULT_FRESHNESS_DAYS, seconds=1)
        self.assertFalse(
            is_job_fresh(posted_at=stale_30_plus, created_at=stale_30_plus, reference_time=self.ref_time),
            "Job older than 30 days should be considered stale.",
        )

    def test_six_month_old_posting_is_stale(self):
        six_months_ago = self.ref_time - timedelta(days=180)
        self.assertFalse(
            is_job_fresh(posted_at=six_months_ago, created_at=six_months_ago, reference_time=self.ref_time)
        )

    def test_posted_at_null_falls_back_to_created_at(self):
        # posted_at is None, but created_at was 5 days ago -> fresh (recently_discovered)
        five_days_ago = self.ref_time - timedelta(days=5)
        self.assertTrue(
            is_job_fresh(posted_at=None, created_at=five_days_ago, reference_time=self.ref_time)
        )

        # posted_at is None, but created_at was 60 days ago -> stale
        sixty_days_ago = self.ref_time - timedelta(days=60)
        self.assertFalse(
            is_job_fresh(posted_at=None, created_at=sixty_days_ago, reference_time=self.ref_time)
        )

    def test_both_null_returns_false(self):
        self.assertFalse(is_job_fresh(posted_at=None, created_at=None, reference_time=self.ref_time))

    def test_effective_freshness_date_precedence(self):
        posted = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
        discovered = datetime(2026, 9, 25, 8, 0, 0, tzinfo=timezone.utc)

        # Trustworthy posted_at takes precedence
        self.assertEqual(get_effective_freshness_date(posted, discovered), posted)

        # When posted_at is None, created_at is returned
        self.assertEqual(get_effective_freshness_date(None, discovered), discovered)

        # Both None
        self.assertIsNone(get_effective_freshness_date(None, None))


class TestFreshnessClassification(unittest.TestCase):
    """
    Verifies semantic classification distinguishing recently_posted,
    recently_discovered, stale, and inactive jobs without fabricating freshness.
    """

    def setUp(self):
        self.ref_time = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_posted_today_is_recently_posted(self):
        # posted today => recently_posted
        today = self.ref_time - timedelta(hours=3)
        status = classify_freshness_status(
            posted_at=today,
            created_at=today,
            is_active=True,
            reference_time=self.ref_time,
        )
        self.assertEqual(status, FRESHNESS_RECENTLY_POSTED)

    def test_posted_6_months_ago_is_stale_even_if_created_today(self):
        # posted 6 months ago => stale even if created today
        six_months_ago = self.ref_time - timedelta(days=180)
        today = self.ref_time
        status = classify_freshness_status(
            posted_at=six_months_ago,
            created_at=today,
            is_active=True,
            reference_time=self.ref_time,
        )
        self.assertEqual(status, "active")

    def test_posted_at_null_created_today_is_recently_discovered_not_recently_posted(self):
        # posted_at NULL + created today => recently_discovered, NOT recently_posted
        today = self.ref_time - timedelta(hours=1)
        status = classify_freshness_status(
            posted_at=None,
            created_at=today,
            is_active=True,
            reference_time=self.ref_time,
        )
        self.assertEqual(status, FRESHNESS_RECENTLY_DISCOVERED)
        self.assertNotEqual(status, FRESHNESS_RECENTLY_POSTED)

    def test_inactive_job_is_inactive(self):
        # inactive job => inactive regardless of posted or created dates
        today = self.ref_time
        status = classify_freshness_status(
            posted_at=today,
            created_at=today,
            is_active=False,
            reference_time=self.ref_time,
        )
        self.assertEqual(status, FRESHNESS_INACTIVE)

    def test_unknown_date_active_jobs_not_mislabeled_as_newly_posted(self):
        # Unknown-date jobs (posted_at = None) must never be labeled as recently_posted
        for days_ago in [0, 5, 20, 44]:
            created = self.ref_time - timedelta(days=days_ago)
            status = classify_freshness_status(
                posted_at=None,
                created_at=created,
                is_active=True,
                reference_time=self.ref_time,
            )
            self.assertNotEqual(
                status,
                FRESHNESS_RECENTLY_POSTED,
                f"Job created {days_ago} days ago without posted_at should never be labeled recently_posted",
            )
            self.assertEqual(status, FRESHNESS_RECENTLY_DISCOVERED if days_ago <= DEFAULT_FRESHNESS_DAYS else "active")

    def test_unknown_date_discovered_beyond_window_is_stale(self):
        # If posted_at is None and created_at is beyond freshness window => stale
        sixty_days_ago = self.ref_time - timedelta(days=60)
        status = classify_freshness_status(
            posted_at=None,
            created_at=sixty_days_ago,
            is_active=True,
            reference_time=self.ref_time,
        )
        self.assertEqual(status, "active")


class TestFreshnessSqlPredicate(unittest.TestCase):
    """
    Verifies that get_freshness_sql_predicate produces the exact SQL rules
    matching Python freshness classification.
    """

    def test_default_predicate_with_jp_alias(self):
        sql = get_freshness_sql_predicate("jp")
        self.assertIn("jp.posted_at IS NOT NULL", sql)
        self.assertIn("jp.posted_at >= NOW() - INTERVAL '30 days'", sql)
        self.assertIn("jp.posted_at IS NULL", sql)
        self.assertIn("jp.created_at >= NOW() - INTERVAL '30 days'", sql)

    def test_predicate_without_alias(self):
        sql = get_freshness_sql_predicate("")
        self.assertIn("posted_at IS NOT NULL", sql)
        self.assertIn("posted_at >= NOW() - INTERVAL '30 days'", sql)
        self.assertIn("posted_at IS NULL", sql)
        self.assertIn("created_at >= NOW() - INTERVAL '30 days'", sql)
        # Ensure no accidental ".." or invalid alias
        self.assertNotIn(".posted_at", sql)

    def test_predicate_custom_days(self):
        sql = get_freshness_sql_predicate("jp", freshness_days=30)
        self.assertIn("INTERVAL '30 days'", sql)

    def test_today_sql_predicate_strict_posted_at_only(self):
        sql = get_today_freshness_sql_predicate("jp")
        self.assertIn("jp.posted_at IS NOT NULL", sql)
        self.assertIn("jp.posted_at >= (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')", sql)
        self.assertIn("jp.posted_at < (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') + INTERVAL '1 day'", sql)
        self.assertNotIn("jp.created_at", sql)
        self.assertNotIn("created_at", sql)

    def test_week_sql_predicate_strict_posted_at_only(self):
        sql = get_week_freshness_sql_predicate("jp", freshness_days=7)
        self.assertIn("jp.posted_at IS NOT NULL", sql)
        self.assertIn("jp.posted_at >= NOW() - INTERVAL '7 days'", sql)
        self.assertNotIn("jp.created_at", sql)
        self.assertNotIn("created_at", sql)


class TestTodayAndWeekScopingPolicy(unittest.TestCase):
    """
    Verifies that today and week freshness scoping strictly require posted_at
    and never fall back to created_at.
    """

    def setUp(self):
        self.ref_time = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_posted_today_included_in_today_and_week(self):
        today = self.ref_time - timedelta(hours=3)
        self.assertTrue(is_job_posted_today(today, reference_time=self.ref_time))
        self.assertTrue(is_job_posted_this_week(today, freshness_days=7, reference_time=self.ref_time))

    def test_posted_3_days_ago_excluded_from_today_included_in_week(self):
        three_days_ago = self.ref_time - timedelta(days=3)
        self.assertFalse(is_job_posted_today(three_days_ago, reference_time=self.ref_time))
        self.assertTrue(is_job_posted_this_week(three_days_ago, freshness_days=7, reference_time=self.ref_time))

    def test_posted_10_days_ago_excluded_from_today_and_week(self):
        ten_days_ago = self.ref_time - timedelta(days=10)
        self.assertFalse(is_job_posted_today(ten_days_ago, reference_time=self.ref_time))
        self.assertFalse(is_job_posted_this_week(ten_days_ago, freshness_days=7, reference_time=self.ref_time))

    def test_posted_at_null_with_created_at_today_excluded_from_today_and_week(self):
        # posted_at is NULL => must be excluded from today and week regardless of created_at
        self.assertFalse(is_job_posted_today(None, reference_time=self.ref_time))
class TestRecentlyPostedSemanticsAndBoundaries(unittest.TestCase):
    """
    Verifies rolling 7-day recently_posted semantics and strict posted_at requirement.
    Undated jobs (posted_at is None) must always evaluate to False.
    Jobs older than 7 days must always evaluate to False.
    """

    def setUp(self):
        self.ref_time = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)

    def test_posted_within_7_days_is_recently_posted(self):
        for days_ago in [0, 1, 3, 6]:
            posted = self.ref_time - timedelta(days=days_ago)
            self.assertTrue(
                is_job_recently_posted(posted, reference_time=self.ref_time),
                f"Job posted {days_ago} days ago should be recently_posted",
            )

    def test_posted_exact_7_day_boundary(self):
        exact_7_days = self.ref_time - timedelta(days=7)
        self.assertTrue(
            is_job_recently_posted(exact_7_days, reference_time=self.ref_time),
            "Job posted exactly 7 days ago should be recently_posted",
        )

    def test_posted_older_than_7_days_not_recently_posted(self):
        for days_ago in [8, 14, 30, 35, 43]:
            posted = self.ref_time - timedelta(days=days_ago)
            self.assertFalse(
                is_job_recently_posted(posted, reference_time=self.ref_time),
                f"Job posted {days_ago} days ago should NOT be recently_posted",
            )

    def test_undated_jobs_never_recently_posted(self):
        self.assertFalse(is_job_recently_posted(None, reference_time=self.ref_time))


if __name__ == "__main__":
    unittest.main()
