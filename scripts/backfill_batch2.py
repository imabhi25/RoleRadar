"""Recompute batch-2 fields on an explicitly selected local PostgreSQL database.

Dry run is the default. --apply writes within one transaction; run again to confirm zero changes.
The shared formatter is display-only, so pay formatting has no stored-row update.
"""
from __future__ import annotations

import argparse
import ipaddress
import json

import psycopg2
from psycopg2.extras import Json

from ingestion.compensation import resolve_compensation
from ingestion.extractor import sanitize_html_to_text
from ingestion.normalizer import (
    classify_workplace,
    is_user_facing_location_eligible,
    normalize_job_locations,
    normalize_job_title,
)
from ingestion.workday_locations import repair_stored_workday_entries


def backfill(conn, *, apply: bool = False) -> dict[str, int]:
    counts = {"salary_location": 0, "salary_format": 0, "workplace": 0, "location_title": 0}
    with conn.cursor() as cur:
        cur.execute("""SELECT jp.id, jp.title, jp.description, jp.locations, l.location, l.country,
                              jp.source_name, jp.compensation, jp.workplace_type
                       FROM job_postings jp JOIN locations l ON l.id = jp.location_id
                       WHERE jp.source_name <> 'sample' ORDER BY jp.id""")
        for jid, title, description, locations, label, country, source, compensation, workplace in cur.fetchall():
            entries = [{**entry, 'location': entry.get('source_location') or entry['location']}
                       for entry in (locations or [{'location': label, 'country': country}])]
            if source == 'workday':
                entries = repair_stored_workday_entries(entries) or entries
            normalized = normalize_job_locations(label, entries)
            primary = next((loc for loc in normalized if is_user_facing_location_eligible(loc['location'], loc['country'])), normalized[0])
            updated_title = normalize_job_title(title)
            updated_pay = resolve_compensation(compensation, description, normalized)
            updated_workplace = classify_workplace(location_text=label, workplace_type_raw=workplace,
                                                   title=updated_title, description=sanitize_html_to_text(description or ''))
            # An absent provider flag cannot be reconstructed; only adopt explicit office evidence over remote.
            if workplace != 'remote' or updated_workplace not in ('hybrid', 'onsite'):
                updated_workplace = workplace
            location_changed = normalized != locations or (primary['location'], primary['country']) != (label, country)
            title_changed = updated_title != title
            pay_changed = updated_pay != compensation
            workplace_changed = updated_workplace != workplace
            counts['salary_location'] += int(pay_changed)
            counts['workplace'] += int(workplace_changed)
            counts['location_title'] += int(location_changed or title_changed)
            if not apply or not (location_changed or title_changed or pay_changed or workplace_changed):
                continue
            if location_changed:
                cur.execute('''INSERT INTO locations(location,country) VALUES (%s,%s)
                               ON CONFLICT(location,country) DO UPDATE SET country=EXCLUDED.country RETURNING id''',
                            (primary['location'], primary['country']))
                location_id = cur.fetchone()[0]
                cur.execute('UPDATE job_postings SET locations=%s, location_id=%s WHERE id=%s',
                            (Json(normalized), location_id, jid))
            cur.execute('UPDATE job_postings SET title=%s, compensation=%s, workplace_type=%s WHERE id=%s',
                        (updated_title, Json(updated_pay) if updated_pay is not None else None, updated_workplace, jid))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='localhost, loopback address, or local Unix-socket directory')
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--database', required=True)
    parser.add_argument('--apply', action='store_true', help='write changes; omitted means read-only dry run')
    args = parser.parse_args()
    if args.host != 'localhost' and not args.host.startswith('/'):
        try:
            local = ipaddress.ip_address(args.host).is_loopback
        except ValueError:
            local = False
        if not local:
            parser.error('only an explicit local host or Unix socket is allowed')
    with psycopg2.connect(host=args.host, port=args.port, dbname=args.database) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT inet_server_addr()')
            address = cur.fetchone()[0]
            if address is not None and not ipaddress.ip_address(address).is_loopback:
                raise SystemExit('Refusing a non-local database connection')
        conn.rollback()
        conn.set_session(readonly=not args.apply)
        counts = backfill(conn, apply=args.apply)
        print(json.dumps({'mode': 'apply' if args.apply else 'dry-run', 'database': args.database, 'rows': counts}, sort_keys=True))


if __name__ == '__main__':
    main()
