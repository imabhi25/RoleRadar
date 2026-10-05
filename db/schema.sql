-- =============================================================================
-- Career Intelligence / Job Analytics Platform (RoleRadar)
-- PostgreSQL Master Database Schema (Phase 2 & Phase 5)
-- =============================================================================

-- Companies table: stores unique hiring organization names and verified company branding.
CREATE TABLE companies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    logo_url TEXT,
    logo_source_url TEXT,
    logo_data BYTEA,
    logo_content_type TEXT,
    logo_status VARCHAR(50) NOT NULL DEFAULT 'unresolved',
    website_url TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Locations table: stores unique combinations of geographic location/city and country.
CREATE TABLE locations (
    id SERIAL PRIMARY KEY,
    location TEXT NOT NULL,
    country VARCHAR(100) NOT NULL,
    UNIQUE (location, country)
);

-- Skills table: stores unique normalized technical skills and proficiencies.
CREATE TABLE skills (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE
);

-- Job Postings table: stores core job posting metadata linked to company and location,
-- with Phase 5 extensions for external ATS ingestion and lifecycle tracking.
CREATE TABLE job_postings (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(100) NOT NULL UNIQUE,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    title VARCHAR(255) NOT NULL,
    location_id INTEGER NOT NULL REFERENCES locations(id),
    description TEXT,
    locations JSONB NOT NULL DEFAULT '[]'::jsonb,
    compensation JSONB,
    workplace_type VARCHAR(20) NOT NULL DEFAULT 'unspecified' CHECK (workplace_type IN ('onsite', 'remote', 'hybrid', 'unspecified')),
    role_type VARCHAR(20) NOT NULL DEFAULT 'unknown' CHECK (role_type IN ('internship', 'co_op', 'new_grad', 'entry_level', 'full_time', 'unknown')),
    source_name VARCHAR(50) NOT NULL DEFAULT 'sample',
    source_job_id VARCHAR(150),
    source_url TEXT,
    company_apply_url TEXT,
    linkedin_url TEXT,
    simplify_url TEXT,
    term_season VARCHAR(10) CHECK (term_season IS NULL OR term_season IN ('winter', 'summer', 'fall')),
    term_year SMALLINT,
    posted_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_eligible_role BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Job Posting Skills table: junction table establishing a many-to-many relationship
-- between job postings and skills with cascading deletions.
CREATE TABLE job_posting_skills (
    job_posting_id INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    PRIMARY KEY (job_posting_id, skill_id)
);

-- Sync Runs table: stores ingestion execution records for monitoring and fail-safe tombstoning.
CREATE TABLE sync_runs (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(50) NOT NULL,
    company_identifier VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL CHECK (status IN ('running', 'success', 'partial_success', 'failed')),
    jobs_fetched INTEGER NOT NULL DEFAULT 0,
    jobs_upserted INTEGER NOT NULL DEFAULT 0,
    jobs_deactivated INTEGER NOT NULL DEFAULT 0,
    snapshot_trustworthy BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

-- Index on foreign key skill_id for fast reverse lookups and skill aggregation queries.
CREATE INDEX idx_job_posting_skills_skill_id
ON job_posting_skills(skill_id);

CREATE INDEX idx_job_postings_company_id
ON job_postings(company_id);

CREATE INDEX idx_job_postings_location_id
ON job_postings(location_id);

-- Composite unique index for external ATS deduplication
CREATE UNIQUE INDEX idx_job_postings_source_unique
ON job_postings(source_name, source_job_id)
WHERE source_job_id IS NOT NULL;

-- Query performance indexes for active postings and filtering
CREATE INDEX idx_job_postings_active_real
ON job_postings(source_name, is_active)
WHERE is_active = TRUE;

CREATE INDEX idx_job_postings_workplace_type
ON job_postings(workplace_type);

CREATE INDEX idx_job_postings_role_type
ON job_postings(role_type);

CREATE INDEX idx_job_postings_posted_at
ON job_postings(posted_at DESC);

CREATE INDEX idx_job_postings_effective_date
ON job_postings((COALESCE(posted_at, created_at)) DESC);

CREATE INDEX idx_job_postings_company_active
ON job_postings(company_id, is_active);

-- Lookup index for sync run monitoring
CREATE INDEX idx_sync_runs_lookup
ON sync_runs(source_name, company_identifier, started_at DESC);

CREATE INDEX idx_sync_runs_confirmation
ON sync_runs(source_name, company_identifier, completed_at DESC)
WHERE snapshot_trustworthy;

