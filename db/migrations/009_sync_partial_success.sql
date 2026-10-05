-- Allow an explicit partial_success sync state: valid rows were ingested but the snapshot was not
-- trustworthy enough to deactivate anything (parse errors, incomplete fetch, suspicious drop).
DO $$
DECLARE con RECORD;
BEGIN
    FOR con IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'sync_runs'::regclass AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%status%'
    LOOP
        EXECUTE format('ALTER TABLE sync_runs DROP CONSTRAINT %I', con.conname);
    END LOOP;
END $$;

ALTER TABLE sync_runs
    ADD CONSTRAINT sync_runs_status_check
    CHECK (status IN ('running', 'success', 'partial_success', 'failed'));
