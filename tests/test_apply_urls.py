"""
Unit tests for Job Application Multi-Route URL Resolution, Ingestion, and API Delivery.
Tests:
- URL classification and validation
- Strict suppression of Indeed and malformed URLs
- Deduplication against canonical company URLs
- ATS platform preservation without exposing ATS branding/names
- Multi-route priority and fallback logic
- Database persistence and backward compatibility
"""

import unittest
from unittest.mock import MagicMock

from ingestion.base import RawJobPosting
from ingestion.normalizer import (
    canonicalize_apply_url,
    classify_application_urls,
    is_indeed_url,
    is_linkedin_job_url,
    is_simplify_job_url,
    is_valid_http_url,
    resolve_primary_apply_url,
)
from ingestion.pipeline import upsert_job_posting


class TestApplyUrlClassification(unittest.TestCase):
    def test_is_valid_http_url(self):
        # Valid URLs
        self.assertTrue(is_valid_http_url("https://jobs.lever.co/palantir/123"))
        self.assertTrue(is_valid_http_url("http://boards.greenhouse.io/figma/jobs/456"))
        self.assertTrue(is_valid_http_url("https://stripe.com/jobs/search?gh_jid=8172503"))
        self.assertTrue(is_valid_http_url("https://jobs.ashbyhq.com/linear/abc-123"))
        self.assertTrue(is_valid_http_url("https://www.linkedin.com/jobs/view/123456789/"))
        self.assertTrue(is_valid_http_url("https://simplify.jobs/p/senior-swe-stripe"))

        # Invalid URLs
        self.assertFalse(is_valid_http_url(None))
        self.assertFalse(is_valid_http_url(""))
        self.assertFalse(is_valid_http_url("   "))
        self.assertFalse(is_valid_http_url("not-a-url"))
        self.assertFalse(is_valid_http_url("javascript:alert(1)"))
        self.assertFalse(is_valid_http_url("data:text/html;base64,..."))
        self.assertFalse(is_valid_http_url("https://"))
        self.assertFalse(is_valid_http_url("http://localhost"))
        self.assertFalse(is_valid_http_url("https://example with space.com"))

    def test_is_linkedin_job_url(self):
        self.assertTrue(is_linkedin_job_url("https://www.linkedin.com/jobs/view/4123456789/"))
        self.assertTrue(is_linkedin_job_url("https://linkedin.com/jobs/collections/recommended/?currentJobId=4123456789"))
        self.assertTrue(is_linkedin_job_url("https://www.linkedin.com/jobs/search/?currentJobId=987654"))
        
        # Generic company page or feed is NOT a job listing
        self.assertFalse(is_linkedin_job_url("https://www.linkedin.com/company/google/"))
        self.assertFalse(is_linkedin_job_url("https://www.linkedin.com/feed/"))
        self.assertFalse(is_linkedin_job_url("https://www.linkedin.com/in/johndoe/"))
        self.assertFalse(is_linkedin_job_url("https://example.com/linkedin/jobs/view/123"))

    def test_is_simplify_job_url(self):
        self.assertTrue(is_simplify_job_url("https://simplify.jobs/p/4442110c-55fa-4a61-8aa2-d1be86cbba35"))
        self.assertTrue(is_simplify_job_url("https://simplify.jobs/c/Linear/Software-Engineer-Full-Stack"))
        self.assertTrue(is_simplify_job_url("https://simplify.jobs/jobs/12345"))
        
        self.assertFalse(is_simplify_job_url("https://example.com/simplify.jobs/p/123"))
        self.assertFalse(is_simplify_job_url(None))

    def test_is_indeed_url_suppression(self):
        self.assertTrue(is_indeed_url("https://www.indeed.com/viewjob?jk=123456"))
        self.assertTrue(is_indeed_url("https://ca.indeed.com/job/software-engineer"))
        self.assertFalse(is_indeed_url("https://stripe.com/jobs"))
        self.assertFalse(is_indeed_url("https://boards.greenhouse.io/figma"))

    def test_canonicalize_apply_url(self):
        url1 = "https://boards.greenhouse.io/figma/jobs/101?gh_jid=101&utm_source=linkedin#apply"
        url2 = "https://boards.greenhouse.io/figma/jobs/101/?gh_jid=101&utm_medium=cpc"
        # Should both canonicalize to the same base URL while preserving functional param gh_jid
        self.assertEqual(canonicalize_apply_url(url1), canonicalize_apply_url(url2))

    def test_classify_urls_company_only(self):
        res = classify_application_urls(
            source_url="https://jobs.ashbyhq.com/linear/abc-123"
        )
        self.assertEqual(res["company_apply_url"], "https://jobs.ashbyhq.com/linear/abc-123")
        self.assertIsNone(res["linkedin_url"])
        self.assertIsNone(res["simplify_url"])
        self.assertEqual(res["source_url"], "https://jobs.ashbyhq.com/linear/abc-123")

    def test_classify_urls_company_plus_linkedin(self):
        res = classify_application_urls(
            source_url="https://boards.greenhouse.io/figma/jobs/101",
            company_apply_url="https://boards.greenhouse.io/figma/jobs/101",
            linkedin_url="https://www.linkedin.com/jobs/view/4123456789/",
        )
        self.assertEqual(res["company_apply_url"], "https://boards.greenhouse.io/figma/jobs/101")
        self.assertEqual(res["linkedin_url"], "https://www.linkedin.com/jobs/view/4123456789/")
        self.assertIsNone(res["simplify_url"])

    def test_classify_urls_company_plus_simplify(self):
        res = classify_application_urls(
            source_url="https://simplify.jobs/p/linear-engineer",
            company_apply_url="https://jobs.ashbyhq.com/linear/abc-123",
            simplify_url="https://simplify.jobs/p/linear-engineer",
        )
        self.assertEqual(res["company_apply_url"], "https://jobs.ashbyhq.com/linear/abc-123")
        self.assertEqual(res["simplify_url"], "https://simplify.jobs/p/linear-engineer")
        self.assertIsNone(res["linkedin_url"])

    def test_classify_urls_all_three(self):
        res = classify_application_urls(
            source_url="https://stripe.com/jobs/search?gh_jid=8172503",
            company_apply_url="https://stripe.com/jobs/search?gh_jid=8172503",
            linkedin_url="https://www.linkedin.com/jobs/view/99887766/",
            simplify_url="https://simplify.jobs/p/stripe-payment-systems",
        )
        self.assertEqual(res["company_apply_url"], "https://stripe.com/jobs/search?gh_jid=8172503")
        self.assertEqual(res["linkedin_url"], "https://www.linkedin.com/jobs/view/99887766/")
        self.assertEqual(res["simplify_url"], "https://simplify.jobs/p/stripe-payment-systems")

    def test_classify_urls_discovered_through_simplify(self):
        # A job discovered through Simplify feed where source_url is Simplify and external link is company ATS
        res = classify_application_urls(
            source_url="https://simplify.jobs/p/scale-ai-swe",
            company_apply_url="https://jobs.lever.co/scale/scale-001",
        )
        self.assertEqual(res["company_apply_url"], "https://jobs.lever.co/scale/scale-001")
        self.assertEqual(res["simplify_url"], "https://simplify.jobs/p/scale-ai-swe")
        self.assertIsNone(res["linkedin_url"])

    def test_classify_urls_duplicate_suppression(self):
        # If LinkedIn or Simplify URL is identical or resolves to the exact company URL
        res = classify_application_urls(
            source_url="https://jobs.lever.co/palantir/123",
            company_apply_url="https://jobs.lever.co/palantir/123",
            linkedin_url="https://jobs.lever.co/palantir/123?utm_source=linkedin", # Duplicate of company
            simplify_url="https://jobs.lever.co/palantir/123#apply", # Duplicate of company
        )
        self.assertEqual(res["company_apply_url"], "https://jobs.lever.co/palantir/123")
        self.assertIsNone(res["linkedin_url"])
        self.assertIsNone(res["simplify_url"])

    def test_classify_urls_indeed_strictly_excluded(self):
        res = classify_application_urls(
            source_url="https://www.indeed.com/viewjob?jk=abc",
            company_apply_url="https://www.indeed.com/viewjob?jk=abc",
            linkedin_url="https://www.indeed.com/viewjob?jk=abc",
            simplify_url="https://www.indeed.com/viewjob?jk=abc",
        )
        self.assertIsNone(res["company_apply_url"])
        self.assertIsNone(res["linkedin_url"])
        self.assertIsNone(res["simplify_url"])
        self.assertIsNone(res["source_url"])

    def test_resolve_primary_apply_url_priority(self):
        # 1. Company URL takes precedence over LinkedIn and Simplify
        p1 = resolve_primary_apply_url(
            company_apply_url="https://jobs.ashbyhq.com/linear/1",
            source_url="https://simplify.jobs/p/1",
            linkedin_url="https://www.linkedin.com/jobs/view/1",
            simplify_url="https://simplify.jobs/p/1",
        )
        self.assertEqual(p1, "https://jobs.ashbyhq.com/linear/1")

        # 2. If company URL is missing, falls back to official source_url
        p2 = resolve_primary_apply_url(
            company_apply_url=None,
            source_url="https://boards.greenhouse.io/figma/1",
            linkedin_url="https://www.linkedin.com/jobs/view/1",
        )
        self.assertEqual(p2, "https://boards.greenhouse.io/figma/1")

        # 3. If only LinkedIn is present, primary uses it
        p3 = resolve_primary_apply_url(
            company_apply_url=None,
            source_url=None,
            linkedin_url="https://www.linkedin.com/jobs/view/12345",
        )
        self.assertEqual(p3, "https://www.linkedin.com/jobs/view/12345")

        # 4. Indeed is rejected
        p4 = resolve_primary_apply_url(
            company_apply_url="https://www.indeed.com/viewjob?jk=123",
            source_url=None,
        )
        self.assertIsNone(p4)


class TestPipelineUpsertUrls(unittest.TestCase):
    def test_upsert_job_posting_persists_multi_routes(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [None, (1001,)]

        posting_id, is_new = upsert_job_posting(
            cur=mock_cur,
            job_id="test:multi-route-1",
            company_id=1,
            title="Senior Full Stack Engineer",
            location_id=10,
            description="Build scalable web applications",
            workplace_type="remote",
            source_name="greenhouse",
            source_job_id="gh-101",
            source_url="https://boards.greenhouse.io/company/jobs/101",
            posted_at=None,
            role_type="full_time",
            company_apply_url="https://boards.greenhouse.io/company/jobs/101",
            linkedin_url="https://www.linkedin.com/jobs/view/88888/",
            simplify_url="https://simplify.jobs/p/company-swe",
        )

        self.assertTrue(is_new)
        self.assertEqual(posting_id, 1001)

        # Verify INSERT statement includes multi-route parameters
        insert_call = mock_cur.execute.call_args_list[1]
        query = insert_call[0][0]
        params = insert_call[0][1]

        self.assertIn("company_apply_url", query)
        self.assertIn("linkedin_url", query)
        self.assertIn("simplify_url", query)
        self.assertEqual(query.count("%s"), len(params))
        self.assertEqual(params[10], "https://boards.greenhouse.io/company/jobs/101")
        self.assertEqual(params[11], "https://www.linkedin.com/jobs/view/88888/")
        self.assertEqual(params[12], "https://simplify.jobs/p/company-swe")


if __name__ == "__main__":
    unittest.main()
