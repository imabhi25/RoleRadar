-- Namespace stored source identities using their own official URL. Public job_id values
-- remain unchanged, so existing links keep working and future syncs update the same row.
WITH scoped AS (
    SELECT id, (regexp_match(split_part(split_part(source_url,'?',1),'#',1),
        '^https?://([^.]+[.]wd[0-9]+)[.]myworkdayjobs[.]com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)/job/')) AS site,
        (regexp_match(split_part(split_part(source_url,'?',1),'#',1), '/([^/]+)/*$'))[1] AS slug
    FROM job_postings WHERE source_name='workday'
), identities AS (
    SELECT id, site[1] || '/' || site[2] || '/' || slug AS identity FROM scoped WHERE site IS NOT NULL AND slug IS NOT NULL
)
UPDATE job_postings jp SET source_job_id=CASE WHEN length(identity)<=150 THEN identity
    ELSE 'sha256:' || encode(sha256(convert_to(identity,'UTF8')),'hex') END
FROM identities i WHERE jp.id=i.id;
