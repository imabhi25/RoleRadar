import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fs from 'node:fs';
import path from 'node:path';
import { apiClient, ApiError, type CompanyInfo, type JobSummary } from '../src/api/client';
import { App } from '../src/App';
import { CompanyPageView } from '../src/components/CompanyPageView';

const job = (id: string): JobSummary => ({
  job_id: id, title: `Role ${id}`, company: 'Fixture', location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'full_time', source_name: 'ashby', skills: ['Python'], posted_at: new Date(Date.now() - 3600_000).toISOString(),
});

function baseMocks() {
  vi.spyOn(apiClient, 'getOverview').mockResolvedValue({ total_postings: 2, total_companies: 1, total_locations: 1, total_skills: 1 });
  vi.spyOn(apiClient, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getJobFilters').mockResolvedValue({ countries: ['Canada'], companies: ['Fixture'], skills: ['Python'], workplace_types: ['hybrid'] });
}

beforeEach(() => {
  vi.stubEnv('DEV', false);
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

describe('a search rejected by the edge firewall', () => {
  it('shows the rejected-search message only for a readable 403', async () => {
    baseMocks();
    const getJobs = vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 1, limit: 20, offset: 0, jobs: [job('a')] });
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });

    getJobs.mockRejectedValueOnce(new ApiError(403, '/api/jobs'));
    window.history.pushState(null, '', '/jobs?q=1%3BDROP%20TABLE%20jobs');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(await screen.findByTestId('search-blocked')).toHaveTextContent('could not be processed');
  });

  it('shows a recoverable connection error for a network failure, never a guess that the search was blocked', async () => {
    baseMocks();
    const getJobs = vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 1, limit: 20, offset: 0, jobs: [job('a')] });
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });

    // The API is perfectly reachable for other requests; that proves nothing about why this one failed.
    getJobs.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    window.history.pushState(null, '', '/jobs?q=rust');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(await screen.findByRole('heading', { name: 'Unable to load jobs' })).toBeInTheDocument();
    expect(screen.queryByTestId('search-blocked')).not.toBeInTheDocument();
    getJobs.mockResolvedValue({ total: 1, limit: 20, offset: 0, jobs: [job('r')] });
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findAllByRole('button', { name: /View details for/ })).toHaveLength(1);
  });

  it('does not infer a blocked search for a 403 on a request with no search text', async () => {
    baseMocks();
    vi.spyOn(apiClient, 'getJobs').mockRejectedValue(new ApiError(403, '/api/jobs'));
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Unable to load jobs' })).toBeInTheDocument();
    expect(screen.queryByTestId('search-blocked')).not.toBeInTheDocument();
  });
});

describe('same-origin proxy fallback (client transport)', () => {
  const html403 = () => new Response('<html>blocked</html>', { status: 403, headers: { 'content-type': 'text/html' } });
  const json200 = () => new Response(JSON.stringify({ total: 0, limit: 20, offset: 0, jobs: [] }), { status: 200, headers: { 'content-type': 'application/json' } });

  it('retries a cross-origin network failure through /api and surfaces the readable status', async () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(String(url));
      if (/^https?:\/\//.test(String(url))) throw new TypeError('Failed to fetch'); // firewall page without CORS headers
      return html403();
    }));
    await expect(apiClient.getJobs({ search: '1;DROP TABLE jobs' })).rejects.toMatchObject({ name: 'ApiError', status: 403 });
    expect(calls).toHaveLength(2);
    expect(calls[0]).toMatch(/^http/);
    expect(calls[1]).toMatch(/^\/api\/jobs\?/);
    vi.unstubAllGlobals();
  });

  it('heals a transient cross-origin failure when the proxy answers', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (/^https?:\/\//.test(String(url))) throw new TypeError('Failed to fetch');
      return json200();
    }));
    await expect(apiClient.getJobs({ search: 'react' })).resolves.toMatchObject({ total: 0 });
    vi.unstubAllGlobals();
  });

  it('reports a network failure when the proxy fails too, and never retries aborted requests', async () => {
    const f = vi.fn(async () => { throw new TypeError('Failed to fetch'); });
    vi.stubGlobal('fetch', f);
    await expect(apiClient.getJobs({ search: 'react' })).rejects.toBeInstanceOf(TypeError);
    expect(f).toHaveBeenCalledTimes(2);
    f.mockClear();
    const controller = new AbortController();
    controller.abort();
    await expect(apiClient.getJobs({ search: 'react' }, controller.signal)).rejects.toBeTruthy();
    expect(f.mock.calls.length).toBeLessThanOrEqual(1);
    vi.unstubAllGlobals();
  });
});

describe('company page', () => {
  const companies: CompanyInfo[] = [
    { name: 'GitLab', logo_url: null, logo_source_url: null, logo_status: 'unresolved', website_url: 'https://gitlab.com', active_jobs_count: 1 },
  ];

  it('shows a not-found state, not an empty profile, for a company that is not listed', async () => {
    vi.spyOn(apiClient, 'getCompanies').mockResolvedValue(companies);
    const getJobs = vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 0, limit: 50, offset: 0, jobs: [] });
    const onCompanyChange = vi.fn();
    render(<CompanyPageView initialCompany="Nope Inc" onBackToJobs={() => {}} onSelectJob={() => {}} onCompanyChange={onCompanyChange} />);
    const panel = await screen.findByTestId('company-not-found');
    expect(panel).toHaveAttribute('role', 'alert');
    expect(screen.queryByText(/Active Roles at Nope Inc/)).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Nope Inc' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Browse all companies' }));
    expect(onCompanyChange).toHaveBeenCalledWith(null);
    expect(getJobs).toHaveBeenCalled();
  });

  it('does not claim "not found" when the directory itself failed to load', async () => {
    vi.spyOn(apiClient, 'getCompanies').mockRejectedValue(new Error('boom'));
    vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 0, limit: 50, offset: 0, jobs: [] });
    render(<CompanyPageView initialCompany="GitLab" onBackToJobs={() => {}} onSelectJob={() => {}} />);
    await screen.findByText(/Active Roles at GitLab/);
    expect(screen.queryByTestId('company-not-found')).not.toBeInTheDocument();
  });

  it('shows the directory spelling for a company opened with different casing', async () => {
    vi.spyOn(apiClient, 'getCompanies').mockResolvedValue(companies);
    vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 0, limit: 50, offset: 0, jobs: [] });
    render(<CompanyPageView initialCompany="gitlab" onBackToJobs={() => {}} onSelectJob={() => {}} />);
    expect(await screen.findByRole('heading', { name: 'GitLab' })).toBeInTheDocument();
  });
});

describe('skip links', () => {
  it('skip-to-content moves focus to <main> without changing the URL', async () => {
    baseMocks();
    vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 1, limit: 20, offset: 0, jobs: [job('a')] });
    window.history.replaceState(null, '', '/jobs?q=x');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    const link = screen.getByRole('link', { name: 'Skip to content' });
    expect(link).toHaveAttribute('href', '#content');
    fireEvent.click(link);
    expect(document.activeElement).toBe(document.getElementById('content'));
    expect(document.getElementById('content')?.tagName).toBe('MAIN');
    expect(window.location.hash).toBe('');
    expect(window.location.search).toBe('?q=x');
  });
});

describe('deployment config', () => {
  const vercel = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'vercel.json'), 'utf-8'));
  const shell = vercel.rewrites.find((r: { destination: string }) => r.destination === '/index.html');
  const matches = (p: string) => new RegExp(`^${shell.source}$`).test(p);

  it('does not answer a missing asset with the HTML app shell', () => {
    expect(matches('/assets/index-missing.js')).toBe(false);
    expect(matches('/logos/nope.svg')).toBe(false);
    expect(matches('/robots.txt')).toBe(false);
  });

  it('still serves the app for real routes and deep links', () => {
    for (const route of ['/jobs', '/stats', '/company', '/company/NVIDIA', '/']) expect(matches(route)).toBe(true);
  });
});
