"""Rejected logo bytes must not survive a migration or a later branding audit."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.database import get_db_connection
from api.main import app
from ingestion.company_resolver import (
    VERIFIED_COMPANY_CATALOG,
    invalidate_rejected_logo,
    resolve_company_branding,
    seed_and_audit_all_target_companies,
)

ROOT = Path(__file__).resolve().parent.parent
REJECTED = (ROOT / "tests/fixtures/branding/rejected-braze-deliveryhero.svg").read_bytes()
MIGRATION = ROOT / "db/migrations/011_retire_incorrect_braze_logo.sql"
REPLACEMENT = b'<svg xmlns="http://www.w3.org/2000/svg"><title>Independent replacement fixture</title></svg>'


def test_braze_does_not_claim_the_mislabeled_delivery_hero_asset_is_verified():
    assert "braze" not in VERIFIED_COMPANY_CATALOG
    assert not (ROOT / "frontend/public/logos/braze.svg").exists()
    branding = resolve_company_branding("Braze, Inc.")
    assert branding["logo_status"] == "unresolved"
    assert branding["logo_url"] is None and branding["logo_source_url"] is None
    assert branding["website_url"] == "https://www.braze.com"


def test_legacy_local_record_is_not_reused_as_verified_branding():
    cur = MagicMock()
    cur.fetchone.return_value = (75, "Braze", "/logos/braze.svg", "https://www.braze.com", "verified", "https://www.braze.com")
    assert resolve_company_branding("Braze", cur=cur)["logo_status"] == "unresolved"


@pytest.mark.parametrize("name,url,stored", [
    ("Braze", "/api/company-logos/75", REJECTED),
    ("Braze, Inc.", "/logos/braze.svg", None),
])
def test_audit_invalidates_exact_rejected_assets(name, url, stored):
    cur = MagicMock()
    assert invalidate_rejected_logo(cur, 75, name, url, stored) is True
    sql, params = cur.execute.call_args.args
    assert "logo_data = NULL" in sql and "logo_status = 'unresolved'" in sql
    assert params == ("https://www.braze.com", 75)


@pytest.mark.parametrize("name,url,stored", [
    ("Braze", "/api/company-logos/75", REPLACEMENT),
    ("Delivery Hero", "/api/company-logos/75", REJECTED),
])
def test_audit_preserves_independent_replacements_and_other_employers(name, url, stored):
    cur = MagicMock()
    assert invalidate_rejected_logo(cur, 75, name, url, stored) is False
    cur.execute.assert_not_called()


@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    yield connection
    connection.rollback()
    connection.close()


def test_migration_clears_existing_bad_cache_and_stops_api_delivery(conn):
    unique = uuid4().hex
    with conn.cursor() as cur:
        # Keep the test transactional while making room for canonical-name fixtures.
        cur.execute("UPDATE companies SET name = name || %s WHERE LOWER(name) IN ('braze', 'braze inc.', 'braze, inc.')", (unique,))
        ids = {}
        for name, data, url in [
            ("Braze", REJECTED, "/api/company-logos/75"),
            ("Braze Inc.", REPLACEMENT, "/api/company-logos/76"),
            ("Braze, Inc.", None, "/logos/braze.svg"),
            ("Delivery Hero fixture " + unique, REJECTED, "/api/company-logos/77"),
        ]:
            cur.execute("""INSERT INTO companies (name, logo_status, logo_url, logo_data, logo_content_type, logo_source_url)
                           VALUES (%s, 'verified', %s, %s, 'image/svg+xml', 'https://www.braze.com') RETURNING id""",
                        (name, url, data))
            ids[name] = cur.fetchone()[0]
        cur.execute(MIGRATION.read_text())
        cur.execute(MIGRATION.read_text())  # idempotent if rerun manually
        for name in ("Braze", "Braze, Inc."):
            cur.execute("SELECT logo_status, logo_url, logo_data, logo_content_type, logo_source_url, website_url FROM companies WHERE id = %s", (ids[name],))
            assert cur.fetchone() == ("unresolved", None, None, None, None, "https://www.braze.com")
        for name, expected in [("Braze Inc.", REPLACEMENT), ("Delivery Hero fixture " + unique, REJECTED)]:
            cur.execute("SELECT logo_status, logo_data FROM companies WHERE id = %s", (ids[name],))
            status, data = cur.fetchone()
            assert status == "verified" and bytes(data) == expected

    @contextmanager
    def cursor():
        with conn.cursor() as cur:
            yield cur
    with patch("api.main.get_db_cursor", cursor):
        assert TestClient(app).get(f"/api/company-logos/{ids['Braze']}").status_code == 404


def test_repeatable_catalog_audit_clears_rejected_bytes_even_without_migration(conn, tmp_path):
    targets = tmp_path / "config"
    targets.mkdir()
    (targets / "target_companies.json").write_text("[]")
    with conn.cursor() as cur:
        # A suffix recognized by normalization lets this coexist with the seeded Braze row.
        name = "Braze (branding regression " + uuid4().hex + ")"
        cur.execute("""INSERT INTO companies (name, logo_status, logo_url, logo_data, logo_content_type)
                       VALUES (%s, 'verified', '/api/company-logos/75', %s, 'image/svg+xml') RETURNING id""", (name, REJECTED))
        cid = cur.fetchone()[0]
        # Isolate the fixture rather than touching existing companies in this transaction.
        wrapped = MagicMock(spec=cur, wraps=cur)
        wrapped.fetchall.return_value = [(cid, name, f"/api/company-logos/{cid}", "verified", REJECTED)]
        wrapped.connection = None
        with patch("ingestion.company_resolver.PROJECT_ROOT", tmp_path):
            result = seed_and_audit_all_target_companies(wrapped)
        assert result["verified_count"] == 0 and name in result["unresolved_companies"]
        cur.execute("SELECT logo_status, logo_data, logo_url FROM companies WHERE id = %s", (cid,))
        assert cur.fetchone() == ("unresolved", None, None)
