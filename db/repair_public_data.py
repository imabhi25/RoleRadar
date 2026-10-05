"""Repair of stored locations, pay and skill links using the current ingestion rules.

Runs inside the transaction of migrations 012, 014 and 015, and is idempotent. Source labels (kept as raw_location),
published pay figures (kept as published, or under source_structured), public job ids, posting dates and source activity
are retained. Batched writes avoid a network round trip for every extracted skill on hosted databases.
"""
# What the backfill deliberately does NOT do: it never re-derives a location from a stored label that lost its source.
# Anthropic's source label "Remote-Friendly (Travel Required) | San Francisco, CA" was stored by an older normalizer as two entries,
# "Remote - Friendly (Travel Required" and "Remote - San Francisco, CA" (it prefixed Remote onto the real city). The stored second
# entry carries no raw label, so it is indistinguishable from a genuine "Remote - San Francisco, CA" posting; stripping "Remote" from
# stored labels would un-remote real remote jobs, which is a guess about where they may be worked from. The backfill therefore only
# drops the entry that is plainly not a place. The correct label is recomputed from the ATS's own string at the next ingestion run
# (every ~6 h), which is the only moment the source label is available; workplace_type is likewise derived at ingestion.
from psycopg2.extras import Json, execute_values
from ingestion.compensation import resolve_compensation
from ingestion.extractor import extract_skills, sanitize_html_to_text
from ingestion.normalizer import normalize_job_locations, is_user_facing_location_eligible
from ingestion.workday_locations import repair_stored_workday_entries


def repair_public_data(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT jp.id,jp.title,jp.description,jp.locations,l.location,l.country,jp.source_name,jp.compensation
            FROM job_postings jp JOIN locations l ON jp.location_id=l.id WHERE jp.source_name<>'sample'""")
        rows = cur.fetchall()
        location_updates = []
        compensation_updates = []
        requested_skills = set()
        for jid, title, description, locations, label, country, source_name, compensation in rows:
            entries = [{**entry, 'location': entry.get('source_location') or entry['location']}
                       for entry in (locations or [{'location': label, 'country': country}])]
            if source_name == 'workday':
                entries = repair_stored_workday_entries(entries) or entries
            normalized = normalize_job_locations(label, entries)
            # Pay qualifiers ("for the US") are judged against the job's repaired locations.
            resolved = resolve_compensation(compensation, description, normalized)
            if resolved != compensation:
                compensation_updates.append((jid, Json(resolved) if resolved else None))
            primary = next((item for item in normalized if is_user_facing_location_eligible(item['location'], item['country'])), normalized[0])
            if normalized != locations or (primary['location'],primary['country']) != (label,country):
                location_updates.append((jid, normalized, primary['location'], primary['country']))
            requested_skills.update((jid, skill) for skill in extract_skills(f'{title}\n{sanitize_html_to_text(description or "")}'))
        if compensation_updates:
            # pay_ranges is a stored generated column: it is recomputed by this write.
            execute_values(cur, """UPDATE job_postings jp SET compensation=data.compensation::jsonb
                FROM (VALUES %s) AS data(id,compensation) WHERE jp.id=data.id""", compensation_updates, page_size=500)
        if location_updates:
            places = sorted({(label,country) for _,_,label,country in location_updates})
            location_rows = execute_values(cur, """INSERT INTO locations(location,country) VALUES %s
                ON CONFLICT(location,country) DO UPDATE SET country=EXCLUDED.country
                RETURNING id,location,country""", places, page_size=500, fetch=True)
            ids = {(label,country): lid for lid,label,country in location_rows}
            execute_values(cur, """UPDATE job_postings jp SET locations=data.locations::jsonb, location_id=data.location_id
                FROM (VALUES %s) AS data(id,locations,location_id) WHERE jp.id=data.id""",
                [(jid,Json(locations),ids[(label,country)]) for jid,locations,label,country in location_updates], page_size=500)
        if requested_skills:
            cur.execute("""SELECT jps.job_posting_id,s.name FROM job_posting_skills jps
                JOIN skills s ON s.id=jps.skill_id WHERE jps.job_posting_id=ANY(%s)""",([row[0] for row in rows],))
            missing = requested_skills - set(cur.fetchall())
            if missing:
                skill_rows = execute_values(cur, """INSERT INTO skills(name) VALUES %s
                    ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id,name""",
                    [(name,) for name in sorted({name for _,name in missing})], page_size=500, fetch=True)
                ids = {name:sid for sid,name in skill_rows}
                execute_values(cur, "INSERT INTO job_posting_skills VALUES %s ON CONFLICT DO NOTHING",
                    [(jid,ids[name]) for jid,name in sorted(missing)], page_size=500)
    return len(rows)
