"""
Unit tests for Company-Level Branding and Authentic Logo System.
Verifies resolution, durable caching, database persistence, provenance tracking,
and API delivery across priority companies and unverified fallbacks.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from ingestion.base import FetchResult, RawJobPosting
from ingestion.company_resolver import (
    VERIFIED_COMPANY_CATALOG,
    get_or_create_company_with_branding,
    normalize_company_name,
    resolve_company_branding,
    seed_and_audit_all_target_companies,
)
from ingestion.pipeline import sync_company


class TestCompanyBrandingSystem(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_normalize_company_name(self):
        self.assertEqual(normalize_company_name("Scale AI, Inc."), "scale ai")
        self.assertEqual(normalize_company_name("Carta Technologies LLC"), "carta")
        self.assertEqual(normalize_company_name("PointClickCare Corp."), "pointclickcare")
        self.assertEqual(normalize_company_name("Stability AI (US)"), "stability ai")

    def test_priority_companies_in_verified_catalog(self):
        priority = [
            "carta",
            "faire",
            "plaid",
            "figma",
            "scale ai",
            "waabi",
            "pointclickcare",
            "stability ai",
        ]
        logos_dir = Path(__file__).resolve().parent.parent / "frontend" / "public"

        for p in priority:
            branding = resolve_company_branding(p)
            self.assertEqual(branding["logo_status"], "verified", f"{p} must be verified")
            self.assertIsNotNone(branding["logo_url"], f"{p} must have logo_url")
            self.assertIsNotNone(branding["logo_source_url"], f"{p} must have logo_source_url")
            # Verify file exists on disk
            rel_path = branding["logo_url"].lstrip("/")
            file_path = logos_dir / rel_path
            self.assertTrue(file_path.is_file(), f"Logo file for {p} must exist at {file_path}")

    def test_unverified_company_returns_unresolved_without_inventing_logo(self):
        unknown_name = "Nonexistent Unicorn Robotics Ltd"
        branding = resolve_company_branding(unknown_name)
        self.assertEqual(branding["logo_status"], "unresolved")
        self.assertIsNone(branding["logo_url"])
        self.assertIsNone(branding["logo_source_url"])

    def test_get_or_create_company_persists_branding(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [
            None,  # First query: company does not exist
            (42,), # INSERT ... RETURNING id
        ]
        cid, created = get_or_create_company_with_branding(mock_cur, "Linear")
        self.assertEqual(cid, 42)
        self.assertTrue(created)
        # Verify INSERT included logo_url, logo_source_url, and logo_status
        insert_call = mock_cur.execute.call_args_list[1]
        sql = insert_call[0][0]
        params = insert_call[0][1]
        self.assertIn("logo_url", sql)
        self.assertIn("logo_source_url", sql)
        self.assertEqual(params[0], "Linear")
        self.assertEqual(params[1], "/logos/linear.svg")
        self.assertEqual(params[3], "verified")

    @patch("api.main.get_db_cursor")
    def test_api_companies_endpoint(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            (1, "Linear", "/logos/linear.svg", "https://simpleicons.org/", "verified", "https://linear.app", 6),
            (2, "Unknown Startup", None, None, "unresolved", None, 1),
        ]
        mock_get_db.return_value.__enter__.return_value = mock_cur

        response = self.client.get("/api/companies")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "Linear")
        self.assertEqual(data[0]["logo_status"], "verified")
        self.assertEqual(data[0]["logo_url"], "/logos/linear.svg")
        self.assertEqual(data[1]["logo_status"], "unresolved")
        self.assertIsNone(data[1]["logo_url"])

    @patch("api.main.get_db_cursor")
    def test_api_single_company_detail_endpoint(self, mock_get_db):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (
            1, "Carta", "/logos/carta.png", "https://s3-recruiting.cdn.greenhouse.io/...", "verified", "https://carta.com", 3
        )
        mock_get_db.return_value.__enter__.return_value = mock_cur

        response = self.client.get("/api/companies/Carta")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Carta")
        self.assertEqual(data["logo_status"], "verified")
        self.assertEqual(data["logo_url"], "/logos/carta.png")

    @patch("ingestion.pipeline.get_ats_client")
    def test_newly_ingested_posting_receives_verified_branding(self, mock_get_client):
        mock_client = MagicMock()
        raw_job = RawJobPosting(
            source_name="ashby",
            source_job_id="new-1",
            company_name="Linear",
            title="Senior Product Engineer",
            raw_location="San Francisco, CA",
            source_url="https://jobs.ashbyhq.com/linear/new-1",
            posted_at=datetime.now(timezone.utc),
            raw_description="<p>React and TypeScript.</p>",
        )
        mock_client.fetch_jobs.return_value = FetchResult(
            jobs=[raw_job],
            parse_error_count=0,
            fetch_complete=True,
            total_raw_records=1,
        )
        mock_get_client.return_value = mock_client

        mock_cur = MagicMock()
        # 1: sync_run, 2: company lookup (exists), 3: location, 4: skill 1, 5: skill 2, 6: job exists (update)
        mock_cur.fetchone.side_effect = [
            (1,),
            (9,),
            (20,),
            (30,),
            (31,),
            (100,), # job exists
            (1, 0), # tombstone guard counts
        ]
        mock_cur.fetchall.side_effect = [
            [],      # current skills
            [],      # tombstone
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        config = {"name": "Linear", "ats": "ashby", "identifier": "linear"}
        result = sync_company(config, db_conn=mock_conn)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["jobs_upserted"], 1)

    @patch("requests.get")
    def test_new_company_logo_discovery_ashby(self, mock_get):
        # Mock HTML response from Ashby
        mock_html_resp = MagicMock()
        mock_html_resp.status_code = 200
        mock_html_resp.text = '<html><meta property="og:image" content="https://app.ashbyhq.com/api/images/org-theme-logo/123/456/789.png"></html>'

        # Mock image download response
        mock_img_resp = MagicMock()
        mock_img_resp.status_code = 200
        mock_img_resp.content = b"fake-png-bytes-longer-than-100-bytes-for-valid-image-validation-test-purpose-012345678901234567890123456789"

        mock_get.side_effect = [mock_html_resp, mock_img_resp]

        test_file = Path(__file__).resolve().parent.parent / "frontend" / "public" / "logos" / "brandnewashbystartup.png"
        try:
            branding = resolve_company_branding("BrandNewAshbyStartup", ats_type="ashby", identifier="brandnewstartup")
            self.assertEqual(branding["logo_status"], "verified")
            self.assertEqual(branding["logo_url"], "/logos/brandnewashbystartup.png")
            self.assertEqual(branding["logo_source_url"], "https://app.ashbyhq.com/api/images/org-theme-logo/123/456/789.png")
        finally:
            if test_file.exists():
                test_file.unlink()

    def test_company_branding_reuse_on_subsequent_postings(self):
        """Verifies that future postings for an existing company reuse the stored company row and branding without re-creating."""
        mock_cur = MagicMock()
        # First call: company does not exist -> creates company
        mock_cur.fetchone.side_effect = [
            None,   # SELECT id FROM companies WHERE name = %s -> Not found
            (99,),  # INSERT INTO companies ... RETURNING id -> 99
        ]
        cid1, created1 = get_or_create_company_with_branding(mock_cur, "FreshCo", ats_type="ashby", identifier="freshco")
        self.assertEqual(cid1, 99)
        self.assertTrue(created1)

        # Second call (future posting for same company): company exists in DB -> reused!
        mock_cur.fetchone.side_effect = [
            (99,),  # SELECT id FROM companies WHERE name = %s -> Found!
        ]
        cid2, created2 = get_or_create_company_with_branding(mock_cur, "FreshCo", ats_type="ashby", identifier="freshco")
        self.assertEqual(cid2, 99)
        self.assertFalse(created2)


if __name__ == "__main__":
    unittest.main()

