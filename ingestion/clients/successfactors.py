"""Reusable official SuccessFactors HTML search for Rogers, Scotiabank and TELUS."""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.clients.careers_html import needs_detail, source_date
from ingestion.http_client import IngestionFetchError

SITES = {"rogers": "https://jobs.rogers.com", "scotiabank": "https://jobs.scotiabank.com", "telus": "https://careers.telus.com"}


class SuccessFactorsClient(BaseATSClient):
    MAX_PAGES = 200

    def fetch_jobs(self, company_name, identifier):
        if identifier not in SITES:
            raise ValueError("Unknown verified SuccessFactors employer")
        root = SITES[identifier]
        jobs, seen = [], set()
        total = None
        offset = errors = count = 0
        complete = True
        for _ in range(self.MAX_PAGES):
            try:
                response = self.http_client.get(root + "/search/", params={"q": "", "startrow": offset, "sortColumn": "referencedate", "sortDirection": "desc"})
                soup = BeautifulSoup(response.text, "html.parser")
                match = re.search(r"Results\s+\d+\s*[–-]\s*\d+\s+of\s+([\d,]+)", soup.get_text(" ", strip=True))
                if not match:
                    raise IngestionFetchError("SuccessFactors result count missing")
                current = int(match[1].replace(",", ""))
                if total is None:
                    total = current
                elif total != current:
                    complete = False
                rows = soup.select("tr.data-row")
                if not rows:
                    if total:
                        complete = False
                    break
            except IngestionFetchError:
                if offset == 0:
                    raise
                complete = False
                break
            count += len(rows)
            for row in rows:
                link = row.select_one("a.jobTitle-link")
                if not link:
                    errors += 1
                    continue
                url = urljoin(root, link.get("href", ""))
                match = re.search(r"/job/.+/(\d+)/?$", urlsplit(url).path)
                if not match or urlsplit(url).hostname != urlsplit(root).hostname:
                    errors += 1
                    continue
                job_id = identifier + ":" + match[1]  # Tenant-scoped ID; never collide across employers.
                if job_id in seen:
                    complete = False
                    continue
                seen.add(job_id)
                title = link.get_text(" ", strip=True)
                loc = row.select_one("td.colLocation .jobLocation") or row.select_one(".jobLocation")
                date = row.select_one("td.colDate .jobDate") or row.select_one(".jobDate")
                job = RawJobPosting("successfactors", job_id, company_name, title,
                                    loc.get_text(" ", strip=True) if loc else "", url,
                                    source_date(date.get_text(strip=True)) if date else None, "", company_apply_url=url)
                if needs_detail(title):
                    try:
                        detail = BeautifulSoup(self.http_client.get(url).text, "html.parser")
                        description = detail.select_one('[itemprop="description"]')
                        if not description or not description.get_text(strip=True):
                            raise IngestionFetchError("SuccessFactors description missing")
                        job.raw_description = description.decode_contents()
                        locations = []
                        for address in detail.select('[itemprop="jobLocation"] [itemprop="address"]'):
                            def field(key):
                                el = address.select_one(f'[itemprop="{key}"]')
                                return (el.get("content") or el.get_text(strip=True)) if el else ""
                            label = ", ".join(x for x in [field("addressLocality"), field("addressRegion"), field("addressCountry")] if x)
                            if label:
                                locations.append({"location": label, "country": field("addressCountry")})
                        if locations:
                            job.raw_location = locations[0]["location"]
                            job.raw_locations = locations
                    except IngestionFetchError:
                        errors += 1
                        complete = False
                        continue
                jobs.append(job)
            offset += len(rows)
            if offset >= total:
                break
        else:
            complete = False
        return FetchResult(jobs, errors, complete and count == total and len(jobs) == count and errors == 0, count)
