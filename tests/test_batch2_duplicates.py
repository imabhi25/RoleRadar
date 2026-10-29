"""Duplicate public results stay deduplicated across counts and pages."""
from psycopg2.extras import Json

from tests.test_public_visibility import conn, _api, _company, _insert  # noqa: F401


def test_duplicate_groups_and_distinct_requisitions(conn):
    name, company_id = _company(conn)
    descriptions = [
        'Build distributed pricing systems and lead infrastructure development with the platform engineering team.',
        'Build customer pricing tools and lead product experimentation with the commerce engineering team.',
    ]
    with conn.cursor() as cur:
        for i in range(8):
            key = name + str(i)
            _insert(cur, company_id, key, days_old=0, location='Vancouver, BC', title='Software Dev Engineer, Pricing Shared Platform')
            text = descriptions[i // 4]
            if i % 2:
                text = '<p>' + text.upper() + '</p>'
            cur.execute('UPDATE job_postings SET description=%s WHERE job_id=%s', (text, key))
            if i % 2:
                cur.execute("UPDATE job_postings SET locations = jsonb_set(locations, '{0,raw_location}', to_jsonb('Vancouver BC'::text), true) WHERE job_id=%s", (key,))
    with _api(conn) as client:
        response = client.get('/api/jobs', params={'company': name, 'limit': 20})
        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 2
        assert len(data['jobs']) == 2
        assert all(job['variant_identifier'] == job['job_id'] for job in data['jobs'])
        first = client.get('/api/jobs', params={'company': name, 'limit': 1, 'offset': 0}).json()
        second = client.get('/api/jobs', params={'company': name, 'limit': 1, 'offset': 1}).json()
        assert first['total'] == second['total'] == 2
        assert first['jobs'][0]['job_id'] != second['jobs'][0]['job_id']

        # A posting with an extra location is a distinct opening even when its primary place and text match.
        with conn.cursor() as cur:
            key = name + 'other-locations'
            _insert(cur, company_id, key, days_old=0, location='Vancouver, BC', title='Software Dev Engineer, Pricing Shared Platform')
            cur.execute('UPDATE job_postings SET description=%s, locations=%s WHERE job_id=%s',
                        (descriptions[0], Json([{'location': 'Vancouver, BC', 'country': 'Canada'}, {'location': 'Toronto, ON', 'country': 'Canada'}]), key))
        assert client.get('/api/jobs', params={'company': name}).json()['total'] == 3


def test_empty_markup_is_not_enough_evidence_to_merge_jobs(conn):
    name, company_id = _company(conn)
    with conn.cursor() as cur:
        for i in range(2):
            key = name + str(i)
            _insert(cur, company_id, key, days_old=0, title='Engineer')
            cur.execute('UPDATE job_postings SET description=%s WHERE job_id=%s', ('<div>' + ' ' * 50 + '</div>', key))
    with _api(conn) as client:
        assert client.get('/api/jobs', params={'company': name}).json()['total'] == 2
