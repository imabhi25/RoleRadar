"""Startup branding audits must not erase independently sourced employer domains."""
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from api.database import get_db_connection
from ingestion.company_resolver import resolve_company_branding, seed_and_audit_all_target_companies


def test_resolving_an_existing_unresolved_logo_preserves_its_official_website():
    cur = MagicMock()
    cur.fetchone.return_value = (1, "Future Employer", None, None, "unresolved", "https://future-employer.example")
    branding = resolve_company_branding("Future Employer", cur=cur)
    assert branding["logo_url"] is None and branding["logo_status"] == "unresolved"
    assert branding["website_url"] == "https://future-employer.example"


def test_ats_logo_discovery_does_not_remove_the_existing_company_website():
    cur = MagicMock()
    cur.fetchone.return_value = (1, "Future Employer", None, None, "unresolved", "https://future-employer.example")
    discovered = {"name": "Future Employer", "logo_url": "/logos/future.png", "logo_source_url": "https://ats.example/verified-logo.png", "logo_status": "verified", "website_url": None}
    with patch("ingestion.company_resolver._discover_ats_branding", return_value=discovered):
        branding = resolve_company_branding("Future Employer", ats_type="ashby", identifier="future-employer", cur=cur)
    assert branding["logo_status"] == "verified"
    assert branding["website_url"] == "https://future-employer.example"


@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    yield connection
    connection.rollback()
    connection.close()


@pytest.mark.parametrize("name,website,expected", [
    ("Safe New Employer", "https://future-employer.example", "https://future-employer.example"),
    ("Safe New Employer", None, None),
    ("RBC", "https://previous-employer-domain.example", "https://rbc.com"),
])
def test_repeated_startup_audits_preserve_independent_sites_or_apply_verified_catalog_replacements(conn, tmp_path, name, website, expected):
    config = tmp_path / "config"
    config.mkdir()
    (config / "target_companies.json").write_text("[]")
    name += " (website regression " + uuid4().hex + ")"
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name, logo_status, website_url) VALUES (%s, 'unresolved', %s) RETURNING id", (name, website))
        cid = cur.fetchone()[0]
        wrapped = MagicMock(spec=cur, wraps=cur)
        wrapped.fetchall.side_effect = lambda: [row for row in cur.fetchall() if row[0] == cid]
        wrapped.connection = None  # keep the verification transaction rollback-only
        with patch("ingestion.company_resolver.PROJECT_ROOT", tmp_path):
            # Catalog asset resolution uses PROJECT_ROOT; point it at the existing public asset tree.
            (tmp_path / "frontend").symlink_to(Path(__file__).resolve().parent.parent / "frontend", target_is_directory=True)
            seed_and_audit_all_target_companies(wrapped)
            seed_and_audit_all_target_companies(wrapped)
        cur.execute("SELECT website_url FROM companies WHERE id = %s", (cid,))
        assert cur.fetchone()[0] == expected
