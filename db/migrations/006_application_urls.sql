-- =============================================================================
-- Migration 006: Multi-Route Job Application URLs
-- Adds official company application URL, LinkedIn listing URL, and Simplify listing URL.
-- =============================================================================

ALTER TABLE job_postings
    ADD COLUMN IF NOT EXISTS company_apply_url TEXT,
    ADD COLUMN IF NOT EXISTS linkedin_url TEXT,
    ADD COLUMN IF NOT EXISTS simplify_url TEXT;

-- Backfill existing active jobs:
-- 1. All existing postings from Greenhouse, Lever, Ashby, or company domains
--    have official company/ATS URLs stored in source_url.
--    Populate company_apply_url from source_url where company_apply_url IS NULL.
UPDATE job_postings
SET company_apply_url = source_url
WHERE company_apply_url IS NULL
  AND source_url IS NOT NULL
  AND source_url NOT LIKE '%linkedin.com%'
  AND source_url NOT LIKE '%simplify.jobs%';

-- 2. If any legacy row had a linkedin or simplify URL in source_url, route it accurately
UPDATE job_postings
SET linkedin_url = source_url
WHERE linkedin_url IS NULL
  AND source_url IS NOT NULL
  AND source_url LIKE '%linkedin.com%';

UPDATE job_postings
SET simplify_url = source_url
WHERE simplify_url IS NULL
  AND source_url IS NOT NULL
  AND source_url LIKE '%simplify.jobs%';
