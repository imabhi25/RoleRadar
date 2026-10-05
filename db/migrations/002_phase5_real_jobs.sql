-- =============================================================================
-- Migration 002: Real Job Ingestion, ATS Metadata & Ingestion Audit Schema
-- Phase 5 Additive Migration for RoleRadar
-- =============================================================================

-- 1. Extend job_postings with ATS metadata and lifecycle tracking
ALTER TABLE job_postings
    ADD COLUMN IF NOT EXISTS description TEXT NULL,
    ADD COLUMN IF NOT EXISTS workplace_type VARCHAR(20) NOT NULL DEFAULT 'unspecified',
    ADD COLUMN IF NOT EXISTS source_name VARCHAR(50) NOT NULL DEFAULT 'sample',
    ADD COLUMN IF NOT EXISTS source_job_id VARCHAR(150) NULL,
    ADD COLUMN IF NOT EXISTS source_url TEXT NULL,
    ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 2. Workplace type constraint validation ('unspecified' as safe fallback)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_workplace_type'
    ) THEN
        ALTER TABLE job_postings
            ADD CONSTRAINT check_workplace_type 
            CHECK (workplace_type IN ('onsite', 'remote', 'hybrid', 'unspecified'));
    END IF;
END $$;

-- 3. Composite unique index for external ATS deduplication
-- Enforces uniqueness per source platform and external job ID
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_source_unique
    ON job_postings(source_name, source_job_id)
    WHERE source_job_id IS NOT NULL;

-- 4. Query performance indexes for filtering and analytics
CREATE INDEX IF NOT EXISTS idx_job_postings_active_real
    ON job_postings(source_name, is_active)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_job_postings_workplace_type 
    ON job_postings(workplace_type);

CREATE INDEX IF NOT EXISTS idx_job_postings_posted_at 
    ON job_postings(posted_at DESC);

CREATE INDEX IF NOT EXISTS idx_job_postings_company_active 
    ON job_postings(company_id, is_active);

-- =============================================================================
-- 5. Ingestion Audit & Safety Table: sync_runs
-- Guard table for monitoring, health tracking, and fail-safe tombstoning
-- =============================================================================
CREATE TABLE IF NOT EXISTS sync_runs (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(50) NOT NULL,
    company_identifier VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    jobs_fetched INTEGER NOT NULL DEFAULT 0,
    jobs_upserted INTEGER NOT NULL DEFAULT 0,
    jobs_deactivated INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NULL,
    error_message TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_runs_lookup
    ON sync_runs(source_name, company_identifier, started_at DESC);
