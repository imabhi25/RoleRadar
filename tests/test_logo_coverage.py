"""Registry companies only claim verified branding when a real asset is available."""
from contextlib import contextmanager
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.database import get_db_connection
from api.main import app
from ingestion.company_resolver import (
    LOGOS_DIR,
    VERIFIED_COMPANY_CATALOG,
    normalize_company_name,
    persist_logo_asset,
    resolve_company_branding,
)

ROOT = Path(__file__).resolve().parent.parent
TARGETS = json.loads((ROOT / "config" / "target_companies.json").read_text())
PRIORITY = ["Amazon", "RBC", "TD", "BMO", "CIBC", "Manulife", "Sun Life", "Ontario Teachers' Pension Plan",
            "Thomson Reuters", "Autodesk", "NVIDIA", "Arctic Wolf", "Geotab", "D2L", "Hootsuite"]
MIME = {".svg", ".png", ".jpg", ".jpeg", ".webp"}


@pytest.mark.parametrize("company", [t["name"] for t in TARGETS])
def test_every_registry_company_has_verified_servable_branding_or_an_honest_fallback(company):
    with patch("ingestion.company_resolver._discover_ats_branding", return_value=None):
        branding = resolve_company_branding(company)
    if normalize_company_name(company) == "braze":
        assert branding["logo_status"] == "unresolved" and branding["logo_url"] is None
        assert branding["logo_source_url"] is None and branding["website_url"] == "https://www.braze.com"
        return
    assert branding["logo_status"] == "verified", f"{company} has no verified logo"
    asset = LOGOS_DIR / branding["logo_url"].removeprefix("/logos/")
    assert asset.is_file() and 0 < asset.stat().st_size <= 2_000_000
    assert asset.suffix.lower() in MIME
    if asset.suffix.lower() == ".svg":
        text = asset.read_text(errors="ignore").lower()
        assert "<svg" in text and "<script" not in text and "javascript:" not in text
    assert branding["logo_source_url"].startswith("https://")
    assert branding["website_url"].startswith("https://")


def test_priority_companies_are_in_the_verified_catalog_with_provenance():
    for name in PRIORITY:
        entry = VERIFIED_COMPANY_CATALOG[normalize_company_name(name)]
        assert entry["logo_status"] == "verified"
        # official employer site/ATS asset, or the Wikimedia Commons brand file used elsewhere in the catalog
        assert entry["logo_source_url"].startswith(("https://commons.wikimedia.org/", "https://www.", "https://arcticwolf.com/", "https://boards.greenhouse.io/"))


@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    yield connection
    connection.rollback()
    connection.close()


def test_logo_bytes_are_persisted_in_postgres_and_served_by_the_api(conn):
    """Durable storage: the bytes live in the database, not on a worker's disk."""
    name = "Logo Fixture " + uuid4().hex[:8]
    branding = resolve_company_branding("RBC")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", (name,))
        cid = cur.fetchone()[0]
        persist_logo_asset(cur, cid, branding)
        cur.execute("SELECT logo_url, length(logo_data), logo_content_type FROM companies WHERE id=%s", (cid,))
        url, size, mime = cur.fetchone()
    assert url == f"/api/company-logos/{cid}" and size > 0 and mime == "image/svg+xml"
    with conn.cursor() as cur:
        cur.execute("UPDATE companies SET logo_status='verified' WHERE id=%s", (cid,))

    @contextmanager
    def cursor():
        with conn.cursor() as c:
            yield c
    with patch("api.main.get_db_cursor", cursor):
        response = TestClient(app).get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["x-content-type-options"] == "nosniff"
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "sandbox" in csp
    # brand SVGs colour paths with inline style attributes, so the CSP must not strip them
    assert "style-src 'unsafe-inline'" in csp
    assert "script-src" not in csp and "'unsafe-eval'" not in csp
    assert response.content.startswith(b"<?xml") or b"<svg" in response.content[:400]


def test_unresolvable_company_is_unverified_not_faked():
    with patch("ingestion.company_resolver._discover_ats_branding", return_value=None):
        branding = resolve_company_branding("Definitely Not A Real Employer " + uuid4().hex[:6])
    assert branding["logo_status"] == "unresolved" and branding["logo_url"] is None


# --------------------------------------------------------------------------- theme-independent assets (Wealthsimple regression)

from ingestion.company_resolver import refresh_persisted_logo_if_stale  # noqa: E402


def _catalog_svgs():
    for key, entry in VERIFIED_COMPANY_CATALOG.items():
        path = LOGOS_DIR / entry["logo_url"].removeprefix("/logos/")
        if path.suffix.lower() == ".svg" and path.is_file():
            yield key, path


@pytest.mark.parametrize("key,path", list(_catalog_svgs()), ids=[k for k, _ in _catalog_svgs()])
def test_svg_logos_render_the_same_regardless_of_os_theme_or_csp(key, path):
    """
    An SVG that switches colour with prefers-color-scheme follows the OS theme, not RoleRadar's theme, and is invisible
    whenever the two disagree (and when a strict CSP drops its <style>). Marks must use fixed, explicit fills.
    """
    svg = path.read_text(errors="ignore")
    assert "prefers-color-scheme" not in svg, f"{key} adapts to the OS theme"
    assert "currentColor" not in svg, f"{key} depends on inherited colour"


def test_wealthsimple_has_a_verified_fixed_colour_logo_persisted_durably(conn):
    branding = resolve_company_branding("Wealthsimple")
    assert branding["logo_status"] == "verified" and branding["logo_url"] == "/logos/wealthsimple.svg"
    svg = (LOGOS_DIR / "wealthsimple.svg").read_text()
    assert 'fill="#1c1b1b"' in svg and "<style" not in svg and "prefers-color-scheme" not in svg
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", ("WS fixture " + uuid4().hex[:6],))
        cid = cur.fetchone()[0]
        # a database that still holds the old theme-dependent bytes is refreshed from the corrected catalog file
        old = b'<svg xmlns="http://www.w3.org/2000/svg"><style>@media (prefers-color-scheme: dark){.w{fill:#fff}}</style><path class="w" d="M0 0h9v9z"/></svg>'
        assert refresh_persisted_logo_if_stale(cur, cid, "Wealthsimple", old) is True
        cur.execute("SELECT logo_data, logo_content_type, logo_status, logo_url FROM companies WHERE id=%s", (cid,))
        data, mime, status, url = cur.fetchone()
        assert bytes(data) == (LOGOS_DIR / "wealthsimple.svg").read_bytes() and mime == "image/svg+xml"
        assert status == "verified" and url == f"/api/company-logos/{cid}"
        # up-to-date logos are left alone, and companies with no catalog file are never touched
        assert refresh_persisted_logo_if_stale(cur, cid, "Wealthsimple", bytes(data)) is False
        assert refresh_persisted_logo_if_stale(cur, cid, "Not In The Catalog " + uuid4().hex[:6], b"x") is False


def test_rbc_uses_the_current_official_blue_and_gold_shield_from_rbc_com(conn):
    branding = resolve_company_branding("RBC")
    assert branding["logo_status"] == "verified" and branding["logo_url"] == "/logos/rbc.svg"
    assert branding["logo_source_url"] == "https://www.rbc.com/dvl/v1.0/assets/images/logos/rbc-logo-shield-blue.svg"
    assert "wikimedia" not in branding["logo_source_url"]
    svg = (LOGOS_DIR / "rbc.svg").read_text()
    assert 'fill="#0059b3"' in svg and 'fill="#ffdf01"' in svg          # RBC blue + gold lion and globe
    assert "#22821e" not in svg                                          # the retired green mark
    assert "prefers-color-scheme" not in svg
    # a production row still holding the old green bytes is replaced from the catalog file on the next seed
    old_green = b'<svg xmlns="http://www.w3.org/2000/svg"><path fill="#22821e" d="M0 0h9v9z"/></svg>'
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", ("RBC fixture " + uuid4().hex[:6],))
        cid = cur.fetchone()[0]
        assert refresh_persisted_logo_if_stale(cur, cid, "RBC", old_green) is True
        cur.execute("SELECT logo_data, logo_content_type, logo_source_url FROM companies WHERE id=%s", (cid,))
        data, mime, source = cur.fetchone()
        assert bytes(data) == (LOGOS_DIR / "rbc.svg").read_bytes() and mime == "image/svg+xml"
        assert source == branding["logo_source_url"]
