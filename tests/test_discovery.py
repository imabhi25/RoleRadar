"""
Unit and integration tests for RoleRadar ATS Discovery System.
All network requests are mocked; no live internet calls are made.
"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from ingestion.cli import main as cli_main
from ingestion.discovery import (
    DiscoveryReport,
    DiscoveryResult,
    DiscoveryStatus,
    build_target_index,
    detect_unsupported_ats,
    discover_company_ats,
    export_new_candidates,
    extract_ats_candidates_from_html,
    is_existing_target,
    is_valid_token,
    load_company_watchlist,
    normalize_ats_identity,
    parse_ats_url,
    run_discovery,
    select_primary_candidate,
)
from ingestion.http_client import IngestionFetchError


class TestAtsUrlParsing(unittest.TestCase):
    """Tests for parse_ats_url across all supported ATS patterns and edge cases."""

    def test_greenhouse_standard_url_detection(self):
        cases = [
            ("https://boards.greenhouse.io/figma", ("greenhouse", "figma")),
            ("https://boards.greenhouse.io/figma/", ("greenhouse", "figma")),
            ("https://boards.greenhouse.io/figma/jobs", ("greenhouse", "figma")),
            ("https://boards.greenhouse.io/figma/jobs/123456", ("greenhouse", "figma")),
            ("http://boards.greenhouse.io/stripe?gh_jid=999", ("greenhouse", "stripe")),
            ("//boards.greenhouse.io/scaleai", ("greenhouse", "scaleai")),
            ("https://boards.eu.greenhouse.io/gitlab", ("greenhouse", "gitlab")),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(parse_ats_url(url), expected)

    def test_greenhouse_embed_and_query_param_detection(self):
        cases = [
            ("https://boards.greenhouse.io/embed/job_board?for=stripe", ("greenhouse", "stripe")),
            ("https://boards.greenhouse.io/embed/job_board/js?for=stripe", ("greenhouse", "stripe")),
            ("https://boards.greenhouse.io/embed/job_board?for=stripe&b=https%3A%2F%2Fstripe.com", ("greenhouse", "stripe")),
            ("https://boards.greenhouse.io/embed/job_app?token=reddit", ("greenhouse", "reddit")),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(parse_ats_url(url), expected)

    def test_greenhouse_new_job_board_domain_detection(self):
        """Specifically verifies job-boards.greenhouse.io support."""
        cases = [
            ("https://job-boards.greenhouse.io/datadog", ("greenhouse", "datadog")),
            ("https://job-boards.greenhouse.io/datadog/", ("greenhouse", "datadog")),
            ("https://job-boards.greenhouse.io/datadog/jobs", ("greenhouse", "datadog")),
            ("https://job-boards.greenhouse.io/datadog/jobs/12345", ("greenhouse", "datadog")),
            ("https://job-boards.eu.greenhouse.io/datadog", ("greenhouse", "datadog")),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(parse_ats_url(url), expected)

    def test_lever_url_detection(self):
        cases = [
            ("https://jobs.lever.co/spotify", ("lever", "spotify")),
            ("https://jobs.lever.co/spotify/", ("lever", "spotify")),
            ("https://jobs.lever.co/spotify/abc-123", ("lever", "spotify")),
            ("https://jobs.lever.co/spotify/abc-123/apply", ("lever", "spotify")),
            ("https://jobs.lever.co/palantir?lever-source=Direct", ("lever", "palantir")),
            ("//jobs.lever.co/waabi", ("lever", "waabi")),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(parse_ats_url(url), expected)

    def test_ashby_url_detection(self):
        cases = [
            ("https://jobs.ashbyhq.com/linear", ("ashby", "linear")),
            ("https://jobs.ashbyhq.com/linear/", ("ashby", "linear")),
            ("https://jobs.ashbyhq.com/linear/e404-58a", ("ashby", "linear")),
            ("https://jobs.ashbyhq.com/openai/application", ("ashby", "openai")),
            ("https://jobs.ashbyhq.com/ramp?ashby_jid=123", ("ashby", "ramp")),
            ("//jobs.ashbyhq.com/supabase", ("ashby", "supabase")),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(parse_ats_url(url), expected)

    def test_malformed_and_invalid_urls(self):
        invalid_cases = [
            "",
            None,
            "not_a_valid_url",
            "https://example.com/careers",
            "https://boards.greenhouse.io",
            "https://boards.greenhouse.io/",
            "https://boards.greenhouse.io/embed",
            "https://boards.greenhouse.io/embed/job_board",
            "https://jobs.lever.co",
            "https://jobs.lever.co/",
            "https://jobs.ashbyhq.com",
            "https://jobs.ashbyhq.com/",
            "https://boards.greenhouse.io/privacy",
            "https://boards.greenhouse.io/terms",
            "https://jobs.lever.co/search",
            "https://jobs.ashbyhq.com/api",
            "https://jobs.lever.co/123456",  # Purely numeric token
        ]
        for item in invalid_cases:
            with self.subTest(item=item):
                self.assertIsNone(parse_ats_url(item))

    def test_token_validation_helper(self):
        self.assertTrue(is_valid_token("figma"))
        self.assertTrue(is_valid_token("datadog"))
        self.assertTrue(is_valid_token("1password"))
        self.assertTrue(is_valid_token("scale-ai"))
        self.assertTrue(is_valid_token("point_click_care"))

        self.assertFalse(is_valid_token(""))
        self.assertFalse(is_valid_token(None))
        self.assertFalse(is_valid_token("a"))  # too short
        self.assertFalse(is_valid_token("embed"))  # reserved
        self.assertFalse(is_valid_token("search"))  # reserved
        self.assertFalse(is_valid_token("users"))  # reserved
        self.assertFalse(is_valid_token("v1"))  # version prefix
        self.assertFalse(is_valid_token("v2"))  # version prefix
        self.assertFalse(is_valid_token("99999"))  # pure digits
        self.assertFalse(is_valid_token("bundle.js"))  # file extension
        self.assertFalse(is_valid_token("data.json"))  # file extension
        self.assertFalse(is_valid_token("page.html"))  # file extension
        self.assertFalse(is_valid_token("foo/bar"))  # slash

    def test_regression_token_validation_artifacts_rejected(self):
        """
        Regression tests proving:
        - Greenhouse /users/... does NOT yield token users
        - Greenhouse /v1/... does NOT yield token v1
        - script/API URLs containing /api/v1/ do not generate candidates
        - valid boards.greenhouse.io/sourcegraph91 still works
        - valid job-boards.greenhouse.io/figma still works
        - Lever and Ashby behavior remains unchanged
        """
        # 1. Greenhouse /users/... does NOT yield token users
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/users/sign_in"))
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/users"))
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/embed/job_board?for=users"))
        self.assertIsNone(parse_ats_url("https://job-boards.greenhouse.io/users"))

        # 2. Greenhouse /v1/... does NOT yield token v1
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/v1/jobs"))
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/v1/boards/v1/jobs"))
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/embed/job_board?for=v1"))
        self.assertIsNone(parse_ats_url("https://job-boards.greenhouse.io/v1"))

        # 3. script/API URLs containing /api/v1/ do not generate candidates
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/api/v1/jobs"))
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/api/v1/boards"))
        self.assertIsNone(parse_ats_url("https://boards.greenhouse.io/embed/job_board/js"))

        # 4. Valid boards.greenhouse.io/sourcegraph91 still works
        self.assertEqual(
            parse_ats_url("https://boards.greenhouse.io/sourcegraph91"),
            ("greenhouse", "sourcegraph91"),
        )
        self.assertEqual(
            parse_ats_url("https://boards.greenhouse.io/sourcegraph91/jobs/12345"),
            ("greenhouse", "sourcegraph91"),
        )

        # 5. Valid job-boards.greenhouse.io/figma still works
        self.assertEqual(
            parse_ats_url("https://job-boards.greenhouse.io/figma"),
            ("greenhouse", "figma"),
        )
        self.assertEqual(
            parse_ats_url("https://job-boards.greenhouse.io/figma/jobs"),
            ("greenhouse", "figma"),
        )

        # 6. Lever and Ashby behavior remains unchanged
        self.assertEqual(
            parse_ats_url("https://jobs.lever.co/spotify"),
            ("lever", "spotify"),
        )
        self.assertEqual(
            parse_ats_url("https://jobs.ashbyhq.com/linear"),
            ("ashby", "linear"),
        )
        self.assertEqual(
            parse_ats_url("https://jobs.ashbyhq.com/mistral.ai"),
            ("ashby", "mistral.ai"),
        )
        self.assertEqual(
            parse_ats_url("https://jobs.ashbyhq.com/runway-ml"),
            ("ashby", "runway-ml"),
        )
        self.assertIsNone(parse_ats_url("https://jobs.lever.co/users"))
        self.assertIsNone(parse_ats_url("https://jobs.ashbyhq.com/v1"))
        self.assertIsNone(parse_ats_url("https://jobs.lever.co/bundle.js"))
        self.assertIsNone(parse_ats_url("https://jobs.ashbyhq.com/widget.json"))


class TestHtmlCandidateExtraction(unittest.TestCase):
    """Tests for parsing HTML content, DOM elements, and script tags."""

    def test_extract_candidates_from_links_and_iframes(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Careers</title></head>
        <body>
            <h1>Join Us</h1>
            <a href="https://boards.greenhouse.io/stripe/jobs/1">Software Engineer</a>
            <iframe src="https://boards.greenhouse.io/embed/job_board?for=stripe"></iframe>
            <a href="https://twitter.com/stripe">Twitter</a>
        </body>
        </html>
        """
        candidates = extract_ats_candidates_from_html(html)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0], ("greenhouse", "stripe"))
        self.assertEqual(candidates[1], ("greenhouse", "stripe"))

    def test_extract_from_data_attributes_and_scripts(self):
        html = """
        <div>
            <div data-board-url="https://jobs.lever.co/spotify"></div>
            <script>
                var board = "https://jobs.ashbyhq.com/linear";
            </script>
        </div>
        """
        candidates = extract_ats_candidates_from_html(html)
        self.assertIn(("lever", "spotify"), candidates)
        self.assertIn(("ashby", "linear"), candidates)

    def test_multiple_ats_links_prefers_dominant_frequency(self):
        # 3 Ashby links vs 1 legacy Greenhouse link
        html = """
        <html>
            <body>
                <a href="https://jobs.ashbyhq.com/linear/job1">Role 1</a>
                <a href="https://jobs.ashbyhq.com/linear/job2">Role 2</a>
                <a href="https://jobs.ashbyhq.com/linear/job3">Role 3</a>
                <a href="https://boards.greenhouse.io/legacylinear">Old</a>
            </body>
        </html>
        """
        candidates = extract_ats_candidates_from_html(html)
        best = select_primary_candidate(candidates)
        self.assertEqual(best, ("ashby", "linear"))

    def test_detect_unsupported_systems(self):
        self.assertEqual(detect_unsupported_ats("Apply on https://myco.myworkdayjobs.com/careers"), "Workday")
        self.assertEqual(detect_unsupported_ats("Powered by Taleo.net portal"), "Taleo")
        self.assertEqual(detect_unsupported_ats("Hosted on icims.com/jobs"), "iCIMS")
        self.assertIsNone(detect_unsupported_ats("Custom in-house career page with no known signatures"))



class TestTargetIdentityMatching(unittest.TestCase):
    """Tests proving strict (provider, token) identity matching for FOUND_EXISTING vs FOUND_NEW."""

    def setUp(self):
        self.target_companies = [
            {"name": "Duolingo", "ats": "greenhouse", "identifier": "duolingo"},
            {"name": "Waabi", "ats": "lever", "identifier": "waabi"},
            {"name": "Linear", "ats": "ashby", "identifier": "linear"},
        ]
        self.target_index = build_target_index(self.target_companies)

    def test_exact_provider_and_token_matches_found_existing(self):
        """Exact provider + token matches FOUND_EXISTING."""
        self.assertTrue(is_existing_target("greenhouse", "duolingo", self.target_index))
        self.assertTrue(is_existing_target("lever", "waabi", self.target_index))
        self.assertTrue(is_existing_target("ashby", "linear", self.target_index))

    def test_same_company_different_or_invalid_token_is_not_found_existing(self):
        """Same company name but different or invalid token is NOT FOUND_EXISTING."""
        self.assertFalse(is_existing_target("greenhouse", "v1", self.target_index))
        self.assertFalse(is_existing_target("greenhouse", "other-token", self.target_index))
        self.assertFalse(is_existing_target("lever", "other-waabi", self.target_index))

    def test_same_token_different_provider_is_not_found_existing(self):
        """Same token but different provider is NOT FOUND_EXISTING."""
        self.assertFalse(is_existing_target("ashby", "duolingo", self.target_index))
        self.assertFalse(is_existing_target("lever", "duolingo", self.target_index))
        self.assertFalse(is_existing_target("greenhouse", "waabi", self.target_index))

    def test_company_name_difference_with_same_provider_token_recognizes_existing(self):
        """Company-name difference with same provider/token still recognizes existing ATS identity."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://boards.greenhouse.io/duolingo"
        mock_resp.text = ""
        mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="Duolingo International Inc.",
            careers_url="https://duolingo.com/careers",
            client=mock_client,
            target_index=self.target_index,
        )
        self.assertEqual(result.status, DiscoveryStatus.FOUND_EXISTING)
        self.assertEqual(result.provider, "greenhouse")
        self.assertEqual(result.token, "duolingo")

    def test_duolingo_greenhouse_duolingo_is_found_existing(self):
        """Duolingo (greenhouse, duolingo) is FOUND_EXISTING."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://boards.greenhouse.io/duolingo"
        mock_resp.text = ""
        mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="Duolingo",
            careers_url="https://careers.duolingo.com",
            client=mock_client,
            target_index=self.target_index,
        )
        self.assertEqual(result.status, DiscoveryStatus.FOUND_EXISTING)
        self.assertEqual(result.provider, "greenhouse")
        self.assertEqual(result.token, "duolingo")

    def test_duolingo_greenhouse_v1_can_never_be_found_existing(self):
        """Duolingo (greenhouse, v1) can NEVER be FOUND_EXISTING."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://careers.duolingo.com"
        mock_resp.text = '<a href="https://boards.greenhouse.io/v1/jobs">Jobs</a>'
        mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="Duolingo",
            careers_url="https://careers.duolingo.com",
            client=mock_client,
            target_index=self.target_index,
        )
        self.assertNotEqual(result.status, DiscoveryStatus.FOUND_EXISTING)
        self.assertFalse(is_existing_target("greenhouse", "v1", self.target_index))

    def test_waabi_lever_waabi_is_found_existing(self):
        """Waabi (lever, waabi) is FOUND_EXISTING."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://jobs.lever.co/waabi"
        mock_resp.text = ""
        mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="Waabi",
            careers_url="https://waabi.ai/careers",
            client=mock_client,
            target_index=self.target_index,
        )
        self.assertEqual(result.status, DiscoveryStatus.FOUND_EXISTING)
        self.assertEqual(result.provider, "lever")
        self.assertEqual(result.token, "waabi")

    def test_ashby_duolingo_is_found_new(self):
        """Discovered (ashby, duolingo) when duolingo is greenhouse is FOUND_NEW, not FOUND_EXISTING."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://jobs.ashbyhq.com/duolingo"
        mock_resp.text = ""
        mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="Duolingo",
            careers_url="https://careers.duolingo.com",
            client=mock_client,
            target_index=self.target_index,
        )
        self.assertEqual(result.status, DiscoveryStatus.FOUND_NEW)
        self.assertEqual(result.provider, "ashby")
        self.assertEqual(result.token, "duolingo")

    def test_case_insensitivity_and_whitespace_in_identity_matching(self):
        """Ensures whitespace and case differences in tokens and providers are normalized."""
        self.assertTrue(is_existing_target(" Greenhouse ", " DUOLINGO ", self.target_index))
        self.assertTrue(is_existing_target("LEVER", "  waabi  ", self.target_index))
        norm_prov, norm_tok = normalize_ats_identity("  GreenHouse  ", "  DuoLingo  ")
        self.assertEqual(norm_prov, "greenhouse")
        self.assertEqual(norm_tok, "duolingo")


class TestCompanyDiscovery(unittest.TestCase):
    """Tests for discover_company_ats with mocked HTTP responses."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.target_index = build_target_index([
            {"name": "Stripe", "ats": "greenhouse", "identifier": "stripe"},
            {"name": "Spotify", "ats": "lever", "identifier": "spotify"},
        ])

    def test_direct_redirect_to_ats(self):
        """Verify redirect to a supported ATS is detected immediately via response.url."""
        mock_resp = MagicMock()
        mock_resp.url = "https://boards.greenhouse.io/stripe"
        mock_resp.text = "<html><body>Redirected</body></html>"
        self.mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="Stripe",
            careers_url="https://stripe.com/careers",
            client=self.mock_client,
            target_index=self.target_index,
        )

        self.assertEqual(result.status, DiscoveryStatus.FOUND_EXISTING)
        self.assertEqual(result.provider, "greenhouse")
        self.assertEqual(result.token, "stripe")

    def test_redirect_to_page_containing_ats(self):
        """Verify redirect to an internal page that embeds an ATS link."""
        mock_resp = MagicMock()
        mock_resp.url = "https://spotify.com/en/jobs"
        mock_resp.text = '<a href="https://jobs.lever.co/spotify">Open Roles</a>'
        self.mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="Spotify",
            careers_url="https://lifeatspotify.com/jobs",
            client=self.mock_client,
            target_index=self.target_index,
        )

        self.assertEqual(result.status, DiscoveryStatus.FOUND_EXISTING)
        self.assertEqual(result.provider, "lever")
        self.assertEqual(result.token, "spotify")

    def test_new_candidate_discovery(self):
        """Verify supported ATS not in target_index is classified as FOUND_NEW."""
        mock_resp = MagicMock()
        mock_resp.url = "https://linear.app/careers"
        mock_resp.text = '<a href="https://jobs.ashbyhq.com/linear">Linear Jobs</a>'
        self.mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="Linear",
            careers_url="https://linear.app/careers",
            client=self.mock_client,
            target_index=self.target_index,  # Linear is not in self.target_index
        )

        self.assertEqual(result.status, DiscoveryStatus.FOUND_NEW)
        self.assertEqual(result.provider, "ashby")
        self.assertEqual(result.token, "linear")

    def test_unsupported_careers_page(self):
        """Verify page with no supported ATS is marked UNSUPPORTED with diagnostic info."""
        mock_resp = MagicMock()
        mock_resp.url = "https://workday-client.com/careers"
        mock_resp.text = '<a href="https://company.myworkdayjobs.com/en-US/careers">Jobs</a>'
        self.mock_client.get.return_value = mock_resp

        result = discover_company_ats(
            company="WorkdayCo",
            careers_url="https://workday-client.com/careers",
            client=self.mock_client,
            target_index=self.target_index,
        )

        self.assertEqual(result.status, DiscoveryStatus.UNSUPPORTED)
        self.assertIn("Workday", result.details)

    def test_http_404_failure(self):
        self.mock_client.get.side_effect = IngestionFetchError("HTTP 404 error from https://example.com/careers: Not Found")

        result = discover_company_ats(
            company="BrokenLink",
            careers_url="https://example.com/careers",
            client=self.mock_client,
            target_index=self.target_index,
        )

        self.assertEqual(result.status, DiscoveryStatus.FAILED)
        self.assertEqual(result.details, "HTTP 404")

    def test_http_403_failure(self):
        self.mock_client.get.side_effect = IngestionFetchError("HTTP 403 error from https://example.com/careers: Forbidden")

        result = discover_company_ats(
            company="BlockedLink",
            careers_url="https://example.com/careers",
            client=self.mock_client,
            target_index=self.target_index,
        )

        self.assertEqual(result.status, DiscoveryStatus.FAILED)
        self.assertEqual(result.details, "HTTP 403")

    def test_connection_timeout_failure(self):
        self.mock_client.get.side_effect = IngestionFetchError("Network error fetching https://example.com: Connection timed out")

        result = discover_company_ats(
            company="TimeoutCo",
            careers_url="https://example.com/careers",
            client=self.mock_client,
            target_index=self.target_index,
        )

        self.assertEqual(result.status, DiscoveryStatus.FAILED)
        self.assertEqual(result.details, "Connection timeout")

    def test_invalid_url_scheme_failure(self):
        result = discover_company_ats(
            company="BadScheme",
            careers_url="ftp://example.com/careers",
            client=self.mock_client,
            target_index=self.target_index,
        )
        self.assertEqual(result.status, DiscoveryStatus.FAILED)
        self.assertEqual(result.details, "Invalid URL scheme")


class TestDiscoveryPipelineAndExport(unittest.TestCase):
    """Tests for run_discovery, watchlist filtering, target comparisons, and candidate exporting."""

    def test_disabled_watchlist_entries_ignored(self):
        mock_watchlist = [
            {"company": "ActiveCo", "careers_url": "https://active.com/careers", "enabled": True},
            {"company": "DisabledCo", "careers_url": "https://disabled.com/careers", "enabled": False},
        ]
        mock_targets = []

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.url = "https://active.com/careers"
        mock_resp.text = '<a href="https://jobs.lever.co/activeco">Jobs</a>'
        mock_client.get.return_value = mock_resp

        report = run_discovery(
            watchlist=mock_watchlist,
            target_companies=mock_targets,
            client=mock_client,
        )

        self.assertEqual(report.companies_checked, 1)
        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0].company, "ActiveCo")
        self.assertEqual(report.results[0].status, DiscoveryStatus.FOUND_NEW)
        mock_client.get.assert_called_once_with("https://active.com/careers", timeout=(5.0, 15.0))

    def test_run_discovery_summary_counts(self):
        mock_watchlist = [
            {"company": "Stripe", "careers_url": "https://stripe.com/careers", "enabled": True},
            {"company": "NewCo", "careers_url": "https://newco.com/careers", "enabled": True},
            {"company": "Shopify", "careers_url": "https://shopify.com/careers", "enabled": True},
            {"company": "BrokenCo", "careers_url": "https://broken.com/careers", "enabled": True},
        ]
        mock_targets = [
            {"name": "Stripe", "ats": "greenhouse", "identifier": "stripe"}
        ]

        mock_client = MagicMock()

        def side_effect(url, **kwargs):
            if "stripe" in url:
                r = MagicMock()
                r.url = "https://boards.greenhouse.io/stripe"
                r.text = ""
                return r
            elif "newco" in url:
                r = MagicMock()
                r.url = "https://newco.com/careers"
                r.text = '<a href="https://jobs.ashbyhq.com/newco">Jobs</a>'
                return r
            elif "shopify" in url:
                r = MagicMock()
                r.url = "https://shopify.com/careers"
                r.text = '<h1>Custom careers</h1>'
                return r
            else:
                raise IngestionFetchError("HTTP 404 error: Not Found")

        mock_client.get.side_effect = side_effect

        progress_calls = []
        report = run_discovery(
            watchlist=mock_watchlist,
            target_companies=mock_targets,
            client=mock_client,
            on_progress=lambda r: progress_calls.append(r),
        )

        self.assertEqual(len(progress_calls), 4)
        self.assertEqual(report.companies_checked, 4)
        self.assertEqual(report.supported_ats_found, 2)
        self.assertEqual(report.already_configured, 1)
        self.assertEqual(report.new_candidates, 1)
        self.assertEqual(report.unsupported, 1)
        self.assertEqual(report.failed, 1)

    def test_export_new_candidates_writes_only_new(self):
        report = DiscoveryReport(
            results=[
                DiscoveryResult(
                    company="ExistingCo",
                    careers_url="https://exist.com/careers",
                    status=DiscoveryStatus.FOUND_EXISTING,
                    provider="greenhouse",
                    token="existingco",
                ),
                DiscoveryResult(
                    company="NewCandidate",
                    careers_url="https://new.com/careers",
                    status=DiscoveryStatus.FOUND_NEW,
                    provider="ashby",
                    token="newcandidate",
                    priority_countries=["United States", "Canada"],
                ),
                DiscoveryResult(
                    company="UnsupportedCo",
                    careers_url="https://unsup.com/careers",
                    status=DiscoveryStatus.UNSUPPORTED,
                ),
            ],
            companies_checked=3,
            supported_ats_found=2,
            already_configured=1,
            new_candidates=1,
            unsupported=1,
            failed=0,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = Path(tmp_dir) / "discovered_sources.json"
            exported_count = export_new_candidates(report, out_file)

            self.assertEqual(exported_count, 1)
            self.assertTrue(out_file.exists())

            with open(out_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["company"], "NewCandidate")
            self.assertEqual(data[0]["ats"], "ashby")
            self.assertEqual(data[0]["identifier"], "newcandidate")
            self.assertEqual(data[0]["priority_countries"], ["United States", "Canada"])


class TestCliIntegration(unittest.TestCase):
    """Verifies CLI flag integration for --discover-sources and --output."""

    @patch("ingestion.cli.run_discovery")
    def test_cli_discover_sources_basic(self, mock_run):
        mock_run.return_value = DiscoveryReport(
            results=[
                DiscoveryResult(
                    company="Figma",
                    careers_url="https://figma.com/careers",
                    status=DiscoveryStatus.FOUND_EXISTING,
                    provider="greenhouse",
                    token="figma",
                )
            ],
            companies_checked=1,
            supported_ats_found=1,
            already_configured=1,
            new_candidates=0,
            unsupported=0,
            failed=0,
        )

        exit_code = cli_main(["--discover-sources"])
        self.assertEqual(exit_code, 0)
        mock_run.assert_called_once()

    @patch("ingestion.cli.export_new_candidates")
    @patch("ingestion.cli.run_discovery")
    def test_cli_discover_sources_with_output(self, mock_run, mock_export):
        mock_run.return_value = DiscoveryReport(
            results=[],
            companies_checked=0,
            supported_ats_found=0,
            already_configured=0,
            new_candidates=0,
            unsupported=0,
            failed=0,
        )
        mock_export.return_value = 0

        exit_code = cli_main(["--discover-sources", "--output", "candidates.json"])
        self.assertEqual(exit_code, 0)
        mock_export.assert_called_once()


if __name__ == "__main__":
    unittest.main()
