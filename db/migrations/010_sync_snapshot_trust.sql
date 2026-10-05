-- Record whether a sync run's SOURCE snapshot was trustworthy (fetch complete, no parse-integrity
-- failure, counts consistent, unique ids), i.e. eligible for tombstone evaluation. Only such runs may
-- count as confirmation that a suspicious drop or empty listing is real.
-- Existing rows default to FALSE, so old history can never shorten a confirmation. No data is changed.
ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS snapshot_trustworthy BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_sync_runs_confirmation
    ON sync_runs (source_name, company_identifier, completed_at DESC)
    WHERE snapshot_trustworthy;
