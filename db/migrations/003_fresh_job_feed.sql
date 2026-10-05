-- =============================================================================
-- Migration 003: Fresh Job Feed Foundation & Role Type Classification
-- Phase 6A Additive Migration for RoleRadar
-- =============================================================================

-- 1. Extend job_postings with role_type classification
ALTER TABLE job_postings
    ADD COLUMN IF NOT EXISTS role_type VARCHAR(20) NOT NULL DEFAULT 'unknown';

-- 2. Validate role_type constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_role_type'
    ) THEN
        ALTER TABLE job_postings
            ADD CONSTRAINT check_role_type 
            CHECK (role_type IN ('internship', 'co_op', 'new_grad', 'full_time', 'unknown'));
    END IF;
END $$;

-- 3. Query performance index for role_type filtering
CREATE INDEX IF NOT EXISTS idx_job_postings_role_type
    ON job_postings(role_type);

-- 4. Composite/expression index for effective freshness date sorting and filtering
-- Effective date = COALESCE(posted_at, created_at)
CREATE INDEX IF NOT EXISTS idx_job_postings_effective_date
    ON job_postings((COALESCE(posted_at, created_at)) DESC);

-- 5. Backfill existing sample and active postings to sensible defaults based on title
UPDATE job_postings
SET role_type = CASE
    WHEN title ~* '\y(?:co[\s\-]op)\y' THEN 'co_op'
    WHEN title ~* '\y(?:intern(?:ship)?s?)\y' THEN 'internship'
    WHEN title ~* '\y(?:new\s+grad(?:uate)?s?|entry[\s\-]level|university\s+grad(?:uate)?)\y' THEN 'new_grad'
    ELSE 'full_time'
END
WHERE role_type = 'unknown';
