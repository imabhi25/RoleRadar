"""Bell's public Phenom-rendered job data, paged without executing site scripts."""
from urllib.parse import urlsplit

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.clients.careers_html import phenom_data, source_date
from ingestion.http_client import IngestionFetchError

ROOT = "https://jobs.bell.ca/ca/en/"


class PhenomClient(BaseATSClient):
    MAX_PAGES = 100

    def fetch_jobs(self, company_name, identifier):
        if identifier != "bell":
            raise ValueError("Only Bell's verified Phenom source is supported")
        jobs, seen = [], set()
        offset = errors = count = 0
        total = None
        complete = True
        for _ in range(self.MAX_PAGES):
            try:
                data = phenom_data(self.http_client.get(ROOT + "search-results", params={"from": offset, "s": 1}).text)
                result = data.get("eagerLoadRefineSearch", {}) if isinstance(data, dict) else {}
                rows = result.get("data", {}).get("jobs")
                current = result.get("totalHits")
                if not isinstance(rows, list) or not isinstance(current, int) or result.get("status") != 200:
                    raise IngestionFetchError("Bell search data missing")
                if total is None:
                    total = current
                elif total != current:
                    complete = False
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
                if not isinstance(row, dict) or not row.get("jobSeqNo") or not row.get("jobId") or not row.get("title") or not row.get("description"):
                    errors += 1
                    continue
                job_id = str(row["jobId"])
                if job_id in seen:
                    complete = False
                    continue
                seen.add(job_id)
                # This is the official site's documented /job/:jobSeqNo route, not a search or company page.
                seq = row["jobSeqNo"]
                if not isinstance(seq, str) or not seq.isalnum():
                    errors += 1
                    continue
                url = ROOT + "job/" + seq
                if urlsplit(url).hostname != "jobs.bell.ca":
                    errors += 1
                    continue
                locations = [{"location": x["location"], "country": row.get("country", "")} for x in row.get("multi_location_array", []) if isinstance(x, dict) and x.get("location")]
                jobs.append(RawJobPosting("phenom", "bell:" + job_id, company_name, row["title"],
                                          row.get("location", ""), url, source_date(row.get("postedDate")), row["description"],
                                          raw_job_type=row.get("type"), company_apply_url=url, raw_locations=locations,
                                          # A student talent community is not an available internship placement.
                                          # Future vacancies with actual recruiting are still legitimate postings.
                                          is_listed=not ("future opportunities" in row["title"].lower()
                                                         and "talent community" in row["description"].lower())))
            offset += len(rows)
            if offset >= total:
                break
        else:
            complete = False
        return FetchResult(jobs, errors, complete and count == total and len(jobs) == count and errors == 0, count)
