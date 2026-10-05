#!/usr/bin/env bash
# Rehearse the production upgrade on real rows, then audit the result.
#   scripts/public_data_audit/rehearse.sh BEFORE_CRAWL_DIR AFTER_DIR
# Needs a PostgreSQL server (PGHOST/PGPORT/PGUSER set) and the frontend dependencies. Creates/drops the database roleradar_replay.
set -euo pipefail
BEFORE="$1"; AFTER="$2"; ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
export PGDATABASE=roleradar_replay SKIP_MIGRATIONS=1
[ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null || true
psql -d postgres -qc "drop database if exists roleradar_replay" -c "create database roleradar_replay"
psql -q -v ON_ERROR_STOP=1 -f db/schema.sql >/dev/null
python -c "from db.migrate import run_migrations; run_migrations(defer_versions={'015_pay_rules_and_audit_repair.sql'})" >/dev/null 2>&1   # production's state: up to 014
python scripts/public_data_audit/replay_snapshot.py "$BEFORE"
# production's Braze row: a verified, ATS-discovered logo and no website
psql -qc "UPDATE companies SET website_url=NULL, logo_status='verified', logo_url='/api/company-logos/'||id, logo_data='\x89504e47'::bytea, logo_content_type='image/png' WHERE name='Braze'"
python -m db.migrate 2>&1 | grep -E "015|Repaired" || true
(python -m uvicorn api.main:app --port "${PORT:-8765}" --log-level warning >/dev/null 2>&1 & echo $! > "$AFTER.api.pid")
sleep 4
python scripts/public_data_audit/crawl.py "http://localhost:${PORT:-8765}" "$AFTER"
kill "$(cat "$AFTER.api.pid")" 2>/dev/null || true; rm -f "$AFTER.api.pid"
(cd frontend && AUDIT_DIR="$AFTER" npx vitest run --config ../scripts/public_data_audit/vitest.audit.config.ts 2>&1 | tail -3)
python scripts/public_data_audit/analyze.py "$AFTER"
