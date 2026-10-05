"""Google's official Canada careers search, using public rendered HTML.

Counts, duplicate IDs, changing pagination and failed details all suppress closure.
Google does not expose posting dates here: leave them unknown, never date them today.
"""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.http_client import IngestionFetchError

ROOT = "https://www.google.com/about/careers/applications/"


class GoogleClient(BaseATSClient):
    MAX_PAGES = 100

    def fetch_jobs(self, company_name, identifier):
        if identifier != "Canada":
            raise ValueError("Google adapter currently supports the complete Canada search slice")
        jobs, seen = [], set()
        count = 0
        errors = 0
        total = None
        complete = True
        for page in range(1, self.MAX_PAGES + 1):
            try:
                response = self.http_client.get(ROOT + "jobs/results/", params={"location": identifier, "page": page})
                soup = BeautifulSoup(response.text, "html.parser")
                matched = re.search(r"([\d,]+)\s+jobs matched", soup.get_text(" ", strip=True))
                if not matched:
                    raise IngestionFetchError("Google results count missing")
                current = int(matched[1].replace(",", ""))
                if total is None:
                    total = current
                elif current != total:
                    complete = False
                rows = [li for li in soup.select("li") if li.select_one('a[href*="jobs/results/"]')]
                if not rows and total:
                    complete = False
                    break
            except IngestionFetchError:
                if page == 1:
                    raise
                complete = False
                break
            count += len(rows)
            for row in rows:
                link = row.select_one('a[href*="jobs/results/"]')
                url = urljoin(ROOT, link["href"])
                match = re.search(r"/results/(\d+)-", urlsplit(url).path)
                title = row.select_one("h3")
                if not match or not title or urlsplit(url).hostname != "www.google.com":
                    errors += 1
                    continue
                job_id = match[1]
                if job_id in seen:
                    complete = False
                    continue
                seen.add(job_id)
                locations = list(dict.fromkeys(
                    label for x in row.select(".r0wTof")
                    if (label := x.get_text(" ", strip=True).strip(" ;")) and any(c.isalpha() for c in label)
                    and not re.fullmatch(r"\+?\d+\s+more", label, re.I)
                ))
                # These are actual source labels, including secondary Canadian locations.
                raw_locations = [{"location": loc} for loc in locations if loc]
                job = RawJobPosting("google", job_id, company_name, title.get_text(" ", strip=True),
                                    locations[0] if locations else "", url, None, "",
                                    company_apply_url=url, raw_locations=raw_locations)
                if "Remote eligible" in row.get_text(" ", strip=True):
                    job.raw_workplace_type = "remote"
                try:
                    detail = BeautifulSoup(self.http_client.get(url).text, "html.parser")
                    about = next((h for h in detail.find_all("h3") if h.get_text(strip=True) == "About the job"), None)
                    if not about:
                        raise IngestionFetchError("Google job detail missing")
                    container = about.parent.parent
                    # Include qualifications, job prose, responsibilities, accommodations and legal text in source order.
                    pieces = container.select(".KwJkGe, .aG5W3, .BDNOWe, .bE3reb")
                    if not pieces or not any("Responsibilities" in x.get_text() for x in pieces):
                        raise IngestionFetchError("Google description structure changed")
                    for piece in pieces:
                        # Callout icons and their decorative close glyph are site chrome.
                        # Keep the actual announcement (dates, interviews, eligibility) intact.
                        for chrome in piece.select(".google-material-icons, .v7dlUb"):
                            chrome.decompose()
                        for anchor in piece.select("a[href]"):
                            # Google's <base> is the applications root. Resolve employer-provided
                            # relative links before the frontend sanitizer rejects them.
                            href = anchor["href"]
                            if not urlsplit(href).scheme:
                                anchor["href"] = urljoin(ROOT, href)
                    job.raw_description = "".join(str(x) for x in pieces)
                except IngestionFetchError:
                    complete = False
                    errors += 1
                    # A listed-but-unreadable role must not overwrite its previously complete description.
                    continue
                jobs.append(job)
            next_page = soup.select_one('a[aria-label="Go to next page"]')
            if not next_page:
                next_page = next((a for a in soup.select('a[href]') if f"page={page + 1}" in a["href"]), None)
            if not next_page:
                break
        else:
            complete = False
        return FetchResult(jobs, errors, complete and count == total and len(jobs) == count and errors == 0, count)
