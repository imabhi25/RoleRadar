"""
Unit tests for SWE role filtering, workplace classification, and location normalization.
"""

import unittest
from ingestion.normalizer import (
    CANADIAN_PROVINCE_CODES,
    ELIGIBLE_COUNTRIES,
    VALID_ROLE_TYPES,
    classify_role_type,
    classify_workplace,
    is_swe_role,
    is_user_facing_location_eligible,
    normalize_location_and_country,
)


class TestSweRoleFilter(unittest.TestCase):
    def test_swe_title_inclusion(self):
        valid_titles = [
            "Software Engineer",
            "Senior Software Engineer",
            "Staff Software Developer",
            "Backend Engineer",
            "Senior Backend Engineer",
            "Backend Software Developer",
            "Frontend Engineer",
            "Frontend UI/UX Engineer",
            "Full Stack Developer",
            "Fullstack Engineer",
            "Platform Engineer",
            "Data Platform Engineer",
            "Infrastructure Engineer",
            "Cloud Infrastructure Architect",
            "Site Reliability Engineer",
            "SRE",
            "DevOps Engineer",
            "Cloud Engineer",
            "Mobile Engineer",
            "iOS Engineer",
            "Android Developer",
            "Embedded Systems & Cloud Engineer",
            "Firmware Engineer",
            "Data Engineer",
            "Machine Learning Engineer",
            "Machine Learning Scientist",
            "AI Engineer",
            "Distributed Systems Engineer",
            "Product Engineer",
            "Senior Product Engineer",
            "Staff Product Engineer",
            "Senior / Staff Product Engineer",
            "Product Engineer, AI",
            "Senior / Staff Fullstack Engineer",
            "MLOps Engineer",
            "MLOps",
            "Applied AI Engineer",
            "Research Engineer",
            "Analytics Engineer",
            "ML Platform Engineer",
            "SWE Intern",
            "Software Engineering Intern",
            "Developer Co-op",
            "Software Engineering Co-op",
            "New Grad SWE",
            "Graduate SWE",
            "Entry-Level SWE",
        ]
        for title in valid_titles:
            with self.subTest(title=title):
                self.assertTrue(is_swe_role(title), f"Expected '{title}' to be recognized as SWE role.")

    def test_unrelated_title_exclusion(self):
        invalid_titles = [
            "Sales Representative",
            "VP of Sales",
            "Engineering Manager, Sales",
            "Account Executive",
            "Technical Account Manager",
            "Technical Recruiter",
            "Senior Recruiter",
            "Software Engineering Recruiter",
            "Staff Accountant",
            "Finance Manager",
            "Senior Product Manager",
            "Product Manager",
            "Project Manager",
            "Scrum Master",
            "Graphic Designer",
            "Product Designer",
            "UI/UX Designer",
            "Customer Support Specialist",
            "Customer Support Engineer",
            "Support Engineer",
            "Design Engineer",
            "Solutions Engineer",
            "Sales Engineer",
            "Customer Success Manager",
            "Help Desk Technician",
            "Business Systems Lead - Procure-to-Pay",
            "Support Systems Lead",
            "Business Systems Analyst",
            "Corporate Systems Manager",
            "Legal Counsel",
            "Office Manager",
            "",
            None,
        ]
        for title in invalid_titles:
            with self.subTest(title=title):
                self.assertFalse(is_swe_role(title), f"Expected '{title}' to be excluded from SWE roles.")

    def test_explicit_product_engineer_and_non_swe_audit_cases(self):
        """
        Explicitly verify that Product Engineer variants are included as SWE,
        while non-SWE 'Engineer' titles (Design, Solutions, Sales, Support) and
        Product Manager / Designer roles are strictly excluded.
        """
        included = [
            "Product Engineer",
            "Senior / Staff Product Engineer",
            "Senior Product Engineer",
            "Staff Product Engineer",
            "Product Engineer, AI",
            "Senior / Staff Fullstack Engineer",
        ]
        for title in included:
            with self.subTest(title=title):
                self.assertTrue(is_swe_role(title), f"Expected '{title}' to be included as SWE role.")

        excluded = [
            "Design Engineer",
            "Solutions Engineer",
            "Sales Engineer",
            "Customer Support Engineer",
            "Support Engineer",
            "Product Designer",
            "Product Manager",
            "Technical Account Manager",
        ]
        for title in excluded:
            with self.subTest(title=title):
                self.assertFalse(is_swe_role(title), f"Expected '{title}' to be excluded from SWE roles.")


class TestWorkplaceClassification(unittest.TestCase):
    def test_remote_classification(self):
        self.assertEqual(classify_workplace(is_remote=True), "remote")
        self.assertEqual(classify_workplace(location_text="Remote"), "remote")
        self.assertEqual(classify_workplace(location_text="Remote - Canada"), "remote")
        self.assertEqual(classify_workplace(location_text="San Francisco (Remote)"), "remote")
        self.assertEqual(classify_workplace(workplace_type_raw="remote"), "remote")
        self.assertEqual(classify_workplace(location_text="Work from home - US"), "remote")

    def test_hybrid_classification(self):
        self.assertEqual(classify_workplace(workplace_type_raw="hybrid"), "hybrid")
        self.assertEqual(classify_workplace(location_text="New York (Hybrid)"), "hybrid")
        self.assertEqual(classify_workplace(location_text="Hybrid - Toronto"), "hybrid")
        self.assertEqual(classify_workplace(location_text="Hybrid - 2 days in office"), "hybrid")
        # Hybrid should take precedence even if remote/onsite terms appear
        self.assertEqual(classify_workplace(location_text="Hybrid remote/onsite schedule"), "hybrid")

    def test_onsite_classification(self):
        self.assertEqual(classify_workplace(workplace_type_raw="onsite"), "onsite")
        self.assertEqual(classify_workplace(workplace_type_raw="On-site"), "onsite")
        self.assertEqual(classify_workplace(location_text="In-Office, Seattle, WA"), "onsite")

    def test_unspecified_fallback(self):
        # Does NOT assume onsite when absent or ambiguous
        self.assertEqual(classify_workplace(location_text="Seattle, WA"), "unspecified")
        self.assertEqual(classify_workplace(location_text="Toronto"), "unspecified")
        self.assertEqual(classify_workplace(location_text="Berlin"), "unspecified")
        self.assertEqual(classify_workplace(location_text=None, workplace_type_raw=None), "unspecified")
        self.assertEqual(classify_workplace(location_text="", workplace_type_raw=""), "unspecified")

    def test_title_and_description_workplace_signals(self):
        # Explicit clues in title
        self.assertEqual(classify_workplace(title="Senior Software Engineer (Remote)"), "remote")
        self.assertEqual(classify_workplace(title="Backend Engineer - Hybrid"), "hybrid")
        self.assertEqual(classify_workplace(title="Full Stack Developer (On-site)"), "onsite")
        # Explicit clues in description
        self.assertEqual(classify_workplace(description="Workplace: Remote\nWe offer great benefits."), "remote")
        self.assertEqual(classify_workplace(description="This role is 100% remote across US."), "remote")
        self.assertEqual(classify_workplace(description="Work Model: Hybrid\nTwo days per week in office."), "hybrid")
        # City without workplace signal remains unspecified
        self.assertEqual(classify_workplace(location_text="Austin, TX", title="Staff Software Engineer"), "unspecified")

    def test_ashby_workplace_precedence(self):
        """
        Ashby regression tests:
        Ashby API returns isRemote=True for Hybrid roles (with workplaceType='Hybrid').
        Explicit structured workplaceType must take strict precedence over isRemote boolean.
        - explicitly hybrid -> hybrid
        - explicitly remote -> remote
        - explicitly onsite -> onsite
        - ambiguous / absent -> unspecified
        """
        # Hybrid takes precedence over is_remote=True
        self.assertEqual(classify_workplace(workplace_type_raw="Hybrid", is_remote=True), "hybrid")
        self.assertEqual(classify_workplace(workplace_type_raw="hybrid", is_remote=True), "hybrid")
        # Explicit remote
        self.assertEqual(classify_workplace(workplace_type_raw="Remote", is_remote=True), "remote")
        # Explicit onsite
        self.assertEqual(classify_workplace(workplace_type_raw="Onsite", is_remote=False), "onsite")
        self.assertEqual(classify_workplace(workplace_type_raw="In-Office", is_remote=False), "onsite")
        # Ambiguous / absent -> unspecified
        self.assertEqual(classify_workplace(workplace_type_raw=None, is_remote=False, location_text="San Francisco, CA"), "unspecified")



class TestLocationAndCountryNormalization(unittest.TestCase):
    def test_country_extraction(self):
        cases = [
            ("San Francisco, CA, USA", ("San Francisco, CA, USA", "United States")),
            ("New York, NY, USA", ("New York, NY, USA", "United States")),
            ("New York, U.S.A.", ("New York, U.S.A.", "United States")),
            ("Austin, United States", ("Austin, United States", "United States")),
            ("Toronto, Canada", ("Toronto, Canada", "Canada")),
            ("Toronto, ON, Canada", ("Toronto, ON, Canada", "Canada")),
            ("Berlin, Germany", ("Berlin, Germany", "Germany")),
            ("London, UK", ("London, UK", "United Kingdom")),
            ("London, U.K.", ("London, U.K.", "United Kingdom")),
            ("London, United Kingdom", ("London, United Kingdom", "United Kingdom")),
            ("Seattle, WA", ("Seattle, WA", "United States")),
            ("Austin, TX", ("Austin, TX", "United States")),
            ("Remote - US", ("Remote", "United States")),
            ("Remote - Canada", ("Remote", "Canada")),
            ("Remote", ("Remote", "Unknown")),
            ("North America", ("North America", "Unknown")),
            ("Europe", ("Europe", "Unknown")),
            ("EMEA", ("EMEA", "Unknown")),
            ("APAC", ("APAC", "Unknown")),
            ("Global", ("Global", "Unknown")),
            ("Worldwide", ("Worldwide", "Unknown")),
            ("USA, United States", ("United States", "United States")),
            ("United States, USA", ("United States", "United States")),
            ("Canada Remote", ("Canada", "Canada")),
            ("U.S.", ("United States", "United States")),
            ("USA", ("United States", "United States")),
            ("New York, U.S.", ("New York, U.S.", "United States")),
            ("", ("Unknown", "Unknown")),
            (None, ("Unknown", "Unknown")),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_location_and_country(raw), expected)

    def test_broad_regions_mapped_to_unknown_country(self):
        """
        Broad geographic regions must normalize to country='Unknown'
        without discarding the useful location display text.
        """
        region_cases = [
            ("North America", ("North America", "Unknown")),
            ("Europe", ("Europe", "Unknown")),
            ("EMEA", ("EMEA", "Unknown")),
            ("APAC", ("APAC", "Unknown")),
            ("Global", ("Global", "Unknown")),
            ("Worldwide", ("Worldwide", "Unknown")),
            ("Latin America", ("Latin America", "Unknown")),
            ("Asia Pacific", ("Asia Pacific", "Unknown")),
            ("Middle East", ("Middle East", "Unknown")),
        ]
        for raw, expected in region_cases:
            with self.subTest(region=raw):
                self.assertEqual(normalize_location_and_country(raw), expected)

    def test_regression_city_alone_and_strict_countries(self):
        """
        Regression test: Verify that bare cities and broad strings do not become countries,
        explicit city + country works, and country aliases/signals are properly resolved.
        """
        cases = [
            # Arbitrary / non-target bare cities must NOT become country
            ("Paris", ("Paris", "Unknown")),
            ("Berlin", ("Berlin", "Unknown")),
            ("München", ("München", "Unknown")),
            ("Dresden", ("Dresden", "Unknown")),
            ("Karlsruhe", ("Karlsruhe", "Unknown")),
            ("Köln", ("Köln", "Unknown")),
            # Curated bare cities mapped directly to sovereign target countries
            ("London", ("London", "United Kingdom")),
            ("San Francisco", ("San Francisco", "United States")),
            ("New York", ("New York", "United States")),
            ("Toronto", ("Toronto", "Canada")),
            # Broad / non-country terms must become Unknown
            ("Anywhere", ("Anywhere", "Unknown")),
            ("Remote Job", ("Remote", "Unknown")),
            ("Hybrid", ("Hybrid", "Unknown")),
            ("Onsite", ("Onsite", "Unknown")),
            ("Worldwide", ("Worldwide", "Unknown")),
            ("Global", ("Global", "Unknown")),
            # Explicit city + country
            ("Paris, France", ("Paris, France", "France")),
            ("Berlin, Germany", ("Berlin, Germany", "Germany")),
            ("Toronto, Canada", ("Toronto, Canada", "Canada")),
            ("London, United Kingdom", ("London, United Kingdom", "United Kingdom")),
            # Explicit US state format
            ("Seattle, WA", ("Seattle, WA", "United States")),
            ("Austin, TX", ("Austin, TX", "United States")),
            ("Wilmington, DE", ("Wilmington, DE", "United States")),
            ("Dover, DE", ("Dover, DE", "United States")),
            # Explicit country aliases
            ("USA, United States", ("United States", "United States")),
            ("United States, USA", ("United States", "United States")),
            ("USA", ("United States", "United States")),
            ("US", ("United States", "United States")),
            ("U.S.", ("United States", "United States")),
            ("U.S.A.", ("United States", "United States")),
            ("UK", ("United Kingdom", "United Kingdom")),
            ("U.K.", ("United Kingdom", "United Kingdom")),
            # Explicit Germany signals
            ("Home Office Deutschland", ("Home Office Deutschland", "Germany")),
            ("Munich (DE)", ("Munich (DE)", "Germany")),
            ("Remote Germany", ("Remote", "Germany")),
            ("Remote - Germany", ("Remote", "Germany")),
            ("Canada Remote", ("Canada", "Canada")),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_location_and_country(raw), expected)

    def test_canadian_city_province_precedence_and_ca_disambiguation(self):
        """
        Verifies that when a known Canadian city/province appears, Canadian context wins,
        and 'CA' at the end of a clearly Canadian location is treated as Canada, not California.
        """
        required_cases = [
            ("Toronto, ON", ("Toronto, ON", "Canada")),
            ("Toronto, ON, CA", ("Toronto, ON, CA", "Canada")),
            ("Toronto, Ontario", ("Toronto, Ontario", "Canada")),
            ("Toronto, Ontario, Canada", ("Toronto, Ontario, Canada", "Canada")),
            ("Vancouver, BC", ("Vancouver, BC", "Canada")),
            ("Vancouver, BC, CA", ("Vancouver, BC, CA", "Canada")),
            ("Waterloo, ON", ("Waterloo, ON", "Canada")),
            ("Montreal, QC", ("Montreal, QC", "Canada")),
            ("Montréal, QC", ("Montréal, QC", "Canada")),
            ("Ottawa, ON", ("Ottawa, ON", "Canada")),
            ("Calgary, AB", ("Calgary, AB", "Canada")),
            # Additional Canadian cities and province combinations
            ("Markham, ON, CA", ("Markham, ON, CA", "Canada")),
            ("Richmond, BC, CA", ("Richmond, BC, CA", "Canada")),
            ("Toronto, CA", ("Toronto, CA", "Canada")),
            ("Vancouver, CA", ("Vancouver, CA", "Canada")),
            ("Waterloo, CA", ("Waterloo, CA", "Canada")),
            ("Montreal, CA", ("Montreal, CA", "Canada")),
            ("Kitchener, ON, CA", ("Kitchener, ON, CA", "Canada")),
        ]
        for raw, expected in required_cases:
            with self.subTest(raw=raw):
                norm_loc, norm_country = normalize_location_and_country(raw)
                self.assertEqual((norm_loc, norm_country), expected)
                self.assertTrue(
                    is_user_facing_location_eligible(norm_loc, norm_country),
                    f"Expected '{norm_loc}' with country '{norm_country}' to be user-facing eligible.",
                )

    def test_us_ambiguous_ca_locations_resolve_to_us(self):
        """
        Verifies that US locations using 'CA' (California) strictly resolve to United States
        when not accompanied by Canadian context.
        """
        us_cases = [
            ("San Francisco, CA", ("San Francisco, CA", "United States")),
            ("Los Angeles, CA", ("Los Angeles, CA", "United States")),
            ("Palo Alto, CA", ("Palo Alto, CA", "United States")),
            ("Mountain View, CA", ("Mountain View, CA", "United States")),
            ("Foster City, CA", ("Foster City, CA", "United States")),
            ("San Jose, CA", ("San Jose, CA", "United States")),
            ("Sunnyvale, CA", ("Sunnyvale, CA", "United States")),
            ("San Francisco, CA, US; Remote, CA, US", ("San Francisco, CA, US; Remote, CA, US", "United States")),
            ("Palo Alto, CA, US; Remote, US", ("Palo Alto, CA, US; Remote, US", "United States")),
        ]
        for raw, expected in us_cases:
            with self.subTest(raw=raw):
                norm_loc, norm_country = normalize_location_and_country(raw)
                self.assertEqual((norm_loc, norm_country), expected)
                self.assertTrue(
                    is_user_facing_location_eligible(norm_loc, norm_country),
                    f"Expected '{norm_loc}' with country '{norm_country}' to be user-facing eligible.",
                )

    def test_prose_containing_on_does_not_count_as_ontario(self):
        """
        Regression test: Ordinary prose containing the English word 'on'
        (e.g. 'Remote on site', 'Working on platform', 'Engineering on infrastructure')
        must NOT be counted as Ontario/Canadian context, and trailing 'CA' must remain United States.
        """
        cases = [
            ("Remote on site, CA", ("Remote on site, CA", "United States")),
            ("Working on platform, CA", ("Working on platform, CA", "United States")),
            ("Engineering on infrastructure, CA", ("Engineering on infrastructure, CA", "United States")),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                norm_loc, norm_country = normalize_location_and_country(raw)
                self.assertEqual((norm_loc, norm_country), expected)

    def test_mixed_us_canada_locations(self):
        """
        Verifies deterministic country resolution and user-facing eligibility
        for cross-border listings (e.g. physical hubs + remote in Canada/US).
        """
        # Primary US hubs + remote Canada or US: resolved to United States based on physical hubs
        us_mixed = "San Francisco, CA, New York, NY, Portland, OR, or Remote within Canada or United States"
        norm_loc, norm_country = normalize_location_and_country(us_mixed)
        self.assertEqual(norm_country, "United States")
        self.assertEqual(norm_loc, us_mixed)
        self.assertTrue(
            is_user_facing_location_eligible(norm_loc, norm_country),
            f"Expected '{norm_loc}' to remain user-facing eligible.",
        )

        # Primary Canadian hub + cross-border remote: resolved to Canada based on physical hub
        ca_mixed = "Toronto, ON, Vancouver, BC, or Remote within Canada or United States"
        norm_loc_ca, norm_country_ca = normalize_location_and_country(ca_mixed)
        self.assertEqual(norm_country_ca, "Canada")
        self.assertEqual(norm_loc_ca, ca_mixed)
        self.assertTrue(
            is_user_facing_location_eligible(norm_loc_ca, norm_country_ca),
            f"Expected '{norm_loc_ca}' to remain user-facing eligible.",
        )


class TestRoleClassification(unittest.TestCase):
    """
    Verifies role type classification for internships, co-ops, new grad,
    full-time roles, and conservative avoidance of false positives.
    """

    def test_internship_classification(self):
        cases = [
            "Software Engineer Intern",
            "Software Engineering Internship",
            "Summer 2026 SWE Intern",
            "Machine Learning Engineering Intern",
            "Data Science Intern (Undergrad)",
        ]
        for title in cases:
            with self.subTest(title=title):
                self.assertEqual(classify_role_type(title), "internship")

    def test_co_op_classification(self):
        cases = [
            "Software Developer Co-op",
            "Engineering Co-op (Fall 2026)",
            "Backend Co-op",
            "Cooperative Education Engineer",
        ]
        for title in cases:
            with self.subTest(title=title):
                self.assertEqual(classify_role_type(title), "co_op")

    def test_new_grad_classification(self):
        cases = [
            "Software Engineer, New Grad",
            "Software Engineer - New Graduate (2026)",
            "Graduate Software Engineer",
            "Early Career Software Engineer",
            "University Graduate SWE",
            "Campus Hire Software Engineer",
        ]
        for title in cases:
            with self.subTest(title=title):
                self.assertEqual(classify_role_type(title), "new_grad")

    def test_full_time_classification(self):
        cases = [
            "Senior Software Engineer",
            "Staff Product Engineer",
            "Software Engineer",
            "Lead Backend Developer",
            "Principal Infrastructure Engineer",
            "Full Stack Engineer",
        ]
        for title in cases:
            with self.subTest(title=title):
                self.assertEqual(classify_role_type(title), "full_time")

    def test_false_positives_and_subtle_cases(self):
        # 'internal' or 'internally' or 'international' should NEVER trigger internship
        self.assertNotEqual(classify_role_type("Internal Tools Engineer"), "internship")
        self.assertEqual(classify_role_type("Internal Software Engineer"), "full_time")
        self.assertNotEqual(classify_role_type("International Specialist"), "internship")
        self.assertEqual(classify_role_type("International Software Engineer"), "full_time")

        # 'graduate' in description (e.g. 'Graduate degree preferred') should not override title
        self.assertEqual(
            classify_role_type(
                title="Software Engineer",
                description="Must possess a graduate degree in Computer Science.",
            ),
            "full_time",
        )

        # Non-engineering roles without SWE patterns
        self.assertEqual(classify_role_type("Student Worker"), "unknown")
        self.assertEqual(classify_role_type("Graduate Recruiter"), "unknown")

        # None and empty
        self.assertEqual(classify_role_type(None), "unknown")
        self.assertEqual(classify_role_type(""), "unknown")
        self.assertEqual(classify_role_type("   "), "unknown")

    def test_valid_role_types_contains_expected(self):
        expected = {"internship", "co_op", "new_grad", "entry_level", "full_time", "unknown"}
        self.assertEqual(VALID_ROLE_TYPES, expected)


class TestUserFacingLocationEligibility(unittest.TestCase):
    """
    Tests geographic quality rules for the user-facing RoleRadar feed (Phase 6B.1):
      - Supported countries strictly: United States, Canada
      - Useful location required (city/state, city/province)
      - Bare countries, broad regions, Unknown, vague remote-only locations, and UK locations rejected
    """

    def test_accept_cases(self):
        accept_cases = [
            # United States
            ("New York, NY", "United States"),
            ("NYC", "United States"),
            ("San Francisco, CA", "United States"),
            ("Seattle, WA", "United States"),
            ("Austin, TX", "United States"),
            ("Chicago, IL", "United States"),
            ("McLean, VA", "United States"),
            ("San Diego, CA", "United States"),
            ("Seattle, WA, United States", "United States"),
            ("Remote (San Francisco, CA)", "United States"),
            ("Remote (Austin, TX)", "United States"),
            # Canada
            ("Toronto, ON, Canada", "Canada"),
            ("Vancouver, BC, Canada", "Canada"),
            ("Montreal, QC, Canada", "Canada"),
            ("Calgary, AB, Canada", "Canada"),
            ("Kitchener, ON, Canada", "Canada"),
            ("Toronto, ON", "Canada"),
            ("Toronto, Canada", "Canada"),
        ]
        for loc, country in accept_cases:
            with self.subTest(loc=loc, country=country):
                self.assertTrue(
                    is_user_facing_location_eligible(loc, country),
                    f"Expected ({loc!r}, {country!r}) to be eligible.",
                )

    def test_reject_cases(self):
        reject_cases = [
            # United Kingdom locations (no longer user-facing eligible)
            ("London, UK", "United Kingdom"),
            ("London, United Kingdom", "United Kingdom"),
            ("Nottingham, UK", "United Kingdom"),
            ("London, England", "United Kingdom"),
            ("London, England, United Kingdom", "United Kingdom"),
            ("Cardiff, London or Remote (UK)", "United Kingdom"),
            ("Manchester", "United Kingdom"),
            ("Edinburgh", "United Kingdom"),
            # Bare country names
            ("United Kingdom", "United Kingdom"),
            ("UK", "United Kingdom"),
            # Vague remote without city detail
            ("Remote - UK", "United Kingdom"),
            # Broad non-country / regional terms
            ("Anywhere", "Unknown"),
            ("Worldwide", "Unknown"),
            ("Global", "Unknown"),
            ("Europe", "Unknown"),
            ("EMEA", "Unknown"),
            ("APAC", "Unknown"),
            ("Unknown", "Unknown"),
            ("Unspecified", "Unknown"),
            # Unsupported sovereign countries
            ("Berlin, Germany", "Germany"),
            ("Paris, France", "France"),
            ("Sydney, Australia", "Australia"),
            ("Tel Aviv, Israel", "Israel"),
            ("Lima, Peru", "Peru"),
            ("Bangalore, India", "India"),
            # Multi-region without recognizable city
            ("USA, Canada, USA timezones", "Canada"),
            ("Northern America, LATAM, Europe, APAC", "Unknown"),
            ("Canada,  Europe,  USA", "United States"),
        ]
        for loc, country in reject_cases:
            with self.subTest(loc=loc, country=country):
                self.assertFalse(
                    is_user_facing_location_eligible(loc, country),
                    f"Expected ({loc!r}, {country!r}) to be rejected.",
                )

    def test_canadian_provinces_and_territories_completeness(self):
        # 10 provinces + 3 territories = 13 codes
        self.assertEqual(len(CANADIAN_PROVINCE_CODES), 13)
        expected_provinces = {
            "ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe", "qc", "sk", "yt"
        }
        self.assertEqual(CANADIAN_PROVINCE_CODES, expected_provinces)
        self.assertEqual(ELIGIBLE_COUNTRIES, ("United States", "Canada"))

    def test_country_fallback_when_country_omitted(self):
        # Infer from location string directly
        self.assertTrue(is_user_facing_location_eligible("Seattle, WA"))
        self.assertTrue(is_user_facing_location_eligible("Toronto, ON, Canada"))
        self.assertFalse(is_user_facing_location_eligible("London, UK"))
        self.assertFalse(is_user_facing_location_eligible("Berlin, Germany"))
        self.assertFalse(is_user_facing_location_eligible("Remote"))
        self.assertTrue(is_user_facing_location_eligible("United States"))
        self.assertFalse(is_user_facing_location_eligible(None))
        self.assertFalse(is_user_facing_location_eligible(""))

    def test_phase_6c_2_eligible_examples(self):
        """Specifically verifies every eligible US/Canada example specified in Phase 6C."""
        cases = [
            "Toronto",
            "Toronto, Ontario, Canada",
            "Vancouver",
            "San Francisco",
            "San Francisco, California",
            "San Francisco Office",
            "New York",
            "Los Angeles, CA or Remote (United States)",
        ]
        for loc in cases:
            with self.subTest(loc=loc):
                norm_loc, norm_country = normalize_location_and_country(loc)
                self.assertIn(norm_country, ("United States", "Canada"))
                self.assertTrue(
                    is_user_facing_location_eligible(loc),
                    f"Expected {loc!r} to be eligible without explicit country.",
                )
                self.assertTrue(
                    is_user_facing_location_eligible(loc, norm_country),
                    f"Expected ({loc!r}, {norm_country!r}) to be eligible with explicit country.",
                )

    def test_phase_6c_2_ineligible_examples(self):
        """Specifically verifies every ineligible example specified in Phase 6C (including UK locations)."""
        cases = [
            "London",
            "Cardiff",
            "Manchester",
            "Edinburgh",
            "Cardiff, London or Remote (UK)",
            "United Kingdom",
            "United Kingdom (Remote)",
            "Remote",
            "Worldwide",
            "Paris",
            "Berlin",
            "EMEA",
            "APAC",
        ]
        for loc in cases:
            with self.subTest(loc=loc):
                self.assertFalse(
                    is_user_facing_location_eligible(loc),
                    f"Expected {loc!r} to be ineligible without explicit country.",
                )
                norm_loc, norm_country = normalize_location_and_country(loc)
                self.assertFalse(
                    is_user_facing_location_eligible(loc, norm_country),
                    f"Expected ({loc!r}, {norm_country!r}) to be ineligible with normalized country.",
                )

    def test_remote_and_country_wide_require_eligible_country(self):
        """Explicit US/Canada scope is eligible; unsupported or unknown scope is not."""
        cases = [
            ("Remote", "United States"),
            ("Remote: United States", "United States"),
            ("U.S. Remote", "United States"),
            ("United States (Remote)", "United States"),
            ("Remote - US", "United States"),
            ("Canada (Remote)", "Canada"),
            ("Canada Remote", "Canada"),
            ("Remote - Canada", "Canada"),
            ("United Kingdom (Remote)", "United Kingdom"),
            ("UK Remote", "United Kingdom"),
            ("Remote - UK", "United Kingdom"),
            ("United States", "United States"),
            ("Canada", "Canada"),
            ("United Kingdom", "United Kingdom"),
            ("Paris", "France"),
            ("Berlin", "Germany"),
            ("Worldwide", "Unknown"),
            ("EMEA", "Unknown"),
            ("APAC", "Unknown"),
        ]
        for loc, country in cases:
            with self.subTest(loc=loc, country=country):
                self.assertEqual(
                    is_user_facing_location_eligible(loc, country), country in ELIGIBLE_COUNTRIES,
                    f"Expected ({loc!r}, {country!r}) to be rejected.",
                )

    def test_curated_cities_and_generic_suffixes(self):
        """Verifies curated cities across US, Canada, UK and generic suffixes like Office, HQ."""
        # US cities
        us_cities = [
            "San Francisco", "New York", "New York City", "Seattle", "Boston",
            "Austin", "Chicago", "Los Angeles", "Palo Alto", "Mountain View",
            "Menlo Park", "Foster City", "Atlanta", "Pittsburgh", "McLean"
        ]
        for city in us_cities:
            with self.subTest(city=city):
                self.assertTrue(is_user_facing_location_eligible(city))
                self.assertTrue(is_user_facing_location_eligible(f"{city} Office"))
                self.assertTrue(is_user_facing_location_eligible(f"{city} HQ"))
                self.assertTrue(is_user_facing_location_eligible(f"{city} Headquarters"))

        # Canada cities
        ca_cities = [
            "Toronto", "Vancouver", "Montreal", "Montréal", "Calgary",
            "Ottawa", "Waterloo", "Kitchener"
        ]
        for city in ca_cities:
            with self.subTest(city=city):
                self.assertTrue(is_user_facing_location_eligible(city))
                self.assertTrue(is_user_facing_location_eligible(f"{city} Office"))

        # UK cities: must accurately normalize to United Kingdom, but are NOT user-facing eligible
        uk_cities = [
            "London", "Cardiff", "Manchester", "Edinburgh", "Bristol",
            "Cambridge", "Oxford"
        ]
        for city in uk_cities:
            with self.subTest(city=city):
                norm_loc, norm_country = normalize_location_and_country(city)
                self.assertEqual(norm_country, "United Kingdom")
                self.assertFalse(is_user_facing_location_eligible(city))
                self.assertFalse(is_user_facing_location_eligible(f"{city} HQ"))
                self.assertFalse(is_user_facing_location_eligible(city, "United Kingdom"))

    def test_full_state_and_province_names(self):
        """Verifies full US state and Canadian province names."""
        self.assertTrue(is_user_facing_location_eligible("San Francisco, California"))
        self.assertTrue(is_user_facing_location_eligible("Austin, Texas"))
        self.assertTrue(is_user_facing_location_eligible("Seattle, Washington"))
        self.assertTrue(is_user_facing_location_eligible("Boston, Massachusetts"))
        self.assertTrue(is_user_facing_location_eligible("New York, New York"))
        self.assertTrue(is_user_facing_location_eligible("Toronto, Ontario"))
        self.assertTrue(is_user_facing_location_eligible("Vancouver, British Columbia"))
        self.assertTrue(is_user_facing_location_eligible("Montreal, Quebec"))
        self.assertTrue(is_user_facing_location_eligible("Calgary, Alberta"))


if __name__ == "__main__":
    unittest.main()


class TestWorkplaceFromRoleSpecificDescriptionEvidence:
    """Real-shaped phrases from the inventory that are explicit about THIS role (and ones that are not)."""

    def test_role_specific_statements_are_classified(self):
        from ingestion.normalizer import classify_workplace as c

        assert c(description="Referenced Salary Location Toronto, Ontario Working Arrangement Hybrid Salary range is") == "hybrid"
        assert c(description="Please note that this is a hybrid position for Winter 2027 (January - April 2027 work term).") == "hybrid"
        assert c(description="must be located in Seattle for this hybrid position. You will report into") == "hybrid"
        assert c(description="Hybrid model: 3 days a week in the office About our Data Science Teams") == "hybrid"
        assert c(description="Ability to work full-time, on-site five days per week, for one year.") == "onsite"
        # Real statements behind Canadian early-career postings that used to stay "unspecified"
        assert c(description="D2L operates in a hybrid work style, with expectation of 3 days per week in office.") == "hybrid"
        assert c(description="Amazon internships are full-time and interns should expect to work in office, Monday-Friday, up to 40 hours.") == "onsite"
        assert c(description="You'll work in a hybrid environment with the expectation to be onsite at least two days per week") == "hybrid"

    def test_single_ats_tag_counts_but_conflicting_tags_do_not(self):
        from ingestion.normalizer import classify_workplace as c

        assert c(description="... www.nvidiabenefits.com/ #LI-Hybrid Your base salary will be determined") == "hybrid"
        assert c(description="#LI-Remote") == "remote"
        assert c(description="Canada-wide. #LI-Hybrid #LI-remote The Base Pay range is") == "unspecified"

    def test_company_wide_or_technical_mentions_stay_unspecified(self):
        from ingestion.normalizer import classify_workplace as c

        for text in (
            "As a hybrid organization, you and your leader choose",
            "We operate as a hybrid workplace to ensure our employees",
            "Location-based hybrid policy: Currently, we expect all staff to be in one of our offices",
            "Hybrid Retrieval: Balancing traditional keyword-based search",
            "public cloud platforms (AWS, Azure, GCP) in hybrid or multi-cloud environments",
            "remote caching and execution, CI observability",
            "we run a hybrid cloud platform; on-call rotation covers 4 days per week in production",
            "Our team expects to work in office hours overlapping with Pacific time",
            "Notice to Applicants for Jobs Located in NYC or Remote Jobs Associated With Office in NYC",
        ):
            assert c(description=text) == "unspecified", text
