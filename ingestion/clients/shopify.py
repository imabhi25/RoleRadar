"""Shopify official public posting loader (its generic Ashby board is unavailable)."""
import re

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.clients.careers_html import needs_detail, shopify_loader, source_date
from ingestion.http_client import IngestionFetchError

ROOT = "https://www.shopify.com/careers"
UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")


class ShopifyClient(BaseATSClient):
    def fetch_jobs(self, company_name, identifier):
        if identifier != "shopify":
            raise ValueError("Invalid Shopify identifier")
        loader = shopify_loader(self.http_client.get(ROOT).text, "($locale)/careers")
        rows = loader.get("jobPostingsWithJobs")
        locations = loader.get("atsLocations")
        if not isinstance(rows, list) or not isinstance(locations, list):
            raise IngestionFetchError("Shopify public posting list missing")
        location_index = {x["id"]: x for x in locations if isinstance(x, dict) and x.get("id")}
        jobs, seen = [], set()
        errors = 0
        for entry in rows:
            row = entry.get("jobPosting") if isinstance(entry, dict) else None
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not UUID.fullmatch(row["id"]) or not row.get("title"):
                errors += 1
                continue
            if row["id"] in seen:
                errors += 1
                continue
            seen.add(row["id"])
            if row.get("status") != "Published" or row.get("isListed") is not True:
                continue
            url = ROOT + "/_" + row["id"]
            loc_ids = row.get("locationIds") or {}
            ids = [loc_ids.get("primaryLocationId")] + (loc_ids.get("secondaryLocationIds") or [])
            raw_locations = []
            for loc_id in ids:
                loc = location_index.get(loc_id, {})
                label = loc.get("externalName") or loc.get("name")
                country = loc.get("address", {}).get("postalAddress", {}).get("addressCountry", "")
                if label:
                    raw_locations.append({"location": label, "country": country})
            # Shopify explicitly distinguishes US internships in the posting title.
            # "Americas" / "Global" alone never establishes eligibility in Canada or the US.
            if re.match(r"^US .+ Internships\b", row["title"]):
                raw_locations.insert(0, {"location": "United States", "country": "United States"})
            job = RawJobPosting("shopify", row["id"], company_name, row["title"],
                                row.get("locationExternalName") or row.get("locationName") or "", url,
                                source_date(row.get("publishedDate")), "", raw_workplace_type=row.get("workplaceType"),
                                raw_job_type=row.get("employmentType"), company_apply_url=url, raw_locations=raw_locations)
            if needs_detail(job.title):
                try:
                    detail = shopify_loader(self.http_client.get(url).text, "($locale)/careers/$posting")
                    posting = detail.get("jobPosting", {})
                    if posting.get("id") != row["id"] or not posting.get("descriptionHtml"):
                        raise IngestionFetchError("Shopify exact posting description missing")
                    job.raw_description = posting["descriptionHtml"]
                    deadline = row.get("applicationDeadline")
                    if deadline:
                        # Preserve the explicit employer deadline; do not treat it as a posting date.
                        from html import escape
                        job.raw_description += "<p>Application Deadline: " + escape(str(deadline)) + "</p>"
                    if row.get("shouldDisplayCompensationOnJobBoard") and row.get("compensationTierSummary"):
                        summary = row["compensationTierSummary"]
                        job.compensation = {"compensationTierSummary": summary}
                        from html import escape
                        if isinstance(summary, str) and summary not in job.raw_description:
                            job.raw_description += "<p>" + escape(summary) + "</p>"
                except IngestionFetchError:
                    errors += 1
                    continue
            jobs.append(job)
        return FetchResult(jobs, errors, errors == 0, len(rows))
