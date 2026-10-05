-- Preserve one row per source requisition with all source locations and compensation tiers.
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS locations JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS compensation JSONB;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_data BYTEA;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_content_type TEXT;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS is_eligible_role BOOLEAN NOT NULL DEFAULT TRUE;
