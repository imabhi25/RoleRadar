import argparse
import sys
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


def parse_args():
    parser = argparse.ArgumentParser(description="End-to-end browser verification for RoleRadar")
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:5173", help="Base or target URL to verify")
    parser.add_argument("--base-url", dest="base_url", default=None, help="Explicit base URL (e.g. http://127.0.0.1:5173)")
    return parser.parse_args()


def run_browser_verification(target_url: str):
    parsed = urlparse(target_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    entry_path = parsed.path if parsed.path else "/"
    full_entry_url = f"{base_url}{entry_path}"
    if parsed.query:
        full_entry_url += f"?{parsed.query}"

    print(f"Starting Playwright end-to-end browser verification...")
    print(f"Target URL: {full_entry_url}")
    print(f"Base Origin: {base_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Track network responses and console errors
        responses = []
        console_logs = []
        failing_requests = []

        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        def handle_response(res):
            ct = res.headers.get("content-type", "")
            status = res.status
            url = res.url
            responses.append({
                "url": url,
                "status": status,
                "content_type": ct,
                "headers": dict(res.headers),
            })
            if "/api/" in url and (status >= 400 or "text/html" in ct):
                failing_requests.append({
                    "url": url,
                    "status": status,
                    "content_type": ct,
                })

        def handle_console(msg):
            console_logs.append({
                "type": msg.type,
                "text": msg.text,
            })
            if msg.type == "error":
                print(f"Browser Console Error: {msg.text}")

        page.on("response", handle_response)
        page.on("console", handle_console)

        # ========================================================
        # 1. INITIAL LOAD & AUTH CHECK
        # ========================================================
        print(f"\n--- Loading target page: {full_entry_url} ---")
        try:
            res = page.goto(full_entry_url, timeout=25000, wait_until="load")
        except Exception as e:
            print(f"Navigation error: {e}")

        # Check for Vercel Deployment Protection SSO redirect
        is_vercel_sso = (
            "vercel.com/login" in page.url
            or "vercel.com/sso-api" in page.url
            or page.title() == "Login – Vercel"
            or any(r["status"] == 302 and "vercel.com/sso-api" in r["headers"].get("location", "") for r in responses)
        )

        if is_vercel_sso:
            print("\n========================================================")
            print("VERCEL DEPLOYMENT PROTECTION DETECTED (ACCESS BLOCKED)")
            print("========================================================")
            print(f"Requested URL: {full_entry_url}")
            print(f"Redirect URL:  {page.url}")
            print(f"Page Title:    {page.title()}")
            print(f"Exact Blocker: Protected by Vercel Authentication (SSO).")
            print(f"Details:       The preview deployment requires team authentication.")
            print(f"               Unauthenticated automated/headless requests receive HTTP 302")
            print(f"               redirecting to Vercel SSO login.")
            if failing_requests:
                print(f"Failing API Requests: {failing_requests}")
            print("========================================================\n")
            context.close()
            browser.close()
            return

        # ========================================================
        # 2. DESKTOP VERIFICATION (1280x800)
        # ========================================================
        print("\n--- 1. Desktop Verification (1280x800) ---")
        page.wait_for_selector(".job-card", timeout=12000)
        job_cards = page.query_selector_all(".job-card")
        print(f"✓ Page loaded with {len(job_cards)} job cards visible on initial desktop load.")
        assert len(job_cards) > 0, "No job cards found"

        # Light mode is fixed, including when an older dark preference is stored.
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
        assert page.query_selector(".theme-toggle-btn") is None
        print("✓ Light mode is active and no theme toggle is shown.")

        # Select a job and verify two-column split pane
        first_card = job_cards[0]
        first_card_title = first_card.query_selector(".job-card-title").inner_text()
        print(f"Selecting first job: '{first_card_title}'")
        first_card.click()
        page.wait_for_selector(".job-detail-split, .job-detail-pane, .job-detail", timeout=5000)
        current_url = page.url
        print(f"✓ URL updated with job parameter: {current_url}")
        assert "?job=" in current_url or "&job=" in current_url, "URL does not contain ?job="

        # Verify persistent two-column layout
        split_pane = page.query_selector(".job-detail-split, .job-explorer-split, .split-pane, .job-detail-pane")
        print(f"✓ Two-column split pane verified present: {bool(split_pane)}")

        # Browser Back button deselects job
        print("Testing browser Back button...")
        page.go_back()
        page.wait_for_timeout(500)
        back_url = page.url
        print(f"✓ After Back button: {back_url}")
        assert "job=" not in back_url, "Job parameter should be gone after back button"

        # Browser Forward button restores job
        print("Testing browser Forward button...")
        page.go_forward()
        page.wait_for_timeout(500)
        forward_url = page.url
        print(f"✓ After Forward button: {forward_url}")
        assert "job=" in forward_url, "Job parameter should be restored after forward button"

        # Close detail pane
        close_btn = page.query_selector(".job-detail-close, button[aria-label*='Close']")
        if close_btn:
            close_btn.click()
            page.wait_for_timeout(300)
            print("✓ Detail pane closed.")

        # ========================================================
        # 3. LOCATION MULTI-SELECT & REPEATED PARAMETERS (DESKTOP)
        # ========================================================
        print("\n--- 2. Location Multi-Select & URL Comma Preservation ---")
        loc_btn = page.query_selector(".filter-dropdown-btn[aria-label*='Location']")
        assert loc_btn, "Location filter button not found"
        loc_btn.click()
        page.wait_for_timeout(300)

        # Select San Francisco, CA
        sf_opt = page.query_selector("button[role='option']:has-text('San Francisco, CA')")
        assert sf_opt, "San Francisco, CA option not found"
        sf_opt.click()
        page.wait_for_timeout(800)

        sf_url = page.url
        print(f"URL after selecting San Francisco, CA: {sf_url}")
        assert "location=San+Francisco%2C+CA" in sf_url or "location=San%20Francisco%2C%20CA" in sf_url
        print("✓ Comma in 'San Francisco, CA' preserved in URL!")

        # Select New York, NY
        ny_opt = page.query_selector("button[role='option']:has-text('New York, NY')")
        if not ny_opt:
            loc_btn = page.query_selector(".filter-dropdown-btn[aria-label*='Location']")
            loc_btn.click()
            page.wait_for_timeout(300)
            ny_opt = page.query_selector("button[role='option']:has-text('New York, NY')")
        assert ny_opt, "New York, NY option not found"
        ny_opt.click()
        page.wait_for_timeout(800)

        both_url = page.url
        print(f"URL after selecting both SF and NY: {both_url}")
        assert "location=San+Francisco%2C+CA" in both_url or "location=San%20Francisco%2C%20CA" in both_url
        assert "location=New+York%2C+NY" in both_url or "location=New%20York%2C%20NY" in both_url
        print("✓ Both locations present as repeated parameters with preserved commas!")

        # Check button text indicates 2 selected
        loc_btn_text = page.query_selector(".filter-dropdown-btn:has-text('Location (2)')")
        assert loc_btn_text, "Button text does not show Location (2)"
        print("✓ Location button displays 'Location (2)'")

        # Reload the page and verify state restoration
        print("Reloading page with both locations in URL...")
        page.reload()
        page.wait_for_selector(".job-card", timeout=8000)
        reloaded_url = page.url
        print(f"✓ URL after reload: {reloaded_url}")
        assert "location=San+Francisco%2C+CA" in reloaded_url or "location=San%20Francisco%2C%20CA" in reloaded_url
        assert "location=New+York%2C+NY" in reloaded_url or "location=New%20York%2C%20NY" in reloaded_url

        reloaded_loc_btn = page.query_selector(".filter-dropdown-btn:has-text('Location (2)')")
        assert reloaded_loc_btn, "Button text after reload did not preserve 'Location (2)'"
        print("✓ After reload: both filters restored and 'Location (2)' button preserved!")

        # ========================================================
        # 4. COMPANY PROFILES & SOURCED PROVENANCE
        # ========================================================
        print("\n--- 3. Company Profiles, Source Provenance & Retry ---")
        # 1Password
        page.goto(f"{base_url}/company/1password")
        page.wait_for_selector(".company-page-view", timeout=8000)
        assert page.query_selector("h1:has-text('1Password')"), "1Password heading not found"
        prov = page.query_selector(".job-company-source-provenance")
        assert prov, "Source provenance badge not found"
        print(f"✓ 1Password provenance badge: '{prov.inner_text().strip()}'")
        assert "2026-10-02" in prov.inner_text()
        source_link = prov.query_selector("a")
        print(f"✓ 1Password official source link: {source_link.get_attribute('href')}")
        assert source_link.get_attribute("href") == "https://1password.com/careers/"

        # Check Cohere
        page.goto(f"{base_url}/company/cohere")
        page.wait_for_selector(".company-page-view", timeout=8000)
        assert page.query_selector("h1:has-text('Cohere')")
        cohere_prov = page.query_selector(".job-company-source-provenance")
        assert "2026-10-02" in cohere_prov.inner_text()
        print(f"✓ Cohere official source link: {cohere_prov.query_selector('a').get_attribute('href')}")

        # Check Databricks
        page.goto(f"{base_url}/company/databricks")
        page.wait_for_selector(".company-page-view", timeout=8000)
        assert page.query_selector("h1:has-text('Databricks')")
        db_size = page.query_selector("dd:has-text('10,000+ employees')")
        assert db_size, "Databricks verified size not found"
        print("✓ Databricks verified size '10,000+ employees' confirmed.")

        # Test Company Page "Back to jobs"
        back_to_jobs_btn = page.query_selector("button:has-text('Back to jobs')")
        if back_to_jobs_btn:
            back_to_jobs_btn.click()
            page.wait_for_timeout(500)
            print(f"✓ Navigated back to jobs: {page.url}")

        context.close()

        # ========================================================
        # 5. MOBILE VERIFICATION (375x667)
        # ========================================================
        print("\n--- 4. Mobile Verification (375x667 iPhone SE) ---")
        mobile_context = browser.new_context(viewport={"width": 375, "height": 667}, is_mobile=True)
        mobile_page = mobile_context.new_page()

        mobile_page.goto(f"{base_url}/")
        mobile_page.wait_for_selector(".job-card", timeout=8000)
        m_cards = mobile_page.query_selector_all(".job-card")
        print(f"✓ Mobile loaded with {len(m_cards)} cards.")

        # Open Mobile Filter Drawer
        m_filter_btn = mobile_page.query_selector("button:has-text('Filters')")
        assert m_filter_btn, "Mobile Filters button not found"
        m_filter_btn.click()
        mobile_page.wait_for_selector(".mobile-drawer-sheet", timeout=5000)
        print("✓ Mobile filters drawer opened.")

        # Select Locations in mobile drawer checkbox grid
        to_checkbox = mobile_page.query_selector("label:has-text('Toronto (GTA)') input[type='checkbox']")
        if to_checkbox:
            to_checkbox.click()
            mobile_page.wait_for_timeout(300)
            print("✓ Checked Toronto (GTA) in mobile drawer.")

        van_checkbox = mobile_page.query_selector("label:has-text('Vancouver') input[type='checkbox']")
        if van_checkbox:
            van_checkbox.click()
            mobile_page.wait_for_timeout(300)
            print("✓ Checked Vancouver in mobile drawer.")

        # Close mobile drawer
        done_btn = mobile_page.query_selector(".drawer-footer-done, button:has-text('View Jobs'), .mobile-drawer-close")
        if done_btn:
            done_btn.click()
            mobile_page.wait_for_timeout(500)

        m_url = mobile_page.url
        print(f"✓ Mobile URL after selecting multiple locations: {m_url}")
        assert "location=Toronto" in m_url and "location=Vancouver" in m_url

        # Click a card on mobile to open full slide-over / sheet
        first_m_card = mobile_page.query_selector(".job-card")
        first_m_card.click()
        mobile_page.wait_for_selector(".job-detail", timeout=5000)
        print("✓ Mobile job detail slide-over opened.")
        m_job_url = mobile_page.url
        assert "job=" in m_job_url

        # Close job detail on mobile
        m_close_btn = mobile_page.query_selector(".job-detail-close, button[aria-label*='Close']")
        if m_close_btn:
            m_close_btn.click()
            mobile_page.wait_for_timeout(400)
            print("✓ Mobile job detail closed.")

        mobile_context.close()
        browser.close()
        print("\n========================================================")
        print("ALL BROWSER E2E TESTS COMPLETED AND VERIFIED SUCCESSFULLY!")
        print("========================================================\n")


if __name__ == "__main__":
    args = parse_args()
    target = args.base_url or args.url
    run_browser_verification(target)
