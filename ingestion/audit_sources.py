"""Read-only audit of configured ATS boards and existing broad feeds. Never opens a DB."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import requests
from ingestion.clients import get_ats_client
from ingestion.http_client import HardenedHttpClient
from ingestion.normalizer import normalize_job_locations, is_user_facing_location_eligible, is_swe_role


def audit(config):
    session = requests.Session()
    http = HardenedHttpClient(session=session, timeout=(5, 12))
    try:
        client = get_ats_client(config['ats'], http_client=http)
        if config.get('broad'):
            kwargs = {'max_pages': 2} if config['ats'] == 'arbeitnow' else {'count': 50}
            result = client.fetch_jobs(**kwargs)
        else:
            result = client.fetch_jobs(config['name'], config['identifier'])
        swe = [j for j in result.jobs if j.is_listed and is_swe_role(j.title)]
        eligible = sum(any(is_user_facing_location_eligible(loc['location'], loc['country']) for loc in normalize_job_locations(j.raw_location, j.raw_locations)) for j in swe)
        return {'company': config['name'], 'source': config['ats'], 'complete': result.fetch_complete,
                'raw_records': result.total_raw_records, 'parse_errors': result.parse_error_count,
                'swe': len(swe), 'eligible': eligible, 'dated': sum(j.posted_at is not None for j in swe),
                'compensation': sum(bool(j.compensation) for j in swe),
                'multiple_locations': sum(len(normalize_job_locations(j.raw_location,j.raw_locations)) > 1 for j in swe)}
    except Exception as exc:
        return {'company': config['name'], 'source': config['ats'], 'error': str(exc)}
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    config = json.loads((Path(__file__).resolve().parents[1] / 'config/target_companies.json').read_text())
    config += [{'name': s, 'ats': s, 'broad': True} for s in ['jobicy','remotive','arbeitnow']]
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(audit, config))
    Path(args.output).write_text(json.dumps(results, indent=2))
    print(json.dumps({'sources':len(results),'errors':sum('error' in r for r in results),'incomplete':sum(r.get('complete') is False for r in results)}))


if __name__ == '__main__':
    main()
