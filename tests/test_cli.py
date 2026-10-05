"""
Unit tests for RoleRadar CLI runner and arguments parsing.
Uses mocks; zero database writes and zero network requests.
"""

import unittest
from unittest.mock import MagicMock, patch

from ingestion.cli import main


class TestIngestionCLI(unittest.TestCase):
    @patch("ingestion.cli.sync_company")
    def test_cli_company_selection(self, mock_sync):
        mock_sync.return_value = {
            "company": "Figma",
            "ats": "greenhouse",
            "status": "success",
            "jobs_fetched": 10,
            "swe_jobs_accepted": 5,
            "jobs_upserted": 5,
            "jobs_deactivated": 0,
        }

        exit_code = main(["--company", "figma"])
        self.assertEqual(exit_code, 0)
        mock_sync.assert_called_once()
        target_called = mock_sync.call_args[0][0]
        self.assertEqual(target_called["name"], "Figma")

    @patch("ingestion.cli.sync_company")
    def test_cli_dry_run_flag(self, mock_sync):
        mock_sync.return_value = {
            "company": "Linear",
            "ats": "ashby",
            "status": "dry_run",
            "jobs_fetched": 15,
            "swe_jobs_accepted": 8,
        }

        exit_code = main(["--company", "linear", "--dry-run"])
        self.assertEqual(exit_code, 0)
        mock_sync.assert_called_once()
        self.assertTrue(mock_sync.call_args[1].get("dry_run"))

    @patch("ingestion.cli.sync_company")
    def test_cli_all_continues_after_company_failure(self, mock_sync):
        # First company fails, second succeeds, etc.
        def mock_side_effect(target, dry_run=False):
            if target["name"] == "Figma":
                return {
                    "company": "Figma",
                    "ats": "greenhouse",
                    "status": "failed",
                    "error_message": "Transient HTTP 500",
                }
            return {
                "company": target["name"],
                "ats": target["ats"],
                "status": "success",
                "jobs_fetched": 10,
                "swe_jobs_accepted": 5,
                "jobs_upserted": 5,
                "jobs_deactivated": 0,
            }

        mock_sync.side_effect = mock_side_effect

        exit_code = main(["--all"])
        # Should return non-zero exit code because Figma failed
        self.assertEqual(exit_code, 1)
        # But all companies should have been processed
        self.assertGreater(mock_sync.call_count, 1)

    def test_cli_unknown_company_exits_with_error(self):
        exit_code = main(["--company", "NonExistentCompanyXYZ"])
        self.assertEqual(exit_code, 1)

    @patch("ingestion.cli.sync_broad_source")
    def test_cli_source_jobicy(self, mock_sync_broad):
        mock_sync_broad.return_value = {
            "company": "Jobicy Feed",
            "ats": "jobicy",
            "status": "success",
            "jobs_fetched": 50,
            "swe_jobs_accepted": 25,
            "jobs_upserted": 25,
            "jobs_deactivated": 0,
        }

        exit_code = main(["--source", "jobicy"])
        self.assertEqual(exit_code, 0)
        mock_sync_broad.assert_called_once_with(source_name="jobicy", dry_run=False, max_pages=None)

    @patch("ingestion.cli.sync_broad_source")
    def test_cli_source_jobicy_dry_run(self, mock_sync_broad):
        mock_sync_broad.return_value = {
            "company": "Jobicy Feed",
            "ats": "jobicy",
            "status": "dry_run",
            "jobs_fetched": 50,
            "swe_jobs_accepted": 25,
            "jobs_upserted": 0,
            "jobs_deactivated": 0,
            "role_type_counts": {"full_time": 20, "internship": 5},
            "workplace_counts": {"remote": 25},
            "country_counts": {"United States": 15, "Canada": 10},
            "oldest_posted_at": "2026-09-01T00:00:00+00:00",
            "newest_posted_at": "2026-09-25T14:00:00+00:00",
            "stale_rejected_count": 2,
            "sample_jobs": [
                {
                    "company": "Supabase",
                    "title": "Backend Engineer",
                    "role_type": "full_time",
                    "workplace": "remote",
                    "posted_at": "2026-09-25T14:00:00+00:00",
                }
            ],
        }

        exit_code = main(["--source", "jobicy", "--dry-run"])
        self.assertEqual(exit_code, 0)
        mock_sync_broad.assert_called_once_with(source_name="jobicy", dry_run=True, max_pages=None)

    @patch("ingestion.cli.sync_broad_source")
    def test_cli_source_remotive(self, mock_sync_broad):
        mock_sync_broad.return_value = {
            "company": "Remotive Feed",
            "ats": "remotive",
            "status": "success",
            "jobs_fetched": 40,
            "swe_jobs_accepted": 30,
            "jobs_upserted": 30,
            "jobs_deactivated": 0,
        }

        exit_code = main(["--source", "remotive"])
        self.assertEqual(exit_code, 0)
        mock_sync_broad.assert_called_once_with(source_name="remotive", dry_run=False, max_pages=None)

    @patch("ingestion.cli.sync_broad_source")
    def test_cli_source_arbeitnow_with_max_pages(self, mock_sync_broad):
        mock_sync_broad.return_value = {
            "company": "Arbeitnow Feed",
            "ats": "arbeitnow",
            "status": "success",
            "jobs_fetched": 100,
            "swe_jobs_accepted": 60,
            "jobs_upserted": 60,
            "jobs_deactivated": 0,
        }

        exit_code = main(["--source", "arbeitnow", "--max-pages", "3"])
        self.assertEqual(exit_code, 0)
        mock_sync_broad.assert_called_once_with(source_name="arbeitnow", dry_run=False, max_pages=3)

    def test_cli_unsupported_source_exits_with_error(self):
        exit_code = main(["--source", "unsupported_aggregator"])
        self.assertEqual(exit_code, 1)

    @patch("ingestion.cli.sync_broad_source")
    def test_cli_source_failure_exits_with_error(self, mock_sync_broad):
        mock_sync_broad.return_value = {
            "company": "Jobicy Feed",
            "ats": "jobicy",
            "status": "failed",
            "error_message": "Network error",
        }

        exit_code = main(["--source", "jobicy"])
        self.assertEqual(exit_code, 1)


class TestTargetCompaniesRegistry(unittest.TestCase):
    """
    Tests for config/target_companies.json integrity:
    uniqueness, valid ATS providers, no duplicate board identifiers,
    preservation of existing targets, and CLI lookup fidelity.
    """

    def setUp(self):
        from ingestion.cli import load_target_companies
        self.targets = load_target_companies()

    def test_registry_has_expanded_target_count(self):
        # We expect 11 original + 26 newly verified targets = 37 targets
        self.assertGreaterEqual(len(self.targets), 35)

    def test_target_registry_uniqueness_of_names(self):
        names = [t["name"].strip().lower() for t in self.targets]
        self.assertEqual(
            len(names),
            len(set(names)),
            f"Duplicate company names found in target registry: {[n for n in names if names.count(n) > 1]}",
        )

    def test_target_registry_valid_ats_names(self):
        valid_ats = {"greenhouse", "lever", "ashby", "workday", "amazon", "google", "shopify", "phenom", "successfactors"}
        for target in self.targets:
            ats = target.get("ats")
            self.assertIn(
                ats,
                valid_ats,
                f"Company '{target.get('name')}' specifies invalid ATS '{ats}'. Must be one of {valid_ats}",
            )

    def test_target_registry_no_duplicate_board_identifiers_within_ats(self):
        boards = [(t["ats"].strip().lower(), t["identifier"].strip().lower()) for t in self.targets]
        self.assertEqual(
            len(boards),
            len(set(boards)),
            f"Duplicate board identifier within same ATS found: {[b for b in boards if boards.count(b) > 1]}",
        )

    def test_existing_targets_preserved(self):
        expected_existing = {
            "Figma": ("greenhouse", "figma"),
            "Cloudflare": ("greenhouse", "cloudflare"),
            "Datadog": ("greenhouse", "datadog"),
            "GitLab": ("greenhouse", "gitlab"),
            "Spotify": ("lever", "spotify"),
            "Palantir": ("lever", "palantir"),
            "Neon": ("lever", "neon"),
            "Metabase": ("lever", "metabase"),
            "Linear": ("ashby", "linear"),
            "Ramp": ("ashby", "ramp"),
            "Supabase": ("ashby", "supabase"),
        }

        registry_map = {t["name"]: (t["ats"], t["identifier"]) for t in self.targets}

        for comp_name, expected_tuple in expected_existing.items():
            self.assertIn(comp_name, registry_map, f"Existing target '{comp_name}' missing from registry!")
            self.assertEqual(
                registry_map[comp_name],
                expected_tuple,
                f"Existing target '{comp_name}' configuration changed! Expected {expected_tuple}, got {registry_map[comp_name]}",
            )

    def test_new_target_lookup_works_via_name_and_slug(self):
        registry_map_lower = {t["name"].lower(): t for t in self.targets}
        slug_map_lower = {t["identifier"].lower(): t for t in self.targets}

        new_targets_sample = [
            ("Anthropic", "anthropic", "greenhouse"),
            ("OpenAI", "openai", "ashby"),
            ("Stripe", "stripe", "greenhouse"),
            ("Waabi", "waabi", "lever"),
            ("PointClickCare", "pointclickcare", "lever"),
            ("Cohere", "cohere", "ashby"),
            ("Robinhood", "robinhood", "greenhouse"),
            ("Scale AI", "scaleai", "greenhouse"),
        ]

        for name, slug, ats in new_targets_sample:
            # Lookup by name
            self.assertIn(name.lower(), registry_map_lower)
            self.assertEqual(registry_map_lower[name.lower()]["ats"], ats)
            self.assertEqual(registry_map_lower[name.lower()]["identifier"], slug)

            # Lookup by identifier
            self.assertIn(slug.lower(), slug_map_lower)
            self.assertEqual(slug_map_lower[slug.lower()]["name"], name)

    @patch("ingestion.cli.sync_company")
    def test_cli_company_lookup_for_new_targets(self, mock_sync):
        mock_sync.return_value = {
            "company": "Anthropic",
            "ats": "greenhouse",
            "status": "success",
            "jobs_fetched": 100,
            "swe_jobs_accepted": 50,
            "jobs_upserted": 50,
            "jobs_deactivated": 0,
        }

        # Case-insensitive name lookup
        exit_code = main(["--company", "anthropic"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_sync.call_args[0][0]["name"], "Anthropic")
        self.assertEqual(mock_sync.call_args[0][0]["identifier"], "anthropic")

        # Identifier lookup for Ashby target
        mock_sync.reset_mock()
        mock_sync.return_value = {
            "company": "OpenAI",
            "ats": "ashby",
            "status": "success",
            "jobs_fetched": 100,
            "swe_jobs_accepted": 50,
            "jobs_upserted": 50,
            "jobs_deactivated": 0,
        }
        exit_code = main(["--company", "openai"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_sync.call_args[0][0]["name"], "OpenAI")
        self.assertEqual(mock_sync.call_args[0][0]["identifier"], "openai")

        # Lever target lookup
        mock_sync.reset_mock()
        mock_sync.return_value = {
            "company": "Waabi",
            "ats": "lever",
            "status": "success",
            "jobs_fetched": 20,
            "swe_jobs_accepted": 10,
            "jobs_upserted": 10,
            "jobs_deactivated": 0,
        }
        exit_code = main(["--company", "waabi"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_sync.call_args[0][0]["name"], "Waabi")
        self.assertEqual(mock_sync.call_args[0][0]["identifier"], "waabi")

    @patch("ingestion.cli.sync_company")
    def test_cli_all_iterates_full_registry(self, mock_sync):
        mock_sync.return_value = {
            "company": "Dummy",
            "ats": "greenhouse",
            "status": "success",
            "jobs_fetched": 1,
            "swe_jobs_accepted": 1,
            "jobs_upserted": 1,
            "jobs_deactivated": 0,
        }

        exit_code = main(["--all", "--dry-run"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_sync.call_count, len(self.targets))


if __name__ == "__main__":
    unittest.main()
