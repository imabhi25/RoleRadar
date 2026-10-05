"""Behavioral regressions for source truth, location parity and public API semantics."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from api.database import get_db_connection
from api.main import app
from ingestion.base import RawJobPosting, FetchResult
from ingestion.clients.ashby import AshbyClient
from ingestion.clients.greenhouse import GreenhouseClient
from ingestion.clients.lever import LeverClient
from ingestion.http_client import IngestionFetchError
from ingestion.normalizer import (is_swe_role, is_user_facing_location_eligible,
    get_user_facing_geography_sql_predicate, normalize_job_locations)
from ingestion.pipeline import sync_company


@pytest.fixture
def conn():
    try:
        connection = get_db_connection()
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    yield connection
    connection.rollback()
    connection.close()


@pytest.mark.parametrize("title,expected", [
    ("Software Engineer, Finance", True), ("Full Stack Software Engineer, Legal", True),
    ("Backend Developer – Payroll", True), ("Software Engineering Recruiter", False),
    ("Support Systems Lead", False), ("Software Engineering Counsel", False),
    ("Sales Engineer, Software", False), ("Payroll Manager", False),
])
def test_role_occupation_precedes_domain(title, expected):
    assert is_swe_role(title) is expected


@pytest.mark.parametrize("label,country,expected", [
    ("Remote", "United States", True), ("Remote", "Unknown", False),
    ("United States", "United States", True), ("Remote - Canada", "Canada", True),
    ("Remote - Ontario", "Canada", True), ("Remote - California", "United States", True),
    ("Canada", "United States", False), ("London", "United States", False),
    ("Berlin", "Canada", False), ("Worldwide", "Canada", False),
    ("USA timezones", "United States", False), ("Hybrid", "Canada", False),
    ("Toronto, ON", "Canada", True), ("San Diego, CA", "United States", True),
    ("Unknown, CA", "United States", False), ("   ", "United States", False),
])
def test_python_and_postgresql_location_semantics(conn, label, country, expected):
    assert is_user_facing_location_eligible(label, country) is expected
    with conn.cursor() as cur:
        cur.execute(f"SELECT {get_user_facing_geography_sql_predicate()} FROM (VALUES (%s, %s)) AS l(location, country)", (label, country))
        assert cur.fetchone()[0] is expected


def test_greenhouse_publication_date_never_uses_updated_at():
    http = Mock()
    http.get_json.return_value = {"jobs": [
        {"id": 1, "title": "Software Engineer", "first_published": "2020-01-01T10:00:00Z", "updated_at": "2026-09-28T00:00:00Z"},
        {"id": 2, "title": "Software Engineer", "first_published": "bad", "updated_at": "2026-09-28T00:00:00Z"},
    ]}
    result = GreenhouseClient(http).fetch_jobs("Fixture", "fixture")
    assert result[0].posted_at == datetime(2020, 1, 1, 10, tzinfo=timezone.utc)
    assert result[1].posted_at is None


def test_ashby_structured_metadata():
    compensation = {"compensationTierSummary": "US: USD 150k–200k; Canada: CAD 130k–180k", "compensationTiers": [{"title": "Canada"}]}
    http = Mock()
    http.get_json.return_value = {"jobs": [{"id": "1", "title": "Software Engineer", "location": "London", "address": {"postalAddress": {"addressCountry": "GB"}}, "secondaryLocations": [{"location": "Remote", "address": {"addressCountry": "CA"}}], "compensation": compensation, "employmentType": "FullTime", "isListed": False, "publishedAt": "2026-01-01T00:00:00", "applyUrl": "https://jobs.ashbyhq.com/fixture/1/application"}]}
    result = AshbyClient(http).fetch_jobs("Fixture", "fixture")
    http.get_json.assert_called_once_with(AshbyClient.BASE_URL.format(identifier="fixture"), params={"includeCompensation": "true"})
    job = result[0]
    assert job.compensation == compensation
    assert job.posted_at.utcoffset() == timedelta(0)
    assert job.is_listed is False
    assert normalize_job_locations(job.raw_location, job.raw_locations) == [{"location": "London", "country": "United Kingdom"}, {"location": "Remote", "country": "Canada"}]
    assert job.company_apply_url.endswith("/application")


def test_lever_repeated_page_fails_instead_of_looping():
    http = Mock()
    http.get_json.return_value = [{"id": "1", "text": "Software Engineer"}]
    adapter = LeverClient(http)
    adapter.PAGE_SIZE = 1
    with pytest.raises(IngestionFetchError):
        adapter.fetch_jobs("Fixture", "fixture")
    assert http.get_json.call_count == 2


def test_public_api_preserves_old_distinct_jobs_and_all_countries(conn):
    name = "Remediation " + uuid4().hex
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name) VALUES (%s) RETURNING id", (name,))
        cid = cur.fetchone()[0]
        # A populated database already has (Remote, United States): reuse that row instead of colliding with it.
        cur.execute("""INSERT INTO locations(location,country) VALUES ('Remote','United States')
                       ON CONFLICT (location,country) DO UPDATE SET country=EXCLUDED.country RETURNING id""")
        lid = cur.fetchone()[0]
        # The stats assertions below describe exactly this fixture. Rows already in a developer's database would
        # change them, so take them out of the public population for this (rolled-back) transaction only.
        cur.execute("UPDATE job_postings SET is_active=FALSE WHERE company_id<>%s", (cid,))
        for suffix, source, days, active in [('old', 'ashby', 180, True), ('older', 'ashby', 365, True), ('unknown', 'ashby', None, True), ('closed', 'ashby', 1, False), ('broad', 'jobicy', 1, True)]:
            cur.execute("""INSERT INTO job_postings(job_id,company_id,location_id,title,source_name,source_job_id,source_url,posted_at,is_active,description,locations,compensation)
            VALUES (%s,%s,%s,'Software Engineer, Finance',%s,%s,%s,%s,%s,'identical boilerplate',%s,%s)""", (name+suffix,cid,lid,source,name+suffix,'https://jobs.ashbyhq.com/fixture/'+suffix, datetime.now(timezone.utc)-timedelta(days=days) if days else None,active,Json([{'location':'Remote','country':'United States'},{'location':'Toronto','country':'Canada'},{'location':'London','country':'United Kingdom'}]),Json({'compensationTierSummary':'CAD 100k–150k'})))
    @contextmanager
    def cursor():
        with conn.cursor() as cur:
            yield cur
    with patch('api.main.get_db_cursor', cursor):
        client = TestClient(app)
        response = client.get('/api/jobs', params={'freshness':'all','company':name, 'country': 'Canada'})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['total'] == 3
        assert [j['job_id'] for j in data['jobs']] == [name+'old',name+'older',name+'unknown']
        assert data['jobs'][0]['freshness_status'] == 'active'
        assert len(data['jobs'][0]['locations']) == 3
        assert data['jobs'][0]['compensation']['compensationTierSummary'] == 'CAD 100k–150k'
        oldest = client.get('/api/jobs', params={'freshness':'all','company':name,'sort':'oldest','limit':1}).json()
        assert oldest['jobs'][0]['job_id'] == name+'older'
        assert client.get('/api/jobs', params={'freshness':'all','company':name,'q':'SWE'}).json()['total'] == 3
        assert client.get('/api/jobs', params={'company':name,'freshness':'week'}).json()['total'] == 0
        assert client.get('/api/jobs/'+name+'closed').status_code == 404
        assert client.get('/api/jobs/'+name+'broad').status_code == 404
        assert client.get('/api/jobs', params={'sort':'title; DROP TABLE jobs'}).status_code == 422
        detail = client.get('/api/jobs/'+name+'old').json()
        assert detail['locations'][2]['country'] == 'United Kingdom'
        assert client.get('/api/jobs/filters').status_code == 200
        countries = client.get('/api/stats/countries').json()
        assert {x['country'] for x in countries} == {'United States','Canada'}
        # Stats describe the PUBLIC (30-day) population: of the three old rows only the undated one that the
        # source listed just now is visible, and the default list agrees with it.
        assert all(x['postings'] == 1 for x in countries)
        assert client.get('/api/jobs', params={'company': name}).json()['total'] == 1
        assert client.get('/api/jobs', params={'company': name, 'freshness': 'all'}).json()['total'] == 3
        # Exercise synonyms against actual PostgreSQL matching, including multiword
        # queries and AND semantics; do not assert only generated SQL fragments.
        for title, query in [('JS Engineer', 'javascript'), ('JavaScript Engineer', 'js'),
                             ('ML Engineer', 'machine learning'), ('Machine Learning Engineer', 'ml'),
                             ('Back-end Engineer', 'backend'), ('SRE', 'site reliability')]:
            with conn.cursor() as cur:
                cur.execute('UPDATE job_postings SET title=%s WHERE company_id=%s', (title,cid))
            assert client.get('/api/jobs', params={'freshness':'all','company':name,'q':query}).json()['total'] == 3
            assert client.get('/api/jobs', params={'freshness':'all','company':name,'q':query+' nonexistent'}).json()['total'] == 0
        # An ineligible duplicate must not suppress a visible official listing.
        with conn.cursor() as cur:
            cur.execute("UPDATE job_postings SET source_url=%s, is_eligible_role=FALSE WHERE job_id=%s", ('https://jobs.ashbyhq.com/fixture/old', name+'unknown'))
        visible = client.get('/api/jobs', params={'freshness':'all','company':name}).json()
        assert {j['job_id'] for j in visible['jobs']} == {name+'old', name+'older'}



def test_real_pipeline_tombstones_only_after_complete_official_snapshot(conn):
    name = 'Lifecycle ' + uuid4().hex
    config = {'name':name,'ats':'greenhouse','identifier':name}
    # Pipeline commits are real; fixture rows are explicitly cleaned after this test.
    def job(key, title='Software Engineer'):
        return RawJobPosting('greenhouse',name+key,name,title,'Remote - Canada','https://example.com/'+name+key,datetime(2020,1,1,tzinfo=timezone.utc),'Python')
    adapter = Mock()
    def sync(jobs, complete=True, errors=0, total=None):
        adapter.fetch_jobs.return_value = FetchResult(jobs,errors,complete,len(jobs) if total is None else total)
        with patch('ingestion.pipeline.get_ats_client', return_value=adapter), patch('ingestion.company_resolver._discover_ats_branding', return_value=None):
            return sync_company(config,db_conn=conn)
    def active():
        with conn.cursor() as cur:
            cur.execute('SELECT source_job_id FROM job_postings WHERE source_job_id LIKE %s AND is_active', (name+'%',))
            return {r[0] for r in cur.fetchall()}
    try:
        assert sync([job('keep'),job('gone')])['status'] == 'success'
        for kwargs in [dict(complete=False),dict(errors=1,total=2),dict(total=3)]:
            result = sync([job('keep')],**kwargs)
            assert result['status'] == 'partial_success'
            assert result['jobs_deactivated'] == 0
            assert active() == {name+'keep',name+'gone'}
        assert sync([job('keep')])['jobs_deactivated'] == 1
        assert active() == {name+'keep'}
        # A title classifier change is not evidence that a job closed.
        assert sync([job('keep','Payroll Manager')])['jobs_deactivated'] == 0
        assert active() == {name+'keep'}
        with conn.cursor() as cur:
            cur.execute('SELECT title, is_eligible_role FROM job_postings WHERE source_job_id=%s',(name+'keep',))
            assert cur.fetchone() == ('Payroll Manager', False)
        # A complete but EMPTY snapshot is suspicious (vendor fault?): it must not wipe the company
        # on first sight, only after consecutive runs keep confirming the empty listing.
        for _ in range(2):
            empty = sync([])
            assert empty['status'] == 'partial_success' and empty['jobs_deactivated'] == 0
            assert 'EMPTY' in empty['tombstone_suppressed_reason']
            assert active() == {name+'keep'}
        confirmed = sync([])
        assert confirmed['status'] == 'success' and confirmed['jobs_deactivated'] == 1
        assert active() == set()
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute('DELETE FROM job_postings WHERE source_job_id LIKE %s',(name+'%',))
            cur.execute('DELETE FROM companies WHERE name=%s',(name,))
            cur.execute('DELETE FROM sync_runs WHERE company_identifier=%s',(name,))
        conn.commit()


@pytest.mark.parametrize('raw,expected', [
    ('Remote (United States | Canada)', {'United States','Canada'}),
    ('San Francisco, CA; Toronto, ON; London, UK', {'United States','Canada','United Kingdom'}),
    ('San Francisco, CA, Toronto, ON', {'United States','Canada'}),
    ('United States, Canada', {'United States','Canada'}),
    ('Remote (United States, Canada)', {'United States','Canada'}),
    ('United States / Canada', {'United States','Canada'}),
    ('Remote or Mississauga', {'Unknown','Canada'}),
])
def test_alternative_locations_keep_countries(raw, expected):
    assert {loc['country'] for loc in normalize_job_locations(raw,[{'location':raw}])} == expected


def test_structured_country_is_job_evidence_not_employer_country():
    locations = normalize_job_locations('North America',[{'location':'North America','address':{'postalAddress':{'addressCountry':'United States'}}}])
    assert locations == [{'location':'United States','country':'United States','source_location':'North America'}]
    assert is_user_facing_location_eligible(locations[0]['location'],locations[0]['country'])
    assert not is_user_facing_location_eligible('North America')


def test_greenhouse_job_location_metadata_does_not_use_employer_offices():
    http = Mock()
    http.get_json.return_value = {'jobs':[{'id':1,'title':'Software Engineer','location':{'name':'Hybrid'},'metadata':[{'name':'Job Posting Location','value':['Austin, US','London, UK']}],'offices':[{'name':'Toronto'}]}]}
    job = GreenhouseClient(http).fetch_jobs('Fixture','fixture')[0]
    assert job.raw_location == 'Hybrid'
    assert {x['country'] for x in normalize_job_locations(job.raw_location,job.raw_locations)} == {'United States','United Kingdom'}


def test_logo_bytes_survive_missing_worker_files(conn, tmp_path):
    from ingestion.company_resolver import persist_logo_asset
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="M0 0h1v1H0z"/></svg>'
    file = tmp_path / 'fixture.svg'
    file.write_bytes(svg)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO companies(name,logo_status) VALUES (%s,'verified') RETURNING id", ('Logo '+uuid4().hex,))
        cid = cur.fetchone()[0]
        with patch('ingestion.company_resolver.LOGOS_DIR',tmp_path):
            persist_logo_asset(cur,cid,{'logo_url':'/logos/fixture.svg','logo_status':'verified'})
    file.unlink()
    @contextmanager
    def cursor():
        with conn.cursor() as cur:
            yield cur
    with patch('api.main.get_db_cursor',cursor):
        response = TestClient(app).get(f'/api/company-logos/{cid}')
        assert response.status_code == 200
        assert response.content == svg
        assert response.headers['content-type'] == 'image/svg+xml'
        assert response.headers['x-content-type-options'] == 'nosniff'


def test_ingestion_preserves_plain_markdown_and_table_semantics():
    from ingestion.extractor import sanitize_html_description
    plain = '**Requirements**\n- Python\n- SQL'
    assert sanitize_html_description(plain) == plain
    table = sanitize_html_description('<table><tr><th>Location</th><th>Salary</th></tr><tr><td>Canada</td><td>CAD 150k</td></tr></table>')
    assert '<table>' in table and '<th>' in table and '<td>CAD 150k</td>' in table


def test_source_status_reports_degraded_sources_without_error_text(conn):
    client_name = "src" + uuid4().hex[:8]
    with conn.cursor() as cur:
        for ident, status, err in [(client_name + "-a", "success", None), (client_name + "-b", "partial_success", "secret internal detail")]:
            cur.execute("""INSERT INTO sync_runs(source_name,company_identifier,status,completed_at,error_message)
                           VALUES (%s,%s,%s,NOW(),%s)""", ("statustest", ident, status, err))
    @contextmanager
    def cursor():
        with conn.cursor() as cur:
            yield cur
    with patch('api.main.get_db_cursor', cursor):
        response = TestClient(app).get('/api/sources/status')
    assert response.status_code == 200
    row = next(r for r in response.json() if r['source_name'] == 'statustest')
    assert row['status'] == 'degraded' and row['companies_tracked'] == 2
    assert row['companies_ok'] == 1 and row['companies_degraded'] == 1
    assert row['last_success_at'] is not None
    assert 'secret' not in response.text


def test_duplicate_suppression_uses_hashable_keys_not_one_or_condition():
    from api.main import get_deduplication_sql_predicate

    sql = get_deduplication_sql_predicate("jp")
    assert sql.count("NOT EXISTS") == 2          # one per identity key, so each can be a hash anti join
    assert "split_part(jp2.source_url" in sql and "jp2.source_job_id" in sql
    assert "jp2.source_name = jp.source_name AND NULLIF(jp2.source_job_id" in sql
