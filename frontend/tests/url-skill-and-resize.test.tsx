import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { apiClient, type JobDetail, type JobSummary } from '../src/api/client';
import { App } from '../src/App';
import { resolveSkillFilter } from '../src/utils/skills';

const job = (id: string): JobSummary => ({
  job_id: id, title: `Role ${id}`, company: 'Fixture', location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'full_time', source_name: 'ashby', skills: ['Python'], posted_at: new Date(Date.now() - 3600_000).toISOString(),
});
const detail = (id: string): JobDetail => ({ ...job(id), company_apply_url: `https://jobs.ashbyhq.com/f/${id}`, description: '<p>Hi</p>' });

const originalMatchMedia = window.matchMedia;
/** A viewport the test can resize: true = desktop split view (min-width: 900px), false = phone. */
function mockViewport(initialDesktop: boolean) {
  let desktop = initialDesktop;
  const listeners = new Set<() => void>();
  window.matchMedia = vi.fn((query: string) => ({
    get matches() { return query.includes('min-width: 900px') ? desktop : false; },
    addEventListener: (_: string, cb: () => void) => listeners.add(cb),
    removeEventListener: (_: string, cb: () => void) => listeners.delete(cb),
  })) as unknown as typeof window.matchMedia;
  return { resize(next: boolean) { desktop = next; act(() => listeners.forEach((cb) => cb())); } };
}

function mocks(skills: string[] = ['Python', 'Rust']) {
  vi.spyOn(apiClient, 'getOverview').mockResolvedValue({ total_postings: 2, total_companies: 1, total_locations: 1, total_skills: 1 });
  vi.spyOn(apiClient, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getJobFilters').mockResolvedValue({ countries: ['Canada'], companies: ['Fixture'], skills, workplace_types: ['hybrid'] });
  const getJobs = vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 2, limit: 20, offset: 0, jobs: [job('a'), job('b')] });
  vi.spyOn(apiClient, 'getJob').mockImplementation(async (id: string) => detail(id));
  return getJobs;
}

beforeEach(() => {
  vi.stubEnv('DEV', false);
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.spyOn(console, 'warn').mockImplementation(() => {});
});
afterEach(() => { window.matchMedia = originalMatchMedia; vi.restoreAllMocks(); });

describe('resolveSkillFilter', () => {
  const offered = ['Python', 'Rust', 'C++', 'Go'];
  it('accepts offered skills, fixes their spelling, and maps known aliases onto offered skills', () => {
    expect(resolveSkillFilter('Python', offered)).toEqual({ status: 'supported', skill: 'Python' });
    expect(resolveSkillFilter('python', offered)).toEqual({ status: 'canonicalized', skill: 'Python' });
    expect(resolveSkillFilter('golang', offered)).toEqual({ status: 'canonicalized', skill: 'Go' });
  });
  it('treats a skill the API offers as valid even if the front end has never heard of it (future skills)', () => {
    expect(resolveSkillFilter('Zig', [...offered, 'Zig'])).toEqual({ status: 'supported', skill: 'Zig' });
    expect(resolveSkillFilter('zig', [...offered, 'Zig'])).toEqual({ status: 'canonicalized', skill: 'Zig' });
  });
  it('rejects unknown values and never lets an alias make an unoffered skill valid', () => {
    expect(resolveSkillFilter('zz', offered).status).toBe('unknown');
    expect(resolveSkillFilter('kubernetes', offered).status).toBe('unknown');   // a known alias, but not offered right now
  });
  it('does not judge when there is nothing to validate against', () => {
    expect(resolveSkillFilter('zz', []).status).toBe('unchecked');
    expect(resolveSkillFilter('zz', null).status).toBe('unchecked');
  });
});

describe('skill filter from the URL', () => {
  it('ignores an unknown skill with a notice, never requests it, and never flashes an empty result list', async () => {
    const getJobs = mocks(['Python', 'Rust']);
    window.history.replaceState(null, '', '/jobs?skill=zz&q=react');
    render(<App />);
    expect(await screen.findByTestId('ignored-skill-notice')).toHaveTextContent('“zz”');
    await screen.findAllByRole('button', { name: /View details for/ });
    expect(getJobs.mock.calls.every(([params]) => !(params as { skill?: string }).skill)).toBe(true);
    expect(getJobs.mock.calls.at(-1)![0]).toMatchObject({ search: 'react' });
    expect(window.location.search).not.toContain('skill=');
    expect(window.location.search).toContain('q=react');
    expect(screen.queryByText('No jobs match your current filters')).not.toBeInTheDocument();
  });

  it('the notice goes away when the reader changes anything', async () => {
    mocks(['Python']);
    window.history.replaceState(null, '', '/jobs?skill=zz');
    render(<App />);
    await screen.findByTestId('ignored-skill-notice');
    const search = screen.getByRole('searchbox');
    await userEvent.type(search, 'x');
    await waitFor(() => expect(screen.queryByTestId('ignored-skill-notice')).not.toBeInTheDocument());
  });

  it('normalises the spelling of an offered skill and keeps filtering by it', async () => {
    const getJobs = mocks(['Python', 'Rust']);
    window.history.replaceState(null, '', '/jobs?skill=python');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    await waitFor(() => expect(getJobs.mock.calls.at(-1)![0]).toMatchObject({ skill: 'Python' }));
    expect(window.location.search).toContain('skill=Python');
    expect(screen.queryByTestId('ignored-skill-notice')).not.toBeInTheDocument();
  });

  it('keeps a skill the API offers that the front end has no built-in knowledge of', async () => {
    const getJobs = mocks(['Python', 'Zig']);
    window.history.replaceState(null, '', '/jobs?skill=Zig');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    expect(getJobs.mock.calls.at(-1)![0]).toMatchObject({ skill: 'Zig' });
    expect(screen.queryByTestId('ignored-skill-notice')).not.toBeInTheDocument();
  });

  it('does not throw a skill away just because the options could not be loaded', async () => {
    const getJobs = mocks();
    vi.spyOn(apiClient, 'getJobFilters').mockRejectedValue(new Error('offline'));
    window.history.replaceState(null, '', '/jobs?skill=Rust');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    expect(getJobs.mock.calls.at(-1)![0]).toMatchObject({ skill: 'Rust' });
    expect(screen.queryByTestId('ignored-skill-notice')).not.toBeInTheDocument();
  });
});

describe('resizing from desktop to a phone', () => {
  it('does not open a modal for the job the app opened automatically', async () => {
    const viewport = mockViewport(true);
    mocks();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await waitFor(() => expect(window.location.search).toContain('job=a'));      // desktop opened the first result
    expect((window.history.state as { autoJob?: boolean } | null)?.autoJob).toBe(true);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    viewport.resize(false);
    await waitFor(() => expect(window.location.search).not.toContain('job='));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    viewport.resize(true);                                                     // and back: desktop opens a job again
    await waitFor(() => expect(window.location.search).toContain('job=a'));
  });

  it('keeps a job the reader chose', async () => {
    const viewport = mockViewport(true);
    mocks();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await waitFor(() => expect(window.location.search).toContain('job=a'));
    await userEvent.click((await screen.findAllByRole('button', { name: /View details for/ }))[1]);
    await waitFor(() => expect(window.location.search).toContain('job=b'));
    expect((window.history.state as { autoJob?: boolean } | null)?.autoJob).toBeFalsy();

    viewport.resize(false);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(window.location.search).toContain('job=b');
  });

  it('treats clicking the auto-opened job as the reader’s own choice', async () => {
    const viewport = mockViewport(true);
    mocks();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await waitFor(() => expect(window.location.search).toContain('job=a'));
    fireEvent.click((await screen.findAllByRole('button', { name: /View details for/ }))[0]);
    await waitFor(() => expect((window.history.state as { autoJob?: boolean } | null)?.autoJob).toBeFalsy());

    viewport.resize(false);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('opens a direct job link as a modal on a phone', async () => {
    mockViewport(false);
    mocks();
    window.history.replaceState(null, '', '/jobs?job=b');
    render(<App />);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(window.location.search).toContain('job=b');
  });

  it('keeps a direct job link when a desktop window is resized to phone width', async () => {
    const viewport = mockViewport(true);
    mocks();
    window.history.replaceState(null, '', '/jobs?job=b');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    expect(window.location.search).toContain('job=b');
    viewport.resize(false);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });
});
