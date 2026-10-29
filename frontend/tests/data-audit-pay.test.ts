/**
 * Public-data audit: what a reader is shown for pay. The stored compensation objects are the golden results of the
 * ingestion/backfill rules (tests/fixtures/data_audit_resolved_compensation.json, asserted by tests/test_data_audit_pay.py),
 * so Python and the front end are tested against one contract. Production records: Coinbase, Anthropic, Samsara, Robinhood,
 * Reddit, TD, NVIDIA, Braze, Mercury, Okta, DoorDash.
 */
import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { formatPay, getCompensationDetail, getJobCardCompensation, isPlausibleCompensationText, payRangeProblem, periodOf } from '../src/utils/compensation';
import { buildJobFacts } from '../src/utils/jobFacts';
import type { JobSummary } from '../src/api/client';

const fixtures = path.resolve(__dirname, '..', '..', 'tests', 'fixtures');
const golden: Record<string, Record<string, unknown>> = JSON.parse(fs.readFileSync(path.join(fixtures, 'data_audit_resolved_compensation.json'), 'utf-8'));
const rules: Array<{ min: number | null; max: number | null; currency: string; interval: string | null; problem: string | null }> =
  JSON.parse(fs.readFileSync(path.join(fixtures, 'pay_rules.json'), 'utf-8')).cases;
const payFact = (id: string) => {
  const job = { job_id: id, title: 'Engineer', company: 'Fixture', location: 'Toronto', country: 'Canada', workplace_type: 'remote', source_name: 'x', skills: [], compensation: golden[id] } as unknown as JobSummary;
  return buildJobFacts(job, { primaryLocation: 'Toronto' }).find((f) => f.key === 'compensation')?.value ?? null;
};

describe('pay rules agree with the Python and SQL definitions (shared fixture)', () => {
  it.each(rules)('$min-$max $currency $interval', (c) => {
    expect(payRangeProblem(c.min, c.max, c.currency, periodOf(c.interval))).toBe(c.problem);
  });
});

describe('what the reader sees for the audited records', () => {
  it('shows nothing for an impossible, placeholder or self-contradictory range, in the card, the pane and the summary text', () => {
    for (const id of ['greenhouse:8177946', 'greenhouse:5428950008', 'greenhouse:8226602']) {
      expect(getJobCardCompensation(golden[id]), id).toBeNull();
      expect(getCompensationDetail(golden[id]), id).toBeNull();
      expect(payFact(id), id).toBeNull();
    }
  });

  it('even before the backfill reaches a row, the same rules hide it (no ingestion flag needed)', () => {
    const coinbase = { min: 152405, max: 179300152, currency: 'USD', interval: 'year', compensationTierSummary: '$152.4K – $179300.2K', source: 'greenhouse' };
    const samsaraCoop = { min: 38, max: 58, currency: 'USD', interval: 'year', compensationTierSummary: '$38 – $58', source: 'greenhouse' };
    const placeholder = { min: 1, max: 2, currency: 'USD', interval: 'year', compensationTierSummary: '$1 – $2', source: 'greenhouse' };
    for (const raw of [coinbase, samsaraCoop, placeholder]) {
      expect(getJobCardCompensation(raw)).toBeNull();
      const job = { job_id: 'x', title: 'E', company: 'F', location: 'T', country: 'Canada', workplace_type: 'remote', source_name: 'x', skills: [], compensation: raw } as unknown as JobSummary;
      expect(buildJobFacts(job).some((f) => f.key === 'compensation')).toBe(false);
    }
    expect(isPlausibleCompensationText('$152.4K – $179300.2K')).toBe(false);
    expect(isPlausibleCompensationText('$1 – $2')).toBe(false);
  });

  it('never invents a period: it shows the one the source stated and says so when there is none', () => {
    expect(getJobCardCompensation(golden['greenhouse:8199744'])).toBe('CA$40/hr');                      // the posting says "hourly range"
    expect(payFact('greenhouse:8199744')).toBe('CA$40/hr');
    expect(getJobCardCompensation(golden['greenhouse:8250389'])).toBe('$230K – $322K');                  // Reddit: no period anywhere
    expect(payFact('greenhouse:8250389')).toBe('US$230K – US$322K');
    const td = 'workday:XMLNAME-2027-Spring-Co-op---Global-Technology---Solutions---Data-Engineer_R_1510111';
    expect(getJobCardCompensation(golden[td])).toBe('$30.74');                       // a small figure could be hourly, weekly or a typo
    expect(payFact(td)).toBe('US$30.74');
    expect(payFact('workday:Data-Scientist-II_R_1514106')).toBe('CA$81.6K – CA$115.2K');
    expect(getJobCardCompensation(golden['greenhouse:8238548'])).not.toBeNull();                       // Braze: "annually"
  });

  it('shows each range the posting states with the place and level the employer wrote, and never merges currencies or places', () => {
    // Samsara "Remote - US": the US range is this job's pay; the Canadian one is listed with its place, not shown as this job's.
    const samsara = golden['greenhouse:8223645'];
    expect(getJobCardCompensation(samsara)).toBe('$113.645K – $191K');
    expect(getCompensationDetail(samsara)).toBe('$113.645K – $191K');
    // Mercury lists US and Canada pay for a job open in both: neither covers every location, so no number on the card.
    const mercury = golden['greenhouse:6184992004'];
    expect(getJobCardCompensation(mercury)).toBeNull();
    expect(getCompensationDetail(mercury)).toBeNull();
    const nvidia = golden['workday:Senior-Compute-Platform-Engineer--LSF-_JR2023960'];     // levels, one explicit currency: a span is honest
    expect(getJobCardCompensation(nvidia)).toBe('$184K – $356.5K');
    expect(getCompensationDetail(nvidia)).toBe('$184K – $356.5K');
  });

  it('pay written for another place never becomes this job\'s pay on a card', () => {
    const base = { source: 'posting_text', ranges: [{ min: 220000, max: 359213, currency: 'CAD', interval: 'year', qualifier: 'For candidates based in the United States', scope: 'none' }] };
    expect(getJobCardCompensation(base)).toBeNull();                                // a Toronto job, pay written for US-based candidates
    expect(getCompensationDetail(base)).toBeNull();
    const dcOnly = { source: 'posting_text', ranges: [{ min: 150000, max: 206000, symbol: '$', interval: 'year', qualifier: 'For Washington D.C. based hires', scope: 'some' }] };
    expect(getJobCardCompensation(dcOnly)).toBeNull();                              // Cloudflare Austin + DC: DC pay only
    const covers = { source: 'posting_text', ranges: [{ min: 108000, max: 135000, currency: 'CAD', qualifier: 'in the Toronto area', scope: 'all', interval: 'year' }] };
    expect(getJobCardCompensation(covers)).toBe('CA$108K – CA$135K');
    // On-target earnings are labelled, never shown as plain base pay.
    const ote = { source: 'posting_text', ranges: [{ min: 154445, max: 185334, currency: 'USD', kind: 'ote', qualifier: 'In US', scope: 'all', interval: 'year' }] };
    expect(getJobCardCompensation(ote)).toBe('$154.445K – $185.334K OTE');
    expect(getCompensationDetail(ote)).toBe('$154.445K – $185.334K OTE');
    // a qualified range with no scope (older row, locations unknown) is not assumed to apply
    expect(getJobCardCompensation({ source: 'posting_text', ranges: [{ min: 1e5, max: 2e5, currency: 'USD', qualifier: 'in the Bay Area' }] })).toBeNull();
  });

  it('keeps believable source pay exactly as it was shown before', () => {
    expect(getJobCardCompensation(golden['greenhouse:8243997'])).toBe('$194K – $267K');
    expect(payFact('greenhouse:8243997')).toBe('US$194K – US$267K');
    expect(getJobCardCompensation(golden['greenhouse:8249493'])).toBeNull();            // DoorDash: the source gave no period
  });

  it('formats both ends of a range alike', () => {
    expect(formatPay(113645, 191000, 'USD', 'year')).toBe('$113.645K – $191K');
    expect(formatPay(184000, 314079, '', 'year', '$')).toBe('$184K – $314.079K');
    expect(formatPay(151200, 189000, 'CAD', 'year')).toBe('CA$151.2K – CA$189K');
  });

  it('pay lifted from the posting is not repeated as "Source pay details"', () => {
    const job = { job_id: 'x', title: 'E', company: 'F', location: 'T', country: 'Canada', workplace_type: 'remote', source_name: 'workday', skills: [], compensation: golden['workday:Data-Scientist-II_R_1514106'] } as unknown as JobSummary;
    const facts = buildJobFacts(job, { primaryLocation: 'T', compensation: '$81,600 - $115,200 CAD' });
    expect(facts.filter((f) => f.key === 'compensation' || f.key === 'sourceCompensation').map((f) => f.key)).toEqual(['compensation']);
  });
});


it('does not show other-country ranges or fall back to their source summary', () => {
  const comp = { source: 'posting_text', compensationTierSummary: '€66K – €91K', ranges: [
    { min: 66000, max: 91000, currency: 'EUR', qualifier: 'For Lisbon based hires', scope: 'unclear' },
    { min: 150000, max: 206000, currency: 'USD', qualifier: 'For Washington DC based hires', scope: 'none' },
  ] };
  expect(getJobCardCompensation(comp)).toBeNull();
  const job = { job_id: 'cloudflare', title: 'Engineer', company: 'Cloudflare', location: 'Austin, TX', country: 'United States', workplace_type: 'hybrid', source_name: 'greenhouse', skills: [], compensation: comp } as JobSummary;
  expect(buildJobFacts(job).some((fact) => fact.key === 'compensation')).toBe(false);
});


it('chooses only a structured salary range matching the job location', () => {
  const ranges = [{ min: 66000, max: 91000, currency: 'EUR', qualifier: 'Lisbon', scope: 'unclear' },
    { min: 150000, max: 200000, currency: 'USD', qualifier: 'Austin', scope: 'all' }];
  expect(getJobCardCompensation({ ranges })).toBe('$150K – $200K');
  expect(getJobCardCompensation({ ranges: ranges.map((range) => ({ ...range, scope: undefined })) })).toBeNull();
});


it('uses compact pay and makes currency unambiguous for Canadian jobs', () => {
  expect(getJobCardCompensation({ min: 107000, max: 157000, currency: 'USD', interval: 'year' })).toBe('$107K – $157K');
  expect(getJobCardCompensation({ min: 107000, max: 157000, currency: 'CAD' }, 'Canada')).toBe('CA$107K – CA$157K');
  expect(getJobCardCompensation({ min: 107000, max: 157000, currency: 'USD' }, 'Canada')).toBe('US$107K – US$157K');
  expect(getJobCardCompensation({ min: 107000, max: 157000, symbol: '$' }, 'Canada')).toBeNull();
  expect(getJobCardCompensation({ min: 66000, max: 91000, currency: 'EUR' })).toBe('€66K – €91K');
  const comp = { source: 'posting_text', ranges: [{ min: 107000, max: 157000, currency: 'CAD', qualifier: 'For Ontario, Canada', scope: 'all' }] };
  expect(getCompensationDetail(comp, 'Canada')).toBe('CA$107K – CA$157K');
});
