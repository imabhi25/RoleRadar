import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { readCss } from './cssTokens';
import { render, screen, waitFor, within, act, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import path from 'node:path';
import { apiClient, type JobDetail, type JobSummary } from '../src/api/client';
import { App } from '../src/App';
import { JobCard } from '../src/components/JobCard';
import { JobFilters, type SelectedFilters } from '../src/components/JobFilters';
import { formatPostedDate } from '../src/utils/formatters';
import { parseUrlSearch, serializeUrlSearch } from '../src/utils/urlState';
import { removeEmptySections, structureDescription } from '../src/utils/descriptionSections';

const css = readCss(path.resolve(__dirname, '..', 'src', 'index.css'));
const rule = (selector: string) =>
  css.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}'))?.[1] ?? '';

function setSplit(enabled: boolean) {
  window.matchMedia = vi.fn((query: string) => ({
    matches: enabled && query.includes('min-width: 900px') && !query.includes('pointer: fine'), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

const summary = (id: string, title: string, posted_at?: string | null): JobSummary => ({
  job_id: id, title, company: 'Fixture', location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'full_time', source_name: 'ashby', skills: ['Python'], posted_at: posted_at ?? new Date(Date.now() - 2 * 3600_000).toISOString(),
});
const detail = (id: string, title: string): JobDetail => ({
  ...summary(id, title), skills: ['Python'], company_apply_url: `https://jobs.ashbyhq.com/fixture/${id}/application`,
  description: '<h2>Requirements</h2><ul><li>Python</li></ul>',
});
const JOBS = [summary('a', 'Role A'), summary('b', 'Role B'), summary('c', 'Role C')];

function mockApi() {
  vi.spyOn(apiClient, 'getOverview').mockResolvedValue({
    total_postings: 3, total_companies: 1, total_locations: 1, total_skills: 2, last_refreshed_at: new Date(Date.now() - 14 * 60_000).toISOString(),
  });
  vi.spyOn(apiClient, 'getCountries').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getSkills').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getRoleStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getWorkplaceStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getCompanyStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getJobFilters').mockResolvedValue({ countries: ['Canada', 'United States'], companies: ['Fixture', 'Other Co'], skills: ['Python', 'Rust'], workplace_types: ['hybrid'] });
  vi.spyOn(apiClient, 'getJobs').mockResolvedValue({ total: 3, limit: 20, offset: 0, jobs: JOBS });
  vi.spyOn(apiClient, 'getJob').mockImplementation(async (id: string) => detail(id, `Role ${id.toUpperCase()}`));
}
const lastQuery = () => vi.mocked(apiClient.getJobs).mock.calls.at(-1)![0];
const pane = () => screen.getByRole('complementary', { name: 'Selected job details' });
const jobParam = () => new URLSearchParams(window.location.search).get('job');
const countryParam = () => new URLSearchParams(window.location.search).get('country');

beforeEach(() => vi.stubEnv('DEV', false));
afterEach(() => { setSplit(false); vi.restoreAllMocks(); });

describe('posted-time text (real posted_at only)', () => {
  const NOW = Date.parse('2026-09-29T12:00:00Z');
  const ago = (ms: number) => new Date(NOW - ms).toISOString();
  it('uses minutes, then hours, then days with correct singular/plural', () => {
    expect(formatPostedDate(ago(20_000), NOW)).toBe('just now');
    expect(formatPostedDate(ago(1 * 60_000), NOW)).toBe('1 minute ago');
    expect(formatPostedDate(ago(45 * 60_000), NOW)).toBe('45 minutes ago');
    expect(formatPostedDate(ago(1 * 3600_000), NOW)).toBe('1 hour ago');
    expect(formatPostedDate(ago(2 * 3600_000), NOW)).toBe('2 hours ago');
    expect(formatPostedDate(ago(8 * 3600_000), NOW)).toBe('8 hours ago');
  });
  it('switches from hours to days exactly at 24 hours', () => {
    expect(formatPostedDate(ago(23 * 3600_000 + 59 * 60_000), NOW)).toBe('23 hours ago');
    expect(formatPostedDate(ago(23 * 3600_000), NOW)).toBe('23 hours ago');
    expect(formatPostedDate(ago(24 * 3600_000), NOW)).toBe('1 day ago');
    expect(formatPostedDate(ago(25 * 3600_000), NOW)).toBe('1 day ago');
    expect(formatPostedDate(ago(47 * 3600_000), NOW)).toBe('1 day ago');
    expect(formatPostedDate(ago(48 * 3600_000), NOW)).toBe('2 days ago');
    expect(formatPostedDate(ago(7 * 86_400_000), NOW)).toBe('7 days ago');
    expect(formatPostedDate(ago(30 * 86_400_000), NOW)).toBe('30 days ago');
    expect(formatPostedDate(ago(44 * 86_400_000), NOW)).toBe('44 days ago');
  });
  it('date-only sources are aged by calendar day, never by a midnight placeholder hour', () => {
    const morning = Date.parse('2026-09-29T05:00:00Z');
    const day = (iso: string) => formatPostedDate(iso, morning, 'date');
    expect(day('2026-09-29T00:00:00Z')).toBe('today'); // a timestamp would say "5 hours ago"
    expect(day('2026-09-28T00:00:00Z')).toBe('yesterday');
    expect(day('2026-09-26T00:00:00Z')).toBe('3 days ago');
    expect(day('2026-08-30T00:00:00Z')).toBe('30 days ago');
    expect(day('2026-09-30T00:00:00Z')).toBeNull(); // tomorrow is not an age
    expect(formatPostedDate('2026-09-29T00:00:00Z', morning)).toBe('5 hours ago'); // timestamps unchanged
  });
  it('a timestamp well in the future yields no age instead of a fabricated date', () => {
    expect(formatPostedDate(new Date(NOW + 3 * 86_400_000).toISOString(), NOW)).toBeNull();
  });
  it('handles missing, invalid and slightly-future timestamps without inventing an age', () => {
    expect(formatPostedDate(null, NOW)).toBeNull();
    expect(formatPostedDate('not a date', NOW)).toBeNull();
    expect(formatPostedDate(new Date(NOW + 5 * 60_000).toISOString(), NOW)).toBe('just now');
  });
  it('shows the bare relative age on the card (no "Posted" prefix), never "Posted today", and omits it without posted_at', () => {
    const { rerender } = render(<JobCard job={summary('x', 'Engineer', new Date(Date.now() - 2 * 3600_000).toISOString())} onClick={() => {}} />);
    expect(screen.getByText('2 hours ago')).toBeInTheDocument();
    expect(screen.queryByText(/posted today/i)).not.toBeInTheDocument();
    expect(document.querySelector('.job-card')?.textContent).not.toMatch(/Posted/);
    rerender(<JobCard job={{ ...summary('x', 'Engineer'), posted_at: null }} onClick={() => {}} />);
    expect(screen.queryByText(/ago$|just now$/)).not.toBeInTheDocument();
  });
  it('never uses created_at or last_seen for the age', () => {
    const job = { ...summary('x', 'Engineer', new Date(Date.now() - 3 * 86_400_000).toISOString()), created_at: new Date().toISOString() };
    render(<JobCard job={job} onClick={() => {}} />);
    expect(screen.getByText('3 days ago')).toBeInTheDocument();
  });
});

describe('no NEW badge and no refresh/sync age', () => {
  it('renders no NEW badge on cards, even for a job posted minutes ago', () => {
    render(<JobCard job={summary('x', 'Engineer', new Date(Date.now() - 5 * 60_000).toISOString())} onClick={() => {}} />);
    expect(screen.queryByText('NEW')).not.toBeInTheDocument();
    expect(document.querySelector('.job-new-badge')).toBeNull();
    expect(css).not.toMatch(/job-new-badge/);
  });

  it('has no header job-count badge and no Refreshed/Synced text anywhere on Jobs or Stats', async () => {
    mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    expect(document.querySelector('.navbar-live-status, .status-dot-green, .live-status-text')).toBeNull();
    expect(document.querySelector('.roleradar-navbar')?.textContent).not.toMatch(/open jobs|Loading/i);
    await waitFor(() => expect(screen.getAllByRole('button', { name: /View details for/ })).toHaveLength(3));
    expect(document.body.textContent).not.toMatch(/refreshed|synced|ingestion completed/i);
    expect(document.querySelector('[title*="ingestion" i]')).toBeNull();
    // the stats tab too
    await userEvent.click(screen.getByRole('link', { name: 'Stats' }));
    expect(document.body.textContent).not.toMatch(/refreshed|synced/i);
  });
});

describe('every visible job count follows the selected country', () => {
  const TOTALS: Record<string, number> = { Canada: 202, 'United States': 49, all: 251 };
  function mockCountryApi() {
    mockApi();
    vi.spyOn(apiClient, 'getOverview').mockImplementation(async (country?: string[]) => ({
      total_postings: TOTALS[country?.[0] ?? 'all'], total_companies: 7, total_locations: 31, total_skills: 22,
    }));
    vi.spyOn(apiClient, 'getJobs').mockImplementation(async (params) => ({
      total: TOTALS[(params?.country as string[] | undefined)?.[0] ?? 'all'], limit: 20, offset: 0, jobs: JOBS,
    }));
  }
  const results = () => document.querySelector('.results-count-number')?.textContent;

  it('fresh /jobs shows the global feed everywhere; Canada and United States counts appear only once selected', async () => {
    mockCountryApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await waitFor(() => expect(results()).toBe('251'));
    const overviewCard = () => screen.getByText('Market overview').closest('.sidebar-card') as HTMLElement;
    expect(within(overviewCard()).getByText('All countries')).toBeInTheDocument();
    expect(within(overviewCard()).queryByText('Country: Canada')).not.toBeInTheDocument();
    expect(within(overviewCard()).getByText('251')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Remove .* filter/ })).not.toBeInTheDocument(); // no stale Canada chip

    const user = userEvent.setup();
    for (const [option, key, label] of [['Canada', 'Canada', 'Country: Canada'], ['United States', 'United States', 'Country: United States'], ['All countries', 'all', 'All countries']] as const) {
      await user.selectOptions(screen.getByRole('combobox', { name: 'Location' }), key === 'all' ? '' : `country:${option}`);
      const expected = TOTALS[key].toLocaleString();
      expect(document.querySelector('.roleradar-navbar')?.textContent).not.toMatch(/open jobs/i);
      await waitFor(() => expect(results()).toBe(expected));
      await waitFor(() => expect(within(overviewCard()).getByText(expected)).toBeInTheDocument());
      expect(within(overviewCard()).getByText(label)).toBeInTheDocument();
    }
  });

  it('a US URL loads with US totals everywhere and the Stats tab is labelled as all countries', async () => {
    mockCountryApi();
    window.history.replaceState(null, '', '/jobs?country=United+States');
    render(<App />);
    await waitFor(() => expect(results()).toBe('49'));
    await userEvent.click(screen.getByRole('link', { name: 'Stats' }));
    expect(await screen.findByText(/across all countries/i)).toBeInTheDocument();
  });
});

describe('Combined location and country control, all countries by default', () => {
  it('a fresh /jobs visit means all countries, keeps the URL clean and selects no country', async () => {
    expect(parseUrlSearch('').filters.country).toEqual([]);
    expect(serializeUrlSearch(parseUrlSearch('').filters, 1)).toBe('');
    mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await waitFor(() => expect(apiClient.getJobs).toHaveBeenCalled());
    expect(lastQuery().country).toBeUndefined();
    expect(screen.getByRole('combobox', { name: 'Location' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Location' })).toHaveValue('');
    expect(screen.queryByRole('button', { name: /Remove Canada/ })).not.toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe('/jobs');
  });

  it('round-trips Canada, United States and all countries through the URL; invalid values fall back to all', () => {
    const cases: Array<[string, string[], string]> = [
      ['', [], ''], ['?country=canada', ['Canada'], '?country=Canada'], ['?country=United%20States', ['United States'], '?country=United+States'],
      ['?country=all', [], ''], ['?country=canada,us', [], ''], ['?country=narnia', [], ''],
    ];
    for (const [input, country, canonical] of cases) {
      const parsed = parseUrlSearch(input);
      expect(parsed.filters.country, input).toEqual(country);
      expect(serializeUrlSearch(parsed.filters, 1), input).toBe(canonical);
      expect(parseUrlSearch(canonical)).toEqual(parsed);
    }
  });

  it('an invalid country URL is canonicalized to /jobs with no country filter', async () => {
    mockApi();
    window.history.replaceState(null, '', '/jobs?country=narnia');
    render(<App />);
    await waitFor(() => expect(apiClient.getJobs).toHaveBeenCalled());
    expect(lastQuery().country).toBeUndefined();
    expect(window.location.search).toBe('');
  });

  it('Location includes countries and updates the API query and URL', async () => {
    mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findByRole('combobox', { name: 'Location' });
    const user = userEvent.setup();

    const list = screen.getByRole('combobox', { name: 'Location' });
    expect(within(list).getByRole('option', { name: 'Canada' })).toHaveValue('country:Canada');
    await user.selectOptions(list, 'country:Canada');
    await waitFor(() => expect(lastQuery()).toEqual(expect.objectContaining({ country: ['Canada'] })));
    expect(countryParam()).toBe('Canada');
    expect(screen.getByRole('combobox', { name: 'Location' })).toBeInTheDocument();

    await user.selectOptions(screen.getByRole('combobox', { name: 'Location' }), 'country:United States');
    await waitFor(() => expect(lastQuery()).toEqual(expect.objectContaining({ country: ['United States'] })));
    expect(countryParam()).toBe('United States');

    await user.selectOptions(screen.getByRole('combobox', { name: 'Location' }), '');
    await waitFor(() => expect(lastQuery().country).toBeUndefined());
    expect(countryParam()).toBeNull(); // the parameter disappears entirely, never country=all
    expect(screen.getByRole('combobox', { name: 'Location' })).toBeInTheDocument();
  });

  it('Reset filters returns to all countries, not Canada', async () => {
    mockApi();
    window.history.replaceState(null, '', '/jobs?country=Canada&role=internship');
    render(<App />);
    await screen.findByRole('combobox', { name: 'Location' });
    await userEvent.click(screen.getAllByRole('button', { name: /reset/i })[0]);
    await screen.findByRole('combobox', { name: 'Location' });
    expect(window.location.search).toBe('');
    expect(lastQuery().country).toBeUndefined();
  });

  it('a direct job link without a country keeps the global list; with a country it keeps that scope', async () => {
    mockApi();
    window.history.replaceState(null, '', '/jobs?job=fixture%3A1');
    const first = render(<App />);
    await waitFor(() => expect(apiClient.getJobs).toHaveBeenCalled());
    expect(lastQuery().country).toBeUndefined();
    expect(screen.getByRole('combobox', { name: 'Location' })).toBeInTheDocument();
    first.unmount();

    mockApi();
    window.history.replaceState(null, '', '/jobs?country=Canada&job=fixture%3A1');
    render(<App />);
    await waitFor(() => expect(lastQuery()).toEqual(expect.objectContaining({ country: ['Canada'] })));
  });

  it('Back/Forward and a refresh on a country URL restore the same country', async () => {
    mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findByRole('combobox', { name: 'Location' });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Location' }), 'country:United States');
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Location' })).toHaveValue('country:United States'));
    await act(async () => { window.history.back(); await new Promise((r) => setTimeout(r, 20)); });
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Location' })).toHaveValue(''));
    await act(async () => { window.history.forward(); await new Promise((r) => setTimeout(r, 20)); });
    await screen.findByRole('combobox', { name: 'Location' });
  });
});

const baseFilters: SelectedFilters = {
  sort: 'recommended', search: '', country: [], company: '', skill: '', workplace_type: [], role_type: [], term: [], freshness: 'recent',
};
function renderFilters(over: Partial<SelectedFilters> = {}) {
  const onFilterChange = vi.fn();
  const selected = { ...baseFilters, ...over };
  render(
    <JobFilters
      filterOptions={{ countries: ['Canada'], companies: ['Fixture', 'Other Co'], skills: ['Python', 'Rust'], workplace_types: ['remote'] }}
      selectedFilters={selected}
      onFilterChange={onFilterChange}
      onReset={() => {}}
    />
  );
  return { onFilterChange, selected };
}

describe('essential native dropdowns', () => {
  it('keeps only five essential filters and delegates menus to the browser', () => {
    renderFilters();
    expect(screen.getAllByRole('combobox').map((select) => select.getAttribute('aria-label'))).toEqual(['Location', 'Job type', 'Experience', 'Workplace', 'Date posted']);
    expect(document.querySelector('.filter-popover')).toBeNull();
    expect(screen.queryByRole('combobox', { name: 'Company' })).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Skill' })).not.toBeInTheDocument();
  });
  it('replaces workplace choices and lets the default clear them', async () => {
    const { onFilterChange } = renderFilters({ workplace_type: ['remote'] });
    const select = screen.getByRole('combobox', { name: 'Workplace' });
    expect(select).toHaveValue('remote');
    await userEvent.selectOptions(select, 'on_site');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...baseFilters, workplace_type: ['on_site'] }, true);
    await userEvent.selectOptions(select, '');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...baseFilters, workplace_type: [] }, true);
  });
  it('separates job type from experience and resets a legacy term when job type changes', async () => {
    const { onFilterChange } = renderFilters({ term: ['summer'] });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Job type' }), 'co_op');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...baseFilters, role_type: ['co_op'], term: [] }, true);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Experience' }), 'entry');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...baseFilters, term: ['summer'], experience_level: ['entry'] }, true);
  });
  it('keeps native selected state and keyboard focus', async () => {
    renderFilters({ freshness: '14d' });
    expect(screen.getByRole('combobox', { name: 'Date posted' })).toHaveValue('14d');
    const select = screen.getByRole('combobox', { name: 'Location' });
    select.focus();
    await userEvent.keyboard('{Tab}');
    expect(screen.getByRole('combobox', { name: 'Job type' })).toHaveFocus();
  });
  it('native sort updates the API query and URL', async () => {
    mockApi(); window.history.replaceState(null, '', '/jobs'); render(<App />);
    const select = await screen.findByRole('combobox', { name: 'Sort jobs' });
    expect(select).toHaveValue('recommended');
    await userEvent.selectOptions(select, 'newest');
    await waitFor(() => expect(lastQuery()).toEqual(expect.objectContaining({ sort: 'newest' })));
    expect(new URLSearchParams(window.location.search).get('sort')).toBe('newest');
    expect(select).toHaveValue('newest');
  });
  it('keeps removed filters from existing URLs visible and removable', async () => {
    const { onFilterChange } = renderFilters({ company: 'Fixture', skill: 'Rust', sponsorship: 'available' });
    expect(screen.getByRole('region', { name: 'Active filters' })).toHaveTextContent('Company: Fixture');
    await userEvent.click(screen.getByRole('button', { name: 'Remove company Fixture filter' }));
    expect(onFilterChange).toHaveBeenLastCalledWith(expect.objectContaining({ company: '' }), true);
    expect(screen.getByRole('button', { name: 'Remove sponsorship filter' })).toBeInTheDocument();
  });
});

describe('split view interaction', () => {
  it('a fresh desktop visit selects the first result without adding a history entry', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    expect(screen.queryByRole('complementary', { name: 'Market overview and sources' })).not.toBeInTheDocument();
    expect(jobParam()).toBe('a');
    expect(apiClient.getJob).toHaveBeenCalledWith('a', expect.any(AbortSignal));

  });

  it('click switches jobs, the selected card does nothing, and desktop details stay open', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /View details for Role A/ }));
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    expect(jobParam()).toBe('a');
    const historyLength = window.history.length;

    await user.click(screen.getByRole('button', { name: /View details for Role B/ }));
    await within(pane()).findByRole('heading', { name: 'Role B' });
    expect(jobParam()).toBe('b');

    // the already selected card: no close, no toggle, no extra history entry, no refetch
    const fetches = vi.mocked(apiClient.getJob).mock.calls.length;
    const before = window.history.length;
    await user.click(screen.getByRole('button', { name: /View details for Role B/ }));
    await user.keyboard('{Enter}');
    expect(jobParam()).toBe('b');
    expect(screen.getByRole('complementary', { name: 'Selected job details' })).toBeInTheDocument();
    expect(window.history.length).toBe(before);
    expect(vi.mocked(apiClient.getJob).mock.calls.length).toBe(fetches);
    expect(before).toBeGreaterThan(historyLength - 1);

    expect(within(pane()).queryByRole('button', { name: 'Close job details' })).not.toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(jobParam()).toBe('b');
    expect(pane()).toBeInTheDocument();
  });

  it('Esc does not close the job while a menu is open or while typing in search', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=a');
    render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role A' });
    screen.getByRole('combobox', { name: 'Workplace' }).focus();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('listbox', { name: 'Workplace' })).not.toBeInTheDocument();
    expect(jobParam()).toBe('a');
    await userEvent.click(screen.getByRole('searchbox'));
    await userEvent.keyboard('{Escape}');
    expect(jobParam()).toBe('a');
  });

  it('a direct selected-job URL restores the detail pane on desktop, and the overlay on mobile', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=b');
    const view = render(<App />);
    await within(await screen.findByRole('complementary', { name: 'Selected job details' })).findByRole('heading', { name: 'Role B' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    view.unmount();
    setSplit(false);
    window.history.replaceState(null, '', '/jobs?job=b');
    render(<App />);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByRole('complementary', { name: 'Selected job details' })).not.toBeInTheDocument();
  });

  it('uses a narrower desktop container with full-size controls', () => {
    expect(css).toMatch(/\.split-capable\.is-split \.job-explorer-right \{ flex-basis: calc\(66% - 6px\); \}/);
    expect(rule('.roleradar-main')).toMatch(/max-width:\s*1440px/);
  });
});

describe('title layout', () => {
  it('the detail title uses the full width, balances at most two lines and never truncates with an ellipsis', () => {
    const title = rule('.job-detail-title');
    expect(title).toMatch(/text-wrap:\s*balance/);
    expect(title).toMatch(/-webkit-line-clamp:\s*2/);
    expect(title).not.toMatch(/text-overflow:\s*ellipsis/);
    expect(title).not.toMatch(/white-space:\s*nowrap/);
    // sizing steps down with the pane width before wrapping; Apply is on its own row so it never competes
    expect(css).toMatch(/@container \(max-width: 620px\) \{ \.job-detail-title \{ font-size: 18px; \} \}/);
    expect(css).toMatch(/@container \(max-width: 520px\) \{ \.job-detail-title \{ font-size: 17px; \} \}/);
    expect(css).toMatch(/@container \(max-width: 480px\) \{ \.job-detail-title \{ font-size: 16px; -webkit-line-clamp: 4; line-clamp: 4; \} \}/);
    expect(css).toMatch(/\.jd-grid \{[^}]*grid-template-areas:[^}]*"company apply close"[^}]*"title title title"/);
  });

  it('a medium title and a long title both render in full in the header', async () => {
    const long = 'Staff Software Engineer, Distributed Systems Infrastructure and Developer Productivity Platform';
    for (const t of ['Senior Software Developer, Build Platform', long]) {
      vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...detail('t', t), title: t });
      const { JobDetailContent } = await import('../src/components/JobDetailContent');
      const view = render(<JobDetailContent jobId="t" variant="pane" onClose={() => {}} />);
      expect((await screen.findByRole('heading', { level: 2 })).textContent).toBe(t.replace(/\s*,\s*/g, ' – '));
      view.unmount();
      vi.restoreAllMocks();
    }
  });

  it('card titles balance their lines and carry no badge beside them', () => {
    expect(rule('.job-card-title')).toMatch(/text-wrap:\s*balance/);
    render(<JobCard job={summary('x', 'Senior Software Developer, Build Platform')} onClick={() => {}} />);
    expect(document.querySelector('.job-card-title')?.children).toHaveLength(1);
  });
});

describe('one divider between adjacent sections', () => {
  it('only the header owns the line under itself; the skills block draws no border of its own', () => {
    expect(rule('.job-detail-skills')).toMatch(/border:\s*0/);
    expect(rule('.job-detail-skills')).toMatch(/padding:\s*0/);
    expect(rule('.job-detail-header')).toMatch(/border-bottom/);
  });

  it('major parts share one hairline; sub-sections are separated by whitespace only', () => {
    expect(css).toMatch(/\.job-part \+ \.job-part,\s*\.job-detail-skills \+ \.job-part \{[^}]*border-top/);
    expect(css).not.toMatch(/\.job-detail \.job-section \+ \.job-section/);
    const heading = css.match(/\.job-detail \.job-description-prose \.job-section-heading \{([^}]*)\}/)?.[1] ?? '';
    expect(heading).toMatch(/border-bottom:\s*0/);
  });

  it('dangling and doubled hr dividers are dropped and never produce a line next to a section border', () => {
    expect(css).toMatch(/hr:has\(\+ \.job-section\)/);
    expect(css).toMatch(/hr:has\(\+ hr\)/);
    const html = structureDescription(removeEmptySections('<h2>Requirements</h2><ul><li>A</li></ul><hr><hr><h2>Benefits</h2><p>Health</p><hr>'), 'Fixture');
    const doc = new DOMParser().parseFromString(html, 'text/html');
    expect(doc.querySelectorAll('hr')).toHaveLength(0);
    expect([...doc.querySelectorAll('section')].map((s) => s.getAttribute('data-section'))).toEqual(['requirements', 'benefits']);
  });

  it('renders the pane with no two consecutive divider elements', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...detail('d', 'Role'), description: '<hr><h2>Requirements</h2><ul><li>A</li></ul><hr><hr><h2>Compensation</h2><p>CA$100k</p><hr>' });
    const { JobDetailContent } = await import('../src/components/JobDetailContent');
    render(<JobDetailContent jobId="d" variant="pane" onClose={() => {}} />);
    await screen.findByText('CA$100k');
    const prose = document.querySelector('.job-description-prose')!;
    expect(prose.querySelectorAll('hr')).toHaveLength(0);
    expect(screen.getByLabelText('Job facts')).toHaveTextContent('CA$100k');
    expect(document.querySelectorAll('.job-part')).toHaveLength(2);
  });
});

describe('focus returns to the originating card', () => {
  const card = (id: string) => document.getElementById(`job-title-btn-${id}`)!;
  it.each([['overlay', false]])('X button (%s) returns focus to the card that opened it', async (_name, split) => {
    setSplit(split as boolean); mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /View details for Role B/ }));
    const close = await screen.findByRole('button', { name: /^Close job details/ });
    await user.click(close);
    await waitFor(() => expect(jobParam()).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(card('b')));
  });
  it.each([['overlay', false]])('Escape (%s) returns focus to the card that opened it', async (_name, split) => {
    setSplit(split as boolean); mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /View details for Role C/ }));
    await screen.findByRole('button', { name: /^Close job details/ });
    await user.keyboard('{Escape}');
    await waitFor(() => expect(jobParam()).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(card('c')));
  });
  it('a desktop deep link stays selected even if its card is not in the current list', async () => {
    setSplit(true); mockApi();
    window.history.replaceState(null, '', '/jobs?job=zzz-not-in-list');
    render(<App />);
    await screen.findByRole('complementary', { name: 'Selected job details' });
    expect(jobParam()).toBe('zzz-not-in-list');
    expect(screen.queryByRole('button', { name: /^Close job details/ })).not.toBeInTheDocument();
  });
});
