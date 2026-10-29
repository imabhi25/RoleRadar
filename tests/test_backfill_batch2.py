"""The batch-2 backfill uses the same ingestion rules and is repeatable."""
from psycopg2.extras import Json

from scripts.backfill_batch2 import backfill
from tests.test_public_visibility import conn, _company, _insert  # noqa: F401


def test_backfill_dry_run_apply_and_repeat(conn):
    name, company_id = _company(conn)
    with conn.cursor() as cur:
        _insert(cur, company_id, name + 'batch2', days_old=0, location='Toronto, ON')
        cur.execute("""UPDATE job_postings SET title=%s, workplace_type='remote', description=%s,
                       locations=%s, compensation=NULL WHERE job_id=%s""",
                    ('Performance ( Toronto)  Engineer',
                     '<p>Employees work in the office Monday, Wednesday, and Thursday.</p>'
                     '<p>For Toronto based hires: salary CA$100,000 - CA$150,000 per year.</p>',
                     Json([{'location': 'Remote - Ontario, Canada (DNU)', 'country': 'Canada'}]), name + 'batch2'))
    before = backfill(conn)
    assert before['salary_location'] >= 1
    assert before['workplace'] >= 1
    assert before['location_title'] >= 1
    with conn.cursor() as cur:
        cur.execute('SELECT workplace_type FROM job_postings WHERE job_id=%s', (name + 'batch2',))
        assert cur.fetchone()[0] == 'remote'
    applied = backfill(conn, apply=True)
    assert applied == before
    with conn.cursor() as cur:
        cur.execute('SELECT title, workplace_type, locations FROM job_postings WHERE job_id=%s', (name + 'batch2',))
        title, workplace, locations = cur.fetchone()
    assert title == 'Performance (Toronto) Engineer'
    assert workplace == 'hybrid'
    assert locations[0]['location'] == 'Remote - Ontario, Canada'
    assert backfill(conn) == {'salary_location': 0, 'salary_format': 0, 'workplace': 0, 'location_title': 0}


def test_cli_rejects_remote_hosts_before_connecting(monkeypatch):
    import sys
    import pytest
    from scripts.backfill_batch2 import main

    monkeypatch.setattr(sys, 'argv', ['backfill_batch2', '--host', 'production.example.com', '--port', '5432', '--database', 'jobber', '--apply'])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
