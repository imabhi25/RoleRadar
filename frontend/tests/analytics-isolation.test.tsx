import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { apiClient, ApiError, type JobDetail, type JobSummary } from '../src/api/client';
import { App } from '../src/App';

const job = (id: string): JobSummary => ({
  job_id: id, title: `Role ${id}`, company: 'Fixture', location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'full_time', source_name: 'ashby', skills: ['Python'], posted_at: new Date(Date.now() - 3600_000).toISOString(),
});
const detail = (id: string): JobDetail => ({
  ...job(id), company_apply_url: `https://jobs.ashbyhq.com/fixture/${id}/application`, description: '<p>Build things</p>',
});

function mockJobsOk() {
  vi.spyOn(apiClient, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getJobFilters').mockResolvedValue({ countries: ['Canada'], companies: ['Fixture'], skills: ['Python'], workplace_types: ['hybrid'] });
  vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 2, limit: 20, offset: 0, jobs: [job('a'), job('b')] });
  vi.spyOn(apiClient, 'getJob').mockImplementation(async (id: string) => detail(id));
}
function breakStats() {
  const fail = () => Promise.reject(new ApiError(500, '/api/stats'));
  vi.spyOn(apiClient, 'getOverview').mockImplementation(fail);
  vi.spyOn(apiClient, 'getCountries').mockImplementation(fail);
  vi.spyOn(apiClient, 'getSkills').mockImplementation(fail);
  vi.spyOn(apiClient, 'getRoleStats').mockImplementation(fail);
  vi.spyOn(apiClient, 'getWorkplaceStats').mockImplementation(fail);
  vi.spyOn(apiClient, 'getCompanyStats').mockImplementation(fail);
}

beforeEach(() => { vi.stubEnv('DEV', false); vi.spyOn(console, 'warn').mockImplementation(() => {}); });
afterEach(() => vi.restoreAllMocks());

describe('analytics failures never block job browsing', () => {
  it('every stats endpoint returns 500 while jobs return 200: list, details and Apply still work', async () => {
    mockJobsOk();
    breakStats();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    const cards = await screen.findAllByRole('button', { name: /View details for/ });
    expect(cards).toHaveLength(2);
    expect(screen.queryByText(/Connection Error/)).not.toBeInTheDocument();
    await userEvent.click(cards[0]);
    const apply = await screen.findByRole('link', { name: /Apply/ });
    expect(apply).toHaveAttribute('href', 'https://jobs.ashbyhq.com/fixture/a/application');
  });

  it('the Stats page shows per-widget errors with Retry, and recovers when the endpoint heals', async () => {
    mockJobsOk();
    breakStats();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    await userEvent.click(screen.getByRole('link', { name: 'Stats' }));
    // The Stats page is a lazy chunk and its six widgets fail independently. Wait for the condition that matters (no widget
    // is still loading) instead of reading whichever alerts happen to exist when the first one appears.
    const stats = await screen.findByRole('region', { name: /Market Insights/ });
    await waitFor(() => expect(stats.querySelectorAll('[aria-busy="true"]')).toHaveLength(0));
    const alerts = within(stats).getAllByRole('alert');
    expect(alerts.length).toBeGreaterThan(1);
    const labelled = (label: RegExp) => alerts.find((a) => label.test(a.textContent ?? ''));
    expect(labelled(/country chart/i)).toBeDefined();
    for (const alert of alerts) expect(within(alert).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    vi.mocked(apiClient.getCountries).mockResolvedValue([{ country: 'Canada', postings: 3, share_pct: 100 }]);
    const countryAlert = labelled(/country chart/i)!;
    await userEvent.click(within(countryAlert).getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(apiClient.getCountries).toHaveBeenCalledTimes(2));
    // The healed widget replaces its alert; the others stay failed and retryable.
    await waitFor(() => expect(within(stats).queryAllByRole('alert').length).toBe(alerts.length - 1));
    // Jobs are still reachable from the Stats page
    await userEvent.click(screen.getByRole('link', { name: 'Jobs' }));
    expect(screen.getAllByRole('button', { name: /View details for/ })).toHaveLength(2);
  });

  it('main navigation is real links with aria-current, not an invalid tablist', async () => {
    mockJobsOk();
    breakStats();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Jobs' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Stats' })).not.toHaveAttribute('aria-current');
    expect(screen.getByRole('link', { name: 'Stats' })).toHaveAttribute('href', '/stats');
  });
});
