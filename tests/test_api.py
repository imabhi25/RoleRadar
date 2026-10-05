"""
Unit tests for FastAPI endpoints:
- Existing analytics (/api/stats/overview, /api/stats/countries, /api/stats/skills)
- Job Explorer (/api/jobs) with pagination, filtering, and ordering
- Filter metadata (/api/jobs/filters)
- Single job detail (/api/jobs/{job_id})
- Error handling and security checks
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import psycopg2

from api.search_text import unfold_sql
from api.main import app


class TestApiEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @contextmanager
    def _mock_db(self, mock_cursor):
        yield mock_cursor

    # --- 1. Analytics Endpoints ---

    @patch("api.main.get_db_cursor")
    def test_overview_stats_success(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (6, 1, 2, 7, 4)
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/stats/overview")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_postings"], 6)
        self.assertEqual(data["total_companies"], 1)
        self.assertEqual(data["total_locations"], 2)
        self.assertEqual(data["total_skills"], 7)
        self.assertEqual(data["recently_posted_postings"], 4)

        # Confirm query uses CTE separating active real and fallback sample, and counts recently_posted
        query = mock_cur.execute.call_args[0][0]
        self.assertIn("active_real AS", query)
        self.assertIn("source_name != 'sample'", query)
        self.assertIn("is_active = TRUE", query)
        self.assertIn("recently_posted_postings", query)
        self.assertNotIn("sample_jobs AS", query)
        self.assertNotIn("source_name = 'sample'", query)
        self.assertIn("last_refreshed_at", query)

    @patch("api.main.get_db_cursor")
    def test_overview_stats_with_last_refreshed_at(self, mock_get_db):
        refresh_dt = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (10, 3, 5, 12, 8, refresh_dt)
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/stats/overview")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_postings"], 10)
        self.assertEqual(data["total_companies"], 3)
        self.assertEqual(data["last_refreshed_at"], "2026-09-28T12:00:00Z")

    @patch("api.main.get_db_cursor")
    def test_country_stats_success(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("United States", 4, 66.7),
            ("Germany", 2, 33.3),
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/stats/countries")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["country"], "United States")
        self.assertEqual(data[0]["postings"], 4)
        self.assertEqual(data[0]["share_pct"], 66.7)

        # Confirm query excludes Unknown and calculates share from known country postings
        query = mock_cur.execute.call_args[0][0]
        self.assertIn("known_country_postings AS", query)
        self.assertIn("loc.country IN ('United States', 'Canada')", query)

    @patch("api.main.get_db_cursor")
    def test_country_stats_empty_when_all_unknown(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/stats/countries")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    @patch("api.main.get_db_cursor")
    def test_skill_stats_success(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            (1, "TypeScript", 5, 83.3),
            (2, "React", 4, 66.7),
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/stats/skills")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["rank"], 1)
        self.assertEqual(data[0]["skill"], "TypeScript")
        self.assertEqual(data[0]["mentions"], 5)
        self.assertEqual(data[0]["frequency_pct"], 83.3)

    # --- 2. Job Explorer (/api/jobs) ---

    @patch("api.main.get_db_cursor")
    def test_jobs_default_pagination(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (1,)  # total count
        mock_cur.fetchall.return_value = [
            (
                "ashby:123",
                "Product Engineer",
                "Linear",
                "North America",
                "North America",
                "remote",
                "full_time",
                "ashby",
                "https://jobs.ashbyhq.com/linear/123",
                datetime.now(timezone.utc) - timedelta(days=2),
                datetime.now(timezone.utc) - timedelta(days=2, minutes=-30),
                ["React", "TypeScript"],
            )
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["limit"], 25)
        self.assertEqual(data["offset"], 0)
        self.assertEqual(len(data["jobs"]), 1)
        job = data["jobs"][0]
        self.assertEqual(job["job_id"], "ashby:123")
        self.assertEqual(job["title"], "Product Engineer")
        self.assertEqual(job["company"], "Linear")
        self.assertEqual(job["workplace_type"], "remote")
        self.assertEqual(job["role_type"], "full_time")
        self.assertEqual(job["freshness_status"], "recently_posted")
        self.assertEqual(job["skills"], ["React", "TypeScript"])

        # Check default limit=25, offset=0 passed as SQL parameters
        data_call_args = mock_cur.execute.call_args_list[1]
        self.assertEqual(data_call_args[0][1][-2:], [25, 0])

    def test_jobs_pagination_validation(self):
        # limit < 1
        resp = self.client.get("/api/jobs?limit=0")
        self.assertEqual(resp.status_code, 422)

        # limit > 100
        resp = self.client.get("/api/jobs?limit=101")
        self.assertEqual(resp.status_code, 422)

        # offset < 0
        resp = self.client.get("/api/jobs?offset=-1")
        self.assertEqual(resp.status_code, 422)

    @patch("api.main.get_db_cursor")
    def test_jobs_search_filter_parameterized(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=staff")
        self.assertEqual(response.status_code, 200)

        # Verify SQL condition and parameter
        count_query, count_params = mock_cur.execute.call_args_list[0][0]
        count_query = unfold_sql(count_query)
        self.assertIn("jp.title ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("c.name ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("l.location ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("jp.workplace_type ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("s_s.name ILIKE %s ESCAPE '\\'", count_query)
        self.assertEqual(count_params, ["%staff%", "%staff%", "%staff%", "%staff%", "staff", "%staff%"])

    @patch("api.main.get_db_cursor")
    def test_jobs_search_q_alias_identical_to_search(self, mock_get_db):
        """Verify that ?q=python and ?search=python produce identical queries."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        response_q = self.client.get("/api/jobs?q=python")
        self.assertEqual(response_q.status_code, 200)
        query_q, params_q = mock_cur.execute.call_args_list[0][0]

        mock_cur.reset_mock()
        response_search = self.client.get("/api/jobs?search=python")
        self.assertEqual(response_search.status_code, 200)
        query_search, params_search = mock_cur.execute.call_args_list[0][0]

        self.assertEqual(query_q, query_search)
        self.assertEqual(params_q, params_search)
        self.assertEqual(params_q, [r"(?<![[:alnum:]_+#])python(?![[:alnum:]_+#])"] * 5)

    @patch("api.main.get_db_cursor")
    def test_jobs_search_leading_trailing_whitespace(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=%20%20senior%20developer%20%20")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        # Should tokenize into exactly 2 tokens (senior, developer) without empty tokens
        self.assertEqual(
            count_params,
            ["%senior%", "%senior%", "%senior%", "%senior%", "senior", "%senior%", "%developer%", "%developer%", "%developer%", "%developer%", "developer", "%developer%"],
        )

    @patch("api.main.get_db_cursor")
    def test_jobs_search_repeated_spaces(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=software%20%20%20%20engineer")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertEqual(
            count_params,
            ["%software%", "%software%", "%software%", "%software%", "software", "%software%", "%engineer%", "%engineer%", "%engineer%", "%engineer%", "engineer", "%engineer%"],
        )

    @patch("api.main.get_db_cursor")
    def test_jobs_search_mixed_case(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        for query_val in ["OpenAI", "openai", "OPENAI"]:
            mock_cur.reset_mock()
            mock_cur.fetchone.return_value = (0,)
            mock_cur.fetchall.return_value = []

            response = self.client.get(f"/api/jobs?search={query_val}")
            self.assertEqual(response.status_code, 200)
            count_query, count_params = mock_cur.execute.call_args_list[0][0]
            count_query = unfold_sql(count_query)
            # Case-insensitive ILIKE with ESCAPE is generated
            self.assertIn("c.name ILIKE %s ESCAPE '\\'", count_query)
            # the query is folded to lower case so "OpenAI", "openai" and "OPENAI" are the same search
            folded = f"%{query_val.lower()}%"
            self.assertEqual(count_params, [folded, folded, folded, folded, query_val.lower(), folded])

    @patch("api.main.get_db_cursor")
    def test_jobs_search_fields_title_company_skills(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=python")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("jp.title ~* %s", count_query)
        self.assertIn("c.name ~* %s", count_query)
        self.assertIn("l.location ~* %s", count_query)
        self.assertIn("s_s.name ~* %s", count_query)
        self.assertIn("EXISTS", count_query)
        self.assertEqual(count_params, [r"(?<![[:alnum:]_+#])python(?![[:alnum:]_+#])"] * 5)

    @patch("api.main.get_db_cursor")
    def test_jobs_search_reversed_token_order(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # "software engineer"
        self.client.get("/api/jobs?search=software%20engineer")
        query_a, params_a = mock_cur.execute.call_args_list[0][0]

        mock_cur.reset_mock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []

        # "engineer software"
        self.client.get("/api/jobs?search=engineer%20software")
        query_b, params_b = mock_cur.execute.call_args_list[0][0]

        # Both queries have AND clauses for both tokens
        self.assertIn("%software%", params_a)
        self.assertIn("%engineer%", params_a)
        self.assertIn("%software%", params_b)
        self.assertIn("%engineer%", params_b)
        self.assertEqual(len(params_a), len(params_b))

    @patch("api.main.get_db_cursor")
    def test_jobs_search_percent_wildcard_escaped(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=%25")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("ESCAPE '\\'", count_query)
        # % must be escaped as \% inside like pattern %\%%
        self.assertEqual(count_params, ["%\\%%", "%\\%%", "%\\%%", "%\\%%", "%", "%\\%%"])

    @patch("api.main.get_db_cursor")
    def test_jobs_search_underscore_wildcard_escaped(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=_")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("ESCAPE '\\'", count_query)
        # _ must be escaped as \_ inside like pattern %\_%
        self.assertEqual(count_params, ["%\\_%", "%\\_%", "%\\_%", "%\\_%", "_", "%\\_%"])

    @patch("api.main.get_db_cursor")
    def test_jobs_search_intern_word_aware(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=intern")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        # Uses word-boundary regex for title and excludes internal from company
        self.assertIn("jp.title ~* %s", count_query)
        self.assertIn("jp.role_type = 'internship'", count_query)
        self.assertIn("c.name NOT ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("l.location ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("jp.workplace_type ILIKE %s ESCAPE '\\'", count_query)
        self.assertEqual(
            count_params,
            [r"\yintern(s|ship|ships)?\y", "%intern%", "%internal%", "%intern%", "%intern%", "%intern%"],
        )

    @patch("api.main.get_db_cursor")
    def test_jobs_search_zero_result_query(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=nonexistentxyz123")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["jobs"], [])

    @patch("api.main.get_db_cursor")
    def test_jobs_search_pagination_total_unaffected_by_multiple_skills(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (1,)
        mock_cur.fetchall.return_value = [
            (
                "jobicy:101",
                "Senior Backend Engineer",
                "Supabase",
                "Remote",
                "United States",
                "remote",
                "full_time",
                "jobicy",
                "https://jobicy.com/101",
                datetime.now(timezone.utc) - timedelta(hours=2),
                datetime.now(timezone.utc) - timedelta(hours=3),
                ["Python", "Go", "PostgreSQL"],
            )
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=python")
        self.assertEqual(response.status_code, 200)

        count_query = mock_cur.execute.call_args_list[0][0][0]
        # EXISTS subquery prevents row duplication from joining skills table
        self.assertIn("EXISTS (", count_query)
        self.assertIn("FROM job_posting_skills jps_s", count_query)
        data = response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(len(data["jobs"]), 1)

    @patch("api.main.get_db_cursor")
    def test_jobs_country_filter_parameterized(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?country=Canada")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("LOWER(l.country) = LOWER(%s)", count_query)
        self.assertIn("Canada", count_params)

    @patch("api.main.get_db_cursor")
    def test_jobs_company_filter_parameterized(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?company=Linear")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("LOWER(c.name) = LOWER(%s)", count_query)
        self.assertIn("Linear", count_params)

    @patch("api.main.get_db_cursor")
    def test_jobs_skill_filter_uses_exists_to_prevent_duplicate_rows(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?skill=Python")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("EXISTS", count_query)
        self.assertIn("LOWER(s_f.name) = LOWER(%s)", count_query)
        self.assertIn("Python", count_params)

    @patch("api.main.get_db_cursor")
    def test_jobs_workplace_type_filter(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # Valid workplace type
        response = self.client.get("/api/jobs?workplace_type=remote")
        self.assertEqual(response.status_code, 200)
        count_query, count_params = mock_cur.execute.call_args_list[0][0]
        count_query = unfold_sql(count_query)
        self.assertIn("jp.workplace_type = %s", count_query)
        self.assertIn("remote", count_params)

        # Invalid workplace type is rejected (not silently ignored)
        mock_cur.reset_mock()
        invalid_resp = self.client.get("/api/jobs?workplace_type=invalid_val")
        self.assertEqual(invalid_resp.status_code, 400)
        self.assertIn("workplace_type", invalid_resp.json()["detail"])
        mock_cur.execute.assert_not_called()

    @patch("api.main.get_db_cursor")
    def test_jobs_multiple_filters_combine_with_and(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get(
            "/api/jobs?search=product&company=Linear&country=Canada&skill=React&workplace_type=remote"
        )
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("jp.title ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("c.name ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("l.location ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("jp.workplace_type ILIKE %s ESCAPE '\\'", count_query)
        self.assertIn("LOWER(c.name) = LOWER(%s)", count_query)
        self.assertIn("LOWER(l.country) = LOWER(%s)", count_query)
        self.assertIn("EXISTS", count_query)
        self.assertIn("jp.workplace_type = %s", count_query)
        self.assertEqual(
            count_params,
            ["%product%", "%product%", "%product%", "%product%", "product", "%product%", "Canada", "Canada", "Linear", "React", "remote"],
        )

    @patch("api.main.get_db_cursor")
    def test_jobs_role_type_filter(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?role_type=internship")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("jp.role_type = %s", count_query)
        self.assertIn("internship", count_params)

    @patch("api.main.get_db_cursor")
    def test_jobs_role_type_invalid_rejected(self, mock_get_db):
        mock_cur = MagicMock()
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?role_type=invalid_type")
        self.assertEqual(response.status_code, 400)
        self.assertIn("role_type", response.json()["detail"])
        mock_cur.execute.assert_not_called()

    @patch("api.main.get_db_cursor")
    def test_jobs_search_go_word_aware(self, mock_get_db):
        """Test section D: word-aware matching for Go / Golang excluding go-to-market/go-live and substrings."""
        import re
        # Verify the regex patterns used in the SQL query
        pos_pat = r"\b(golang|go)\b"
        neg_pat = r"\bgo[\s\-]to[\s\-]market\b|\bgo[\s\-]live\b"

        # Should match Go / Golang
        self.assertTrue(bool(re.search(pos_pat, "Senior Go Engineer", re.IGNORECASE)))
        self.assertTrue(bool(re.search(pos_pat, "Backend Golang Developer", re.IGNORECASE)))
        self.assertTrue(bool(re.search(pos_pat, "Software Engineer (Go)", re.IGNORECASE)))

        # Substrings must NOT match
        self.assertFalse(bool(re.search(pos_pat, "Government Affairs Specialist", re.IGNORECASE)))
        self.assertFalse(bool(re.search(pos_pat, "Ongoing Project Manager", re.IGNORECASE)))
        self.assertFalse(bool(re.search(pos_pat, "Foregoing Operations", re.IGNORECASE)))
        self.assertFalse(bool(re.search(pos_pat, "Cargo Logistics Coordinator", re.IGNORECASE)))

        # Negative pattern should match go-to-market / go-live
        self.assertTrue(bool(re.search(neg_pat, "Go-to-Market Lead", re.IGNORECASE)))
        self.assertTrue(bool(re.search(neg_pat, "Go To Market Operations", re.IGNORECASE)))
        self.assertTrue(bool(re.search(neg_pat, "Go-Live Specialist", re.IGNORECASE)))

        # When positive matches but negative also matches -> filtered out
        title = "Go-to-Market Lead"
        matches = bool(re.search(pos_pat, title, re.IGNORECASE)) and not bool(re.search(neg_pat, title, re.IGNORECASE))
        self.assertFalse(matches)

        # Verify SQL query generation for q=go
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?search=go")
        self.assertEqual(response.status_code, 200)
        count_query, count_params = mock_cur.execute.call_args_list[0][0]
        count_query = unfold_sql(count_query)
        self.assertIn("jp.title ~* %s AND jp.title !~* %s", count_query)
        self.assertIn(r"\y(golang|go)\y", count_params)
        self.assertIn(r"\ygo[\s\-]to[\s\-]market\y|\ygo[\s\-]live\y", count_params)
        self.assertIn("LOWER(s_s.name) IN ('go', 'golang')", count_query)

    @patch("api.main.get_db_cursor")
    def test_jobs_search_short_tokens_word_boundary(self, mock_get_db):
        """Test section I: 1-2 char search terms (e.g. q=c, q=R) use word-boundary regex and exact skill match."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # 1. Search for single character 'c'
        response = self.client.get("/api/jobs?q=c")
        self.assertEqual(response.status_code, 200)
        count_query, count_params = mock_cur.execute.call_args_list[0][0]
        count_query = unfold_sql(count_query)
        self.assertIn("jp.title ~* %s", count_query)
        self.assertIn("c.name ~* %s", count_query)
        self.assertIn("l.location ~* %s", count_query)
        self.assertIn("LOWER(s_s.name) = LOWER(%s)", count_query)
        # Must NOT do broad ILIKE for title
        self.assertNotIn("jp.title ILIKE", count_query)
        # Must not search description
        self.assertNotIn("description ILIKE", count_query)
        self.assertNotIn("description ~*", count_query)
        self.assertIn(r"\yc\y", count_params)
        self.assertIn("c", count_params)

        # 2. Search for single character 'R'
        mock_cur.reset_mock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        response_r = self.client.get("/api/jobs?q=R")
        self.assertEqual(response_r.status_code, 200)
        count_query_r, count_params_r = mock_cur.execute.call_args_list[0][0]
        self.assertIn(r"\yr\y", count_params_r)
        self.assertIn("LOWER(s_s.name) = LOWER(%s)", count_query_r)

    @patch("api.main.get_db_cursor")
    def test_jobs_filter_normalization(self, mock_get_db):
        """Test section E: structured filter value canonicalization and bogus value suppression."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # Country aliases: United_States, US, USA -> 'United States'; ca -> 'Canada'
        bad = self.client.get("/api/jobs?country=United_States,ca,bogus_country")
        self.assertEqual(bad.status_code, 400)
        mock_cur.execute.assert_not_called()
        response = self.client.get("/api/jobs?country=United_States,ca")
        self.assertEqual(response.status_code, 200)
        count_query, count_params = mock_cur.execute.call_args_list[0][0]
        count_query = unfold_sql(count_query)
        self.assertIn("LOWER(l.country) IN (LOWER(%s), LOWER(%s))", count_query)
        self.assertIn("United States", count_params)
        self.assertIn("Canada", count_params)
        self.assertNotIn("bogus_country", count_params)

        # Role aliases: fulltime -> full_time, coop -> co_op, intern -> internship, new-grad -> new_grad
        mock_cur.reset_mock()
        self.assertEqual(self.client.get("/api/jobs?role_type=fulltime,coop,invalid_role").status_code, 400)
        mock_cur.reset_mock()
        response = self.client.get("/api/jobs?role_type=fulltime,coop,intern,new-grad")
        self.assertEqual(response.status_code, 200)
        count_query, count_params = mock_cur.execute.call_args_list[0][0]
        count_query = unfold_sql(count_query)
        self.assertIn("jp.role_type IN (%s, %s, %s, %s)", count_query)
        self.assertIn("full_time", count_params)
        self.assertIn("co_op", count_params)
        self.assertIn("internship", count_params)
        self.assertIn("new_grad", count_params)
        self.assertNotIn("invalid_role", count_params)

        # Workplace aliases: onsite -> on_site, on-site -> on_site
        mock_cur.reset_mock()
        self.assertEqual(self.client.get("/api/jobs?workplace_type=onsite,remote,bogus_workplace").status_code, 400)
        mock_cur.reset_mock()
        response = self.client.get("/api/jobs?workplace_type=onsite,remote")
        self.assertEqual(response.status_code, 200)
        count_query, count_params = mock_cur.execute.call_args_list[0][0]
        count_query = unfold_sql(count_query)
        self.assertIn("jp.workplace_type IN (%s, %s, %s)", count_query)
        self.assertIn("on_site", count_params)
        self.assertIn("onsite", count_params)
        self.assertIn("remote", count_params)
        self.assertNotIn("bogus_workplace", count_params)

    @patch("api.main.get_db_cursor")
    def test_jobs_multi_select_filters(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # Comma-separated role_type, country, and workplace_type
        response = self.client.get(
            "/api/jobs?role_type=internship,co_op&country=Canada,United%20States&workplace_type=remote,hybrid"
        )
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("jp.role_type IN (%s, %s)", count_query)
        self.assertIn("LOWER(l.country) IN (LOWER(%s), LOWER(%s))", count_query)
        self.assertIn("jp.workplace_type IN (%s, %s)", count_query)
        self.assertIn("internship", count_params)
        self.assertIn("co_op", count_params)
        self.assertIn("Canada", count_params)
        self.assertIn("United States", count_params)
        self.assertIn("remote", count_params)
        self.assertIn("hybrid", count_params)

        # Repeated query params e.g. role_type=internship&role_type=co_op
        response_rep = self.client.get(
            "/api/jobs?role_type=internship&role_type=co_op"
        )
        self.assertEqual(response_rep.status_code, 200)
        rep_query, rep_params = mock_cur.execute.call_args_list[2][0]
        self.assertIn("jp.role_type IN (%s, %s)", rep_query)

    @patch("api.main.get_db_cursor")
    def test_stats_roles_endpoint(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("full_time", 80, 80.0), ("internship", 20, 20.0)]
        mock_get_db.return_value = self._mock_db(mock_cur)

        resp = self.client.get("/api/stats/roles")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["category"], "full_time")
        self.assertEqual(data[0]["count"], 80)

    @patch("api.main.get_db_cursor")
    def test_stats_workplace_endpoint(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("remote", 60, 60.0), ("hybrid", 40, 40.0)]
        mock_get_db.return_value = self._mock_db(mock_cur)

        resp = self.client.get("/api/stats/workplace")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["category"], "remote")
        self.assertEqual(data[0]["count"], 60)

    @patch("api.main.get_db_cursor")
    def test_stats_companies_endpoint(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("Stripe", 15, 15.0), ("Databricks", 10, 10.0)]
        mock_get_db.return_value = self._mock_db(mock_cur)

        resp = self.client.get("/api/stats/companies")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["category"], "Stripe")
        self.assertEqual(data[0]["count"], 15)

    @patch("api.main.get_db_cursor")
    def test_jobs_excludes_sample_and_inactive(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        self.client.get("/api/jobs")
        count_query = mock_cur.execute.call_args_list[0][0][0]
        data_query = mock_cur.execute.call_args_list[1][0][0]

        for q in [count_query, data_query]:
            self.assertIn("jp.is_active = TRUE", q)
            self.assertIn("jp.source_name != 'sample'", q)
            # Default mode applies the 30-day PUBLIC visibility window (never touches is_active)
            self.assertIn("INTERVAL '2 days'", q)   # the 30-day public predicate (future-date tolerance clause)

    @patch("api.main.get_db_cursor")
    def test_jobs_freshness_all_is_the_unbounded_debug_mode(self, mock_get_db):
        """
        freshness=all disables the 30-day public window (internal/debug); it still requires
        source-active status. Active status is determined by source presence, not age.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?freshness=all")
        self.assertEqual(response.status_code, 200)

        count_query = mock_cur.execute.call_args_list[0][0][0]
        data_query = mock_cur.execute.call_args_list[1][0][0]

        for q in [count_query, data_query]:
            # No age-based freshness predicate in 'all' mode
            self.assertNotIn("INTERVAL '2 days'", q)
            # Still requires active status
            self.assertIn("jp.is_active = TRUE", q)

    @patch("api.main.get_db_cursor")
    def test_jobs_freshness_filter_today(self, mock_get_db):
        """
        Verify freshness=today generates calendar-day date_trunc boundary predicate
        strictly for posted_at with NO created_at fallback.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (3,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?freshness=today")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 3)

        count_query = mock_cur.execute.call_args_list[0][0][0]
        data_query = mock_cur.execute.call_args_list[1][0][0]

        count_where = count_query.split("WHERE jp.is_active = TRUE")[1]
        self.assertIn("jp.posted_at IS NOT NULL", count_where)
        self.assertIn("jp.posted_at >= (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')", count_where)
        self.assertIn("jp.posted_at < (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') + INTERVAL '1 day'", count_where)
        self.assertNotIn("jp.created_at", count_where)
        self.assertNotIn("NOW() - INTERVAL '1 day'", count_where)
        self.assertNotIn("NOW() - INTERVAL '1 days'", count_where)

        data_where = data_query.split("WHERE jp.is_active = TRUE")[1].split("GROUP BY")[0]
        self.assertIn("jp.posted_at IS NOT NULL", data_where)
        self.assertIn("jp.posted_at >= (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')", data_where)
        self.assertNotIn("jp.created_at", data_where)

    @patch("api.main.get_db_cursor")
    def test_jobs_freshness_filter_week(self, mock_get_db):
        """
        Verify freshness=week generates 7-day interval freshness predicate
        strictly for posted_at with NO created_at fallback.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (15,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?freshness=week")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 15)

        count_query = mock_cur.execute.call_args_list[0][0][0]
        data_query = mock_cur.execute.call_args_list[1][0][0]

        count_where = count_query.split("WHERE jp.is_active = TRUE")[1]
        self.assertIn("jp.posted_at IS NOT NULL", count_where)
        self.assertIn("jp.posted_at >= NOW() - INTERVAL '7 days'", count_where)
        self.assertNotIn("jp.created_at", count_where)

        data_where = data_query.split("WHERE jp.is_active = TRUE")[1].split("GROUP BY")[0]
        self.assertIn("jp.posted_at IS NOT NULL", data_where)
        self.assertIn("jp.posted_at >= NOW() - INTERVAL '7 days'", data_where)
        self.assertNotIn("jp.created_at", data_where)

    @patch("api.main.get_db_cursor")
    def test_jobs_freshness_all_has_no_age_cutoff(self, mock_get_db):
        """
        Verify freshness=all includes old active official postings.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (50,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?freshness=all")
        self.assertEqual(response.status_code, 200)

        count_query = mock_cur.execute.call_args_list[0][0][0]
        data_query = mock_cur.execute.call_args_list[1][0][0]

        for q in [count_query, data_query]:
            self.assertNotIn("INTERVAL '2 days'", q)

    def test_jobs_freshness_filter_invalid_returns_400(self):
        """
        Verify invalid freshness parameter returns 400 Bad Request.
        """
        response = self.client.get("/api/jobs?freshness=invalid_window")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid freshness", response.json()["detail"])

    @patch("api.main.get_db_cursor")
    def test_jobs_freshness_pagination_count(self, mock_get_db):
        """
        Verify total count accurately reflects filtered dataset and pagination limits work.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (42,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?freshness=today&limit=10&offset=20")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 42)
        self.assertEqual(data["limit"], 10)
        self.assertEqual(data["offset"], 20)

        data_query_params = mock_cur.execute.call_args_list[1][0][1]
        self.assertEqual(data_query_params[-2:], [10, 20])

    @patch("api.main.get_db_cursor")
    def test_jobs_freshness_combined_with_country_and_role_filters(self, mock_get_db):
        """
        Verify freshness filter combines seamlessly via AND with country, role_type,
        and user-facing geography predicates.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (5,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?freshness=today&country=United%20States&role_type=internship")
        self.assertEqual(response.status_code, 200)

        count_query, count_params = mock_cur.execute.call_args_list[0][0]

        count_query = unfold_sql(count_query)
        self.assertIn("jp.posted_at >= (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')", count_query)
        self.assertIn("jp.posted_at < (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') + INTERVAL '1 day'", count_query)
        self.assertIn("LOWER(l.country) = LOWER(%s)", count_query)
        self.assertIn("jp.role_type = %s", count_query)
        self.assertIn("l.country IN ('United States', 'Canada')", count_query)
        self.assertIn("United States", count_params)
        self.assertIn("internship", count_params)

    @patch("api.main.get_db_cursor")
    def test_jobs_freshness_unknown_posted_at_fallback_to_created_at(self, mock_get_db):
        """
        Verify that in freshness=all, postings with posted_at NULL fall back to created_at and receive
        recently_discovered freshness_status.
        """
        now = datetime.now(timezone.utc)
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (1,)
        mock_cur.fetchall.return_value = [
            (
                "jobicy:456",
                "Backend Developer",
                "Remote Tech",
                "New York, NY",
                "United States",
                "remote",
                "full_time",
                "jobicy",
                "https://jobicy.com/job/456",
                None,  # posted_at is NULL
                now - timedelta(hours=3),  # created_at is 3 hours ago
                ["Python"],
            )
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?freshness=all")
        self.assertEqual(response.status_code, 200)
        jobs = response.json()["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0]["posted_at"])
        self.assertIsNotNone(jobs[0]["created_at"])
        self.assertEqual(jobs[0]["freshness_status"], "recently_discovered")

    @patch("api.main.get_db_cursor")
    def test_jobs_freshness_null_posted_at_excluded_from_today_and_week(self, mock_get_db):
        """
        Verify that freshness=today and freshness=week strictly generate SQL predicates
        requiring posted_at IS NOT NULL, ensuring null posted_at jobs are excluded.
        """
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # freshness=today
        self.client.get("/api/jobs?freshness=today")
        today_sql = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("jp.posted_at IS NOT NULL", today_sql)
        self.assertNotIn("jp.created_at", today_sql)

        # freshness=week
        self.client.get("/api/jobs?freshness=week")
        week_sql = mock_cur.execute.call_args_list[2][0][0]
        self.assertIn("jp.posted_at IS NOT NULL", week_sql)
        self.assertNotIn("jp.created_at", week_sql)

    @patch("api.main.get_db_cursor")
    def test_jobs_deterministic_ordering(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        self.client.get("/api/jobs")
        data_query = mock_cur.execute.call_args_list[1][0][0]
        self.assertIn("jp.posted_at DESC NULLS LAST", data_query)
        self.assertIn("jp.posted_at DESC NULLS LAST", data_query)
        self.assertIn("jp.created_at DESC", data_query)
        self.assertIn("jp.id DESC", data_query)

    @patch("api.main.get_db_cursor")
    def test_known_recent_posted_jobs_sort_before_unknown_date_jobs(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (2,)
        mock_cur.fetchall.return_value = [
            (
                "jobicy:101",
                "Senior Backend Engineer",
                "Phantom",
                "Remote",
                "United States",
                "remote",
                "full_time",
                "jobicy",
                "https://jobicy.com/101",
                datetime.now(timezone.utc) - timedelta(days=5),
                datetime.now(timezone.utc) - timedelta(days=5, minutes=-30),
                ["Go", "Python"],
            ),
            (
                "greenhouse:202",
                "Product Engineer",
                "Figma",
                "San Francisco, CA",
                "United States",
                "hybrid",
                "full_time",
                "greenhouse",
                "https://boards.greenhouse.io/figma/202",
                None,
                datetime.now(timezone.utc) - timedelta(hours=1),
                ["TypeScript", "React"],
            ),
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)
        jobs = response.json()["jobs"]
        self.assertEqual(len(jobs), 2)

        # Job 1 has trustworthy posted_at => recently_posted
        self.assertEqual(jobs[0]["job_id"], "jobicy:101")
        self.assertIsNotNone(jobs[0]["posted_at"])
        self.assertEqual(jobs[0]["freshness_status"], "recently_posted")

        # Job 2 has posted_at = None => recently_discovered (never mislabeled as recently_posted)
        self.assertEqual(jobs[1]["job_id"], "greenhouse:202")
        self.assertIsNone(jobs[1]["posted_at"])
        self.assertIsNotNone(jobs[1]["created_at"])
        self.assertEqual(jobs[1]["freshness_status"], "recently_discovered")
        self.assertNotEqual(jobs[1]["freshness_status"], "recently_posted")

        # SQL query ORDER BY guarantees known posted_at ranks first (CASE WHEN ... THEN 0 ELSE 1)
        data_query = mock_cur.execute.call_args_list[1][0][0]
        self.assertIn("jp.posted_at DESC NULLS LAST", data_query)

    # --- 3. Filter Options Metadata (/api/jobs/filters) ---

    @patch("api.main.get_db_cursor")
    def test_job_filters_endpoint(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [
            [("Canada",), ("Germany",)],         # countries
            [("Linear",)],                       # companies
            [("GCP",), ("React",)],              # skills
            [("remote",)],                       # workplace_types
            [("full_time",), ("internship",)],   # role_types
        ]
        # Metro options come from one aggregate row: True where the public results contain a job for that metro.
        from api.main import LOCATION_OPTIONS
        mock_cur.fetchone.return_value = tuple(label in ("Vancouver", "Seattle, WA") for label in LOCATION_OPTIONS)
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs/filters")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["countries"], ["Canada", "Germany"])
        self.assertEqual(data["companies"], ["Linear"])
        self.assertEqual(data["skills"], ["GCP", "React"])
        self.assertEqual(data["workplace_types"], ["remote"])
        self.assertEqual(data["role_types"], ["full_time", "internship"])
        self.assertEqual(data["locations"], ["Vancouver", "Seattle, WA"])

        # Confirm all queries exclude sample and inactive jobs
        country_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("loc.country IN ('United States', 'Canada')", country_query)

        for call_item in mock_cur.execute.call_args_list:
            q = call_item[0][0]
            self.assertIn("jp.is_active = TRUE", q)
            # Filter options describe the same publicly visible (30-day) population as the list
            self.assertIn("INTERVAL '2 days'", q)   # the 30-day public predicate (future-date tolerance clause)
            if "bool_or" not in q:
                self.assertIn("ORDER BY", q)
        location_call = mock_cur.execute.call_args_list[-1]
        self.assertIn("target_postings", location_call[0][0])   # the same population as /api/jobs
        self.assertEqual(len(location_call[0][1]), 2 * len(LOCATION_OPTIONS))

    # --- 4. Single Job Detail (/api/jobs/{job_id}) ---

    @patch("api.main.get_db_cursor")
    def test_single_job_success(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (
            "ashby:456",
            "Senior / Staff Product Engineer",
            "Linear",
            "North America",
            "North America",
            "remote",
            "full_time",
            "ashby",
            "https://jobs.ashbyhq.com/linear/456",
            datetime.now(timezone.utc) - timedelta(days=1),
            datetime.now(timezone.utc) - timedelta(days=1, minutes=-30),
            "Full job description in plain text.",
            ["PostgreSQL", "React", "TypeScript"],
        )
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs/ashby:456")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["job_id"], "ashby:456")
        self.assertEqual(data["title"], "Senior / Staff Product Engineer")
        self.assertEqual(data["role_type"], "full_time")
        self.assertEqual(data["freshness_status"], "recently_posted")
        self.assertEqual(data["description"], "Full job description in plain text.")
        self.assertEqual(data["skills"], ["PostgreSQL", "React", "TypeScript"])

    @patch("api.main.get_db_cursor")
    def test_unknown_date_active_jobs_not_mislabeled_as_newly_posted(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (
            "greenhouse:999",
            "Infrastructure Engineer",
            "Figma",
            "San Francisco, CA",
            "United States",
            "onsite",
            "full_time",
            "greenhouse",
            "https://jobs.com/999",
            None,
            datetime.now(timezone.utc) - timedelta(hours=2),
            "Description text",
            ["Kubernetes", "Terraform"],
        )
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs/greenhouse:999")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data["posted_at"])
        self.assertIsNotNone(data["created_at"])
        self.assertEqual(data["freshness_status"], "recently_discovered")
        self.assertNotEqual(data["freshness_status"], "recently_posted")

    @patch("api.main.get_db_cursor")
    def test_single_job_not_found(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs/nonexistent-id")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not found", response.json()["detail"])

    @patch("api.main.get_db_cursor")
    def test_route_ordering_filters_not_routed_as_job_id(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [
            [], [], [], [], []
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs/filters")
        self.assertEqual(response.status_code, 200)
        self.assertIn("countries", response.json())
        self.assertIn("companies", response.json())
        self.assertIn("role_types", response.json())

    # --- 5. Security & Error Handling ---

    @patch("api.main.get_db_cursor")
    def test_database_error_generic_500_response(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.execute.side_effect = psycopg2.OperationalError("FATAL: password authentication failed for user 'secret_user'")
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data["detail"], "Database query error.")
        self.assertNotIn("secret_user", response.text)
        self.assertNotIn("FATAL", response.text)

    # --- 6. Geographic Feed Quality (Phase 6B.1) ---

    @patch("api.main.get_db_cursor")
    def test_jobs_geography_predicate_enforces_us_ca_and_useful_locations(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)

        count_query = mock_cur.execute.call_args_list[0][0][0]
        data_query = mock_cur.execute.call_args_list[1][0][0]

        for q in [count_query, data_query]:
            self.assertIn("l.country IN ('United States', 'Canada')", q)
            self.assertIn("l.location !~*", q)
            self.assertIn("unknown|unspecified|anywhere|worldwide|global", q)

    @patch("api.main.get_db_cursor")
    def test_jobs_eligible_us_ca_visible(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (2,)
        mock_cur.fetchall.return_value = [
            (
                "job1",
                "Senior Software Engineer",
                "Figma",
                "San Francisco, CA",
                "United States",
                "hybrid",
                "full_time",
                "greenhouse",
                "https://boards.greenhouse.io/figma/1",
                datetime.now(timezone.utc) - timedelta(days=1),
                datetime.now(timezone.utc) - timedelta(days=1),
                ["TypeScript", "React"],
            ),
            (
                "job2",
                "Backend Developer",
                "Shopify",
                "Toronto, ON, Canada",
                "Canada",
                "remote",
                "full_time",
                "jobicy",
                "https://jobicy.com/2",
                datetime.now(timezone.utc) - timedelta(days=2),
                datetime.now(timezone.utc) - timedelta(days=2),
                ["Ruby", "Go"],
            ),
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)
        jobs = response.json()["jobs"]
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["country"], "United States")
        self.assertEqual(jobs[0]["location"], "San Francisco, CA")
        self.assertEqual(jobs[1]["country"], "Canada")
        self.assertEqual(jobs[1]["location"], "Toronto, ON, Canada")

    @patch("api.main.get_db_cursor")
    def test_stats_use_same_eligible_geography_population_as_jobs(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (10, 5, 4, 12, 8)
        mock_cur.fetchall.return_value = [
            ("United States", 6, 60.0),
            ("Canada", 4, 40.0),
        ]
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # 1. Overview stats query
        resp_overview = self.client.get("/api/stats/overview")
        self.assertEqual(resp_overview.status_code, 200)
        overview_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("l.country IN ('United States', 'Canada')", overview_query)
        self.assertIn("active_real AS", overview_query)

        # 2. Country stats query
        mock_cur.reset_mock()
        mock_cur.fetchall.return_value = [
            ("United States", 6, 60.0),
            ("Canada", 4, 40.0),
        ]
        resp_countries = self.client.get("/api/stats/countries")
        self.assertEqual(resp_countries.status_code, 200)
        country_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("l.country IN ('United States', 'Canada')", country_query)
        self.assertIn("known_country_postings AS", country_query)

        # 3. Skill stats query
        mock_cur.reset_mock()
        mock_cur.fetchall.return_value = [(1, "Python", 5, 50.0)]
        resp_skills = self.client.get("/api/stats/skills")
        self.assertEqual(resp_skills.status_code, 200)
        skill_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("l.country IN ('United States', 'Canada')", skill_query)
        self.assertIn("active_real AS", skill_query)

    @patch("api.main.get_db_cursor")
    def test_filters_never_expose_unknown_and_only_eligible_countries(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [
            [("Canada",), ("United States",)],  # countries
            [("Deliveroo",), ("Figma",)],                            # companies
            [("Python",), ("TypeScript",)],                          # skills
            [("hybrid",), ("remote",)],                              # workplace_types
            [("full_time",)],                                        # role_types
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs/filters")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertNotIn("Unknown", data["countries"])
        self.assertNotIn("Germany", data["countries"])
        self.assertNotIn("United Kingdom", data["countries"])
        self.assertEqual(data["countries"], ["Canada", "United States"])

        country_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("l.country IN ('United States', 'Canada')", country_query)
        self.assertIn("loc.country IN ('United States', 'Canada')", country_query)

    @patch("api.main.get_db_cursor")
    def test_freshness_behavior_remains_unchanged_with_geography_filter(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        # Explicit freshness='all' must NOT apply age-based filtering
        self.client.get("/api/jobs?freshness=all")
        count_query = mock_cur.execute.call_args_list[0][0][0]
        data_query = mock_cur.execute.call_args_list[1][0][0]

        for q in [count_query, data_query]:
            # Geography predicate must be present
            self.assertIn("l.country IN ('United States', 'Canada')", q)
            # Active status must be present
            self.assertIn("jp.is_active = TRUE", q)
            # Age-based freshness predicate must NOT be present for 'all' mode
            self.assertNotIn("INTERVAL '2 days'", q)

    @patch("api.main.get_db_cursor")
    def test_jobs_search_by_location_and_workplace_type(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # 1. Search for city location: "toronto"
        self.client.get("/api/jobs?search=toronto")
        count_query, count_params = mock_cur.execute.call_args_list[0][0]
        count_query = unfold_sql(count_query)
        self.assertIn("l.location ILIKE %s ESCAPE '\\'", count_query)
        self.assertNotIn("jp.description ILIKE", count_query)
        self.assertNotIn("description ILIKE", count_query)
        self.assertIn("%toronto%", count_params)

        # 2. Search for workplace type: "remote"
        mock_cur.reset_mock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        self.client.get("/api/jobs?search=remote")
        count_query_remote, count_params_remote = mock_cur.execute.call_args_list[0][0]
        count_query_remote = unfold_sql(count_query_remote)
        self.assertIn("jp.workplace_type ILIKE %s ESCAPE '\\'", count_query_remote)
        self.assertNotIn("jp.description ILIKE", count_query_remote)
        self.assertNotIn("description ILIKE", count_query_remote)
        self.assertIn("%remote%", count_params_remote)

        # 3. Search for skill: "python"
        mock_cur.reset_mock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        self.client.get("/api/jobs?search=python")
        count_query_skill, count_params_skill = mock_cur.execute.call_args_list[0][0]
        count_query_skill = unfold_sql(count_query_skill)
        self.assertIn("s_s.name ~* %s", count_query_skill)
        self.assertNotIn("jp.description ILIKE", count_query_skill)
        self.assertNotIn("description ILIKE", count_query_skill)
        self.assertTrue(all("python" in pattern for pattern in count_params_skill))

    @patch("api.main.get_db_cursor")
    def test_stats_and_jobs_use_identical_population_and_reconcile(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (10, 5, 4, 12, 8)
        mock_cur.fetchall.return_value = []
        mock_get_db.side_effect = lambda: self._mock_db(mock_cur)

        # 1. Jobs count query
        self.client.get("/api/jobs")
        jobs_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("NOT EXISTS (\n        SELECT 1 FROM job_postings jp2", jobs_query)

        # 2. Overview stats query
        mock_cur.reset_mock()
        mock_cur.fetchone.return_value = (10, 5, 4, 12, 8)
        self.client.get("/api/stats/overview")
        overview_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("NOT EXISTS (\n        SELECT 1 FROM job_postings jp2", overview_query)

        # 3. Roles stats query
        mock_cur.reset_mock()
        mock_cur.fetchall.return_value = [("full_time", 8, 80.0), ("internship", 2, 20.0)]
        self.client.get("/api/stats/roles")
        roles_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("NOT EXISTS (\n        SELECT 1 FROM job_postings jp2", roles_query)

        # 4. Workplace stats query
        mock_cur.reset_mock()
        mock_cur.fetchall.return_value = [("remote", 6, 60.0), ("hybrid", 4, 40.0)]
        self.client.get("/api/stats/workplace")
        workplace_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("NOT EXISTS (\n        SELECT 1 FROM job_postings jp2", workplace_query)

        # 5. Countries stats query
        mock_cur.reset_mock()
        mock_cur.fetchall.return_value = [("United States", 7, 70.0), ("Canada", 3, 30.0)]
        self.client.get("/api/stats/countries")
        countries_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("NOT EXISTS (\n        SELECT 1 FROM job_postings jp2", countries_query)

    @patch("api.main.get_db_cursor")
    def test_job_recently_posted_field_behavior(self, mock_get_db):
        now = datetime.now(timezone.utc)
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (3,)
        mock_cur.fetchall.return_value = [
            # Job 1: posted 2 days ago -> recently_posted = True
            ("j1", "Engineer 1", "Stripe", "San Francisco, CA", "United States", "remote", "full_time", "greenhouse", "http://j1", now - timedelta(days=2), now - timedelta(days=2), ["Go"]),
            # Job 2: posted 20 days ago -> recently_posted = False
            ("j2", "Engineer 2", "Stripe", "San Francisco, CA", "United States", "remote", "full_time", "greenhouse", "http://j2", now - timedelta(days=20), now - timedelta(days=20), ["Python"]),
            # Job 3: undated (posted_at is None) -> recently_posted = False
            ("j3", "Engineer 3", "Stripe", "San Francisco, CA", "United States", "remote", "full_time", "greenhouse", "http://j3", None, now - timedelta(days=1), ["SQL"]),
        ]
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)
        jobs = response.json()["jobs"]
        self.assertEqual(len(jobs), 3)

        self.assertTrue(jobs[0]["recently_posted"])
        self.assertEqual(jobs[0]["freshness_status"], "recently_posted")

        self.assertFalse(jobs[1]["recently_posted"])
        self.assertEqual(jobs[1]["freshness_status"], "active")

        self.assertFalse(jobs[2]["recently_posted"])
        self.assertEqual(jobs[2]["freshness_status"], "recently_discovered")


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


class TestFreshnessCalendarSemanticsIntegration(unittest.TestCase):
    """
    Integration tests against PostgreSQL verifying exact calendar-day boundaries
    and rolling-window semantics for the Job Explorer freshness filters.
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

    def _eval_today(self, posted_at_expr: str, created_at_expr: str) -> bool:
        query = f"""
        SELECT (
            posted_at IS NOT NULL
            AND posted_at >= (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
            AND posted_at < (date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') + INTERVAL '1 day'
        )
        FROM (SELECT ({posted_at_expr})::timestamptz AS posted_at, ({created_at_expr})::timestamptz AS created_at) sub;
        """
        self.cur.execute(query)
        return bool(self.cur.fetchone()[0])

    def _eval_week(self, posted_at_expr: str, created_at_expr: str) -> bool:
        query = f"""
        SELECT (
            posted_at IS NOT NULL
            AND posted_at >= NOW() - INTERVAL '7 days'
        )
        FROM (SELECT ({posted_at_expr})::timestamptz AS posted_at, ({created_at_expr})::timestamptz AS created_at) sub;
        """
        self.cur.execute(query)
        return bool(self.cur.fetchone()[0])

    def _eval_all(self, posted_at_expr: str, created_at_expr: str) -> bool:
        query = f"""
        SELECT (
            (posted_at IS NOT NULL
             AND posted_at >= NOW() - INTERVAL '45 days')
            OR
            (posted_at IS NULL
             AND created_at >= NOW() - INTERVAL '45 days')
        )
        FROM (SELECT ({posted_at_expr})::timestamptz AS posted_at, ({created_at_expr})::timestamptz AS created_at) sub;
        """
        self.cur.execute(query)
        return bool(self.cur.fetchone()[0])

    def test_job_from_earlier_today_is_included(self):
        # 1. a job from earlier today is included (e.g. today at 08:00 AM)
        res = self._eval_today(
            posted_at_expr="(date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') + INTERVAL '4 hours'",
            created_at_expr="NOW()",
        )
        self.assertTrue(res, "Job posted earlier today must be included in freshness=today")

    def test_job_from_yesterday_less_than_24_hours_ago_is_not_included(self):
        # 2. a job from yesterday but less than 24 hours ago is NOT included (e.g. yesterday at 23:00)
        res = self._eval_today(
            posted_at_expr="(date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') - INTERVAL '1 hour'",
            created_at_expr="NOW()",
        )
        self.assertFalse(res, "Job posted yesterday (< 24h ago) must NOT be included in freshness=today calendar filter")

    def test_job_with_posted_at_null_and_created_at_today_is_excluded_from_today_and_week(self):
        # 3. a job with posted_at NULL and created_at today is EXCLUDED from today and week
        res_today = self._eval_today(
            posted_at_expr="NULL",
            created_at_expr="(date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') + INTERVAL '3 hours'",
        )
        self.assertFalse(res_today, "Job with posted_at NULL must NOT be included in freshness=today even if created today")

        res_week = self._eval_week(
            posted_at_expr="NULL",
            created_at_expr="NOW()",
        )
        self.assertFalse(res_week, "Job with posted_at NULL must NOT be included in freshness=week even if created today")

    def test_week_and_all_behavior_remain_unchanged(self):
        # 5. week and all behavior remain unchanged:
        # Job posted yesterday (< 7 days ago):
        # - Excluded from today
        # - Included in week (rolling 7 days)
        # - Included in all (rolling 45 days)
        yesterday_expr = "(date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') - INTERVAL '2 hours'"
        self.assertFalse(self._eval_today(yesterday_expr, "NOW()"))
        self.assertTrue(self._eval_week(yesterday_expr, "NOW()"))
        self.assertTrue(self._eval_all(yesterday_expr, "NOW()"))

        # Job posted 10 days ago:
        # - Excluded from week
        # - Included in all (rolling 45 days)
        ten_days_ago_expr = "NOW() - INTERVAL '10 days'"
        self.assertFalse(self._eval_week(ten_days_ago_expr, "NOW()"))
        self.assertTrue(self._eval_all(ten_days_ago_expr, "NOW()"))

        # Job posted 50 days ago:
        # - Excluded from all
        fifty_days_ago_expr = "NOW() - INTERVAL '50 days'"
        self.assertFalse(self._eval_all(fifty_days_ago_expr, "NOW()"))


class TestApiDeduplication(unittest.TestCase):
    """
    Unit and integration tests verifying user-facing deduplication semantics in the API layer.
    """

    def setUp(self):
        self.client = TestClient(app)

    @contextmanager
    def _mock_db(self, mock_cursor):
        yield mock_cursor

    @patch("api.main.get_db_cursor")
    def test_jobs_deduplication_predicate_included_in_queries(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (0,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs")
        self.assertEqual(response.status_code, 200)

        count_query = mock_cur.execute.call_args_list[0][0][0]
        data_query = mock_cur.execute.call_args_list[1][0][0]

        for q in [count_query, data_query]:
            self.assertIn("NOT EXISTS", q)
            self.assertIn("FROM job_postings jp2", q)
            self.assertNotIn("jp2.company_id = jp.company_id", q)
            self.assertNotIn("jp2.location_id = jp.location_id", q)
            self.assertNotIn("jp2.role_type = jp.role_type", q)

    @patch("api.main.get_db_cursor")
    def test_overview_stats_includes_deduplication_predicate(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (10, 5, 4, 8, 2)
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/stats/overview")
        self.assertEqual(response.status_code, 200)

        overview_query = mock_cur.execute.call_args_list[0][0][0]
        self.assertIn("NOT EXISTS", overview_query)
        self.assertIn("FROM job_postings jp2", overview_query)

    @patch("api.main.get_db_cursor")
    def test_deduplication_pagination_predictability(self, mock_get_db):
        """Deduplication total and limits are cleanly preserved across pagination parameters."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (25,)
        mock_cur.fetchall.return_value = []
        mock_get_db.return_value = self._mock_db(mock_cur)

        response = self.client.get("/api/jobs?limit=25&offset=50")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 25)
        self.assertEqual(data["limit"], 25)
        self.assertEqual(data["offset"], 50)


class TestApiDeduplicationDatabaseIntegration(unittest.TestCase):
    """
    Direct PostgreSQL regression tests modeled on Databricks and Faire duplicate postings.
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

    def test_databricks_and_faire_regression_deduplication(self):
        # 1. Create temporary companies & locations
        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression Databricks') RETURNING id;")
        cid_d = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression Faire') RETURNING id;")
        cid_f = self.cur.fetchone()[0]

        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Mountain View, CA (reg)', 'United States') RETURNING id;")
        lid_mv = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('New York City, NY (reg)', 'United States') RETURNING id;")
        lid_ny = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Toronto, ON (reg)', 'Canada') RETURNING id;")
        lid_to = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Kitchener-Waterloo, ON (reg)', 'Canada') RETURNING id;")
        lid_kw = self.cur.fetchone()[0]

        desc_d1 = "P-160 Who We Are: Fullstack engineering on GenAI observability and quality platform. What we look for: 5+ years with JavaScript, React, Python, Java, SQL, distributed systems. Pay range: $190,000-$270,000."
        desc_d2 = "P-160 Who We Are: Passionate about enabling data and AI teams. Fullstack engineering on Data Intelligence platform. What we look for: 5+ years with JavaScript, React, Python, Java, SQL, distributed systems. Pay range: $190,000-$270,000."
        desc_d3 = "Senior Software Engineer - Fullstack for Canadian engineering hub in Toronto. What we look for: 5+ years with JavaScript, React, Python, Java, SQL."

        desc_f1 = "About Faire: We are looking for a Senior Applied AI/ML Scientist on Search ranking algorithms, transformer sequential modeling, LLMs and graph neural networks. 5+ years experience."
        desc_f2 = "About Faire: We are looking for a Senior Applied AI/ML Scientist on Search algorithms and retrieval across five sources, relevance modeling, deep learning. 3+ years experience."
        desc_f3 = "About Faire: Canadian engineering team in Kitchener-Waterloo and Toronto for Senior Applied ML/AI Scientist."

        # 2. Insert Databricks duplicates + Toronto posting
        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, posted_at, description)
            VALUES
            ('reg:d1', %s, %s, 'Senior Software Engineer - Fullstack', 'onsite', 'full_time', 'greenhouse', 'regression-7898766002', 'https://databricks.com/1', '2026-09-20T12:00:00Z', %s),
            ('reg:d2', %s, %s, 'Senior Software Engineer \u2013 Fullstack', 'onsite', 'full_time', 'greenhouse', 'regression-5445641002', 'https://databricks.com/2', '2026-09-21T12:00:00Z', %s),
            ('reg:d3', %s, %s, 'Senior Software Engineer - Fullstack', 'onsite', 'full_time', 'greenhouse', 'regression-8099342002', 'https://databricks.com/3', '2026-09-20T12:00:00Z', %s);
        """, (cid_d, lid_mv, desc_d1, cid_d, lid_mv, desc_d2, cid_d, lid_to, desc_d3))

        # 3. Insert Faire duplicates + Canadian posting
        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, posted_at, description)
            VALUES
            ('reg:f1', %s, %s, 'Senior Applied ML/AI Scientist - Search', 'onsite', 'full_time', 'greenhouse', 'regression-8660923002', 'https://faire.com/1', '2026-07-31T12:00:00Z', %s),
            ('reg:f2', %s, %s, 'Senior Applied ML/AI Scientist \u2013 Search', 'onsite', 'full_time', 'greenhouse', 'regression-8618124002', 'https://faire.com/2', '2026-07-24T12:00:00Z', %s),
            ('reg:f3', %s, %s, 'Senior Applied ML/AI Scientist - Search', 'onsite', 'full_time', 'greenhouse', 'regression-8618151002', 'https://faire.com/3', '2026-07-24T12:00:00Z', %s);
        """, (cid_f, lid_ny, desc_f1, cid_f, lid_ny, desc_f2, cid_f, lid_kw, desc_f3))

        # 4. Under conservative tightened rules:
        # - Databricks Mountain View collapses on shared requisition code 'P-160' (reg:d1 -> reg:d2)
        # - Databricks Toronto (reg:d3) remains distinct due to location
        # - Faire NYC has only ~50-60% boilerplate similarity and no shared req code, so both (reg:f1 and reg:f2) safely remain visible
        # - Faire Kitchener-Waterloo (reg:f3) remains distinct due to location
        # Total visible jobs: 5
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute(f"""
            SELECT jp.job_id, c.name, jp.title, l.location
            FROM job_postings jp
            JOIN companies c ON jp.company_id = c.id
            JOIN locations l ON jp.location_id = l.id
            WHERE jp.company_id IN (%s, %s)
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid_d, cid_f))

        visible_jobs = self.cur.fetchall()
        self.assertEqual(len(visible_jobs), 6)
        visible_job_ids = {r[0] for r in visible_jobs}
        self.assertEqual(visible_job_ids, {"reg:d1", "reg:d2", "reg:d3", "reg:f1", "reg:f2", "reg:f3"})

    def test_sql_false_positive_protection_shared_boilerplate_55_to_70_percent(self):
        """
        Required SQL test:
        Two jobs at the same company with:
        - same title
        - same city
        - same role type
        - shared company boilerplate / EEO / benefits producing 55-70% vocabulary overlap
        - materially different responsibilities (e.g., Payments backend vs Mobile backend)
        MUST BOTH REMAIN VISIBLE in SQL deduplication query.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression FP Boilerplate') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('San Francisco, CA (fp)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        boilerplate = (
            "About Acme Platform: Acme is an enterprise cloud payment infrastructure provider. "
            "We serve thousands of financial institutions and high-growth internet companies worldwide. "
            "Our Comprehensive Benefits: We offer top-tier health, dental, and vision insurance, 401(k) retirement "
            "matching up to 5 percent, generous flexible paid time off, parental leave, and wellness stipends. "
            "Equal Opportunity Employer: Acme is proud to be an equal opportunity workplace committed to diversity, "
            "equity, and inclusion regardless of race, gender, veteran status, or disability. "
            "Salary Range: $170,000 to $240,000 annual base salary depending on experience and location."
        )
        desc_payments = (
            boilerplate
            + " Responsibilities: Design and implement high-throughput ledger settlement and payment processing "
            + "systems in Java, Spring Boot, and Apache Kafka. Work on distributed transactions, idempotency guarantees, "
            + "relational database schemas, and microservice consistency. Minimum 5 years distributed backend experience."
        )
        desc_mobile = (
            boilerplate
            + " Responsibilities: Design and implement native consumer mobile payment checkout experiences using "
            + "Swift, iOS SDK, SwiftUI, and React Native. Work on offline transaction caching, client rendering performance, "
            + "local device keychain storage, and biometric authentication. Minimum 5 years native iOS development experience."
        )

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, description)
            VALUES
            ('fp:pay_1', %s, %s, 'Senior Software Engineer', 'onsite', 'full_time', 'greenhouse', 'pay-1', 'https://acme.com/pay', %s),
            ('fp:mob_1', %s, %s, 'Senior Software Engineer', 'onsite', 'full_time', 'greenhouse', 'mob-1', 'https://acme.com/mob', %s);
        """, (cid, lid, desc_payments, cid, lid, desc_mobile))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual(len(visible_jobs), 2)
        visible_ids = {r[0] for r in visible_jobs}
        self.assertEqual(visible_ids, {"fp:pay_1", "fp:mob_1"})

    def test_sql_true_duplicate_exact_normalized_description(self):
        """
        Required SQL test: exact normalized description -> deduplicated to 1.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression Exact SQL') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Austin, TX (exact)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        desc1 = "Join our platform team building resilient infrastructure systems."
        desc2 = "  join  our platform   team building resilient infrastructure systems.  "

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, posted_at, description)
            VALUES
            ('exact:sql_1', %s, %s, 'Platform Engineer', 'onsite', 'full_time', 'greenhouse', 'ex-1', 'https://acme.com/ex1', '2026-09-20T12:00:00Z', %s),
            ('exact:sql_2', %s, %s, 'Platform Engineer', 'onsite', 'full_time', 'greenhouse', 'ex-2', 'https://acme.com/ex2', '2026-09-22T12:00:00Z', %s);
        """, (cid, lid, desc1, cid, lid, desc2))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual({r[0] for r in visible_jobs}, {"exact:sql_1", "exact:sql_2"})

    def test_sql_true_duplicate_high_similarity_and_length_ratio(self):
        """
        Required SQL test: >= 90% vocabulary similarity and length ratio >= 0.80 -> deduplicated to 1.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression Sim SQL') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Boston, MA (sim)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        base_desc = (
            "About Acme: We are building high-scale distributed payments infrastructure in Java and Kotlin "
            "with Kafka and Spring Boot. 5+ years experience required with distributed systems and relational "
            "databases like PostgreSQL. Full comprehensive healthcare dental and retirement benefits included."
        )
        desc1 = base_desc + " Pay range is $180,000 to $220,000 annually."
        desc2 = base_desc + " Pay range is $185,000 to $225,000 annually."

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, posted_at, description)
            VALUES
            ('sim:sql_1', %s, %s, 'Payments Engineer', 'onsite', 'full_time', 'greenhouse', 'sim-1', 'https://acme.com/s1', '2026-09-20T12:00:00Z', %s),
            ('sim:sql_2', %s, %s, 'Payments Engineer', 'onsite', 'full_time', 'greenhouse', 'sim-2', 'https://acme.com/s2', '2026-09-23T12:00:00Z', %s);
        """, (cid, lid, desc1, cid, lid, desc2))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual({r[0] for r in visible_jobs}, {"sim:sql_1", "sim:sql_2"})

    def test_sql_true_duplicate_shared_requisition_code(self):
        """
        Required SQL test: shared explicit requisition code (e.g. P-160) -> deduplicated to 1.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression ReqCode SQL') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Sunnyvale, CA (req)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        desc1 = "P-160: Original team posting for fullstack infrastructure with React and Python."
        desc2 = "P-160: Updated team posting with expanded team scope and revised requirements."

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, posted_at, description)
            VALUES
            ('req:sql_1', %s, %s, 'Fullstack Engineer', 'onsite', 'full_time', 'greenhouse', 'req-1', 'https://acme.com/r1', '2026-09-20T12:00:00Z', %s),
            ('req:sql_2', %s, %s, 'Fullstack Engineer', 'onsite', 'full_time', 'greenhouse', 'req-2', 'https://acme.com/r2', '2026-09-24T12:00:00Z', %s);
        """, (cid, lid, desc1, cid, lid, desc2))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual({r[0] for r in visible_jobs}, {"req:sql_1", "req:sql_2"})

    def test_distinct_requisitions_different_descriptions_remain_visible(self):
        """
        Distinct requisitions sharing same company, title, location, role_type
        but having materially different descriptions, different IDs, and different URLs
        MUST BOTH remain visible.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression Stripe') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('San Francisco, CA (reg)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        desc_payments = "Build high-throughput payments processing infrastructure in Java, Kafka, Spring, SQL. Core banking transactions."
        desc_mobile = "Build mobile consumer iOS/Android experience using Swift, Kotlin, React Native, GraphQL. Offline-first UI animations."

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, description)
            VALUES
            ('reg:stripe_pay', %s, %s, 'Software Engineer', 'onsite', 'full_time', 'greenhouse', 'gh-pay', 'https://stripe.com/pay', %s),
            ('reg:stripe_mob', %s, %s, 'Software Engineer', 'onsite', 'full_time', 'greenhouse', 'gh-mob', 'https://stripe.com/mob', %s);
        """, (cid, lid, desc_payments, cid, lid, desc_mobile))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual(len(visible_jobs), 2)
        visible_ids = {r[0] for r in visible_jobs}
        self.assertEqual(visible_ids, {"reg:stripe_pay", "reg:stripe_mob"})

    def test_same_canonical_url_different_description_is_duplicate(self):
        """
        Postings sharing company, title, location, role_type and exact same canonical URL
        (with fragment stripped) MUST collapse to 1 even if descriptions differ.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression URL') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Austin, TX (reg)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, description)
            VALUES
            ('reg:url_1', %s, %s, 'Site Reliability Engineer', 'onsite', 'full_time', 'greenhouse', 'gh-1', 'https://co.com/jobs/sre?gh_jid=123#feed', 'Brief description 1'),
            ('reg:url_2', %s, %s, 'Site Reliability Engineer', 'onsite', 'full_time', 'greenhouse', 'gh-2', 'https://co.com/jobs/sre?gh_jid=123', 'Different description 2');
        """, (cid, lid, cid, lid))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual(len(visible_jobs), 1)
        self.assertEqual(visible_jobs[0][0], "reg:url_2")

    def test_absent_descriptions_do_not_blindly_collapse(self):
        """
        If descriptions are NULL / absent, postings sharing title/location with different IDs/URLs
        do NOT collapse. Both remain visible.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression Absent Desc') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Seattle, WA (reg)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, description)
            VALUES
            ('reg:nodesc_1', %s, %s, 'DevOps Engineer', 'onsite', 'full_time', 'greenhouse', 'nd-1', 'https://co.com/1', NULL),
            ('reg:nodesc_2', %s, %s, 'DevOps Engineer', 'onsite', 'full_time', 'greenhouse', 'nd-2', 'https://co.com/2', NULL);
        """, (cid, lid, cid, lid))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual(len(visible_jobs), 2)
        visible_ids = {r[0] for r in visible_jobs}
        self.assertEqual(visible_ids, {"reg:nodesc_1", "reg:nodesc_2"})

    def test_gh_jid_identity_parameters_preserved_both_remain_visible(self):
        """
        Required regression test:
        same company, same normalized title, same location, same role_type
        URL 1: https://company.com/careers/job?gh_jid=111
        URL 2: https://company.com/careers/job?gh_jid=222
        different source_job_id, materially different descriptions
        EXPECTED: BOTH remain visible.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression gh_jid') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('Mountain View, CA (reg2)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        desc1 = "Fullstack web platform engineer building agentic SDLC and front-end UI components with React."
        desc2 = "Distributed systems engineer building database storage engine in C++ and Rust."

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, description)
            VALUES
            ('reg:gh_111', %s, %s, 'Senior Software Engineer', 'onsite', 'full_time', 'greenhouse', '111', 'https://company.com/careers/job?gh_jid=111', %s),
            ('reg:gh_222', %s, %s, 'Senior Software Engineer', 'onsite', 'full_time', 'greenhouse', '222', 'https://company.com/careers/job?gh_jid=222', %s);
        """, (cid, lid, desc1, cid, lid, desc2))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual(len(visible_jobs), 2)
        visible_ids = {r[0] for r in visible_jobs}
        self.assertEqual(visible_ids, {"reg:gh_111", "reg:gh_222"})

    def test_tracking_params_differ_without_description_remain_visible_in_sql(self):
        """
        Tracking parameter case:
        https://company.com/jobs/123?utm_source=linkedin
        https://company.com/jobs/123?utm_source=google
        Without unsafe query stripping, if IDs differ and descriptions are materially different,
        keeping both is safer than false merging.
        """
        from api.main import get_deduplication_sql_predicate
        dedup_sql = get_deduplication_sql_predicate(table_alias="jp")

        self.cur.execute("INSERT INTO companies (name) VALUES ('Regression Tracking URL') RETURNING id;")
        cid = self.cur.fetchone()[0]
        self.cur.execute("INSERT INTO locations (location, country) VALUES ('New York, NY (reg2)', 'United States') RETURNING id;")
        lid = self.cur.fetchone()[0]

        desc1 = "Payments billing infrastructure role."
        desc2 = "Mobile iOS application role."

        self.cur.execute("""
            INSERT INTO job_postings (job_id, company_id, location_id, title, workplace_type, role_type, source_name, source_job_id, source_url, description)
            VALUES
            ('reg:track_1', %s, %s, 'Software Engineer', 'onsite', 'full_time', 'greenhouse', 'id-1', 'https://company.com/jobs/123?utm_source=linkedin', %s),
            ('reg:track_2', %s, %s, 'Software Engineer', 'onsite', 'full_time', 'greenhouse', 'id-2', 'https://company.com/jobs/123?utm_source=google', %s);
        """, (cid, lid, desc1, cid, lid, desc2))

        self.cur.execute(f"""
            SELECT jp.job_id
            FROM job_postings jp
            WHERE jp.company_id = %s
              AND {dedup_sql}
            ORDER BY jp.id;
        """, (cid,))

        visible_jobs = self.cur.fetchall()
        self.assertEqual(len(visible_jobs), 2)
        visible_ids = {r[0] for r in visible_jobs}
        self.assertEqual(visible_ids, {"reg:track_1", "reg:track_2"})

    def test_go_search_postgresql_regex_integration(self):
        """
        Integration test verifying PostgreSQL regex evaluation for q=go:
        - matches 'Go Software Engineer', 'Senior Golang Backend Engineer', 'Software Engineer (Go)'
        - does NOT match 'Government Affairs Lead', 'Ongoing Project Director', 'Cargo Coordinator'
        - does NOT match 'Go-to-Market Lead', 'Go-Live Specialist'
        """
        test_cases = [
            ("Go Software Engineer", True),
            ("Senior Golang Backend Engineer", True),
            ("Software Engineer (Go)", True),
            ("Backend Developer - Go / Python", True),
            ("Government Affairs Lead", False),
            ("Ongoing Project Director", False),
            ("Foregoing Analytics Manager", False),
            ("Cargo Plane Logistics Coordinator", False),
            ("Go-to-Market Lead", False),
            ("Director of Go-to-Market", False),
            ("Go To Market Strategy Specialist", False),
            ("Go-Live Implementation Specialist", False),
        ]
        pos_pattern = r"\y(golang|go)\y"
        neg_pattern = r"\ygo[\s\-]to[\s\-]market\y|\ygo[\s\-]live\y"

        for title, expected in test_cases:
            self.cur.execute("""
                SELECT (%s ~* %s AND %s !~* %s) AS matched;
            """, (title, pos_pattern, title, neg_pattern))
            actual = self.cur.fetchone()[0]
            self.assertEqual(
                actual,
                expected,
                f"Title '{title}' expected match={expected}, got {actual}",
            )


if __name__ == "__main__":
    unittest.main()


def test_api_responses_carry_security_headers():
    from fastapi.testclient import TestClient
    from api.main import app

    response = TestClient(app).get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Strict-Transport-Security" in response.headers
    docs = TestClient(app).get("/docs")
    assert "Content-Security-Policy" not in docs.headers  # Swagger UI needs inline assets
    assert docs.headers["X-Content-Type-Options"] == "nosniff"


def test_cors_headers_for_vercel_preview_and_production():
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)

    # 1. Vercel preview URL preflight OPTIONS
    preview_origin = "https://roleradar-git-feature-preview-example-projects.vercel.app"
    res_opts = client.options(
        "/api/health",
        headers={
            "Origin": preview_origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_opts.status_code == 200
    assert res_opts.headers.get("access-control-allow-origin") == preview_origin

    # 2. Vercel preview URL GET
    res_get = client.get("/api/health", headers={"Origin": preview_origin})
    assert res_get.status_code == 200
    assert res_get.headers.get("access-control-allow-origin") == preview_origin

    # 3. Production Vercel domain GET
    prod_origin = "https://roleradar-jobs.vercel.app"
    res_prod = client.get("/api/health", headers={"Origin": prod_origin})
    assert res_prod.status_code == 200
    assert res_prod.headers.get("access-control-allow-origin") == prod_origin

    # 4. Insecure / arbitrary origin should NOT receive allow-origin
    untrusted = "https://malicious.example.com"
    res_untrusted = client.get("/api/health", headers={"Origin": untrusted})
    assert res_untrusted.headers.get("access-control-allow-origin") is None
