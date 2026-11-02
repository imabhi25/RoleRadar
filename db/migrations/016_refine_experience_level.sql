-- Refine experience level classification:
-- 1. Correctly recognize "plus" ("3 plus years") and "years in [skill/domain]".
-- 2. Prevent roles that mentor/coach junior staff, or have professional consultant titles,
--    from falling into "entry" level.
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
            '([0-9]{1,2})[ ]*(?:[+]|\yplus\y|[-–][ ]*[0-9]{1,2})?[ ]*years?[ ]+(?:(?:(?:of|in)[ ]+)?(?:(?:relevant|professional|industry|hands.on|software|engineering|work)[ ]+)*(?:experience|develop|build|working|design|programming)|(?:of|in)[ ]+[a-z0-9#+]+)', 'gi') LOOP
            IF line ~* '\yor\y' THEN line_years := LEAST(COALESCE(line_years,matches[1]::int),matches[1]::int);
            ELSE line_years := GREATEST(COALESCE(line_years,0),matches[1]::int); END IF;
        END LOOP;
        IF line_years IS NOT NULL THEN required_years := GREATEST(COALESCE(required_years,0),line_years); END IF;
    END LOOP;
    IF content ~* '\y(coach|mentor|guide|supervise|direct)\y[^.\n]{0,80}\y(junior|entry|interns?)\y' THEN
        IF required_years IS NULL OR required_years < 3 THEN required_years := 3; END IF;
    END IF;
    IF job_title ~* '\y(consultant|specialist|advisor)\y' THEN
        IF required_years IS NULL OR required_years < 3 THEN required_years := 3; END IF;
    END IF;
    IF required_years >= 8 THEN RETURN 'senior'; END IF;
    IF required_years >= 3 THEN RETURN 'mid'; END IF;
    IF required_years IS NOT NULL OR role IN ('new_grad','entry_level') THEN RETURN 'entry'; END IF;
    IF job_title ~* '\y(mid[ -]?level|intermediate)\y' THEN RETURN 'mid'; END IF;
    RETURN 'unknown';
END $$;

UPDATE job_postings SET title = title;
