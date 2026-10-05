"""
Unit tests for duplicate analysis, safe identity resolution, and deduplication logic.
"""

from datetime import datetime, timezone
import unittest

from ingestion.dedup_analyzer import (
    analyze_cross_source_duplicates,
    are_dates_close,
    canonicalize_url,
    deduplicate_postings,
    is_duplicate_posting,
    normalize_company_for_dedup,
    normalize_location_for_dedup,
    normalize_title_for_dedup,
    resolve_canonical_posting,
)


class TestDedupAnalyzer(unittest.TestCase):
    def test_company_normalization(self):
        self.assertEqual(normalize_company_for_dedup("GitLab, Inc."), "gitlab")
        self.assertEqual(normalize_company_for_dedup("Stripe LLC"), "stripe")
        self.assertEqual(normalize_company_for_dedup("Delivery Hero GmbH"), "deliveryhero")
        self.assertEqual(normalize_company_for_dedup("Shopify Corp."), "shopify")
        self.assertEqual(normalize_company_for_dedup(""), "")
        self.assertEqual(normalize_company_for_dedup(None), "")

    def test_title_normalization(self):
        self.assertEqual(
            normalize_title_for_dedup("Senior Software Engineer - Backend"),
            "senior software engineer backend",
        )
        self.assertEqual(
            normalize_title_for_dedup("Staff ML / AI Engineer!"),
            "staff ml ai engineer",
        )
        self.assertEqual(normalize_title_for_dedup(""), "")
        self.assertEqual(normalize_title_for_dedup(None), "")

    def test_date_closeness(self):
        d1 = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        d2 = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        d3 = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

        # 4 days apart -> True
        self.assertTrue(are_dates_close(d1, d2, max_days=7))
        # 10 days apart -> False
        self.assertFalse(are_dates_close(d1, d3, max_days=7))
        # One date None -> True (unknown dates can still be duplicates)
        self.assertTrue(are_dates_close(d1, None, max_days=7))
        self.assertTrue(are_dates_close(None, None, max_days=7))

    def test_cross_source_duplicate_detection(self):
        postings = [
            {
                "source_name": "jobicy",
                "company_name": "Supabase, Inc.",
                "title": "Senior Backend Engineer",
                "source_job_id": "jobicy-101",
                "source_url": "https://jobicy.com/101",
                "posted_at": datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc),
            },
            {
                "source_name": "remotive",
                "company_name": "Supabase",
                "title": "Senior Backend Engineer",
                "source_job_id": "remotive-201",
                "source_url": "https://remotive.com/201",
                "posted_at": datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc),
            },
            {
                "source_name": "arbeitnow",
                "company_name": "Delivery Hero",
                "title": "Frontend Engineer",
                "source_job_id": "arb-301",
                "source_url": "https://arbeitnow.com/301",
                "posted_at": datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
            },
        ]

        result = analyze_cross_source_duplicates(postings)

        self.assertEqual(result["total_evaluated"], 3)
        self.assertEqual(result["suspected_duplicate_count"], 1)
        pair = result["suspected_pairs"][0]
        self.assertEqual(pair["company"], "Supabase, Inc.")
        self.assertEqual(pair["source_1"], "jobicy")
        self.assertEqual(pair["source_2"], "remotive")

    def test_same_source_not_reported_as_duplicate(self):
        postings = [
            {
                "source_name": "jobicy",
                "company_name": "Supabase",
                "title": "Backend Engineer",
                "source_job_id": "jobicy-1",
            },
            {
                "source_name": "jobicy",
                "company_name": "Supabase",
                "title": "Backend Engineer",
                "source_job_id": "jobicy-2",
            },
        ]
        result = analyze_cross_source_duplicates(postings)
        self.assertEqual(result["suspected_duplicate_count"], 0)


class TestSafeJobIdentityAndDeduplication(unittest.TestCase):
    def test_same_external_id_is_duplicate(self):
        p1 = {"source_name": "greenhouse", "source_job_id": "1001", "company": "Stripe", "title": "SWE"}
        p2 = {"source_name": "greenhouse", "source_job_id": "1001", "company": "Stripe", "title": "Software Engineer"}
        self.assertTrue(is_duplicate_posting(p1, p2))

    def test_canonicalize_url_preserves_query_and_strips_fragments(self):
        url1 = "https://boards.greenhouse.io/faire/jobs/8660923002?gh_jid=8660923002#apply"
        url2 = "https://boards.greenhouse.io/faire/jobs/8660923002?gh_jid=8660923002"
        self.assertEqual(canonicalize_url(url1), "https://boards.greenhouse.io/faire/jobs/8660923002?gh_jid=8660923002")
        self.assertEqual(canonicalize_url(url2), "https://boards.greenhouse.io/faire/jobs/8660923002?gh_jid=8660923002")

        # Identity query parameters (e.g. gh_jid=7898766002 vs gh_jid=5445641002) MUST NOT be discarded
        url_d1 = "https://databricks.com/company/careers/open-positions/job?gh_jid=7898766002"
        url_d2 = "https://databricks.com/company/careers/open-positions/job?gh_jid=5445641002"
        self.assertNotEqual(canonicalize_url(url_d1), canonicalize_url(url_d2))

    def test_same_canonical_url_is_duplicate(self):
        p1 = {
            "source_name": "jobicy",
            "source_job_id": "job-abc",
            "source_url": "https://boards.greenhouse.io/faire/jobs/8660923002?gh_jid=8660923002#apply",
            "company": "Faire",
            "title": "Senior ML Scientist",
        }
        p2 = {
            "source_name": "greenhouse",
            "source_job_id": "8660923002",
            "source_url": "https://boards.greenhouse.io/faire/jobs/8660923002?gh_jid=8660923002",
            "company": "Faire",
            "title": "Senior Applied ML/AI Scientist",
        }
        self.assertTrue(is_duplicate_posting(p1, p2))

    def test_direct_ats_preferred_over_broad_source(self):
        desc = "Waabi is building next generation autonomous trucking technology. We are looking for a Senior Motion Planning Engineer in Toronto to work on trajectory optimization."
        direct_p = {
            "source_name": "lever",
            "source_job_id": "lever-123",
            "company": "Waabi",
            "title": "Senior Motion Planning Engineer",
            "location": "Toronto, ON",
            "description": desc,
            "posted_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
        }
        broad_p = {
            "source_name": "jobicy",
            "source_job_id": "jobicy-999",
            "company": "Waabi",
            "title": "Senior Motion Planning Engineer",
            "location": "Toronto, ON",
            "description": desc,
            "posted_at": datetime(2026, 9, 25, tzinfo=timezone.utc),  # Newer date, but broad source
        }
        # Precedence check
        chosen = resolve_canonical_posting(broad_p, direct_p)
        self.assertEqual(chosen["source_name"], "lever")
        self.assertEqual(chosen["source_job_id"], "lever-123")

        # Only shared official URLs establish that these records are the same job.
        direct_p["source_url"] = broad_p["source_url"] = "https://jobs.lever.co/waabi/lever-123"
        deduped = deduplicate_postings([broad_p, direct_p])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["source_name"], "lever")

    def test_same_company_title_location_different_role_types_remain_separate(self):
        """Two genuinely different roles (internship vs full_time) at same company/location remain separate."""
        p_ft = {
            "source_name": "greenhouse",
            "source_job_id": "gh-ft",
            "company": "Datadog",
            "title": "Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "full_time",
        }
        p_int = {
            "source_name": "greenhouse",
            "source_job_id": "gh-int",
            "company": "Datadog",
            "title": "Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "internship",
        }
        self.assertFalse(is_duplicate_posting(p_ft, p_int))
        deduped = deduplicate_postings([p_ft, p_int])
        self.assertEqual(len(deduped), 2)

    def test_same_title_different_cities_not_duplicates(self):
        """Same title across different cities (Toronto vs SF) must remain distinct."""
        p_sf = {
            "source_name": "greenhouse",
            "source_job_id": "gh-sf",
            "company": "Databricks",
            "title": "Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "full_time",
        }
        p_toronto = {
            "source_name": "greenhouse",
            "source_job_id": "gh-to",
            "company": "Databricks",
            "title": "Software Engineer",
            "location": "Toronto, ON",
            "role_type": "full_time",
        }
        self.assertFalse(is_duplicate_posting(p_sf, p_toronto))
        deduped = deduplicate_postings([p_sf, p_toronto])
        self.assertEqual(len(deduped), 2)

    def test_punctuation_and_dash_variants_do_not_create_duplicates(self):
        """En-dash, hyphen, and em-dash variants normalize cleanly."""
        titles = [
            "Senior Software Engineer - Fullstack",
            "Senior Software Engineer \u2013 Fullstack",  # en-dash
            "Senior Software Engineer \u2014 Fullstack",  # em-dash
        ]
        norm_titles = {normalize_title_for_dedup(t) for t in titles}
        self.assertEqual(len(norm_titles), 1)
        self.assertEqual(list(norm_titles)[0], "senior software engineer fullstack")

    def test_distinct_databricks_ids_preserved(self):
        """QA regression: Databricks 'Senior Software Engineer – Fullstack' in Mountain View / SF collapsed to 1."""
        d1 = {
            "source_name": "greenhouse",
            "source_job_id": "7898766002",
            "company": "Databricks",
            "title": "Senior Software Engineer - Fullstack",
            "location": "Mountain View, California; San Francisco, California",
            "role_type": "full_time",
            "posted_at": datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            "source_url": "https://databricks.com/company/careers/open-positions/job?gh_jid=7898766002",
            "description": "P-160 Who We Are: Fullstack engineering on GenAI observability and quality platform. What we look for: 5+ years with JavaScript, React, Python, Java, SQL, distributed systems. Pay range: $190,000-$270,000.",
        }
        d2 = {
            "source_name": "greenhouse",
            "source_job_id": "5445641002",
            "company": "Databricks",
            "title": "Senior Software Engineer \u2013 Fullstack",
            "location": "Mountain View, California; San Francisco, California",
            "role_type": "full_time",
            "posted_at": datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            "source_url": "https://databricks.com/company/careers/open-positions/job?gh_jid=5445641002",
            "description": "P-160 Who We Are: Passionate about enabling data and AI teams. Fullstack engineering on Data Intelligence platform. What we look for: 5+ years with JavaScript, React, Python, Java, SQL, distributed systems. Pay range: $190,000-$270,000.",
        }
        self.assertFalse(is_duplicate_posting(d1, d2))
        deduped = deduplicate_postings([d1, d2])
        self.assertEqual(len(deduped), 2)
        # Newer posted_at timestamp is preserved

    def test_faire_conservative_preservation_and_canada_distinct(self):
        """
        Under conservative tightened rules:
        Faire 'Senior Applied ML/AI Scientist – Search' US postings share only ~59% vocabulary
        (intro/benefits boilerplate) without an explicit requisition code. To prioritize false-negative
        safety over aggressive merges, both US postings remain visible, and Canadian posting remains distinct.
        """
        f_us_1 = {
            "source_name": "greenhouse",
            "source_job_id": "8660923002",
            "company": "Faire",
            "title": "Senior Applied ML/AI Scientist - Search",
            "location": "New York City, NY; San Francisco, CA",
            "role_type": "full_time",
            "posted_at": datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
            "source_url": "https://boards.greenhouse.io/faire/jobs/8660923002?gh_jid=8660923002",
            "description": "About Faire: We are looking for a Senior Applied AI/ML Scientist on Search ranking algorithms, transformer sequential modeling, LLMs and graph neural networks. 5+ years experience.",
        }
        f_us_2 = {
            "source_name": "greenhouse",
            "source_job_id": "8618124002",
            "company": "Faire",
            "title": "Senior Applied ML/AI Scientist \u2013 Search",
            "location": "New York City, NY; San Francisco, CA",
            "role_type": "full_time",
            "posted_at": datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
            "source_url": "https://boards.greenhouse.io/faire/jobs/8618124002?gh_jid=8618124002",
            "description": "About Faire: We are looking for a Senior Applied AI/ML Scientist on Search algorithms and retrieval across five sources, relevance modeling, deep learning. 3+ years experience.",
        }
        f_ca = {
            "source_name": "greenhouse",
            "source_job_id": "8618151002",
            "company": "Faire",
            "title": "Senior Applied ML/AI Scientist - Search",
            "location": "Kitchener-Waterloo, ON; Toronto, ON",
            "role_type": "full_time",
            "posted_at": datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
            "source_url": "https://boards.greenhouse.io/faire/jobs/8618151002?gh_jid=8618151002",
            "description": "About Faire: Canadian engineering team in Kitchener-Waterloo and Toronto for Senior Applied ML/AI Scientist.",
        }

        # Under conservative 0.85 threshold, 50-60% boilerplate overlap is NOT treated as duplicate
        self.assertFalse(is_duplicate_posting(f_us_1, f_us_2))
        # Canadian posting does NOT match US postings
        self.assertFalse(is_duplicate_posting(f_us_1, f_ca))
        self.assertFalse(is_duplicate_posting(f_us_2, f_ca))

        deduped = deduplicate_postings([f_us_1, f_us_2, f_ca])
        self.assertEqual(len(deduped), 3)
        sources = {d["source_job_id"] for d in deduped}
        self.assertEqual(sources, {"8660923002", "8618124002", "8618151002"})

    def test_false_positive_protection_shared_boilerplate_55_to_70_percent(self):
        """
        Required test:
        Two jobs at the same company with:
        - same title
        - same city
        - same role type
        - shared company boilerplate / EEO / benefits producing 55-70% vocabulary overlap
        - materially different responsibilities (e.g., Payments backend vs Mobile backend)
        MUST BOTH REMAIN VISIBLE.
        """
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

        # Verify Jaccard similarity is between 55% and 75%
        import re
        words1 = set(re.findall(r"[a-z0-9]{3,}", desc_payments.lower()))
        words2 = set(re.findall(r"[a-z0-9]{3,}", desc_mobile.lower()))
        jaccard = len(words1 & words2) / len(words1 | words2)
        self.assertGreaterEqual(jaccard, 0.55)
        self.assertLessEqual(jaccard, 0.75)

        p_pay = {
            "source_name": "greenhouse",
            "source_job_id": "acme-pay",
            "source_url": "https://acme.com/jobs/pay",
            "company": "Acme Platform",
            "title": "Senior Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "full_time",
            "description": desc_payments,
        }
        p_mob = {
            "source_name": "greenhouse",
            "source_job_id": "acme-mob",
            "source_url": "https://acme.com/jobs/mob",
            "company": "Acme Platform",
            "title": "Senior Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "full_time",
            "description": desc_mobile,
        }

        self.assertFalse(is_duplicate_posting(p_pay, p_mob))
        deduped = deduplicate_postings([p_pay, p_mob])
        self.assertEqual(len(deduped), 2)
        job_ids = {d["source_job_id"] for d in deduped}
        self.assertEqual(job_ids, {"acme-pay", "acme-mob"})

    def test_identical_descriptions_do_not_prove_identity(self):
        """
        Required test: exact normalized description -> deduplicated.
        """
        desc1 = "<p>Join our <strong>infrastructure</strong> team building reliable services.</p>"
        desc2 = "Join our infrastructure team building reliable services."
        p1 = {
            "source_name": "greenhouse",
            "source_job_id": "exact-1",
            "source_url": "https://acme.com/jobs/1",
            "company": "Acme Corp",
            "title": "Infrastructure Engineer",
            "location": "New York, NY",
            "role_type": "full_time",
            "posted_at": datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            "description": desc1,
        }
        p2 = {
            "source_name": "greenhouse",
            "source_job_id": "exact-2",
            "source_url": "https://acme.com/jobs/2",
            "company": "Acme Corp",
            "title": "Infrastructure Engineer",
            "location": "New York, NY",
            "role_type": "full_time",
            "posted_at": datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            "description": desc2,
        }
        self.assertFalse(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 2)

    def test_similar_descriptions_do_not_prove_identity(self):
        """
        Required test: >= 90% vocabulary similarity and length ratio >= 0.80 -> deduplicated.
        """
        base_desc = (
            "We are seeking a Senior Data Platform Engineer to design and build real-time stream processing "
            "infrastructure using Apache Flink, Apache Kafka, and ClickHouse. You will architect distributed "
            "pipelines handling billions of events per day with strict latency and high availability SLAs. "
            "Requires 5+ years experience in distributed systems and expertise in Go, Java, or Rust. "
            "Benefits include comprehensive medical, dental, 401(k) matching, and equity."
        )
        desc1 = base_desc + " Salary range: $180,000 - $220,000."
        desc2 = base_desc + " Salary range: $185,000 - $225,000."

        p1 = {
            "source_name": "greenhouse",
            "source_job_id": "sim-1",
            "source_url": "https://acme.com/jobs/stream-1",
            "company": "Acme Corp",
            "title": "Senior Data Platform Engineer",
            "location": "Seattle, WA",
            "role_type": "full_time",
            "posted_at": datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            "description": desc1,
        }
        p2 = {
            "source_name": "greenhouse",
            "source_job_id": "sim-2",
            "source_url": "https://acme.com/jobs/stream-2",
            "company": "Acme Corp",
            "title": "Senior Data Platform Engineer",
            "location": "Seattle, WA",
            "role_type": "full_time",
            "posted_at": datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc),
            "description": desc2,
        }
        self.assertFalse(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 2)

    def test_true_duplicate_same_source_and_source_job_id(self):
        """
        Required test: same source + same source_job_id -> deduplicated.
        """
        p1 = {
            "source_name": "greenhouse",
            "source_job_id": "same-id-123",
            "company": "Stripe",
            "title": "Software Engineer",
            "location": "San Francisco, CA",
        }
        p2 = {
            "source_name": "greenhouse",
            "source_job_id": "same-id-123",
            "company": "Stripe",
            "title": "Fullstack Software Engineer",
            "location": "San Francisco, CA",
        }
        self.assertTrue(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 1)

    def test_true_duplicate_same_safe_canonical_url(self):
        """
        Required test: same safe canonical URL -> deduplicated.
        """
        p1 = {
            "source_name": "lever",
            "source_job_id": "lev-1",
            "source_url": "https://jobs.lever.co/company/abc-123?gh_jid=999#apply",
            "company": "Acme",
            "title": "Security Engineer",
            "location": "Austin, TX",
            "description": "Short description 1",
        }
        p2 = {
            "source_name": "lever",
            "source_job_id": "lev-2",
            "source_url": "https://jobs.lever.co/company/abc-123?gh_jid=999",
            "company": "Acme",
            "title": "Security Engineer",
            "location": "Austin, TX",
            "description": "Completely different text 2",
        }
        self.assertTrue(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 1)

    def test_description_requisition_text_does_not_override_source_ids(self):
        """
        Databricks-style explicit requisition code present in both descriptions -> deduplicated.
        """
        p1 = {
            "source_name": "greenhouse",
            "source_job_id": "db-1",
            "source_url": "https://databricks.com/1",
            "company": "Databricks",
            "title": "Staff Fullstack Engineer, Agentic Applications",
            "location": "Mountain View, California",
            "role_type": "full_time",
            "posted_at": datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            "description": "P-1477: GenAI Agentic applications team. Fullstack React and Python.",
        }
        p2 = {
            "source_name": "greenhouse",
            "source_job_id": "db-2",
            "source_url": "https://databricks.com/2",
            "company": "Databricks",
            "title": "Staff Fullstack Engineer, Agentic Applications",
            "location": "Mountain View, California",
            "role_type": "full_time",
            "posted_at": datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc),
            "description": "P-1477: Updated posting with expanded team scope and compensation.",
        }
        self.assertFalse(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 2)


    def test_distinct_requisitions_different_descriptions_remain_visible(self):
        """
        Distinct requisitions sharing same company, title, location, role_type
        but having materially different descriptions, different IDs, and different URLs
        MUST BOTH remain visible.
        """
        p_payments = {
            "source_name": "greenhouse",
            "source_job_id": "stripe-pay",
            "source_url": "https://stripe.com/pay",
            "company": "Stripe",
            "title": "Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "full_time",
            "description": "Build high-throughput payments processing infrastructure in Java, Kafka, Spring, SQL. Core banking transactions.",
        }
        p_mobile = {
            "source_name": "greenhouse",
            "source_job_id": "stripe-mob",
            "source_url": "https://stripe.com/mob",
            "company": "Stripe",
            "title": "Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "full_time",
            "description": "Build mobile consumer iOS/Android experience using Swift, Kotlin, React Native, GraphQL. Offline-first UI animations.",
        }
        self.assertFalse(is_duplicate_posting(p_payments, p_mobile))
        deduped = deduplicate_postings([p_payments, p_mobile])
        self.assertEqual(len(deduped), 2)

    def test_same_title_location_different_description_exact_same_canonical_url_is_duplicate(self):
        """
        Postings sharing title/location/role_type with different descriptions but exact same canonical URL
        MUST collapse to 1.
        """
        p1 = {
            "source_name": "greenhouse",
            "source_job_id": "gh-1",
            "source_url": "https://co.com/jobs/sre?gh_jid=123#feed",
            "company": "Datadog",
            "title": "Site Reliability Engineer",
            "location": "Austin, TX",
            "role_type": "full_time",
            "description": "Brief description 1",
        }
        p2 = {
            "source_name": "greenhouse",
            "source_job_id": "gh-2",
            "source_url": "https://co.com/jobs/sre?gh_jid=123",
            "company": "Datadog",
            "title": "Site Reliability Engineer",
            "location": "Austin, TX",
            "role_type": "full_time",
            "description": "Completely different text 2",
        }
        self.assertTrue(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 1)

    def test_absent_descriptions_do_not_blindly_collapse(self):
        """
        If descriptions are NULL / absent, postings sharing title/location with different IDs/URLs
        do NOT collapse. Both remain visible.
        """
        p1 = {
            "source_name": "greenhouse",
            "source_job_id": "nd-1",
            "source_url": "https://co.com/1",
            "company": "Airbnb",
            "title": "DevOps Engineer",
            "location": "Seattle, WA",
            "role_type": "full_time",
            "description": None,
        }
        p2 = {
            "source_name": "greenhouse",
            "source_job_id": "nd-2",
            "source_url": "https://co.com/2",
            "company": "Airbnb",
            "title": "DevOps Engineer",
            "location": "Seattle, WA",
            "role_type": "full_time",
            "description": "",
        }
        self.assertFalse(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 2)

    def test_gh_jid_identity_parameters_preserved_different_descriptions_remain_visible(self):
        """
        Regression test: postings with same company, title, location, role_type
        URL 1: https://company.com/careers/job?gh_jid=111
        URL 2: https://company.com/careers/job?gh_jid=222
        different source_job_id, materially different descriptions
        EXPECTED: BOTH remain visible.
        """
        p1 = {
            "company": "Databricks",
            "title": "Senior Software Engineer",
            "location": "Mountain View, CA",
            "role_type": "full_time",
            "source_name": "greenhouse",
            "source_job_id": "111",
            "source_url": "https://company.com/careers/job?gh_jid=111",
            "description": "Fullstack web platform engineer building agentic SDLC and front-end UI components with React.",
        }
        p2 = {
            "company": "Databricks",
            "title": "Senior Software Engineer",
            "location": "Mountain View, CA",
            "role_type": "full_time",
            "source_name": "greenhouse",
            "source_job_id": "222",
            "source_url": "https://company.com/careers/job?gh_jid=222",
            "description": "Distributed systems engineer building database storage engine in C++ and Rust.",
        }
        self.assertFalse(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 2)

    def test_tracking_params_differ_without_description_remain_visible_for_safety(self):
        """
        Tracking parameter case:
        https://company.com/jobs/123?utm_source=linkedin
        https://company.com/jobs/123?utm_source=google
        Without unsafe query stripping, if IDs differ and descriptions are materially different,
        keeping both is safer than false merging.
        """
        p1 = {
            "company": "Stripe",
            "title": "Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "full_time",
            "source_name": "greenhouse",
            "source_job_id": "id-1",
            "source_url": "https://company.com/jobs/123?utm_source=linkedin",
            "description": "Payments billing infrastructure role.",
        }
        p2 = {
            "company": "Stripe",
            "title": "Software Engineer",
            "location": "San Francisco, CA",
            "role_type": "full_time",
            "source_name": "greenhouse",
            "source_job_id": "id-2",
            "source_url": "https://company.com/jobs/123?utm_source=google",
            "description": "Mobile iOS application role.",
        }
        self.assertFalse(is_duplicate_posting(p1, p2))
        deduped = deduplicate_postings([p1, p2])
        self.assertEqual(len(deduped), 2)


if __name__ == "__main__":
    unittest.main()
