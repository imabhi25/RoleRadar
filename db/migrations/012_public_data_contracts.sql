-- Canonical, source-aware pay ranges for existing records and every future write.
CREATE OR REPLACE FUNCTION jobber_pay_ranges(pay jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    parts jsonb := '[]'::jsonb;
    result jsonb := '[]'::jsonb;
    part jsonb;
    tier jsonb;
    lo numeric;
    hi numeric;
    currency text;
    period text;
    multiplier numeric;
    floor_amount numeric;
BEGIN
    IF jsonb_typeof(pay) <> 'object' OR pay IS NULL THEN RETURN result; END IF;
    IF jsonb_typeof(pay->'ranges') = 'array' AND jsonb_array_length(pay->'ranges') > 0 THEN
        FOR part IN SELECT value FROM jsonb_array_elements(pay->'ranges') LOOP
            parts := parts || jsonb_build_array((pay - 'ranges') || part);
        END LOOP;
    ELSIF pay ? 'min' OR pay ? 'max' THEN
        parts := parts || jsonb_build_array(pay);
    END IF;
    IF jsonb_typeof(pay->'summaryComponents') = 'array' THEN
        parts := parts || (pay->'summaryComponents');
    END IF;
    IF jsonb_typeof(pay->'compensationTiers') = 'array' THEN
        FOR tier IN SELECT value FROM jsonb_array_elements(pay->'compensationTiers') LOOP
            IF jsonb_typeof(tier->'components') = 'array' THEN parts := parts || (tier->'components'); END IF;
        END LOOP;
    END IF;
    FOR part IN SELECT value FROM jsonb_array_elements(parts) LOOP
        IF jsonb_typeof(part) <> 'object' THEN CONTINUE; END IF;
        IF part ? 'compensationType' AND lower(part->>'compensationType') NOT IN ('salary','basesalary','hourly','wage') THEN CONTINUE; END IF;
        currency := upper(COALESCE(part->>'currencyCode', part->>'currency', ''));
        period := lower(COALESCE(part->>'interval', ''));
        multiplier := CASE WHEN period ~ 'year|annual' THEN 1 WHEN period ~ 'month' THEN 12
            WHEN period ~ 'week' THEN 52 WHEN period ~ 'day|daily' THEN 260 WHEN period ~ 'hour' THEN 2080 END;
        IF currency !~ '^[A-Z]{3}$' OR multiplier IS NULL THEN CONTINUE; END IF;
        lo := CASE WHEN COALESCE(part->>'minValue', part->>'min') ~ '^[0-9]+([.][0-9]+)?$'
            THEN COALESCE(part->>'minValue', part->>'min')::numeric END;
        hi := CASE WHEN COALESCE(part->>'maxValue', part->>'max') ~ '^[0-9]+([.][0-9]+)?$'
            THEN COALESCE(part->>'maxValue', part->>'max')::numeric END;
        floor_amount := CASE WHEN multiplier = 1 THEN 1000 WHEN multiplier = 12 THEN 100 WHEN multiplier = 52 THEN 25 ELSE 5 END;
        IF (lo IS NULL AND hi IS NULL) OR COALESCE(lo, hi) <= 0 OR COALESCE(hi, lo) <= 0
            OR (lo IS NOT NULL AND hi IS NOT NULL AND lo > hi)
            OR (currency IN ('USD','CAD','AUD','GBP','EUR') AND LEAST(COALESCE(lo,hi),COALESCE(hi,lo)) < floor_amount)
        THEN CONTINUE; END IF;
        result := result || jsonb_build_array(jsonb_build_object('currency', currency,
            'min_annual', COALESCE(lo,hi)*multiplier, 'max_annual', COALESCE(hi,lo)*multiplier, 'period', period));
    END LOOP;
    RETURN result;
END $$;

-- Explicit employer titles take precedence. Only experience requirements (not company age,
-- preferred experience or a degree's duration) contribute to the fallback. Years are a
-- conservative fallback: 0-2 entry, 3-7 mid, 8+ senior; unspecified remains unknown.
CREATE OR REPLACE FUNCTION jobber_experience_level(job_title text, role text, description text) RETURNS text
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    content text;
    line text;
    preferred boolean := false;
    matches text[];
    required_years int := NULL;
    line_years int;
BEGIN
    IF role IN ('internship','co_op') OR job_title ~* '\y(intern|internship|co[ -]?op)\y' THEN RETURN 'internship'; END IF;
    IF job_title ~* '\y(senior|sr[.]?|lead|staff|principal|architect|director|vp|head|manager|distinguished)\y' THEN RETURN 'senior'; END IF;
    IF job_title ~* '\y(junior|entry[ -]?level|new[ -]?grad(uate)?)\y' THEN RETURN 'entry'; END IF;
    content := regexp_replace(COALESCE(description,''), '<h[1-6][^>]*>', E'\n# ', 'gi');
    content := regexp_replace(content, '<(/(p|li|h[1-6])|br)[^>]*>', E'\n', 'gi');
    content := regexp_replace(content, '<[^>]*>', ' ', 'g');
    FOR line IN SELECT unnest(regexp_split_to_array(content, E'\n')) LOOP
        IF line LIKE '# %' OR trim(line) ~* '^(preferred qualifications|desired qualifications|nice to have|requirements|qualifications|responsibilities|about us|about the company):?$' THEN
            preferred := line ~* 'preferred|desired|nice.to.have|bonus|stand.out|company|about us';
            CONTINUE;
        END IF;
        IF preferred OR line ~* '\y(preferred|preferably|bonus|nice.to.have|not required)\y' THEN CONTINUE; END IF;
        line_years := NULL;
        FOR matches IN SELECT regexp_matches(line,
            '([0-9]{1,2})[ ]*(?:[+]|[-–][ ]*[0-9]{1,2})?[ ]*years?[ ]+(?:of[ ]+)?(?:relevant[ ]+|professional[ ]+|industry[ ]+|hands.on[ ]+|software[ ]+|engineering[ ]+|work[ ]+)*(?:experience|develop|build|working|design|programming)', 'gi') LOOP
            IF line ~* '\yor\y' THEN line_years := LEAST(COALESCE(line_years,matches[1]::int),matches[1]::int);
            ELSE line_years := GREATEST(COALESCE(line_years,0),matches[1]::int); END IF;
        END LOOP;
        IF line_years IS NOT NULL THEN required_years := GREATEST(COALESCE(required_years,0),line_years); END IF;
    END LOOP;
    IF required_years >= 8 THEN RETURN 'senior'; END IF;
    IF required_years >= 3 THEN RETURN 'mid'; END IF;
    IF required_years IS NOT NULL OR role IN ('new_grad','entry_level') THEN RETURN 'entry'; END IF;
    IF job_title ~* '\y(mid[ -]?level|intermediate)\y' THEN RETURN 'mid'; END IF;
    RETURN 'unknown';
END $$;

ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS pay_ranges jsonb
    GENERATED ALWAYS AS (jobber_pay_ranges(compensation)) STORED;
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS experience_level text
    GENERATED ALWAYS AS (jobber_experience_level(title,role_type,description)) STORED;
CREATE INDEX IF NOT EXISTS idx_job_postings_experience_level ON job_postings(experience_level);
ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS search_document tsvector GENERATED ALWAYS AS
    (to_tsvector('simple', translate(lower(COALESCE(title,'') || ' ' || regexp_replace(COALESCE(description,''), '<[^>]*>', ' ', 'g')), 'àáâãäåāăąçćčďđèéêëēėęěğìíîïīįłñńňòóôõöøōőřśšşťùúûüūůűųýÿźżž-–—‑', 'aaaaaaaaacccddeeeeeeeegiiiiiilnnnoooooooorssstuuuuuuuuyyzzz    '))) STORED;
CREATE INDEX IF NOT EXISTS idx_job_postings_search_document ON job_postings USING gin(search_document);

-- Merge case-only company duplicates without losing job relationships. Keep the verified,
-- readable company name and the existing public job ids.
CREATE TEMP TABLE company_case_merges ON COMMIT DROP AS
SELECT id, first_value(id) OVER (PARTITION BY lower(trim(name))
    ORDER BY (logo_status='verified') DESC, (name <> lower(name)) DESC, id) AS canonical_id FROM companies;
UPDATE job_postings jp SET company_id=m.canonical_id FROM company_case_merges m
    WHERE jp.company_id=m.id AND m.id<>m.canonical_id;
DELETE FROM companies c USING company_case_merges m WHERE c.id=m.id AND m.id<>m.canonical_id;
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_name_folded ON companies(lower(trim(name)));
