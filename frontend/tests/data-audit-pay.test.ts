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
    expect(payFact('greenhouse:8250389')).toBe('$230K – $322K · period not stated');
    const td = 'workday:XMLNAME-2027-Spring-Co-op---Global-Technology---Solutions---Data-Engineer_R_1510111';
    expect(getJobCardCompensation(golden[td])).toBe('$30.74 (period not stated)');                       // a small figure could be hourly, weekly or a typo
    expect(payFact(td)).toBe('$30.74 · period not stated');
    expect(payFact('workday:Data-Scientist-II_R_1514106')).toBe('CA$81.6K – CA$115.2K · period not stated');
    expect(getJobCardCompensation(golden['greenhouse:8238548'])).toMatch(/\/yr$/);                       // Braze: "annually"
  });

  it('shows each range the posting states with the place and level the employer wrote, and never merges currencies or places', () => {
    // Samsara "Remote - US": the US range is this job's pay; the Canadian one is listed with its place, not shown as this job's.
    const samsara = golden['greenhouse:8223645'];
    expect(getJobCardCompensation(samsara)).toBe('$113,645 – $191,000/yr');
    expect(getCompensationDetail(samsara)).toBe('$113,645 – $191,000/yr for the US · $106,675 – $138,050/yr for Canada');
    // Mercury lists US and Canada pay for a job open in both: neither covers every location, so no number on the card.
    const mercury = golden['greenhouse:6184992004'];
    expect(getJobCardCompensation(mercury)).toBe('Pay varies by location');
    expect(getCompensationDetail(mercury)).toBe('$200.7K – $250.9K US employees (any location) · CA$189.7K – CA$237.1K Canadian employees (any location) · period not stated');
    const nvidia = golden['workday:Senior-Compute-Platform-Engineer--LSF-_JR2023960'];     // levels, one explicit currency: a span is honest
    expect(getJobCardCompensation(nvidia)).toBe('$184K – $356.5K');
    expect(getCompensationDetail(nvidia)).toBe('$184K – $287.5K for Level 4 · $224K – $356.5K for Level 5 · period not stated');
  });

  it('pay written for another place never becomes this job\'s pay on a card', () => {
    const base = { source: 'posting_text', ranges: [{ min: 220000, max: 359213, currency: 'CAD', interval: 'year', qualifier: 'For candidates based in the United States', scope: 'none' }] };
    expect(getJobCardCompensation(base)).toBe('Pay varies by location');                                // a Toronto job, pay written for US-based candidates
    expect(getCompensationDetail(base)).toBe('CA$220,000 – CA$359,213/yr For candidates based in the United States');
    const dcOnly = { source: 'posting_text', ranges: [{ min: 150000, max: 206000, symbol: '$', interval: 'year', qualifier: 'For Washington D.C. based hires', scope: 'some' }] };
    expect(getJobCardCompensation(dcOnly)).toBe('Pay varies by location');                              // Cloudflare Austin + DC: DC pay only
    const covers = { source: 'posting_text', ranges: [{ min: 108000, max: 135000, currency: 'CAD', qualifier: 'in the Toronto area', scope: 'all', interval: 'year' }] };
    expect(getJobCardCompensation(covers)).toBe('CA$108K – CA$135K/yr');
    // On-target earnings are labelled, never shown as plain base pay.
    const ote = { source: 'posting_text', ranges: [{ min: 154445, max: 185334, currency: 'USD', kind: 'ote', qualifier: 'In US', scope: 'all', interval: 'year' }] };
    expect(getJobCardCompensation(ote)).toBe('$154,445 – $185,334/yr OTE');
    expect(getCompensationDetail(ote)).toBe('$154,445 – $185,334/yr In US (on-target earnings)');
    // a qualified range with no scope (older row, locations unknown) is not assumed to apply
    expect(getJobCardCompensation({ source: 'posting_text', ranges: [{ min: 1e5, max: 2e5, currency: 'USD', qualifier: 'in the Bay Area' }] })).toBe('Pay varies by location');
  });

  it('keeps believable source pay exactly as it was shown before', () => {
    expect(getJobCardCompensation(golden['greenhouse:8243997'])).toBe('$174K – $267K/yr');
    expect(payFact('greenhouse:8243997')).toBe('$174K – $267K/yr · Multiple ranges');
    expect(getJobCardCompensation(golden['greenhouse:8249493'])).toBe('$137.1K – $299.3K');            // DoorDash: the source gave no period
  });

  it('formats both ends of a range alike', () => {
    expect(formatPay(113645, 191000, 'USD', 'year')).toBe('$113,645 – $191,000/yr');
    expect(formatPay(184000, 314079, '', 'year', '$')).toBe('$184,000 – $314,079/yr');
    expect(formatPay(151200, 189000, 'CAD', 'year')).toBe('CA$151.2K – CA$189K/yr');
  });

  it('pay lifted from the posting is not repeated as "Source pay details"', () => {
    const job = { job_id: 'x', title: 'E', company: 'F', location: 'T', country: 'Canada', workplace_type: 'remote', source_name: 'workday', skills: [], compensation: golden['workday:Data-Scientist-II_R_1514106'] } as unknown as JobSummary;
    const facts = buildJobFacts(job, { primaryLocation: 'T', compensation: '$81,600 - $115,200 CAD' });
    expect(facts.filter((f) => f.key === 'compensation' || f.key === 'sourceCompensation').map((f) => f.key)).toEqual(['compensation']);
  });
});
