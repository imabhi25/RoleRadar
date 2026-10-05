import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { readCss } from './cssTokens';
import { render, screen, waitFor, within, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { apiClient, type JobDetail, type JobSummary } from '../src/api/client';
import { App } from '../src/App';
import { buildJobFacts, hasFactValue } from '../src/utils/jobFacts';
import { splitPolicySections } from '../src/utils/descriptionSections';

function setSplit(enabled: boolean, reducedMotion = false) {
  window.matchMedia = vi.fn((query: string) => ({
    matches: (enabled && query.includes('min-width: 900px')) || (reducedMotion && query.includes('prefers-reduced-motion')),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

const summary = (id: string, title: string, company = 'Fixture'): JobSummary => ({
  job_id: id, title, company, location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'co_op', source_name: 'ashby', skills: ['Python'],
});

const detail = (id: string, title: string, over: Partial<JobDetail> = {}): JobDetail => ({
  job_id: id, title, company: 'Fixture', location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'co_op', source_name: 'ashby', skills: ['Python', 'SQL'], posted_at: '2026-09-28T12:00:00Z',
  academic_term: 'Winter 2027', company_apply_url: `https://jobs.ashbyhq.com/fixture/${id}/application`,
  locations: [{ location: 'Toronto, ON', country: 'Canada' }],
  compensation: { compensationTierSummary: '$166k–$195k CAD' },
  description: 'About the role\nBuild reliable software\n\nEqual Opportunity\nWe are an equal opportunity employer.',
  ...over,
});

const JOBS = [summary('a', 'Role A'), summary('b', 'Role B'), summary('c', 'Role C')];

function mockApi(details: Record<string, JobDetail> = {}) {
  vi.spyOn(apiClient, 'getOverview').mockResolvedValue({ total_postings: 3, total_companies: 1, total_locations: 1, total_skills: 2 });
  vi.spyOn(apiClient, 'getCountries').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getSkills').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getRoleStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getWorkplaceStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getCompanyStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getJobFilters').mockResolvedValue({ countries: ['Canada'], companies: ['Fixture'], skills: [], workplace_types: ['hybrid'] });
  vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 3, limit: 20, offset: 0, jobs: JOBS });
  vi.spyOn(apiClient, 'getJob').mockImplementation(async (id: string) => details[id] ?? detail(id, `Role ${id.toUpperCase()}`));
}

const pane = () => screen.getByRole('complementary', { name: 'Selected job details' });
const jobParam = () => new URLSearchParams(window.location.search).get('job');

beforeEach(() => vi.stubEnv('DEV', false));
afterEach(() => setSplit(false));

describe('desktop split view', () => {
  it('auto-selects the first result by replacing history, without moving focus or refetching the list', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs');
    const initialHistory = window.history.length;
    render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    expect(jobParam()).toBe('a');
    expect(window.history.length).toBe(initialHistory);
    expect(apiClient.getJobs).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(document.body);
  });

  it('waits for the new filtered results before selecting their first job, then leaves empty results unselected', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    let resolveFiltered!: (value: Awaited<ReturnType<typeof apiClient.getJobs>>) => void;
    vi.mocked(apiClient.getJobs).mockImplementationOnce(() => new Promise((resolve) => { resolveFiltered = resolve; }));
    const detailCalls = vi.mocked(apiClient.getJob).mock.calls.length;
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Workplace' }), 'remote');
    expect(jobParam()).toBeNull();
    expect(apiClient.getJob).toHaveBeenCalledTimes(detailCalls);
    await act(async () => resolveFiltered({ total: 1, offset: 0, limit: 20, jobs: [JOBS[2]] }));
    await within(pane()).findByRole('heading', { name: 'Role C' });
    expect(jobParam()).toBe('c');
    expect(new URLSearchParams(window.location.search).get('workplace')).toBe('remote');
    vi.mocked(apiClient.getJobs).mockResolvedValueOnce({ total: 0, offset: 0, limit: 20, jobs: [] });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Workplace' }), 'on_site');
    await screen.findByRole('heading', { name: 'No jobs match your current filters' });
    expect(jobParam()).toBeNull();
    await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Selected job details' })).not.toBeInTheDocument());
  });

  it('does not replace a company-page URL when the hidden Jobs tab finishes loading', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/company');
    render(<App />);
    await screen.findByRole('heading', { name: 'Companies Hiring on RoleRadar', exact: false });
    await waitFor(() => expect(apiClient.getJobs).toHaveBeenCalled());
    expect(window.location.pathname).toBe('/company');
    expect(jobParam()).toBeNull();
    expect(apiClient.getJob).not.toHaveBeenCalled();
  });

  it('renders the selected job in a pane (no modal) and highlights its card', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    expect(await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(document.getElementById('job-title-btn-a')).toHaveAttribute('aria-current', 'true'));
    expect(document.getElementById('job-title-btn-b')).not.toHaveAttribute('aria-current');
  });

  it('changing the selection updates the pane and URL, and Back restores the previous job', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    await userEvent.click(await screen.findByRole('button', { name: /View details for Role B/ }));
    await within(pane()).findByRole('heading', { name: 'Role B' });
    expect(jobParam()).toBe('b');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await act(async () => { window.history.back(); await new Promise((r) => setTimeout(r, 20)); });
    await within(pane()).findByRole('heading', { name: 'Role A' });
    expect(jobParam()).toBe('a');
  });

  it('selecting jobs does not refetch or reload the job list', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    const calls = vi.mocked(apiClient.getJobs).mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: /View details for Role B/ }));
    await within(pane()).findByRole('heading', { name: 'Role B' });
    await userEvent.keyboard('j');
    await within(pane()).findByRole('heading', { name: 'Role C' });
    expect(vi.mocked(apiClient.getJobs).mock.calls.length).toBe(calls);
  });

  it('keeps Apply as an official text link and offers no Copy link action', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    const apply = await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('link', { name: /Apply for Role A at Fixture/ });
    expect(apply).toHaveAttribute('href', 'https://jobs.ashbyhq.com/fixture/a/application');
    expect(apply).toHaveAttribute('target', '_blank');
    expect(apply).toHaveAttribute('rel', 'noopener noreferrer');
    expect(apply).toHaveTextContent('Apply');
    expect(screen.queryByText(/copy link/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /copy/i })).not.toBeInTheDocument();
  });

  it('J/K and arrow keys move through jobs; Esc leaves desktop selection open', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    await screen.findByRole('button', { name: /View details for Role C/ });
    await userEvent.keyboard('j');
    await within(pane()).findByRole('heading', { name: 'Role B' });
    expect(jobParam()).toBe('b');
    await userEvent.keyboard('{ArrowDown}');
    await within(pane()).findByRole('heading', { name: 'Role C' });
    await userEvent.keyboard('j'); // already last: stays put
    expect(jobParam()).toBe('c');
    await userEvent.keyboard('k');
    await within(pane()).findByRole('heading', { name: 'Role B' });
    await userEvent.keyboard('{ArrowUp}');
    await within(pane()).findByRole('heading', { name: 'Role A' });
    await userEvent.keyboard('{Escape}');
    expect(pane()).toBeInTheDocument();
    expect(jobParam()).toBe('a');
  });

  it('does not hijack keys while typing or on other controls', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    const search = screen.getByRole('searchbox');
    await userEvent.click(search);
    await userEvent.keyboard('jkj{ArrowDown}');
    expect(search).toHaveValue('jkj');
    expect(jobParam()).toBe('a');
    await userEvent.keyboard('{Escape}');
    expect(jobParam()).toBe('a');
    const sort = screen.getByRole('combobox', { name: 'Sort jobs' });
    sort.focus();
    fireEvent.keyDown(sort, { key: 'j' });
    fireEvent.keyDown(sort, { key: 'Escape' });
    expect(jobParam()).toBe('a');
    const apply = within(pane()).getByRole('link', { name: /^Apply for/ });
    apply.focus();
    fireEvent.keyDown(apply, { key: 'j' });
    expect(jobParam()).toBe('a');
  });

  it('does not render Unknown/N/A and does not repeat metadata; facts omit missing values', async () => {
    setSplit(true);
    mockApi({ a: detail('a', 'Role A'), b: detail('b', 'Role B', {
      posted_at: null, role_type: 'unknown', workplace_type: 'unspecified', academic_term: null, compensation: null, skills: [],
    }) });
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    const full = await screen.findByRole('complementary', { name: 'Selected job details' });
    await within(full).findByRole('heading', { name: 'Role A' });
    // the header renders from the list summary first; wait for the loaded detail (it adds the posted date)
    await within(full).findByText('Sep 28, 2026');
    const facts = within(full).getByLabelText('Job facts');
    expect(within(facts).getByText('Sep 28, 2026')).toBeInTheDocument();
    expect(within(facts).getByText('Co-op')).toBeInTheDocument();
    expect(within(facts).getByText('Hybrid')).toBeInTheDocument();
    expect(within(facts).getByText('Winter 2027')).toBeInTheDocument();
    expect(within(facts).getByText('$166k–$195k CAD')).toBeInTheDocument();
    // each fact appears once in the whole pane, and the location only in the header
    for (const text of ['Co-op', 'Hybrid', 'Winter 2027']) expect(within(full).getAllByText(text)).toHaveLength(1);
    expect(within(full).getAllByText(/Toronto/)).toHaveLength(1);
    // the role description comes before skills, with facts at the top
    const skills = within(full).getByLabelText('Skills and technologies');
    expect(facts.compareDocumentPosition(skills) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(full.querySelector('.job-description-prose')!.compareDocumentPosition(skills) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: /View details for Role B/ }));
    await within(pane()).findByRole('heading', { name: 'Role B' });
    expect(within(pane()).queryByLabelText('Job facts')).not.toBeInTheDocument();
    expect(pane().textContent).not.toMatch(/unknown|n\/a|not available|unspecified/i);
    expect(within(pane()).queryByLabelText('Skills and technologies')).not.toBeInTheDocument();
  });

  it('collapses only clearly boilerplate policy sections', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    const p = await screen.findByRole('complementary', { name: 'Selected job details' });
    const details = await within(p).findByText('Company policies & disclosures');
    const box = details.closest('details')!;
    expect(box).not.toHaveAttribute('open');
    expect(box.textContent).toMatch(/equal opportunity employer/i);
    expect(p.querySelector('.modal-description')!.textContent).toMatch(/Build reliable software/);
  });
});

describe('split-view transition behaviour', () => {
  it('keeps one pane element while switching jobs and shows the list summary immediately', async () => {
    setSplit(true);
    mockApi();
    let resolveB!: (value: JobDetail) => void;
    vi.mocked(apiClient.getJob).mockImplementation((id: string) =>
      id === 'b' ? new Promise<JobDetail>((resolve) => { resolveB = resolve; }) : Promise.resolve(detail(id, `Role ${id.toUpperCase()}`))
    );
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    const first = await screen.findByRole('complementary', { name: 'Selected job details' });
    await within(first).findByRole('heading', { name: 'Role A' });
    await userEvent.click(screen.getByRole('button', { name: /View details for Role B/ }));
    // header shows the list summary while the detail request is still pending; same pane element
    expect(await within(pane()).findByRole('heading', { name: 'Role B' })).toBeInTheDocument();
    expect(pane()).toBe(first);
    // facts come from the list summary too, so the header does not jump when the detail arrives
    expect(within(pane()).getByLabelText('Job facts')).toBeInTheDocument();
    expect(within(pane()).queryByLabelText('Skills and technologies')).not.toBeInTheDocument();
    await act(async () => resolveB(detail('b', 'Role B')));
    await within(pane()).findByLabelText('Skills and technologies');
    expect(pane()).toBe(first);
    expect(screen.queryByText('Loading job details...')).not.toBeInTheDocument();
  });

  it('retains the selected pane under Escape even with reduced motion', async () => {
    setSplit(true, true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    const original = pane();
    await userEvent.keyboard('{Escape}');
    expect(pane()).toBe(original);
    expect(jobParam()).toBe('a');
  });

  it('defines the split transition in CSS, with reduced-motion overrides and no layout snap', async () => {
    const path = await import('node:path');
    const css = readCss(path.resolve(__dirname, '..', 'src', 'index.css'));
    expect(css).toMatch(/\.split-capable \.job-explorer-right \{[^}]*transition: flex-basis 260ms cubic-bezier/);
    expect(css).toMatch(/\.job-detail-pane\.pane-enter \{ animation: paneEnter 260ms/);
    expect(css).toMatch(/\.job-detail-pane\.pane-exit \{ animation: paneExit 220ms/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{[^@]*\.split-capable \.job-explorer-right[^@]*transition: none !important[^@]*animation: none !important/);
    expect(css).toMatch(/\.job-card\.is-selected|\.company-logo-container\.logo-card \{[^}]*width: 60px[^}]*height: 42px/s);
  });
});

describe('mobile keeps the single-column overlay', () => {
  it('opens the detail as a dialog, without a split pane, and Esc closes it', async () => {
    setSplit(false); mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findByRole('button', { name: /View details for Role A/ });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(jobParam()).toBeNull();
    await userEvent.click(await screen.findByRole('button', { name: /View details for Role A/ }));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('heading', { name: 'Role A' })).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Selected job details' })).not.toBeInTheDocument();
    expect(jobParam()).toBe('a');
    const apply = within(dialog).getByRole('link', { name: /Apply for Role A at Fixture/ });
    expect(apply).toHaveAttribute('href', 'https://jobs.ashbyhq.com/fixture/a/application');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('does not use J/K browsing on mobile', async () => {
    setSplit(false); mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findByRole('button', { name: /View details for Role A/ });
    await userEvent.keyboard('j');
    expect(jobParam()).toBeNull();
  });
});

describe('job facts and description helpers', () => {
  it('never treats placeholder text as a fact', () => {
    for (const v of ['Unknown', 'N/A', 'Not available', 'unspecified', '', '  ', null, undefined]) expect(hasFactValue(v as string)).toBe(false);
    expect(hasFactValue('Hybrid')).toBe(true);
    expect(buildJobFacts(detail('x', 'X', { posted_at: null, role_type: 'unknown', workplace_type: 'unspecified', academic_term: null, compensation: null }))).toEqual([]);
    const relative = buildJobFacts(detail('x', 'X'))[0];
    expect(relative).toMatchObject({ key: 'posted', value: 'Sep 28, 2026' });
  });

  it('collapses boilerplate sections but never role content', () => {
    const html = '<h2>About the role</h2><p>Build things</p><h2>Responsibilities</h2><ul><li>Ship</li></ul>' +
      '<h2>Compensation</h2><p>$100k</p><h2>Benefits</h2><p>Dental</p>' +
      '<h2>Equal Opportunity Employer</h2><p>EEO text</p><h2>AI Usage Disclosure</h2><p>We use AI</p><h2>Privacy Notice</h2><p>Privacy</p>';
    const { mainHtml, policiesHtml } = splitPolicySections(html);
    for (const kept of ['About the role', 'Responsibilities', 'Compensation', 'Benefits']) expect(mainHtml).toContain(kept);
    for (const moved of ['Equal Opportunity Employer', 'AI Usage Disclosure', 'Privacy Notice']) {
      expect(policiesHtml).toContain(moved);
      expect(mainHtml).not.toContain(moved);
    }
  });

  it('does not collapse content without a boilerplate heading, or a description that is all boilerplate', () => {
    expect(splitPolicySections('<p>We are an equal opportunity employer.</p>').policiesHtml).toBe('');
    const only = '<h2>Equal Opportunity</h2><p>x</p>';
    expect(splitPolicySections(only)).toEqual({ mainHtml: only, policiesHtml: '' });
    expect(splitPolicySections('<h2>Qualifications and accommodations</h2><p>y</p>').policiesHtml).toBe('');
  });
});
