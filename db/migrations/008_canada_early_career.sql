-- =============================================================================
-- Migration 008: Canada-first early-career support
--   * entry_level role type
--   * explicit academic term metadata (Winter/Summer/Fall + year)
--   * discovery_candidates: Simplify (and similar) discovery inputs. These rows are
--     NEVER public jobs; they only become visible after verification through an
--     official employer source that the normal ingestion pipeline then ingests.
-- =============================================================================

-- Replace the role_type CHECK (whatever it was named) with one that includes entry_level.
DO $$
DECLARE con RECORD;
BEGIN
    FOR con IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'job_postings'::regclass AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%role_type%'
    LOOP
        EXECUTE format('ALTER TABLE job_postings DROP CONSTRAINT %I', con.conname);
    END LOOP;
END $$;

ALTER TABLE job_postings
    ADD CONSTRAINT job_postings_role_type_check
    CHECK (role_type IN ('internship', 'co_op', 'new_grad', 'entry_level', 'full_time', 'unknown'));

ALTER TABLE job_postings
    ADD COLUMN IF NOT EXISTS term_season VARCHAR(10),
    ADD COLUMN IF NOT EXISTS term_year SMALLINT;

ALTER TABLE job_postings DROP CONSTRAINT IF EXISTS job_postings_term_season_check;
ALTER TABLE job_postings
    ADD CONSTRAINT job_postings_term_season_check
    CHECK (term_season IS NULL OR term_season IN ('winter', 'summer', 'fall'));

CREATE INDEX IF NOT EXISTS idx_job_postings_term ON job_postings(term_season, term_year)
    WHERE term_season IS NOT NULL;

CREATE TABLE IF NOT EXISTS discovery_candidates (
    id SERIAL PRIMARY KEY,
    candidate_key TEXT NOT NULL UNIQUE,
    source_repo TEXT NOT NULL,
    source_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    title TEXT NOT NULL,
    location_text TEXT,
    locations JSONB NOT NULL DEFAULT '[]'::jsonb,
    role_type VARCHAR(20),
    term_season VARCHAR(10),
    term_year SMALLINT,
    discovered_url TEXT,
    simplify_url TEXT,
    official_url TEXT,
    official_url_verified BOOLEAN NOT NULL DEFAULT FALSE,
    company_configured BOOLEAN NOT NULL DEFAULT FALSE,
    provider VARCHAR(50),
    provider_identifier TEXT,
    eligible_country VARCHAR(50),
    status VARCHAR(30) NOT NULL DEFAULT 'discovered'
        CHECK (status IN ('discovered', 'already_known', 'official_url_resolved', 'verified',
                          'unsupported_source', 'official_not_found', 'closed', 'invalid', 'deferred')),
    verification_status VARCHAR(30) NOT NULL DEFAULT 'unverified',
    status_reason TEXT,
    matched_source_name VARCHAR(50),
    matched_source_job_id VARCHAR(150),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_discovery_candidates_status ON discovery_candidates(status);
