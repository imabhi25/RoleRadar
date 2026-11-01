const API_BASE = 'https://roleradar-api.vercel.app';

export function escapeXml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/**
 * Validates whether a job posting has all required structured data fields
 * according to Google Search Central guidelines and our job-page markup rules:
 * - Must have title, company, and valid posted_at date.
 * - Must be active and not closed or expired.
 * - For 100% remote jobs: must have verified applicant location requirements
 *   (Google requires applicantLocationRequirements for TELECOMMUTE; omitting TELECOMMUTE
 *    must not make a remote job look office-based).
 * - For non-remote / hybrid jobs: must have at least one physical office location.
 *
 * Jobs failing these criteria are excluded from the sitemap to prevent Googlebot
 * from encountering invalid JobPosting markup or crawling incomplete postings.
 */
export function isJobEligibleForMarkup(job) {
  if (!job || typeof job !== 'object') return false;
  if (!job.title || !String(job.title).trim()) return false;
  if (!job.company || !String(job.company).trim()) return false;
  if (!job.posted_at) return false;

  const postedDate = new Date(job.posted_at);
  if (isNaN(postedDate.getTime())) return false;

  // Closed or expired jobs must be excluded immediately
  if (job.is_active === false || job.status === 'closed' || job.expired === true) {
    return false;
  }

  const workplace = (job.workplace_type || '').toLowerCase();
  const isRemoteOnly = workplace === 'remote';

  let hasVerifiedApplicantCountries = false;
  if (Array.isArray(job.applicant_location_requirements) && job.applicant_location_requirements.length > 0) {
    const countries = job.applicant_location_requirements
      .map((c) => String(c).trim())
      .filter((c) => /^(?:Canada|United States|United Kingdom)$/i.test(c));
    if (countries.length > 0) {
      hasVerifiedApplicantCountries = true;
    }
  }

  if (isRemoteOnly) {
    // Remote-only jobs MUST have verified applicant locations
    if (!hasVerifiedApplicantCountries) {
      return false;
    }
  } else {
    // Non-remote or hybrid jobs MUST have at least one physical location
    const hasLocationsList =
      Array.isArray(job.locations) &&
      job.locations.some((l) => l && String(l.location || l.raw_location || '').trim());
    const hasSingleLocation = Boolean(job.location && String(job.location).trim());
    if (!hasLocationsList && !hasSingleLocation) {
      return false;
    }
  }

  return true;
}

/**
 * Fetches all jobs from the API across all pages (handling pagination beyond the first 500).
 * Treats any failed or malformed page response as an error, ensuring incomplete sitemaps
 * are never treated as successful.
 */
export async function fetchEligibleJobs(apiBase = API_BASE, fetchImpl = fetch) {
  const PAGE_LIMIT = 100;
  const firstUrl = `${apiBase}/api/jobs?limit=${PAGE_LIMIT}&offset=0`;

  const firstRes = await fetchImpl(firstUrl, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(8000)
  });

  if (!firstRes.ok) {
    throw new Error(`Failed to fetch initial page of jobs: HTTP ${firstRes.status}`);
  }

  const firstData = await firstRes.json();
  if (!firstData || typeof firstData !== 'object' || !Array.isArray(firstData.jobs)) {
    throw new Error('Malformed initial page response from jobs API');
  }

  const total = firstData.total;
  if (
    typeof total !== 'number' ||
    Number.isNaN(total) ||
    !Number.isInteger(total) ||
    total < 0
  ) {
    throw new Error(`Invalid total in initial page response: ${total}`);
  }

  const jobsCount = firstData.jobs.length;
  if (total < jobsCount || (jobsCount > 0 && total === 0) || (total > 0 && jobsCount === 0)) {
    throw new Error(
      `Inconsistent total in initial page response: total=${total} but jobs.length=${jobsCount}`
    );
  }

  // Reject short initial page when more pages are expected
  if (total > PAGE_LIMIT && jobsCount < PAGE_LIMIT) {
    throw new Error(
      `Incomplete initial page response: expected ${PAGE_LIMIT} jobs for total=${total}, but received ${jobsCount}`
    );
  }

  // Reject incomplete initial page when total should fit entirely within PAGE_LIMIT
  if (total <= PAGE_LIMIT && jobsCount !== total) {
    throw new Error(
      `Inconsistent total in initial page response: total=${total} but jobs.length=${jobsCount}`
    );
  }

  const allJobs = [...firstData.jobs];

  let currentTotal = total;
  let nextOffset = PAGE_LIMIT;

  // Process page requests in batches of 6 to avoid socket exhaustion
  const BATCH_SIZE = 6;
  while (nextOffset < currentTotal) {
    const batchOffsets = [];
    for (let b = 0; b < BATCH_SIZE && nextOffset < currentTotal; b++) {
      batchOffsets.push(nextOffset);
      nextOffset += PAGE_LIMIT;
    }

    const batchPromises = batchOffsets.map(async (offset) => {
      const url = `${apiBase}/api/jobs?limit=${PAGE_LIMIT}&offset=${offset}`;
      const res = await fetchImpl(url, {
        headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(8000)
      });
      if (!res.ok) {
        throw new Error(`Sitemap pagination failed at offset ${offset}: HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!data || typeof data !== 'object' || !Array.isArray(data.jobs)) {
        throw new Error(`Sitemap pagination received malformed response at offset ${offset}`);
      }
      return { offset, data };
    });

    const batchResults = await Promise.all(batchPromises);

    for (const { offset, data } of batchResults) {
      const pageJobs = data.jobs;
      const pageJobsCount = pageJobs.length;

      // Validate total in later page response if present
      if ('total' in data) {
        const pageTotal = data.total;
        if (
          typeof pageTotal !== 'number' ||
          Number.isNaN(pageTotal) ||
          !Number.isInteger(pageTotal) ||
          pageTotal < 0
        ) {
          throw new Error(
            `Sitemap pagination received invalid total at offset ${offset}: ${pageTotal}`
          );
        }

        // Account for catalog changing during pagination:
        // Update currentTotal to reflect dynamic additions or removals in the catalog.
        if (pageTotal !== currentTotal) {
          if (pageTotal < offset) {
            throw new Error(
              `Inconsistent catalog change during pagination: total decreased to ${pageTotal} below current offset ${offset}`
            );
          }
          currentTotal = pageTotal;
        }

        if (pageTotal < offset + pageJobsCount) {
          throw new Error(
            `Inconsistent response at offset ${offset}: total=${pageTotal} is less than offset ${offset} + jobs.length ${pageJobsCount}`
          );
        }
      }

      // Check for empty page when jobs were expected
      if (pageJobsCount === 0 && offset < currentTotal) {
        throw new Error(
          `Sitemap pagination received empty page at offset ${offset} (total=${currentTotal})`
        );
      }

      // Check for short page:
      if (offset + PAGE_LIMIT < currentTotal) {
        // Intermediate page must return full PAGE_LIMIT
        if (pageJobsCount < PAGE_LIMIT) {
          throw new Error(
            `Incomplete paginated response at offset ${offset}: expected ${PAGE_LIMIT} jobs for total=${currentTotal}, but received ${pageJobsCount}`
          );
        }
      } else {
        // Final page must return all remaining jobs up to currentTotal
        const expectedFinalCount = currentTotal - offset;
        if (pageJobsCount < expectedFinalCount) {
          throw new Error(
            `Incomplete final page response at offset ${offset}: expected ${expectedFinalCount} jobs for total=${currentTotal}, but received ${pageJobsCount}`
          );
        }
      }

      allJobs.push(...pageJobs);
    }
  }

  // Deduplicate and filter strictly for jobs with verified markup data
  const seenJobIds = new Set();
  const eligibleJobs = [];

  for (const job of allJobs) {
    if (!job || !job.job_id || seenJobIds.has(job.job_id)) continue;
    seenJobIds.add(job.job_id);
    if (isJobEligibleForMarkup(job)) {
      eligibleJobs.push(job);
    }
  }

  // Sort deterministically by posted_at descending, then job_id
  eligibleJobs.sort((a, b) => {
    const timeA = new Date(a.posted_at || 0).getTime();
    const timeB = new Date(b.posted_at || 0).getTime();
    if (timeB !== timeA) return timeB - timeA;
    return String(a.job_id).localeCompare(String(b.job_id));
  });

  return eligibleJobs;
}

/**
 * Builds the complete dynamic sitemap XML document.
 * Includes existing general pages (/jobs, /stats, /company) and all eligible active job URLs.
 * Omit <lastmod> unless a reliable timestamp represents a meaningful change to that job page;
 * posted_at is an initial publication timestamp, not a page modification date.
 */
export function generateSitemapXml(eligibleJobs = [], siteUrl = 'https://roleradar-jobs.vercel.app') {
  const normalizedSiteUrl = siteUrl.replace(/\/+$/, '');

  const generalPages = [
    { path: '/jobs' },
    { path: '/stats' },
    { path: '/company' }
  ];

  let xml = '<?xml version="1.0" encoding="UTF-8"?>\n';
  xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n';

  // 1. General core pages
  for (const page of generalPages) {
    const loc = escapeXml(`${normalizedSiteUrl}${page.path}`);
    xml += '  <url>\n';
    xml += `    <loc>${loc}</loc>\n`;
    xml += '  </url>\n';
  }

  // 2. Active, eligible job pages (omitting <lastmod> as no verified modification timestamp exists)
  for (const job of eligibleJobs) {
    const encodedJobId = encodeURIComponent(job.job_id);
    const loc = escapeXml(`${normalizedSiteUrl}/jobs/${encodedJobId}`);

    xml += '  <url>\n';
    xml += `    <loc>${loc}</loc>\n`;
    xml += '  </url>\n';
  }

  xml += '</urlset>\n';
  return xml;
}

export default async function handler(req, res) {
  const host = req.headers['x-forwarded-host'] || req.headers['host'] || 'roleradar-jobs.vercel.app';
  const protocol = req.headers['x-forwarded-proto'] || 'https';
  const siteUrl = `${protocol}://${host}`;

  try {
    const eligibleJobs = await fetchEligibleJobs(API_BASE);
    const xml = generateSitemapXml(eligibleJobs, siteUrl);

    res.statusCode = 200;
    res.setHeader('Content-Type', 'application/xml; charset=utf-8');
    // Cache at edge for 1 hour, stale-while-revalidate for 30 minutes
    res.setHeader('Cache-Control', 'public, s-maxage=3600, stale-while-revalidate=1800');
    res.end(xml);
  } catch (err) {
    console.error('Error generating dynamic sitemap:', err);

    // Treat incomplete / failed pagination as a service error, NOT a successful sitemap
    res.statusCode = 503;
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Retry-After', '60');
    res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate');
    res.end('Service Unavailable: unable to generate complete sitemap');
  }
}
