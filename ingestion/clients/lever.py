"""
Lever Postings API adapter for RoleRadar.
Fetches and standardizes postings from public Lever boards with pagination and date conversion.
"""

from datetime import datetime, timezone
import html
import logging
import re
from typing import List

from ingestion.base import BaseATSClient, FetchResult, RawJobPosting
from ingestion.compensation import build_compensation, interval_from_text
from ingestion.http_client import IngestionFetchError

logger = logging.getLogger("ingestion.clients.lever")


class LeverClient(BaseATSClient):
    """
    Client for the public Lever Postings API.
    """

    BASE_URL = "https://api.lever.co/v0/postings/{identifier}"
    PAGE_SIZE = 100

    def fetch_jobs(self, company_name: str, identifier: str) -> FetchResult:
        url = self.BASE_URL.format(identifier=identifier)
        postings: List[RawJobPosting] = []
        skip = 0
        total_raw_records = 0
        parse_error_count = 0
        seen_page_ids = set()

        while True:
            params = {"mode": "json", "limit": self.PAGE_SIZE, "skip": skip}
            payload = self.http_client.get_json(url, params=params)

            if not isinstance(payload, list):
                raise IngestionFetchError(
                    f"Malformed Lever response for '{company_name}' ({identifier}): "
                    "expected JSON array of postings."
                )

            page_ids = tuple(str(j.get("id")) for j in payload if isinstance(j, dict))
            if payload and (page_ids in seen_page_ids or skip >= 100000):
                raise IngestionFetchError("Lever pagination repeated or exceeded its safety limit")
            seen_page_ids.add(page_ids)
            total_raw_records += len(payload)

            if not payload:
                break

            for job in payload:
                if not isinstance(job, dict):
                    logger.warning("Skipping non-dict job entry in Lever feed for %s", company_name)
                    parse_error_count += 1
                    continue

                job_id_val = job.get("id")
                title_val = job.get("text")

                if not isinstance(job_id_val, (str, int)) or not str(job_id_val).strip() or not isinstance(title_val, str) or not title_val.strip():
                    logger.warning(
                        "Skipping malformed Lever job record (missing id or text) for %s: %s",
                        company_name,
                        job,
                    )
                    parse_error_count += 1
                    continue

                source_job_id = str(job_id_val).strip()
                title = str(title_val).strip()

                categories = job.get("categories") if isinstance(job.get("categories"), dict) else {}
                raw_location = str(categories.get("location") or job.get("country") or "").strip()

                raw_workplace_type = categories.get("workplaceType") or job.get("workplaceType")
                if raw_workplace_type:
                    raw_workplace_type = str(raw_workplace_type).strip()
                else:
                    raw_workplace_type = None

                source_url = str(job.get("hostedUrl") or job.get("applyUrl") or "").strip()

                # Assemble complete description from description/descriptionPlain, lists, and additional/additionalPlain
                desc_parts = []
                main_desc = job.get("description") or job.get("descriptionPlain")
                if main_desc and str(main_desc).strip():
                    desc_parts.append(str(main_desc).strip())
                else:
                    opening = job.get("opening") or job.get("openingPlain")
                    if opening and str(opening).strip():
                        desc_parts.append(str(opening).strip())
                    body = job.get("descriptionBody") or job.get("descriptionBodyPlain")
                    if body and str(body).strip():
                        desc_parts.append(str(body).strip())

                lists_val = job.get("lists")
                if isinstance(lists_val, list):
                    for sec in lists_val:
                        if isinstance(sec, dict):
                            sec_title = sec.get("text")
                            sec_content = sec.get("content")
                            sec_blocks = []
                            if sec_title and str(sec_title).strip():
                                sec_blocks.append(f"<h3>{str(sec_title).strip()}</h3>")
                            if sec_content and str(sec_content).strip():
                                content_str = str(sec_content).strip()
                                if "<li" in content_str.lower() and not re.match(r"^\s*<(?:ul|ol)\b", content_str, re.IGNORECASE):
                                    content_str = f"<ul>\n{content_str}\n</ul>"
                                sec_blocks.append(content_str)
                            if sec_blocks:
                                desc_parts.append("\n".join(sec_blocks))

                additional_val = job.get("additional") or job.get("additionalPlain")
                if additional_val and str(additional_val).strip():
                    desc_parts.append(str(additional_val).strip())

                raw_description = "\n\n".join(desc_parts).strip()

                # Lever publishes pay in separate fields (salaryRange / salaryDescription), not in the description body.
                compensation = None
                salary_range = job.get("salaryRange") if isinstance(job.get("salaryRange"), dict) else None
                if salary_range:
                    compensation = build_compensation(
                        salary_range.get("currency"),
                        salary_range.get("min"),
                        salary_range.get("max"),
                        interval_from_text(salary_range.get("interval")),
                        source="lever",
                    )
                salary_note = str(job.get("salaryDescription") or "").strip()
                if not salary_note and job.get("salaryDescriptionPlain"):
                    salary_note = f"<p>{html.escape(str(job['salaryDescriptionPlain']).strip())}</p>"
                if salary_note:
                    if compensation is not None:
                        compensation["note"] = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", salary_note))).strip()
                    # Dedupe the complete narrative, never just a salary figure: the separate
                    # field may add bonus, benefits or eligibility caveats missing from the body.
                    def normalized_text(value):
                        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()

                    plain_body = normalized_text(raw_description)
                    if normalized_text(salary_note) not in plain_body:
                        has_section = bool(re.search(r"<h\d[^>]*>\s*(?:compensation|salary|pay)\b", raw_description, re.I))
                        heading = "" if has_section else "<h3>Compensation</h3>\n"
                        raw_description = (raw_description + "\n\n" + heading + salary_note).strip()

                posted_at = None
                created_at_val = job.get("createdAt")
                if isinstance(created_at_val, (int, float)) and created_at_val > 0:
                    try:
                        posted_at = datetime.fromtimestamp(created_at_val / 1000.0, tz=timezone.utc)
                    except (ValueError, OverflowError, OSError) as err:
                        logger.warning(
                            "Invalid createdAt timestamp %r for %s job %s: %s",
                            created_at_val,
                            company_name,
                            source_job_id,
                            err,
                        )

                postings.append(
                    RawJobPosting(
                        source_name="lever",
                        source_job_id=source_job_id,
                        company_name=company_name,
                        title=title,
                        raw_location=raw_location,
                        source_url=source_url,
                        posted_at=posted_at,
                        raw_description=raw_description,
                        raw_workplace_type=raw_workplace_type,
                        company_apply_url=job.get("applyUrl"),
                        raw_job_type=categories.get("commitment"),
                        compensation=compensation,
                        raw_locations=[{"location": loc} for loc in categories.get("allLocations", []) if isinstance(loc, str)],
                    )
                )

            # If fewer than PAGE_SIZE results returned, all pages have been consumed
            if len(payload) < self.PAGE_SIZE:
                break

            skip += len(payload)

        logger.info(
            "Successfully parsed %d Lever postings for %s (%s) with %d parse errors (total raw: %d)",
            len(postings),
            company_name,
            identifier,
            parse_error_count,
            total_raw_records,
        )
        return FetchResult(
            jobs=postings,
            parse_error_count=parse_error_count,
            fetch_complete=True,
            total_raw_records=total_raw_records,
        )
