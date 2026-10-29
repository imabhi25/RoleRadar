-- Compute once on insert/update rather than normalizing every posting during each feed request.
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS batch2_description_hash text GENERATED ALWAYS AS
    (md5(lower(regexp_replace(regexp_replace(coalesce(description, ''), '<[^>]+>', ' ', 'g'), '[^[:alnum:]]+', '', 'g')))) STORED;
CREATE INDEX IF NOT EXISTS idx_job_postings_batch2_duplicate_lookup
ON job_postings (company_id, location_id, lower(trim(title)), batch2_description_hash, id)
WHERE is_active = TRUE AND is_eligible_role = TRUE;
