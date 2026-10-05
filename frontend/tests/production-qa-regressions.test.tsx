import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { apiClient, type JobSummary } from '../src/api/client';
import { JobExplorer } from '../src/components/JobExplorer';
import type { SelectedFilters } from '../src/components/JobFilters';
import { getJobCardCompensation } from '../src/utils/compensation';
import { buildJobFacts } from '../src/utils/jobFacts';
import { formatPostedDate, formatPostingDate } from '../src/utils/formatters';
import { summarizeLocations } from '../src/utils/locations';

const base: JobSummary = { job_id: 'fixture', company: 'Fixture', title: 'Software Engineer', location: 'Toronto', country: 'Canada', source_name: 'ashby', skills: [] };
const filters: SelectedFilters = { search: '', country: [], company: '', skill: '', workplace_type: [], role_type: [], term: [], freshness: 'recent' };
const response = (id: string) => ({ total: 1, limit: 20, offset: 0, jobs: [{ ...base, job_id: id, title: `Result ${id}` }] });
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('salary placeholder guard in every display', () => {
  it.each(['USD', 'CAD', 'EUR', 'GBP', 'AUD'])('hides 1–2 equivalent in %s cards and facts', (currencyCode) => {
    const compensation = { summaryComponents: [{ compensationType: 'Salary', currencyCode, minValue: 1, maxValue: 2, interval: 'YEAR' }], compensationTierSummary: `${currencyCode} 1 – ${currencyCode} 2 /yr` };
    expect(getJobCardCompensation(compensation)).toBeNull();
    expect(buildJobFacts({ ...base, compensation }, { compensation: '$1 – $2 /yr' }).some((f) => f.key === 'compensation')).toBe(false);
  });
  it.each(['$1 – $2', '$0 – $0 /yr', 'CA$1 – CA$2', '$1 - 2 per year', '1 – 2 CAD', '$500 – $900/yr'])('hides malformed summaries: %s', (compensationTierSummary) => {
    expect(getJobCardCompensation({ compensationTierSummary })).toBeNull();
    expect(buildJobFacts({ ...base, compensation: { compensationTierSummary } }).some((f) => f.key === 'compensation')).toBe(false);
  });
  it('preserves real hourly, monthly, million-dollar and other-currency amounts and skips bad components', () => {
    expect(getJobCardCompensation({ compensationTierSummary: '$1M – $2M/yr' })).toBe('$1M – $2M/yr');
    expect(getJobCardCompensation({ compensationTierSummary: 'CA$32 – CA$43/hr' })).toBe('CA$32 – CA$43/hr');
    expect(getJobCardCompensation({ summaryComponents: [{ minValue: 2000, maxValue: 3000, currencyCode: 'JPY', interval: 'HOUR' }] })).toBe('JPY 2K – JPY 3K/hr');
    expect(getJobCardCompensation({ summaryComponents: [{ minValue: 3000, maxValue: 5000, currencyCode: 'EUR', interval: 'MONTH' }] })).toBe('€3K – €5K/mo');
    const compensation = { summaryComponents: [{ compensationType: 'Salary', currencyCode: 'USD', minValue: 1, maxValue: 2, interval: 'YEAR' }, { compensationType: 'Salary', currencyCode: 'USD', minValue: 150000, maxValue: 200000, interval: 'YEAR' }] };
    expect(getJobCardCompensation(compensation)).toBe('$150K – $200K/yr');
    expect(buildJobFacts({ ...base, compensation }).find((f) => f.key === 'compensation')?.value).toBe('$150K – $200K/yr');
  });
});

describe('shared posting calendar', () => {
  it('uses the same local date for timestamps and preserves date-only posting and deadline days', () => {
    const instant = '2026-10-04T01:30:00Z';
    vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-04T02:00:00Z'));
    const expected = new Date(instant).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    expect(formatPostingDate(instant)).toBe(expected);
    expect(buildJobFacts({ ...base, posted_at: instant }).find((f) => f.key === 'posted')?.value).toBe(expected);
    expect(formatPostingDate(instant, 'date')).toBe('Oct 4, 2026');
    expect(buildJobFacts(base, { deadline: '2026-10-04' }).find((f) => f.key === 'deadline')?.value).toBe('Oct 4, 2026');
  });
  it('uses the viewer calendar for date-only age and agrees on future suppression', () => {
    const now = new Date('2026-10-04T02:00:00Z');
    const viewerDay = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
    const statedDay = new Date(viewerDay).toISOString().slice(0, 10);
    expect(formatPostedDate(statedDay, now.getTime(), 'date')).toBe('today');
    vi.useFakeTimers(); vi.setSystemTime(now);
    const future = '2026-10-05T12:00:00Z';
    expect(formatPostedDate(future, now.getTime())).toBeNull();
    expect(buildJobFacts({ ...base, posted_at: future }).some((f) => f.key === 'posted')).toBe(false);
  });
});

describe('US locations across cards and details', () => {
  it.each([
    ['US, CA, Santa Clara', 'United States', 'Santa Clara, CA, United States'],
    ['US, CA, Santa Clara', '', 'Santa Clara, CA, United States'],
    ['USA, NY, NEW YORK', 'United States', 'New York, NY, United States'],
    ['San Francisco, SF9', 'United States', 'San Francisco'],
    ['San Francisco, SF9, United States', 'United States', 'San Francisco, United States'],
    ['Toronto, ON, CA', 'Canada', 'Toronto, ON, Canada'],
    ['San Francisco, CA', 'United States', 'San Francisco, CA'],
    ['Santa Clara, CA, 95054', 'United States', 'Santa Clara, CA, 95054'],
    ['Toronto, ON, M5J 2N8', 'Canada', 'Toronto, ON, M5J 2N8, Canada'],
    ['Another City, SF9', 'United States', 'Another City, SF9'],
  ])('formats %s without dropping meaningful address parts', (location, country, expected) => {
    expect(summarizeLocations({ location, country }).primary).toBe(expected);
    expect(summarizeLocations({ location: '', country, locations: [{ location, country, source_location: location }] }).primary).toBe(expected);
  });
});

describe('rapid search with deliberately reordered responses', () => {
  it('hides old cards during typing/debounce, allows more typing, and rejects late successes and errors', async () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() });
    vi.spyOn(apiClient, 'getJobFilters').mockResolvedValue({ countries: [], companies: [], skills: [], workplace_types: [] });
    const pending = new Map<string, { resolve: (r: ReturnType<typeof response>) => void; reject: (e: Error) => void; signal?: AbortSignal }>();
    vi.spyOn(apiClient, 'getJobs').mockImplementation((params, signal) => {
      if (!params?.search) return Promise.resolve(response('initial'));
      return new Promise((resolve, reject) => pending.set(params.search!, { resolve, reject, signal }));
    });
    function Harness() {
      const [state, setState] = useState(filters);
      return <JobExplorer filters={state} page={1} selectedJobId={null} onSelectJob={() => {}} onFiltersChange={setState} />;
    }
    render(<Harness />);
    await screen.findByRole('button', { name: /View details for Result initial/ });
    const input = screen.getByRole('searchbox');
    fireEvent.change(input, { target: { value: 'old' } });
    expect(screen.queryByRole('button', { name: /Result initial/ })).not.toBeInTheDocument();
    expect(document.querySelector('.job-list-container')).toHaveAttribute('aria-busy', 'true');
    await waitFor(() => expect(pending.has('old')).toBe(true));
    expect(input).toBeEnabled();
    fireEvent.change(input, { target: { value: 'new' } });
    await waitFor(() => expect(pending.has('new')).toBe(true));
    expect(pending.get('old')!.signal?.aborted).toBe(true);
    await act(async () => pending.get('new')!.resolve(response('new')));
    await screen.findByRole('button', { name: /View details for Result new/ });
    await act(async () => pending.get('old')!.resolve(response('old')));
    expect(screen.queryByRole('button', { name: /Result old/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Result new/ })).toBeInTheDocument();
    fireEvent.change(input, { target: { value: 'failure' } });
    await waitFor(() => expect(pending.has('failure')).toBe(true));
    fireEvent.change(input, { target: { value: 'latest' } });
    await waitFor(() => expect(pending.has('latest')).toBe(true));
    await act(async () => pending.get('latest')!.resolve(response('latest')));
    await act(async () => pending.get('failure')!.reject(new Error('stale server failure')));
    expect(screen.getByRole('button', { name: /Result latest/ })).toBeInTheDocument();
    expect(screen.queryByText(/Unable to load job postings/)).not.toBeInTheDocument();
  });
});
