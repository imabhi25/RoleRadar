"""Shopify official public posting loader (its generic Ashby board is unavailable)."""
from html import escape
import re

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.clients.careers_html import needs_detail, shopify_loader, source_date
from ingestion.http_client import IngestionFetchError

ORIGIN = "https://www.shopify.com"
ROOT = ORIGIN + "/careers"
UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
POSTING_PATH = re.compile(r"/careers/[a-z0-9-]*_([a-f0-9-]+)")


def _location_index(locations):
    return {loc["id"]: loc for loc in locations if isinstance(loc, dict) and loc.get("id")}


def _posting_locations(posting, locations):
    loc_ids = posting.get("locationIds") or {}
    ids = [loc_ids.get("primaryLocationId")] + (loc_ids.get("secondaryLocationIds") or [])
    result = []
    for loc_id in ids:
        loc = locations.get(loc_id, {})
        label = loc.get("externalName") or loc.get("name")
        address = (loc.get("address") or {}).get("postalAddress") or {}
        if label:
            result.append({"location": label, "country": address.get("addressCountry") or ""})
    return result


class ShopifyClient(BaseATSClient):
    def fetch_jobs(self, company_name, identifier):
        if identifier != "shopify":
            raise ValueError("Invalid Shopify identifier")
        loader = shopify_loader(self.http_client.get(ROOT).text, "($locale)/careers")
        roles = loader.get("roles")
        uses_role_list = isinstance(roles, list)
        rows = roles if uses_role_list else loader.get("jobPostingsWithJobs")
        locations = [] if uses_role_list else loader.get("atsLocations")
        if not isinstance(rows, list) or not isinstance(locations, list):
            raise IngestionFetchError("Shopify public posting list missing")
        location_index = _location_index(locations)
        jobs, seen = [], set()
        errors = 0
        for entry in rows:
            if not isinstance(entry, dict):
                errors += 1
                continue
            row = entry if uses_role_list else entry.get("jobPosting")
            if not isinstance(row, dict):
                errors += 1
                continue
            posting_id, title = row.get("id"), row.get("title")
            if (not isinstance(posting_id, str) or not UUID.fullmatch(posting_id)
                    or not isinstance(title, str) or not title.strip() or posting_id in seen):
                errors += 1
                continue
            seen.add(posting_id)
            if uses_role_list:
                href = row.get("href")
                path = POSTING_PATH.fullmatch(href) if isinstance(href, str) else None
                if not path or path[1] != posting_id:
                    errors += 1
                    continue
                url = ORIGIN + href
            else:
                if row.get("status") != "Published" or row.get("isListed") is not True:
                    continue
                url = ROOT + "/_" + posting_id

            posting = row
            posting_locations = location_index
            description = ""
            if needs_detail(title):
                try:
                    detail = shopify_loader(self.http_client.get(url).text, "($locale)/careers/$posting")
                    public_posting = detail.get("jobPosting")
                    if not isinstance(public_posting, dict) or public_posting.get("id") != posting_id:
                        raise IngestionFetchError("Shopify exact posting missing")
                    description = public_posting.get("descriptionHtml")
                    if not isinstance(description, str) or not description.strip():
                        raise IngestionFetchError("Shopify exact posting description missing")
                    if uses_role_list:
                        if public_posting.get("status") != "Published" or public_posting.get("isListed") is not True:
                            raise IngestionFetchError("Shopify role is no longer listed")
                        posting = public_posting
                        detail_locations = detail.get("locations")
                        if isinstance(detail_locations, list):
                            posting_locations = _location_index(detail_locations)
                except IngestionFetchError:
                    errors += 1
                    continue

            raw_locations = _posting_locations(posting, posting_locations)
            if uses_role_list and not raw_locations and isinstance(row.get("locations"), list):
                raw_locations = [{"location": label} for label in row["locations"] if isinstance(label, str) and label]
            # Shopify explicitly distinguishes US internships in the posting title.
            # "Americas" / "Global" alone never establishes eligibility in Canada or the US.
            if re.match(r"^US .+ Internships\b", title):
                raw_locations.insert(0, {"location": "United States", "country": "United States"})
            job = RawJobPosting(
                "shopify", posting_id, company_name, title,
                posting.get("locationExternalName") or posting.get("locationName") or row.get("location") or "",
                url, source_date(posting.get("publishedDate")), description,
                raw_workplace_type=posting.get("workplaceType"), raw_job_type=posting.get("employmentType"),
                company_apply_url=url, raw_locations=raw_locations,
            )
            if description:
                deadline = posting.get("applicationDeadline")
                if deadline:
                    # Preserve the explicit employer deadline separately from the posting date.
                    job.raw_description += "<p>Application Deadline: " + escape(str(deadline)) + "</p>"
                summary = posting.get("compensationTierSummary") if posting.get("shouldDisplayCompensationOnJobBoard") else None
                compensation = posting.get("compensation") or {}
                display = compensation.get("displaySettings") or {}
                if display.get("shouldShowOnJobPostings") or display.get("shouldShowOnJobBoard"):
                    summary = compensation.get("compensationTierSummary") or summary
                if summary:
                    job.compensation = {"compensationTierSummary": summary}
                    if isinstance(summary, str) and summary not in job.raw_description:
                        job.raw_description += "<p>" + escape(summary) + "</p>"
            jobs.append(job)
        return FetchResult(jobs, errors, errors == 0, len(rows))
