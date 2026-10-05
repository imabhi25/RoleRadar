"""
Deterministic unit tests for ATS adapters (Greenhouse, Lever, Ashby) and target configuration.
All tests use static fixtures and mocked HTTP responses; zero live network requests.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from ingestion.clients import (
    ArbeitnowClient,
    AshbyClient,
    GreenhouseClient,
    JobicyClient,
    LeverClient,
    RemotiveClient,
    get_ats_client,
    get_broad_source_client,
)
from ingestion.http_client import HardenedHttpClient, IngestionFetchError

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(filename: str):
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestGreenhouseClient(unittest.TestCase):
    def setUp(self):
        self.mock_http = MagicMock(spec=HardenedHttpClient)
        self.client = GreenhouseClient(http_client=self.mock_http)
        self.fixture_data = load_fixture("greenhouse_jobs.json")

    def test_successful_parsing_and_mapping(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Figma", identifier="figma")

        # 5 items in fixture: 2 malformed skipped, 3 valid postings returned
        self.assertEqual(len(postings), 3)
        self.assertEqual(postings.parse_error_count, 2)
        self.assertEqual(postings.total_raw_records, 5)
        self.assertTrue(postings.fetch_complete)

        first = postings[0]
        self.assertEqual(first.source_name, "greenhouse")
        self.assertEqual(first.source_job_id, "101")
        self.assertEqual(first.company_name, "Figma")
        self.assertEqual(first.title, "Senior Backend Engineer")
        self.assertEqual(first.raw_location, "San Francisco, CA")
        self.assertEqual(first.source_url, "https://boards.greenhouse.io/figma/jobs/101")
        self.assertIn("Python and Docker", first.raw_description)
        # Greenhouse updated_at is NOT treated as original posted_at
        self.assertIsNone(first.posted_at)

    def test_handles_missing_optional_fields(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Figma", identifier="figma")

        second = postings[1]
        self.assertEqual(second.source_job_id, "102")
        self.assertEqual(second.title, "Frontend Developer")
        self.assertEqual(second.raw_location, "")
        self.assertEqual(second.raw_description, "")
        self.assertIsNone(second.posted_at)

    def test_does_not_filter_non_swe_jobs(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Figma", identifier="figma")

        third = postings[2]
        self.assertEqual(third.title, "Senior Technical Recruiter")
        self.assertEqual(third.source_job_id, "104")

    def test_malformed_source_response_raises_error(self):
        # Source response is not a dict or lacks 'jobs' list
        for bad_payload in [[], {"unexpected": "format"}, None, "string"]:
            self.mock_http.get_json.return_value = bad_payload
            with self.subTest(payload=bad_payload):
                with self.assertRaises(IngestionFetchError):
                    self.client.fetch_jobs(company_name="Figma", identifier="figma")


class TestLeverClient(unittest.TestCase):
    def setUp(self):
        self.mock_http = MagicMock(spec=HardenedHttpClient)
        self.client = LeverClient(http_client=self.mock_http)
        self.fixture_data = load_fixture("lever_jobs.json")

    def test_successful_parsing_and_mapping(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Spotify", identifier="spotify")

        # 4 items in fixture: 1 malformed skipped, 3 valid postings returned
        self.assertEqual(len(postings), 3)
        self.assertEqual(postings.parse_error_count, 1)
        self.assertEqual(postings.total_raw_records, 4)
        self.assertTrue(postings.fetch_complete)

        first = postings[0]
        self.assertEqual(first.source_name, "lever")
        self.assertEqual(first.source_job_id, "lev-001")
        self.assertEqual(first.company_name, "Spotify")
        self.assertEqual(first.title, "Full Stack Engineer")
        self.assertEqual(first.raw_location, "Toronto, Canada")
        self.assertEqual(first.raw_workplace_type, "hybrid")
        self.assertEqual(first.source_url, "https://jobs.lever.co/spotify/lev-001")
        self.assertIn("TypeScript and React", first.raw_description)

        # Millisecond timestamp conversion verification (1672531199000 -> 2022-12-31 23:59:59 UTC)
        expected_dt = datetime(2022, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        self.assertEqual(first.posted_at, expected_dt)

    def test_handles_missing_optional_fields(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Spotify", identifier="spotify")

        second = postings[1]
        self.assertEqual(second.source_job_id, "lev-002")
        self.assertEqual(second.title, "Data Platform Engineer")
        self.assertEqual(second.raw_location, "")
        self.assertIsNone(second.raw_workplace_type)
        self.assertIsNone(second.posted_at)

    def test_does_not_filter_non_swe_jobs(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Spotify", identifier="spotify")

        third = postings[2]
        self.assertEqual(third.title, "Sales Director")
        self.assertEqual(third.raw_workplace_type, "on-site")

    def test_malformed_source_response_raises_error(self):
        for bad_payload in [{"jobs": []}, None, "bad string"]:
            self.mock_http.get_json.return_value = bad_payload
            with self.subTest(payload=bad_payload):
                with self.assertRaises(IngestionFetchError):
                    self.client.fetch_jobs(company_name="Spotify", identifier="spotify")

    def test_lever_complete_description_with_lists_and_additional(self):
        full_lever_job = [
            {
                "id": "lev-full-001",
                "text": "Senior Backend Engineer",
                "categories": {"location": "Toronto, ON"},
                "description": "<p>Overview of the role.</p>",
                "lists": [
                    {
                        "text": "What you'll do",
                        "content": "<ul><li>Build distributed systems</li></ul>",
                    },
                    {
                        "text": "What we're looking for",
                        "content": "<ul><li>5+ years Go experience</li></ul>",
                    },
                ],
                "additional": "<p>Competitive compensation and comprehensive benefits.</p>",
                "createdAt": 1672531199000,
            }
        ]
        self.mock_http.get_json.return_value = full_lever_job
        postings = self.client.fetch_jobs(company_name="Spotify", identifier="spotify")
        self.assertEqual(len(postings), 1)
        desc = postings[0].raw_description
        self.assertIn("Overview of the role", desc)
        self.assertIn("<h3>What you'll do</h3>", desc)
        self.assertIn("Build distributed systems", desc)
        self.assertIn("<h3>What we're looking for</h3>", desc)
        self.assertIn("5+ years Go experience", desc)
        self.assertIn("Competitive compensation and comprehensive benefits", desc)


class TestAshbyClient(unittest.TestCase):
    def setUp(self):
        self.mock_http = MagicMock(spec=HardenedHttpClient)
        self.client = AshbyClient(http_client=self.mock_http)
        self.fixture_data = load_fixture("ashby_jobs.json")

    def test_successful_parsing_and_mapping(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Linear", identifier="linear")

        # 4 items in fixture: 1 malformed skipped, 3 valid postings returned
        self.assertEqual(len(postings), 3)
        self.assertEqual(postings.parse_error_count, 1)
        self.assertEqual(postings.total_raw_records, 4)
        self.assertTrue(postings.fetch_complete)

        first = postings[0]
        self.assertEqual(first.source_name, "ashby")
        self.assertEqual(first.source_job_id, "ash-001")
        self.assertEqual(first.company_name, "Linear")
        self.assertEqual(first.title, "Site Reliability Engineer")
        self.assertEqual(first.raw_location, "Remote - US")
        self.assertEqual(first.raw_workplace_type, "Remote")
        self.assertEqual(first.source_url, "https://jobs.ashbyhq.com/linear/ash-001")
        self.assertIn("Kubernetes and Terraform", first.raw_description)

        # ISO timestamp conversion verification
        expected_dt = datetime(2023, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(first.posted_at, expected_dt)

    def test_handles_missing_optional_fields(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Linear", identifier="linear")

        second = postings[1]
        self.assertEqual(second.source_job_id, "ash-002")
        self.assertEqual(second.title, "Mobile Engineer (iOS)")
        self.assertEqual(second.raw_location, "")
        self.assertIsNone(second.raw_workplace_type)
        self.assertIsNone(second.posted_at)

    def test_does_not_filter_non_swe_jobs(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(company_name="Linear", identifier="linear")

        third = postings[2]
        self.assertEqual(third.title, "Product Designer")
        self.assertEqual(third.raw_workplace_type, "Onsite")

    def test_ashby_hybrid_precedence_over_is_remote(self):
        """Ashby jobs with workplaceType='Hybrid' and isRemote=True must map raw_workplace_type to 'Hybrid'."""
        hybrid_payload = {
            "jobs": [
                {
                    "id": "ash-hybrid-1",
                    "title": "Senior Software Engineer, Compute Platform",
                    "locationName": "San Francisco, CA",
                    "isRemote": True,
                    "workplaceType": "Hybrid",
                    "jobUrl": "https://jobs.ashbyhq.com/replit/ash-hybrid-1",
                    "descriptionHtml": "<p>Hybrid 3 days in office</p>",
                }
            ]
        }
        self.mock_http.get_json.return_value = hybrid_payload
        postings = self.client.fetch_jobs(company_name="Replit", identifier="replit")
        self.assertEqual(len(postings), 1)
        self.assertEqual(postings[0].raw_workplace_type, "Hybrid")

    def test_malformed_source_response_raises_error(self):
        for bad_payload in [[], {"wrong": "format"}, None, "string"]:
            self.mock_http.get_json.return_value = bad_payload
            with self.subTest(payload=bad_payload):
                with self.assertRaises(IngestionFetchError):
                    self.client.fetch_jobs(company_name="Linear", identifier="linear")



class TestJobicyClient(unittest.TestCase):
    def setUp(self):
        self.mock_http = MagicMock(spec=HardenedHttpClient)
        self.client = JobicyClient(http_client=self.mock_http)
        self.fixture_data = load_fixture("jobicy_response.json")

    def test_successful_parsing_and_mapping(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(count=50)

        # 6 items in fixture: 2 malformed skipped, 4 valid postings returned
        self.assertEqual(len(postings), 4)
        self.assertEqual(postings.parse_error_count, 2)
        self.assertEqual(postings.total_raw_records, 6)
        self.assertTrue(postings.fetch_complete)

        first = postings[0]
        self.assertEqual(first.source_name, "jobicy")
        self.assertEqual(first.source_job_id, "1001")
        self.assertEqual(first.company_name, "Supabase")
        self.assertEqual(first.title, "Senior Backend Engineer")
        self.assertEqual(first.raw_location, "USA, Canada, Europe")
        self.assertEqual(first.raw_workplace_type, "remote")
        self.assertEqual(first.raw_job_type, "Full-Time")
        self.assertEqual(first.source_url, "https://jobicy.com/jobs/1001-senior-backend-engineer")
        self.assertIn("Senior Backend Engineer", first.raw_description)
        self.assertEqual(
            first.posted_at,
            datetime(2026, 9, 25, 14, 30, 0, tzinfo=timezone.utc),
        )

    def test_iso_date_with_z_suffix_and_internship(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(count=50)

        second = postings[1]
        self.assertEqual(second.source_job_id, "1002")
        self.assertEqual(second.company_name, "Vercel")
        self.assertEqual(second.title, "Software Engineer Intern")
        self.assertEqual(second.raw_job_type, "Internship")
        self.assertEqual(
            second.posted_at,
            datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc),
        )

    def test_handles_missing_or_invalid_pub_date(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(count=50)

        fourth = postings[3]
        self.assertEqual(fourth.source_job_id, "1004")
        self.assertEqual(fourth.title, "Fullstack Developer")
        self.assertEqual(fourth.raw_location, "Remote")
        self.assertEqual(fourth.raw_job_type, "Full-Time")
        self.assertIsNone(fourth.posted_at)

    def test_query_parameters_constructed_properly(self):
        self.mock_http.get_json.return_value = {"jobs": []}
        self.client.fetch_jobs(count=25, geo="usa", industry="engineering")

        called_url = self.mock_http.get_json.call_args[0][0]
        self.assertIn("count=25", called_url)
        self.assertIn("geo=usa", called_url)
        self.assertIn("industry=engineering", called_url)

    def test_malformed_source_response_raises_error(self):
        for bad_payload in [[], {"unexpected": "payload"}, None, "string"]:
            self.mock_http.get_json.return_value = bad_payload
            with self.subTest(payload=bad_payload):
                with self.assertRaises(IngestionFetchError):
                    self.client.fetch_jobs(count=50)


class TestRemotiveClient(unittest.TestCase):
    def setUp(self):
        self.mock_http = MagicMock(spec=HardenedHttpClient)
        self.client = RemotiveClient(http_client=self.mock_http)
        self.fixture_data = load_fixture("remotive_response.json")

    def test_successful_parsing_and_mapping(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(category="software-development")

        self.assertEqual(len(postings), 4)
        self.assertEqual(postings.total_raw_records, 4)
        self.assertEqual(postings.parse_error_count, 0)
        self.assertTrue(postings.fetch_complete)

        first = postings[0]
        self.assertEqual(first.source_name, "remotive")
        self.assertEqual(first.source_job_id, "2001")
        self.assertEqual(first.company_name, "Doist")
        self.assertEqual(first.title, "Senior Python Engineer")
        self.assertEqual(first.raw_location, "USA, Canada")
        self.assertEqual(first.raw_workplace_type, "remote")
        self.assertEqual(first.raw_job_type, "full_time")
        self.assertEqual(
            first.posted_at,
            datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            first.source_url,
            "https://remotive.com/remote-jobs/software-development/senior-python-engineer-2001",
        )

        second = postings[1]
        self.assertEqual(second.source_job_id, "2002")
        self.assertEqual(second.company_name, "Shopify")
        self.assertEqual(second.title, "Software Developer Co-op")
        self.assertEqual(second.raw_location, "Canada Remote")
        self.assertEqual(second.raw_job_type, "internship")

    def test_attribution_and_legal_notice(self):
        self.mock_http.get_json.return_value = self.fixture_data
        self.client.fetch_jobs()
        attribution = self.client.get_attribution()
        self.assertIn("Remotive", attribution)

    def test_malformed_source_response_raises_error(self):
        for bad_payload in [[], {"unexpected": "payload"}, None, "string"]:
            self.mock_http.get_json.return_value = bad_payload
            with self.subTest(payload=bad_payload):
                with self.assertRaises(IngestionFetchError):
                    self.client.fetch_jobs()


class TestArbeitnowClient(unittest.TestCase):
    def setUp(self):
        self.mock_http = MagicMock(spec=HardenedHttpClient)
        self.client = ArbeitnowClient(http_client=self.mock_http)
        self.fixture_data = load_fixture("arbeitnow_response.json")

    def test_successful_parsing_and_mapping(self):
        self.mock_http.get_json.return_value = self.fixture_data
        postings = self.client.fetch_jobs(max_pages=1)

        self.assertEqual(len(postings), 3)
        self.assertEqual(postings.total_raw_records, 3)
        self.assertEqual(postings.parse_error_count, 0)
        self.assertTrue(postings.fetch_complete)

        first = postings[0]
        self.assertEqual(first.source_name, "arbeitnow")
        self.assertEqual(first.source_job_id, "senior-frontend-engineer-berlin-12345")
        self.assertEqual(first.company_name, "Delivery Hero")
        self.assertEqual(first.title, "Senior Frontend Engineer")
        self.assertEqual(first.raw_location, "Berlin, Germany")
        self.assertEqual(first.raw_workplace_type, "remote")
        self.assertEqual(first.raw_job_type, "Full Time")
        self.assertEqual(
            first.posted_at,
            datetime.fromtimestamp(1727280000, tz=timezone.utc),
        )
        self.assertEqual(
            first.source_url,
            "https://www.arbeitnow.com/jobs/companies/delivery-hero/senior-frontend-engineer-berlin-12345",
        )

        third = postings[2]
        self.assertEqual(third.company_name, "Zalando")
        self.assertIsNone(third.raw_workplace_type)

    def test_pagination_and_deduplication(self):
        page1 = {
            "data": [
                {
                    "slug": "job-1",
                    "company_name": "Tech Corp",
                    "title": "Engineer 1",
                    "description": "<p>Desc</p>",
                    "remote": True,
                    "url": "https://arbeitnow.com/job-1",
                    "created_at": 1727280000,
                }
            ],
            "links": {"next": "https://arbeitnow.com/api?page=2"},
        }
        page2 = {
            "data": [
                {
                    "slug": "job-1",  # duplicate slug across pages
                    "company_name": "Tech Corp",
                    "title": "Engineer 1 Duplicate",
                    "description": "<p>Desc</p>",
                    "remote": True,
                    "url": "https://arbeitnow.com/job-1",
                    "created_at": 1727280000,
                },
                {
                    "slug": "job-2",
                    "company_name": "Tech Corp",
                    "title": "Engineer 2",
                    "description": "<p>Desc 2</p>",
                    "remote": False,
                    "url": "https://arbeitnow.com/job-2",
                    "created_at": 1727281000,
                }
            ],
            "links": {"next": None},
        }

        self.mock_http.get_json.side_effect = [page1, page2]
        postings = self.client.fetch_jobs(max_pages=2)

        self.assertEqual(len(postings), 2)
        slugs = [p.source_job_id for p in postings]
        self.assertEqual(slugs, ["job-1", "job-2"])

    def test_attribution(self):
        attribution = self.client.get_attribution()
        self.assertIn("Arbeitnow", attribution)

    def test_malformed_source_response_raises_error(self):
        for bad_payload in [[], {"unexpected": "payload"}, None, "string"]:
            self.mock_http.get_json.side_effect = None
            self.mock_http.get_json.return_value = bad_payload
            with self.subTest(payload=bad_payload):
                with self.assertRaises(IngestionFetchError):
                    self.client.fetch_jobs(max_pages=1)


class TestAdapterFactoryAndConfig(unittest.TestCase):
    def test_get_ats_client_factory(self):
        gh_client = get_ats_client("greenhouse")
        self.assertIsInstance(gh_client, GreenhouseClient)

        lever_client = get_ats_client({"ats": "lever", "name": "Spotify"})
        self.assertIsInstance(lever_client, LeverClient)

        ashby_client = get_ats_client("ashby")
        self.assertIsInstance(ashby_client, AshbyClient)

        jobicy_client = get_ats_client("jobicy")
        self.assertIsInstance(jobicy_client, JobicyClient)

        remotive_client = get_ats_client("remotive")
        self.assertIsInstance(remotive_client, RemotiveClient)

        arbeitnow_client = get_ats_client("arbeitnow")
        self.assertIsInstance(arbeitnow_client, ArbeitnowClient)

        jobicy_broad = get_broad_source_client("jobicy")
        self.assertIsInstance(jobicy_broad, JobicyClient)

        remotive_broad = get_broad_source_client("remotive")
        self.assertIsInstance(remotive_broad, RemotiveClient)

        arbeitnow_broad = get_broad_source_client("arbeitnow")
        self.assertIsInstance(arbeitnow_broad, ArbeitnowClient)

        with self.assertRaises(ValueError):
            get_ats_client("unsupported_ats")

    def test_target_companies_configuration(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "target_companies.json"
        self.assertTrue(config_path.exists(), "config/target_companies.json must exist")

        with open(config_path, "r", encoding="utf-8") as f:
            companies = json.load(f)

        self.assertIsInstance(companies, list)
        self.assertGreaterEqual(len(companies), 6, "Must have at least 6 companies configured")
        self.assertLessEqual(len(companies), 100, "Must have at most 100 companies configured")

        seen_identifiers = set()
        seen_ats = set()

        for c in companies:
            self.assertIn("name", c)
            self.assertIn("ats", c)
            self.assertIn("identifier", c)
            self.assertIn(c["ats"], ["greenhouse", "lever", "ashby", "workday", "amazon", "google", "shopify", "phenom", "successfactors"])
            # Strictly NO LinkedIn
            self.assertNotIn("linkedin", c["identifier"].lower())
            seen_identifiers.add(c["identifier"])
            seen_ats.add(c["ats"])

        # Every configured official adapter must be represented and supported.
        self.assertEqual(seen_ats, {"greenhouse", "lever", "ashby", "workday", "amazon", "google", "shopify", "phenom", "successfactors"})
        self.assertEqual(len(seen_identifiers), len(companies), "Identifiers must be unique")


if __name__ == "__main__":
    unittest.main()
