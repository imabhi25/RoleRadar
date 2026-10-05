import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { apiClient, ApiError, type JobDetail, type JobSummary } from '../src/api/client';
import { App } from '../src/App';
import { parseUrlSearch, MAX_PAGE } from '../src/utils/urlState';

const job = (id: string, title = `Role ${id}`): JobSummary => ({
  job_id: id, title, company: 'Fixture', location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'full_time', source_name: 'ashby', skills: ['Python'], posted_at: new Date(Date.now() - 3600_000).toISOString(),
});
const detail = (id: string): JobDetail => ({ ...job(id), company_apply_url: `https://jobs.ashbyhq.com/f/${id}`, description: '<p>Hi</p>' });

function baseMocks() {
  vi.spyOn(apiClient, 'getOverview').mockResolvedValue({ total_postings: 2, total_companies: 1, total_locations: 1, total_skills: 1 });
  vi.spyOn(apiClient, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getJobFilters').mockResolvedValue({ countries: ['Canada'], companies: ['Fixture'], skills: ['Python'], workplace_types: ['hybrid'] });
}
beforeEach(() => { vi.stubEnv('DEV', false); vi.spyOn(console, 'error').mockImplementation(() => {}); vi.spyOn(console, 'warn').mockImplementation(() => {}); });
afterEach(() => vi.restoreAllMocks());

describe('a failed query never shows the previous query as current', () => {
  it('drops the old cards and count when the new request fails, and Retry recovers the requested query', async () => {
    baseMocks();
    const getJobs = vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 2, limit: 20, offset: 0, jobs: [job('a'), job('b')] });
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    expect(await screen.findAllByRole('button', { name: /View details for/ })).toHaveLength(2);

    getJobs.mockRejectedValueOnce(new ApiError(500, '/api/jobs'));
    window.history.pushState(null, '', '/jobs?q=rust');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await screen.findByRole('heading', { name: 'Unable to load jobs' });
    expect(screen.queryAllByRole('button', { name: /View details for/ })).toHaveLength(0);
    expect(document.querySelector('.results-count-number')?.textContent).toBe('—');

    getJobs.mockResolvedValue({ total: 1, limit: 20, offset: 0, jobs: [job('r', 'Rust Engineer')] });
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('Rust Engineer')).toBeInTheDocument();
    expect(getJobs.mock.calls.at(-1)![0]).toMatchObject({ search: 'rust' });
  });
});

describe('missing job ids', () => {
  it('404 shows a final unavailable state with a way back, and no Retry', async () => {
    baseMocks();
    vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 2, limit: 20, offset: 0, jobs: [job('a'), job('b')] });
    vi.spyOn(apiClient, 'getJob').mockRejectedValue(new ApiError(404, '/api/jobs/gone'));
    window.history.replaceState(null, '', '/jobs?job=gone');
    render(<App />);
    const state = await screen.findByTestId('job-unavailable');
    expect(state).toHaveTextContent('no longer available');
    // The dialog's accessible name must not still say it is loading.
    expect(screen.getByRole('heading', { level: 2, name: 'Job unavailable' })).toBeInTheDocument();
    expect(screen.queryByText('Loading job details...')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Back to jobs' }));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get('job')).toBeNull());
  });

  it('a transient 500 offers Retry, which loads the job', async () => {
    baseMocks();
    vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 2, limit: 20, offset: 0, jobs: [job('a'), job('b')] });
    const getJob = vi.spyOn(apiClient, 'getJob').mockRejectedValueOnce(new ApiError(500, '/api/jobs/a')).mockImplementation(async (id: string) => detail(id));
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    expect(screen.queryByTestId('job-unavailable')).not.toBeInTheDocument();
    const retry = await screen.findByRole('button', { name: 'Retry' });
    expect(screen.queryByText('Loading job details...')).not.toBeInTheDocument();
    await userEvent.click(retry);
    expect(await screen.findByRole('link', { name: /Apply/ })).toBeInTheDocument();
    expect(getJob).toHaveBeenCalledTimes(2);
  });
});

describe('huge page numbers', () => {
  it('are clamped before an API offset is computed', () => {
    expect(parseUrlSearch('?page=99999999999').page).toBe(MAX_PAGE);
    expect(parseUrlSearch('?page=5000').page).toBe(5000);
    expect((MAX_PAGE - 1) * 20).toBeLessThanOrEqual(100_000);
    expect(parseUrlSearch('?page=abc').page).toBe(1);
  });
});

describe('job card semantics', () => {
  it('is an article with one native button, not an article acting as a button', async () => {
    const { JobCard } = await import('../src/components/JobCard');
    const onClick = vi.fn();
    render(<JobCard job={job('x', 'Staff Engineer')} onClick={onClick} selected />);
    const article = document.querySelector('article.job-card')!;
    expect(article).not.toHaveAttribute('role');
    expect(article).not.toHaveAttribute('tabindex');
    const buttons = article.querySelectorAll('button, a, [tabindex]');
    expect(buttons).toHaveLength(1);
    const button = screen.getByRole('button', { name: 'View details for Staff Engineer at Fixture' });
    expect(button).toHaveAttribute('aria-current', 'true');
    await userEvent.click(button);
    button.focus();
    await userEvent.keyboard('{Enter}');
    await userEvent.keyboard(' ');
    expect(onClick).toHaveBeenCalledTimes(3);
  });
});

describe('job card location and workplace', () => {
  it('leads with the location in the filtered country and does not repeat Remote', async () => {
    const { JobCard } = await import('../src/components/JobCard');
    const multi: JobSummary = {
      ...job('m', 'Platform Engineer'), location: 'San Francisco, CA', country: 'United States', workplace_type: 'hybrid',
      locations: [{ location: 'San Francisco, CA', country: 'United States' }, { location: 'Toronto, ON', country: 'Canada' }],
    };
    const { rerender } = render(<JobCard job={multi} onClick={() => {}} />);
    expect(document.querySelector('.meta-location')?.textContent).toMatch(/San Francisco/);
    rerender(<JobCard job={multi} onClick={() => {}} preferredCountries={['Canada']} />);
    expect(document.querySelector('.meta-location')?.textContent).toMatch(/Toronto/);
    expect(document.querySelector('.meta-location')?.textContent).toMatch(/\+1/);
    const remote: JobSummary = { ...job('r', 'Remote Eng'), location: 'Remote - Canada', country: 'Canada', workplace_type: 'remote' };
    rerender(<JobCard job={remote} onClick={() => {}} />);
    const chips = [...document.querySelectorAll('.meta-detail')].map((e) => e.textContent);
    expect(chips.filter((c) => /remote/i.test(c ?? ''))).toHaveLength(0);
    expect(chips).toEqual(['Canada', '1 hour ago']);
  });
});
