"""
Unit tests for RoleRadar ingestion pipeline, transaction handling, and tombstoning safety.
Uses mocked database connections and clients; zero live network calls.
"""

from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, call, patch

from ingestion.base import FetchResult, RawJobPosting
from ingestion.http_client import IngestionFetchError
from ingestion.pipeline import (
    build_job_id,
    get_or_create_company,
    get_or_create_location,
    get_or_create_skill,
    sync_broad_source,
    sync_company,
    sync_posting_skills,
    upsert_job_posting,
)


class TestPipelineHelpers(unittest.TestCase):
    def test_build_job_id_deterministic(self):
        # Normal length identifier
        job_id = build_job_id("greenhouse", "12345")
        self.assertEqual(job_id, "greenhouse:12345")
        self.assertLessEqual(len(job_id), 100)

        # Extremely long identifier (exceeds 100 chars)
        very_long_vendor_id = "a" * 150
        hashed_job_id = build_job_id("greenhouse", very_long_vendor_id)
        self.assertLessEqual(len(hashed_job_id), 100)
        self.assertTrue(hashed_job_id.startswith("greenhouse:"))
        # Deterministic check
        self.assertEqual(hashed_job_id, build_job_id("greenhouse", very_long_vendor_id))

    def test_get_or_create_location_preserves_long_location_string(self):
        """
        Regression test: ensures get_or_create_location preserves long location strings
        exceeding 255 characters (e.g. multi-location strings from Datadog) without
        artificial slicing or truncation in Python.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [None, (99,)]

        long_loc = (
            "Boston, Massachusetts, USA; Connecticut, USA, Remote; Delaware, USA, Remote; "
            "District of Columbia, USA, Remote; Maryland, USA, Remote; Massachusetts, USA, Remote; "
            "New Hampshire, USA, Remote; New Jersey, USA, Remote; New York, USA, Remote; "
            "Rhode Island, USA, Remote"
        )
        self.assertGreater(len(long_loc), 255)

        loc_id, is_new = get_or_create_location(mock_cur, long_loc, "United States")
        self.assertTrue(is_new)
        self.assertEqual(loc_id, 99)

        # Check SELECT and INSERT queries both received the complete, non-truncated string
        select_query, select_params = mock_cur.execute.call_args_list[0][0]
        self.assertEqual(select_params[0], long_loc)

        insert_query, insert_params = mock_cur.execute.call_args_list[1][0]
        self.assertEqual(insert_params[0], long_loc)

    def test_upsert_job_posting_insert_new(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [None, (42,)]  # First query: not found; second: INSERT RETURNING id

        def validating_execute(query, params=None):
            if params is not None:
                placeholders = query.count("%s")
                if placeholders != len(params):
                    raise IndexError(
                        f"tuple index out of range: {placeholders} placeholders vs {len(params)} parameters"
                    )
            return None

        mock_cur.execute.side_effect = validating_execute

        posting_id, is_new = upsert_job_posting(
            cur=mock_cur,
            job_id="gh:101",
            company_id=1,
            title="Backend Engineer",
            location_id=2,
            description="Python API",
            workplace_type="remote",
            source_name="greenhouse",
            source_job_id="101",
            source_url="https://jobs.com/101",
            posted_at=None,
            role_type="full_time",
        )

        self.assertTrue(is_new)
        self.assertEqual(posting_id, 42)
        # Verify INSERT was called
        executed_sql = mock_cur.execute.call_args_list[1][0][0]
        self.assertIn("INSERT INTO job_postings", executed_sql)

    def test_upsert_job_posting_placeholder_parameter_count_matches(self):
        """
        Regression test: ensures that the INSERT query in upsert_job_posting
        has the exact number of %s placeholders as elements in the parameter tuple.
        Prevents 'IndexError: tuple index out of range' errors in psycopg2.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [None, (99,)]

        calls = []

        def capturing_execute(query, params=None):
            calls.append((query, params))
            if params is not None:
                placeholders = query.count("%s")
                if placeholders != len(params):
                    raise IndexError(
                        f"tuple index out of range: {placeholders} placeholders vs {len(params)} parameters"
                    )

        mock_cur.execute.side_effect = capturing_execute

        posting_id, is_new = upsert_job_posting(
            cur=mock_cur,
            job_id="test:101",
            company_id=1,
            title="Software Engineer",
            location_id=1,
            description="Desc",
            workplace_type="remote",
            source_name="test_source",
            source_job_id="101",
            source_url="https://jobs.com/101",
            posted_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            role_type="full_time",
        )

        self.assertTrue(is_new)
        self.assertEqual(posting_id, 99)
        self.assertEqual(len(calls), 2)
        insert_query, insert_params = calls[1]
        self.assertEqual(insert_query.count("%s"), len(insert_params))

    def test_upsert_job_posting_update_existing_preserves_created_at(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (10,)  # Existing record found with id 10

        posting_id, is_new = upsert_job_posting(
            cur=mock_cur,
            job_id="gh:101",
            company_id=1,
            title="Senior Backend Engineer",
            location_id=2,
            description="Updated description",
            workplace_type="hybrid",
            source_name="greenhouse",
            source_job_id="101",
            source_url="https://jobs.com/101",
            posted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        self.assertFalse(is_new)
        self.assertEqual(posting_id, 10)
        # Verify UPDATE was called and created_at was NOT modified
        executed_sql = mock_cur.execute.call_args_list[1][0][0]
        self.assertIn("UPDATE job_postings", executed_sql)
        self.assertNotIn("created_at =", executed_sql)
        self.assertIn("last_seen_at = NOW()", executed_sql)
        self.assertIn("is_active = TRUE", executed_sql)

    def test_sync_posting_skills(self):
        mock_cur = MagicMock()
        # Current linked skills: 1 and 2
        mock_cur.fetchall.return_value = [(1,), (2,)]
        # Target skills: 2 and 3 -> remove 1, add 3, keep 2
        added, removed = sync_posting_skills(mock_cur, job_posting_id=10, skill_ids={2, 3})

        self.assertEqual(added, 1)
        self.assertEqual(removed, 1)


class TestPipelineSyncLifecycle(unittest.TestCase):
    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value.__enter__.return_value = self.mock_cur

        self.company_config = {
            "name": "Figma",
            "ats": "greenhouse",
            "identifier": "figma",
        }

    @patch("ingestion.pipeline.get_ats_client")
    def test_clean_sync_permits_tombstoning(self, mock_get_client):
        # Clean fetch: 0 parse errors, fetch complete
        mock_client = MagicMock()
        raw_job = RawJobPosting(
            source_name="greenhouse",
            source_job_id="101",
            company_name="Figma",
            title="Senior Software Engineer",
            raw_location="San Francisco, CA",
            source_url="https://jobs.com/101",
            posted_at=None,
            raw_description="<p>Python and PostgreSQL developer.</p>",
        )
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[raw_job],
            parse_error_count=0,
            fetch_complete=True,
            total_raw_records=1,
        )
        mock_get_client.return_value = mock_client

        # Mock sequence of SQL returns
        # 1. sync_runs insert
        # 2. company get/create
        # 3. location get/create
        # 4. skill get/create (Python, PostgreSQL)
        # 5. job_postings upsert check (None -> INSERT)
        # 6. sync_posting_skills current IDs ([])
        # 7. tombstoning RETURNING id ([(99,)]) -> 1 deactivated
        self.mock_cur.fetchone.side_effect = [
            (1,),       # sync_runs id
            (10,),      # company_id
            (20,),      # location_id
            (30,),      # skill 1
            (31,),      # skill 2
            None, (40,), # job check (None), insert returning id 40
            (1, 0),     # tombstone guard: active count, would-deactivate count
        ]
        self.mock_cur.fetchall.side_effect = [
            [],         # current skills
            [(99,)],    # tombstone deactivated IDs
        ]

        result = sync_company(self.company_config, db_conn=self.mock_conn)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["jobs_fetched"], 1)
        self.assertEqual(result["swe_jobs_accepted"], 1)
        self.assertEqual(result["jobs_upserted"], 1)
        self.assertEqual(result["jobs_deactivated"], 1)
        self.assertIsNone(result["error_message"])

        # Confirm tombstone UPDATE was executed
        all_sql = [c[0][0] for c in self.mock_cur.execute.call_args_list]
        tombstone_sql = [s for s in all_sql if "SET is_active = FALSE" in s]
        self.assertTrue(len(tombstone_sql) > 0)
        # Verify safety scopes
        self.assertIn("source_name != 'sample'", tombstone_sql[0])
        self.assertIn("last_seen_at <", tombstone_sql[0])

    @patch("ingestion.pipeline.get_ats_client")
    def test_parse_errors_suppress_tombstoning(self, mock_get_client):
        # Degraded fetch: 1 parse error
        mock_client = MagicMock()
        raw_job = RawJobPosting(
            source_name="greenhouse",
            source_job_id="101",
            company_name="Figma",
            title="Backend Engineer",
            raw_location="San Francisco, CA",
            source_url="https://jobs.com/101",
            posted_at=None,
            raw_description="<p>Python</p>",
        )
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[raw_job],
            parse_error_count=1,
            fetch_complete=True,
            total_raw_records=2,
        )
        mock_get_client.return_value = mock_client

        self.mock_cur.fetchone.side_effect = [
            (1,),       # sync_runs id
            (10,),      # company_id
            (20,),      # location_id
            (30,),      # skill
            None, (40,) # job insert
        ]
        self.mock_cur.fetchall.return_value = []

        result = sync_company(self.company_config, db_conn=self.mock_conn)

        # Valid rows were saved, so this is an explicit partial success with tombstoning suppressed
        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["parse_error_count"], 1)
        self.assertEqual(result["jobs_deactivated"], 0)
        self.assertIn("tombstoning suppressed", result["error_message"].lower())

        # Verify tombstoning UPDATE was NEVER executed
        all_sql = [c[0][0] for c in self.mock_cur.execute.call_args_list]
        tombstone_sql = [s for s in all_sql if "SET is_active = FALSE" in s]
        self.assertEqual(len(tombstone_sql), 0)

    @patch("ingestion.pipeline.get_ats_client")
    def test_feed_failure_suppresses_tombstoning_and_marks_failed(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.fetch_jobs.side_effect = IngestionFetchError("Connection timed out")
        mock_get_client.return_value = mock_client

        self.mock_cur.fetchone.return_value = (5,)  # sync_run_id

        result = sync_company(self.company_config, db_conn=self.mock_conn)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["jobs_upserted"], 0)
        self.assertEqual(result["jobs_deactivated"], 0)
        self.assertIn("Connection timed out", result["error_message"])

    @patch("ingestion.pipeline.get_ats_client")
    def test_non_swe_jobs_excluded_from_upsert(self, mock_get_client):
        mock_client = MagicMock()
        swe_job = RawJobPosting(
            source_name="greenhouse",
            source_job_id="101",
            company_name="Figma",
            title="Backend Engineer",
            raw_location="San Francisco, CA",
            source_url="https://jobs.com/101",
            posted_at=None,
            raw_description="Python",
        )
        non_swe_job = RawJobPosting(
            source_name="greenhouse",
            source_job_id="102",
            company_name="Figma",
            title="Technical Recruiter",
            raw_location="San Francisco, CA",
            source_url="https://jobs.com/102",
            posted_at=None,
            raw_description="Recruiting",
        )
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[swe_job, non_swe_job],
            parse_error_count=0,
            fetch_complete=True,
            total_raw_records=2,
        )
        mock_get_client.return_value = mock_client

        self.mock_cur.fetchone.side_effect = [
            (1,),       # sync_runs id
            (10,),      # company_id
            (20,),      # location_id
            (30,),      # skill
            None, (40,), # job insert (only for swe_job!)
            (1, 0),     # tombstone guard counts
        ]
        self.mock_cur.fetchall.side_effect = [[], []]

        result = sync_company(self.company_config, db_conn=self.mock_conn)

        self.assertEqual(result["jobs_fetched"], 2)
        self.assertEqual(result["swe_jobs_accepted"], 1)
        self.assertEqual(result["jobs_upserted"], 1)

    @patch("ingestion.pipeline.get_ats_client")
    def test_dry_run_performs_zero_database_writes(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[
                RawJobPosting(
                    source_name="greenhouse",
                    source_job_id="101",
                    company_name="Figma",
                    title="Software Engineer",
                    raw_location="Remote",
                    source_url="https://jobs.com/101",
                    posted_at=None,
                    raw_description="<p>Go and Kubernetes</p>",
                )
            ],
            parse_error_count=0,
            fetch_complete=True,
            total_raw_records=1,
        )
        mock_get_client.return_value = mock_client

        result = sync_company(self.company_config, db_conn=self.mock_conn, dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["swe_jobs_accepted"], 1)
        # Ensure zero cursor execution
        self.mock_cur.execute.assert_not_called()


class TestBroadSourceSync(unittest.TestCase):
    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value.__enter__.return_value = self.mock_cur

    @patch("ingestion.pipeline.get_ats_client")
    def test_broad_source_sync_does_not_tombstone_historical_jobs(self, mock_get_client):
        mock_client = MagicMock()
        swe_job1 = RawJobPosting(
            source_name="jobicy",
            source_job_id="101",
            company_name="Supabase",
            title="Senior Backend Engineer",
            raw_location="Remote",
            source_url="https://jobicy.com/101",
            posted_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            raw_description="Postgres, Python, Docker",
            raw_workplace_type="remote",
            raw_job_type="Full-Time",
        )
        swe_job2 = RawJobPosting(
            source_name="jobicy",
            source_job_id="102",
            company_name="Vercel",
            title="Software Engineer Intern",
            raw_location="USA",
            source_url="https://jobicy.com/102",
            posted_at=datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc),
            raw_description="React, TypeScript",
            raw_workplace_type="remote",
            raw_job_type="Internship",
        )
        non_swe_job = RawJobPosting(
            source_name="jobicy",
            source_job_id="103",
            company_name="DesignCo",
            title="Brand Designer",
            raw_location="Worldwide",
            source_url="https://jobicy.com/103",
            posted_at=datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc),
            raw_description="Figma design",
            raw_workplace_type="remote",
            raw_job_type="Full-Time",
        )
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[swe_job1, swe_job2, non_swe_job],
            parse_error_count=0,
            fetch_complete=True,
            total_raw_records=3,
        )
        mock_get_client.return_value = mock_client

        self.mock_cur.fetchone.side_effect = [
            (1,),        # sync_runs id
            (10,), (20,), (30,), (31,), (32,), None, (40,),  # job 1
            (11,), (21,), (33,), (34,), None, (41,),          # job 2
        ]
        self.mock_cur.fetchall.return_value = []

        result = sync_broad_source("jobicy", db_conn=self.mock_conn, count=50)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["jobs_fetched"], 3)
        self.assertEqual(result["swe_jobs_accepted"], 2)
        self.assertEqual(result["jobs_upserted"], 2)
        self.assertEqual(result["jobs_deactivated"], 0)
        self.assertIsNone(result["error_message"])

        # CRITICAL: Verify tombstoning UPDATE was NEVER executed
        all_sql = [c[0][0] for c in self.mock_cur.execute.call_args_list]
        tombstone_sql = [s for s in all_sql if "SET is_active = FALSE" in s]
        self.assertEqual(len(tombstone_sql), 0, "Broad source sync must never deactivate historical jobs")

    @patch("ingestion.pipeline.get_ats_client")
    def test_broad_source_dry_run_no_writes(self, mock_get_client):
        mock_client = MagicMock()
        swe_job = RawJobPosting(
            source_name="jobicy",
            source_job_id="101",
            company_name="Supabase",
            title="Senior Backend Engineer",
            raw_location="Remote",
            source_url="https://jobicy.com/101",
            posted_at=datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            raw_description="Postgres",
            raw_workplace_type="remote",
            raw_job_type="Full-Time",
        )
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[swe_job],
            parse_error_count=0,
            fetch_complete=True,
            total_raw_records=1,
        )
        mock_get_client.return_value = mock_client

        result = sync_broad_source("jobicy", db_conn=self.mock_conn, dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["jobs_fetched"], 1)
        self.assertEqual(result["swe_jobs_accepted"], 1)
        self.assertEqual(len(result["sample_jobs"]), 1)
        sample = result["sample_jobs"][0]
        self.assertEqual(sample["company"], "Supabase")
        self.assertEqual(sample["role_type"], "full_time")
        self.assertEqual(sample["workplace"], "remote")
        # Ensure zero cursor execution
        self.mock_cur.execute.assert_not_called()

    @patch("ingestion.pipeline.get_ats_client")
    def test_broad_source_sync_failure_records_error(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.fetch_jobs.side_effect = IngestionFetchError("Jobicy API down")
        mock_get_client.return_value = mock_client
        self.mock_cur.fetchone.return_value = (5,)

        result = sync_broad_source("jobicy", db_conn=self.mock_conn)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["jobs_upserted"], 0)
        self.assertEqual(result["jobs_deactivated"], 0)
        self.assertIn("Jobicy API down", result["error_message"])

    @patch("ingestion.pipeline.get_ats_client")
    def test_remotive_broad_source_dry_run(self, mock_get_client):
        mock_client = MagicMock()
        swe_job = RawJobPosting(
            source_name="remotive",
            source_job_id="2001",
            company_name="Doist",
            title="Senior Python Engineer",
            raw_location="USA, Canada",
            source_url="https://remotive.com/2001",
            posted_at=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
            raw_description="Python, PostgreSQL",
            raw_workplace_type="remote",
            raw_job_type="full_time",
        )
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[swe_job],
            parse_error_count=0,
            fetch_complete=True,
            total_raw_records=1,
        )
        mock_get_client.return_value = mock_client

        result = sync_broad_source("remotive", db_conn=self.mock_conn, dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["jobs_fetched"], 1)
        self.assertEqual(result["swe_jobs_accepted"], 1)
        self.assertIn("country_counts", result)
        self.mock_cur.execute.assert_not_called()

    @patch("ingestion.pipeline.get_ats_client")
    def test_arbeitnow_broad_source_dry_run_with_max_pages(self, mock_get_client):
        mock_client = MagicMock()
        swe_job = RawJobPosting(
            source_name="arbeitnow",
            source_job_id="arb-001",
            company_name="Delivery Hero",
            title="Analytics Engineer",
            raw_location="Berlin, Germany",
            source_url="https://arbeitnow.com/arb-001",
            posted_at=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
            raw_description="SQL, Python",
            raw_workplace_type="remote",
            raw_job_type="Full Time",
        )
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[swe_job],
            parse_error_count=0,
            fetch_complete=True,
            total_raw_records=1,
        )
        mock_get_client.return_value = mock_client

        result = sync_broad_source("arbeitnow", db_conn=self.mock_conn, dry_run=True, max_pages=2)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["jobs_fetched"], 1)
        self.assertEqual(result["swe_jobs_accepted"], 1)
        mock_client.fetch_jobs.assert_called_with(max_pages=2)
        self.mock_cur.execute.assert_not_called()


def is_local_db_available() -> bool:
    try:
        from api.database import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
        conn.close()
        return True
    except Exception:
        return False


class TestPipelineUpsertDatabaseIntegration(unittest.TestCase):
    """
    Real database integration tests for upsert_job_posting:
    Exercises real psycopg2 cursor execution against PostgreSQL,
    verifying no 'IndexError: tuple index out of range' occurs,
    and confirming that inserting a new job and updating an existing job
    correctly persists role_type, posted_at, is_active, and preserves created_at.
    All operations are rolled back in tearDown so no test data persists.
    """

    @classmethod
    def setUpClass(cls):
        if not is_local_db_available():
            raise unittest.SkipTest("Local PostgreSQL database is not accessible")

    def setUp(self):
        from api.database import get_db_connection
        self.conn = get_db_connection()
        self.cur = self.conn.cursor()

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_real_db_upsert_new_and_update_existing_lifecycle(self):
        # 1. Fetch valid company and location foreign keys
        # Create the foreign-key rows explicitly (rolled back in tearDown) so the test
        # does not depend on pre-existing data or on test order.
        self.cur.execute("INSERT INTO companies (name) VALUES ('Pipeline Upsert Fixture Co') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute(
            "INSERT INTO locations (location, country) VALUES ('Fixture City, ON', 'Canada') "
            "ON CONFLICT (location, country) DO UPDATE SET country = EXCLUDED.country RETURNING id;"
        )
        lid = self.cur.fetchone()[0]

        test_posted_at = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)

        # 2. INSERT NEW job posting through upsert_job_posting
        # Regression check: will raise IndexError if %s placeholder count mismatches params
        posting_id, is_new = upsert_job_posting(
            cur=self.cur,
            job_id="test:regression_job_1",
            company_id=cid,
            title="Senior Backend Engineer",
            location_id=lid,
            description="Initial test description",
            workplace_type="remote",
            source_name="test_integration",
            source_job_id="reg_101",
            source_url="https://example.com/reg_101",
            posted_at=test_posted_at,
            role_type="full_time",
        )

        self.assertTrue(is_new)
        self.assertIsInstance(posting_id, int)

        # Verify inserted row in database
        self.cur.execute(
            """
            SELECT title, workplace_type, role_type, source_name, source_job_id,
                   source_url, posted_at, is_active, created_at, updated_at
            FROM job_postings
            WHERE id = %s;
            """,
            (posting_id,),
        )
        row = self.cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Senior Backend Engineer")
        self.assertEqual(row[1], "remote")
        self.assertEqual(row[2], "full_time")
        self.assertEqual(row[3], "test_integration")
        self.assertEqual(row[4], "reg_101")
        self.assertEqual(row[5], "https://example.com/reg_101")
        self.assertEqual(row[6], test_posted_at)
        self.assertTrue(row[7])  # is_active is TRUE
        created_at_initial = row[8]
        updated_at_initial = row[9]
        self.assertIsNotNone(created_at_initial)

        # 3. UPDATE existing job posting through upsert_job_posting
        updated_posting_id, is_new_update = upsert_job_posting(
            cur=self.cur,
            job_id="test:regression_job_1",
            company_id=cid,
            title="Lead Backend Engineer",
            location_id=lid,
            description="Updated description",
            workplace_type="hybrid",
            source_name="test_integration",
            source_job_id="reg_101",
            source_url="https://example.com/reg_101_v2",
            posted_at=test_posted_at,
            role_type="full_time",
        )

        self.assertFalse(is_new_update)
        self.assertEqual(updated_posting_id, posting_id)

        # Verify updated row
        self.cur.execute(
            """
            SELECT title, workplace_type, role_type, is_active, created_at, updated_at
            FROM job_postings
            WHERE id = %s;
            """,
            (posting_id,),
        )
        updated_row = self.cur.fetchone()
        self.assertEqual(updated_row[0], "Lead Backend Engineer")
        self.assertEqual(updated_row[1], "hybrid")
        self.assertEqual(updated_row[2], "full_time")
        self.assertTrue(updated_row[3])  # is_active remains TRUE
        self.assertEqual(updated_row[4], created_at_initial, "created_at MUST remain unchanged on update")
        self.assertGreaterEqual(updated_row[5], updated_at_initial)

    def test_real_db_location_length_exceeds_255_chars(self):
        """
        Regression test: verifies that a location string longer than 255 characters
        (such as Datadog's multi-region Greenhouse listing) can be inserted and queried
        through get_or_create_location in PostgreSQL without StringDataRightTruncation error.
        """
        long_loc = (
            "Boston, Massachusetts, USA; Connecticut, USA, Remote; Delaware, USA, Remote; "
            "District of Columbia, USA, Remote; Maryland, USA, Remote; Massachusetts, USA, Remote; "
            "New Hampshire, USA, Remote; New Jersey, USA, Remote; New York, USA, Remote; "
            "Rhode Island, USA, Remote"
        )
        self.assertGreater(len(long_loc), 255)

        loc_id, is_new = get_or_create_location(self.cur, long_loc, "United States")
        self.assertTrue(is_new)
        self.assertIsInstance(loc_id, int)

        # Idempotent retrieval
        loc_id_2, is_new_2 = get_or_create_location(self.cur, long_loc, "United States")
        self.assertFalse(is_new_2)
        self.assertEqual(loc_id, loc_id_2)

        # Verify exact text in database
        self.cur.execute("SELECT location, country FROM locations WHERE id = %s;", (loc_id,))
        row = self.cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], long_loc)
        self.assertEqual(row[1], "United States")


if __name__ == "__main__":
    unittest.main()
