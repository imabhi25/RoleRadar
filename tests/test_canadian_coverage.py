"""Official career adapters: real-shaped markup and failure-aware snapshot guarantees."""
import json
from types import SimpleNamespace

import pytest

from ingestion.clients import get_ats_client
from ingestion.clients.google import GoogleClient
from ingestion.clients.phenom import PhenomClient
from ingestion.clients.shopify import ShopifyClient
from ingestion.clients.successfactors import SuccessFactorsClient
from ingestion.clients.careers_html import shopify_loader, source_date
from ingestion.http_client import IngestionFetchError
from ingestion.normalizer import OFFICIAL_SOURCES, normalize_job_locations, is_swe_role


class Pages:
    def __init__(self, respond):
        self.respond = respond

    def get(self, url, params=None):
        result = self.respond(url, params or {})
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result)


def google_list(ids, total=None, next_page=None):
    rows = ''.join(f'''<li class="lLd3Je"><h3>Software Developer Intern {i}</h3>
        <span class="r0wTof">Waterloo, ON, Canada</span><span class="r0wTof">;</span><span class="r0wTof">; Toronto, ON, Canada</span>
        <a href="jobs/results/{i}-software-developer-intern">Learn more</a></li>''' for i in ids)
    following = f'<a href="?page={next_page}">Next</a>' if next_page else ''
    return f'<span>{total if total is not None else len(ids)} jobs matched</span><ul>{rows}</ul>{following}'


GOOGLE_DETAIL = '''<div><div class="KwJkGe"><i class="google-material-icons">info_outline</i><span class="v7dlUb">X</span>
    <p>Canada residency required. Applications close February 26, 2027.</p><h3>Minimum qualifications:</h3><ul><li>Python</li></ul></div>
    <div class="aG5W3"><h3>About the job</h3><p>Canada: $120000 CAD + bonus + equity + benefits.</p></div>
    <div class="BDNOWe"><h3>Responsibilities</h3><p>Develop reliable software.</p></div>
    <div class="bE3reb">Accommodations: contact us. <a href="./privacy-policy">Privacy</a></div></div>'''


def test_google_complete_pagination_preserves_details_locations_and_unknown_dates():
    http = Pages(lambda url, p: (google_list([1], 2, 2) if p['page'] == 1 else google_list([2], 2)) if p else GOOGLE_DETAIL)
    result = GoogleClient(http).fetch_jobs('Google', 'Canada')
    assert result.fetch_complete and result.total_raw_records == 2
    job = result.jobs[0]
    assert job.posted_at is None
    assert [x['country'] for x in normalize_job_locations(job.raw_location, job.raw_locations)] == ['Canada', 'Canada']
    assert all(x in job.raw_description for x in ['Minimum qualifications', 'bonus', 'equity', 'benefits', 'Accommodations'])
    assert job.raw_description.index('Minimum qualifications') < job.raw_description.index('Responsibilities')
    assert job.company_apply_url.endswith('/results/1-software-developer-intern')
    assert 'info_outline' not in job.raw_description and 'class="v7dlUb"' not in job.raw_description
    assert 'Canada residency required' in job.raw_description and 'February 26, 2027' in job.raw_description
    assert 'https://www.google.com/about/careers/applications/privacy-policy' in job.raw_description


@pytest.mark.parametrize('failure', ['duplicate', 'page_failure', 'count_change', 'missing_detail', 'missing_count'])
def test_google_incomplete_snapshots_cannot_close_jobs(failure):
    def respond(url, p):
        if not p:
            return '<h1>Job unavailable</h1>' if failure == 'missing_detail' else GOOGLE_DETAIL
        if p['page'] == 1:
            if failure == 'missing_count':
                return 'Service unavailable'
            return google_list([1], 2, 2)
        if failure == 'page_failure':
            return IngestionFetchError('HTTP 503')
        return google_list([1 if failure == 'duplicate' else 2], 3 if failure == 'count_change' else 2)
    if failure == 'missing_count':
        with pytest.raises(IngestionFetchError):
            GoogleClient(Pages(respond)).fetch_jobs('Google', 'Canada')
    else:
        result = GoogleClient(Pages(respond)).fetch_jobs('Google', 'Canada')
        assert not result.fetch_complete
        if failure == 'missing_detail':
            assert result.jobs == []  # Never overwrite stored descriptions with a transient blank.


def sf_list(ids, total, title='Software Developer'):
    rows = ''.join(f'''<tr class="data-row"><td><a class="jobTitle-link" href="/job/Toronto-Developer/{i}/">{title}</a></td>
       <td class="colLocation"><span class="jobLocation">Toronto, ON, CA</span></td>
       <td class="colDate"><span class="jobDate">Sep 29, 2026</span></td></tr>''' for i in ids)
    return f'<p>Results 1 – {len(ids)} of {total}</p><table>{rows}</table>'


SF_DETAIL = '''<span itemprop="jobLocation"><span itemprop="address"><meta itemprop="addressLocality" content="Montreal"/>
  <meta itemprop="addressRegion" content="QC"/><meta itemprop="addressCountry" content="CA"/></span></span>
  <span itemprop="jobLocation"><span itemprop="address"><meta itemprop="addressLocality" content="Toronto"/>
  <meta itemprop="addressCountry" content="CA"/></span></span>
  <span itemprop="description"><h2>Responsibilities</h2><p>Work in our office three days each week.</p>
  <p>Application Deadline: 10/30/2026</p><ul><li>Python</li></ul></span>'''


def test_successfactors_tenant_scoped_ids_dates_and_multiple_locations():
    http = Pages(lambda url, p: sf_list([123], 1) if '/search/' in url else SF_DETAIL)
    r = SuccessFactorsClient(http).fetch_jobs('Rogers', 'rogers')
    s = SuccessFactorsClient(http).fetch_jobs('Scotiabank', 'scotiabank')
    assert r.fetch_complete and s.fetch_complete
    assert r.jobs[0].source_job_id != s.jobs[0].source_job_id
    assert r.jobs[0].posted_at.isoformat() == '2026-09-29T00:00:00+00:00'
    assert len(r.jobs[0].raw_locations) == 2
    assert '10/30/2026' in r.jobs[0].raw_description
    assert r.jobs[0].company_apply_url == 'https://jobs.rogers.com/job/Toronto-Developer/123/'


@pytest.mark.parametrize('failure', ['page_failure', 'detail_failure', 'duplicate', 'missing_count', 'missing_description'])
def test_successfactors_failure_suppresses_closure(failure):
    def respond(url, p):
        if '/search/' in url:
            if failure == 'missing_count':
                return '<h1>Access denied</h1>'
            if p['startrow'] == 0:
                return sf_list([123], 2)
            return IngestionFetchError('HTTP 500') if failure == 'page_failure' else sf_list([123 if failure == 'duplicate' else 124], 2)
        return IngestionFetchError('HTTP 500') if failure == 'detail_failure' else '<p>Removed</p>' if failure == 'missing_description' else SF_DETAIL
    if failure == 'missing_count':
        with pytest.raises(IngestionFetchError):
            SuccessFactorsClient(Pages(respond)).fetch_jobs('Rogers', 'rogers')
    else:
        result = SuccessFactorsClient(Pages(respond)).fetch_jobs('Rogers', 'rogers')
        assert not result.fetch_complete
        if failure in ('detail_failure', 'missing_description'):
            assert result.jobs == []


def bell_page(ids, total):
    rows = [{'jobId': str(i), 'jobSeqNo': f'BECACA{i}EXTERNALENCA', 'title': 'Software Developer Intern',
             'description': '<p>Hybrid: Canada only. Python and Java.</p>', 'location': 'Montreal, Quebec',
             'country': 'Canada', 'postedDate': '2026-09-29T00:00:00.000+0000',
             'multi_location_array': [{'location': 'Toronto, Ontario'}, {'location': 'Montreal, Quebec'}]} for i in ids]
    return 'phApp.ddo = ' + json.dumps({'eagerLoadRefineSearch': {'status': 200, 'totalHits': total, 'data': {'jobs': rows}}}) + ';'


def test_bell_complete_snapshot_and_exact_official_route():
    result = PhenomClient(Pages(lambda u, p: bell_page([1] if p['from'] == 0 else [2], 2))).fetch_jobs('Bell', 'bell')
    assert result.fetch_complete and result.total_raw_records == 2
    assert result.jobs[0].company_apply_url == 'https://jobs.bell.ca/ca/en/job/BECACA1EXTERNALENCA'
    assert 'Canada only' in result.jobs[0].raw_description
    assert len(result.jobs[0].raw_locations) == 2


def test_bell_talent_community_is_not_counted_as_an_open_internship():
    page = bell_page([1], 1).replace('Software Developer Intern', 'Intern Program - Future Opportunities').replace(
        'Hybrid: Canada only. Python and Java.', 'This posting builds our student talent community for future opportunities.')
    result = PhenomClient(Pages(lambda u, p: page)).fetch_jobs('Bell', 'bell')
    assert result.fetch_complete and result.jobs[0].is_listed is False


@pytest.mark.parametrize('failure', ['duplicate', 'page_failure', 'count_change', 'malformed'])
def test_bell_incomplete_snapshot_suppresses_closure(failure):
    def respond(u, p):
        if p['from'] == 0:
            return 'Access denied' if failure == 'malformed' else bell_page([1], 2)
        if failure == 'page_failure':
            return IngestionFetchError('HTTP 503')
        return bell_page([1 if failure == 'duplicate' else 2], 3 if failure == 'count_change' else 2)
    if failure == 'malformed':
        with pytest.raises(IngestionFetchError):
            PhenomClient(Pages(respond)).fetch_jobs('Bell', 'bell')
    else:
        assert not PhenomClient(Pages(respond)).fetch_jobs('Bell', 'bell').fetch_complete


def router_page(route, loader):
    """Encode a small real-shaped reference table, including booleans and undefined."""
    pool = []
    def ref(v):
        if v is None:
            return -5
        i = len(pool)
        pool.append(None)
        if isinstance(v, dict):
            pool[i] = {f'_{ref(k)}': ref(value) for k, value in v.items()}
        elif isinstance(v, list):
            pool[i] = [ref(x) for x in v]
        else:
            pool[i] = v
        return i
    ref({'loaderData': {route: loader}})
    return '<script>window.__reactRouterContext.streamController.enqueue(' + json.dumps(json.dumps(pool)) + ');</script>'


POSTING_ID = '4931fbca-d2b7-47a8-b87a-287c344153f6'


def shopify_pages(detail_failure=False, us_internship=False):
    posting = {'id': POSTING_ID, 'title': 'Software Engineering Intern', 'status': 'Published', 'isListed': True,
               'workplaceType': 'Remote', 'employmentType': 'Intern', 'locationName': 'Canada',
               'locationIds': {'primaryLocationId': 'canada', 'secondaryLocationIds': []},
               'publishedDate': '2026-09-28', 'applicationDeadline': '2026-10-12T04:00:00.000Z'}
    if us_internship:
        posting.update(title='US Software Engineering Internships Summer 2027', locationName='Americas', locationIds={})
    listing = router_page('($locale)/careers', {'jobPostingsWithJobs': [{'jobPosting': posting, 'job': {'hiringTeam': 'Never stored'}}],
                         'atsLocations': [{'id': 'canada', 'name': 'Canada', 'address': {'postalAddress': {'addressCountry': 'Canada'}}}]})
    detail = router_page('($locale)/careers/$posting', {'jobPosting': {'id': POSTING_ID, 'descriptionHtml': '<h3>Responsibilities</h3><p>Build software with Python.</p>'}})
    return Pages(lambda url, p: listing if url.endswith('/careers') else IngestionFetchError('HTTP 503') if detail_failure else detail)


def test_shopify_public_loader_preserves_original_html_deadline_and_geography():
    result = ShopifyClient(shopify_pages()).fetch_jobs('Shopify', 'shopify')
    assert result.fetch_complete
    job = result.jobs[0]
    assert job.raw_workplace_type == 'Remote' and job.raw_locations[0]['country'] == 'Canada'
    assert job.posted_at.isoformat() == '2026-09-28T00:00:00+00:00'
    assert '<h3>Responsibilities</h3>' in job.raw_description and '2026-10-12' in job.raw_description
    assert 'hiringTeam' not in job.raw_description
    assert job.company_apply_url == 'https://www.shopify.com/careers/_' + POSTING_ID


def test_shopify_failed_detail_keeps_snapshot_incomplete_and_omits_blank_update():
    result = ShopifyClient(shopify_pages(True)).fetch_jobs('Shopify', 'shopify')
    assert not result.fetch_complete and result.parse_error_count == 1 and result.jobs == []


def test_shopify_explicit_us_internship_does_not_become_canadian_remote_job():
    job = ShopifyClient(shopify_pages(us_internship=True)).fetch_jobs('Shopify', 'shopify').jobs[0]
    locations = normalize_job_locations(job.raw_location, job.raw_locations)
    assert any(x['country'] == 'United States' for x in locations)
    assert all(x['country'] != 'Canada' for x in locations)


def test_shopify_changed_encoding_fails_closed():
    with pytest.raises(IngestionFetchError):
        shopify_loader('<script>throw new Error("blocked")</script>', '($locale)/careers')


@pytest.mark.parametrize('source,kind', [('google', GoogleClient), ('shopify', ShopifyClient), ('phenom', PhenomClient), ('successfactors', SuccessFactorsClient)])
def test_official_source_registration(source, kind):
    assert isinstance(get_ats_client(source), kind)
    assert source in OFFICIAL_SOURCES


def test_source_dates_never_substitute_today_for_unknown():
    assert source_date('Posted recently') is None
    assert source_date(None) is None


@pytest.mark.parametrize('title,description,expected', [
    ('2027 Graduate Program, Technology Services - Emerging AI and Data Solutions', 'Software programming with Python and Java.', True),
    ('2027 Internship Program - Networks', 'Build software APIs with Python and Git.', True),
    ('2027 Graduate Program - Networks', 'Maintain telecom equipment and physical network installations.', False),
    ('2027 Graduate Program - Human Resources', 'Our software uses Python, Java and Git.', False),
    ('2027 Graduate Program - Finance', 'Python and Java software.', False),
    ('2027 Graduate Program - Technology', '', False),
])
def test_technical_student_programs_require_actual_software_evidence(title, description, expected):
    assert is_swe_role(title, description) is expected


@pytest.mark.parametrize('kind', [GoogleClient, ShopifyClient, PhenomClient, SuccessFactorsClient])
def test_adapter_rejects_unverified_identifiers(kind):
    with pytest.raises(ValueError):
        kind(Pages(lambda u, p: pytest.fail('Must not fetch an arbitrary URL'))).fetch_jobs('Unknown', 'https://example.com')
