"""End-to-end regressions for the adversarial review, using PostgreSQL 16."""
from pathlib import Path
from uuid import uuid4
import pytest
from psycopg2.extras import Json
from tests.test_public_visibility import conn, _api, _company, _insert
from ingestion.normalizer import normalize_job_locations, is_user_facing_location_eligible
from ingestion.clients.workday import WorkdayClient
from tests.test_workday_amazon import FakeWorkday, make_listing
from db.repair_public_data import repair_public_data


@pytest.mark.parametrize('pay,annual', [
    ({'min':80000,'max':115200,'currency':'CAD','interval':'year'},115200),
    ({'min':45,'max':60,'currency':'CAD','interval':'hour'},124800),
    ({'currency':'CAD','interval':'year','ranges':[{'min':90000,'max':130000}]},130000),
    ({'summaryComponents':[{'minValue':90000,'maxValue':140000,'currencyCode':'CAD','interval':'1 YEAR','compensationType':'Salary'}]},140000),
    ({'compensationTiers':[{'components':[{'minValue':90000,'maxValue':150000,'currencyCode':'CAD','interval':'year','compensationType':'Salary'}]}]},150000),
])
def test_salary_filter_reads_all_provider_shapes(conn,pay,annual):
    name,cid=_company(conn)
    with conn.cursor() as cur:
        _insert(cur,cid,name,days_old=0)
        cur.execute('UPDATE job_postings SET compensation=%s WHERE job_id=%s',(Json(pay),name))
    with _api(conn) as client:
        params={'company':name,'min_compensation':annual,'compensation_currency':'CAD'}
        assert client.get('/api/jobs',params=params).json()['total']==1
        assert client.get('/api/jobs',params={**params,'min_compensation':annual+1}).json()['total']==0
        assert client.get('/api/jobs',params={**params,'compensation_currency':'USD'}).json()['total']==0


@pytest.mark.parametrize('pay', [None,[],{}, {'ranges':'invalid'}, {'min':'oops','max':'?','currency':'CAD','interval':'year'},
    {'min':1,'max':2,'currency':'USD','interval':'year'}, {'min':150000,'max':90000,'currency':'CAD','interval':'year'},
    {'min':90000,'max':100000,'currency':'CAD'},
    {'summaryComponents':[{'minValue':100000,'maxValue':200000,'currencyCode':'CAD','interval':'year','compensationType':'Equity'}]},
])
def test_pay_garbage_is_not_a_salary_or_a_query_error(conn,pay):
    with conn.cursor() as cur:
        cur.execute('SELECT jobber_pay_ranges(%s)',(Json(pay),))
        assert cur.fetchone()[0]==[]


@pytest.mark.parametrize('title,description,expected', [
    ('Software Engineer','<h2>Requirements</h2><p>12+ years of software engineering experience.</p>','senior'),
    ('Product Engineer','<p>10+ years building distributed systems.</p>','senior'),
    ('Data Engineer','<p>8 years of professional experience.</p>','senior'),
    ('Associate Director DevOps','<p>5+ years experience.</p>','senior'),
    ('Software Engineer','<p>5 years experience.</p>','mid'),
    ('Software Engineer','<h2>Preferred qualifications</h2><p>10 years experience.</p>','unknown'),
    ('Software Engineer','Preferred qualifications:\n10 years experience.','unknown'),
    ('Software Engineer','<h2>About the company</h2><p>20 years building great software.</p><h2>Requirements</h2><p>2 years experience.</p>','entry'),
    ('Software Engineer','<p>12 years experience or a degree and 2 years experience.</p>','entry'),
    ('Software Engineer','<p>Passionate about programming.</p>','unknown'),
])
def test_experience_uses_required_evidence_not_associate_or_company_age(conn,title,description,expected):
    with conn.cursor() as cur:
        cur.execute("SELECT jobber_experience_level(%s,'full_time',%s)",(title,description))
        assert cur.fetchone()[0]==expected
    name,cid=_company(conn)
    with conn.cursor() as cur:
        _insert(cur,cid,name,days_old=0,title=title)
        cur.execute('UPDATE job_postings SET description=%s WHERE job_id=%s',(description,name))
    with _api(conn) as client:
        result=client.get('/api/jobs',params={'company':name}).json()['jobs'][0]
        assert result['experience_level']==expected
        assert client.get('/api/jobs/'+name).json()['experience_level']==expected
        if expected!='unknown':
            assert client.get('/api/jobs',params={'company':name,'experience_level':expected}).json()['total']==1


@pytest.mark.parametrize('query,matching,not_matching', [
    ('Java','Java','JavaScript'), ('nodejs','Node.js','NotNodejs'), ('js','JavaScript','Java'),
    ('postgres','PostgreSQL','Postgreslike'), ('"C#"','C#','C++'), ('C#','C#','C++'), ('Ruby','Ruby','rubylike'), ('Kafka','Kafka','Kafkaesque'),
    ('"distributed systems"','distributed systems','systems distributed'), ('cafe','café','restaurant'),
])
def test_description_search_keeps_technical_and_phrase_boundaries(conn,query,matching,not_matching):
    name,cid=_company(conn)
    with conn.cursor() as cur:
        for i,description in enumerate((matching,not_matching)):
            _insert(cur,cid,name+str(i),days_old=0,title='Software Engineer '+str(i))
            cur.execute('UPDATE job_postings SET description=%s WHERE job_id=%s',('<p>'+description+'</p>',name+str(i)))
    with _api(conn) as client:
        response=client.get('/api/jobs',params={'company':name,'q':query})
        assert response.status_code==200,response.text
        assert [j['job_id'] for j in response.json()['jobs']]==[name+'0']


@pytest.mark.parametrize('label', ['Washington, D.C.','Washington, D.C., United States','Remote US & Canada','Remote, Canada; Remote, United States'])
def test_explicit_location_variants_are_eligible_in_python_and_sql(conn,label):
    locations=normalize_job_locations(label)
    assert all(is_user_facing_location_eligible(l['location'],l['country']) for l in locations)
    assert all(' - ,' not in l['location'] for l in locations)
    name,cid=_company(conn)
    with conn.cursor() as cur:
        _insert(cur,cid,name,days_old=0,location=label)
    with _api(conn) as client:
        assert client.get('/api/jobs',params={'company':name}).json()['total']==1


def test_company_counts_match_the_public_list_not_raw_postings(conn):
    name,cid=_company(conn)
    with conn.cursor() as cur:
        for suffix,age,location in [('fresh',0,'Toronto, ON'),('old',60,'Toronto, ON'),('outside',0,'London, United Kingdom')]:
            _insert(cur,cid,name+suffix,days_old=age,location=location,title='Software Engineer '+suffix)
        _insert(cur,cid,name+'sample',days_old=0,title='Sample Software Engineer')
        cur.execute("UPDATE job_postings SET source_name='sample' WHERE job_id=%s",(name+'sample',))
        cur.execute('INSERT INTO companies(name) VALUES(%s)',(name+' empty',))
    with _api(conn) as client:
        count=client.get('/api/jobs',params={'company':name}).json()['total']
        companies=client.get('/api/companies').json()
        assert next(c for c in companies if c['name']==name)['active_jobs_count']==count==1
        assert not any(c['name']==name+' empty' for c in companies)


def test_stored_location_and_missing_skill_links_are_repaired(conn):
    name,cid=_company(conn)
    with conn.cursor() as cur:
        _insert(cur,cid,name,days_old=0)
        cur.execute("UPDATE job_postings SET description='<p>C# Ruby Kafka</p>',locations=%s WHERE job_id=%s",
            (Json([{'location':'Canada','country':'Canada','source_location':'Remote US & Canada'}]),name))
    repair_public_data(conn)
    with _api(conn) as client:
        job=client.get('/api/jobs/'+name).json()
        assert {l['country'] for l in job['locations']}=={'Canada','United States'}
        assert {'C#','Ruby','Kafka'}<=set(job['skills'])
    with conn.cursor() as cur:
        cur.execute('SELECT job_id FROM job_postings WHERE job_id=%s',(name,))
        assert cur.fetchone()[0]==name


def test_workday_site_identity_and_existing_public_links(conn):
    first=WorkdayClient(http_client=FakeWorkday([make_listing(1)])).fetch_jobs('One','acme.wd3/Careers').jobs[0]
    class OtherTenant(FakeWorkday):
        def post_json(self,url,*args,**kwargs):
            return super().post_json(url.replace('other','acme'),*args,**kwargs)
    second=WorkdayClient(http_client=OtherTenant([make_listing(1)])).fetch_jobs('Two','other.wd3/Careers').jobs[0]
    assert first.source_job_id.startswith('acme.wd3/Careers/')
    # Adapter uses the identifier, not the shared title/slug, as part of identity.
    assert first.source_job_id!=second.source_job_id
    name,cid=_company(conn)
    slug='Software-Developer-1_R-1'
    with conn.cursor() as cur:
        _insert(cur,cid,name,days_old=0)
        cur.execute("UPDATE job_postings SET source_name='workday',source_job_id=%s,source_url=%s WHERE job_id=%s",
            (slug,'https://tenant.wd3.myworkdayjobs.com/en-US/Careers/job/Toronto/'+slug+'?source=web',name))
        cur.execute(Path('db/migrations/013_scope_workday_identities.sql').read_text())
        cur.execute('SELECT job_id,source_job_id FROM job_postings WHERE job_id=%s',(name,))
        assert cur.fetchone()==(name,'tenant.wd3/Careers/'+slug)


def test_migration_backfills_existing_rows_merges_case_only_companies(conn):
    name,cid=_company(conn)
    with conn.cursor() as cur:
        _insert(cur,cid,name,days_old=0,title='Software Engineer')
        cur.execute("UPDATE job_postings SET description='<p>10+ years experience.</p>',compensation=%s WHERE job_id=%s",
            (Json({'min':80000,'max':100000,'currency':'CAD','interval':'year'}),name))
        cur.execute('DROP INDEX idx_companies_name_folded')
        cur.execute("INSERT INTO companies(name,logo_status) VALUES(%s,'verified') RETURNING id",(name.upper(),))
        canonical=cur.fetchone()[0]
        cur.execute('ALTER TABLE job_postings DROP COLUMN pay_ranges, DROP COLUMN experience_level, DROP COLUMN search_document')
        cur.execute(Path('db/migrations/012_public_data_contracts.sql').read_text())
        cur.execute('SELECT job_id,company_id,experience_level,pay_ranges FROM job_postings WHERE job_id=%s',(name,))
        job_id,company_id,level,pay=cur.fetchone()
        assert (job_id,company_id,level)==(name,canonical,'senior')
        assert pay[0]['max_annual']==100000
        cur.execute('SELECT count(*) FROM companies WHERE lower(name)=lower(%s)',(name,))
        assert cur.fetchone()[0]==1


def test_scoped_workday_upsert_preserves_old_links_and_other_employers(conn):
    from ingestion.pipeline import upsert_job_posting
    name,cid=_company(conn)
    other,other_id=_company(conn)
    with conn.cursor() as cur:
        _insert(cur,cid,name,days_old=0)
        cur.execute('SELECT location_id FROM job_postings WHERE job_id=%s',(name,))
        lid=cur.fetchone()[0]
        slug='Software-Developer-1_R-1'
        url='https://tenant.wd3.myworkdayjobs.com/Careers/job/Toronto/'+slug
        cur.execute("UPDATE job_postings SET source_name='workday',source_job_id=%s,source_url=%s WHERE job_id=%s",(slug,url,name))
        cur.execute(Path('db/migrations/013_scope_workday_identities.sql').read_text())
        for company_id,tenant,public_id in [(cid,'tenant','new-link-that-must-not-replace-old'),(other_id,'other',other)]:
            upsert_job_posting(cur,job_id=public_id,company_id=company_id,title='Software Engineer',location_id=lid,
                description='<p>Java</p>',workplace_type='onsite',source_name='workday',source_job_id=tenant+'.wd3/Careers/'+slug,
                source_url=url.replace('tenant',tenant),posted_at=None,role_type='full_time')
        cur.execute("SELECT job_id,company_id FROM job_postings WHERE source_name='workday' AND company_id=ANY(%s) ORDER BY company_id",([cid,other_id],))
        assert cur.fetchall()==[(name,cid),(other,other_id)]


def test_identity_backfill_waits_for_the_serialized_migration_runner(conn):
    from db.migrate import run_migrations
    name,cid=_company(conn)
    slug="Dev_"+uuid4().hex
    with conn.cursor() as cur:
        _insert(cur,cid,name,days_old=0)
        cur.execute("UPDATE job_postings SET source_name='workday',source_job_id=%s,source_url=%s WHERE job_id=%s",(slug,'https://tenant.wd3.myworkdayjobs.com/Careers/job/Toronto/'+slug,name))
        cur.execute("DELETE FROM schema_migrations WHERE version='013_scope_workday_identities.sql'")
    # Exercise real SQL while leaving fixture changes inside its rollback transaction.
    class Transaction:
        def cursor(self):
            return conn.cursor()
        def commit(self):
            pass
    from unittest.mock import patch
    with patch('db.migrate.seed_and_audit_all_target_companies',return_value={'verified_count':0}):
        run_migrations(Transaction(),defer_versions={'013_scope_workday_identities.sql'})
    with conn.cursor() as cur:
        cur.execute('SELECT source_job_id FROM job_postings WHERE job_id=%s',(name,))
        assert cur.fetchone()[0]==slug
    with patch('db.migrate.seed_and_audit_all_target_companies',return_value={'verified_count':0}):
        run_migrations(Transaction())
    with conn.cursor() as cur:
        cur.execute('SELECT job_id,source_job_id FROM job_postings WHERE job_id=%s',(name,))
        assert cur.fetchone()==(name,'tenant.wd3/Careers/'+slug)


def test_backfill_batches_missing_skill_links_and_is_idempotent(conn):
    repair_public_data(conn)  # Bring the controlled corpus to the current rules before measuring new rows.
    name,cid=_company(conn)
    with conn.cursor() as cur:
        for i in range(200):
            _insert(cur,cid,name+str(i),days_old=0,title='Software Engineer '+str(i))
        cur.execute("UPDATE job_postings SET description='<p>C# Ruby Kafka</p>' WHERE company_id=%s",(cid,))
    class Cursor:
        def __init__(self,inner,owner):
            self.inner,self.owner=inner,owner
        def __enter__(self):
            self.inner.__enter__()
            return self
        def __exit__(self,*args):
            return self.inner.__exit__(*args)
        def __getattr__(self,key):
            return getattr(self.inner,key)
        def execute(self,*args,**kwargs):
            self.owner.statements+=1
            return self.inner.execute(*args,**kwargs)
    class Connection:
        statements=0
        def cursor(self):
            return Cursor(conn.cursor(),self)
    measured=Connection()
    repair_public_data(measured)
    assert measured.statements<=12  # Hundreds of jobs must not cause thousands of hosted DB round trips.
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM job_posting_skills jps JOIN job_postings jp ON jp.id=jps.job_posting_id WHERE jp.company_id=%s',(cid,))
        assert cur.fetchone()[0]==600
    repair_public_data(conn)
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM job_posting_skills jps JOIN job_postings jp ON jp.id=jps.job_posting_id WHERE jp.company_id=%s',(cid,))
        assert cur.fetchone()[0]==600
