import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { readCss } from './cssTokens';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import path from 'node:path';
import { apiClient, ApiError, type JobSummary } from '../src/api/client';
import { App } from '../src/App';
import { CompanyLogo } from '../src/components/CompanyLogo';
import { CountryChart, OVERLAP_NOTE } from '../src/components/CountryChart';
import { normalizeAllCapsHeading, presentHeadings } from '../src/utils/descriptionSections';

const JOBS: JobSummary[] = ['a', 'b'].map((id) => ({
  job_id: id, title: `Role ${id.toUpperCase()}`, company: 'Fixture', location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid',
  role_type: 'full_time', source_name: 'ashby', skills: ['Python'], posted_at: new Date(Date.now() - 3600_000).toISOString(),
}));

function mockApi(getJobs?: typeof apiClient.getJobs) {
  vi.spyOn(apiClient, 'getOverview').mockResolvedValue({ total_postings: 2, total_companies: 1, total_locations: 1, total_skills: 1 });
  vi.spyOn(apiClient, 'getCountries').mockResolvedValue([{ country: 'Canada', postings: 2, share_pct: 100 }]);
  vi.spyOn(apiClient, 'getSkills').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getRoleStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getWorkplaceStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getCompanyStats').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(apiClient, 'getJobFilters').mockResolvedValue({ countries: ['Canada'], companies: ['Fixture'], skills: ['Python'], workplace_types: ['hybrid'] });
  vi.spyOn(apiClient, 'getJobs').mockImplementation(getJobs ?? (async () => ({ total: 2, limit: 20, offset: 0, jobs: JOBS })));
}

beforeEach(() => { vi.stubEnv('DEV', false); try { localStorage.setItem('roleradar-theme', 'light'); } catch { /* ignore */ } });
afterEach(() => vi.restoreAllMocks());

describe('blocked search (HTTP 403 from the edge firewall)', () => {
  const blocking = async (params?: { search?: string; q?: string }) => {
    if ((params?.search ?? params?.q ?? '').includes('union select')) throw new ApiError(403, '/api/jobs');
    return { total: 2, limit: 20, offset: 0, jobs: JOBS };
  };

  it('shows a localized search message, keeps the search controls, and never the connection error', async () => {
    mockApi(blocking as typeof apiClient.getJobs);
    window.history.replaceState(null, '', '/jobs?q=union+select');
    render(<App />);
    const alert = await screen.findByTestId('search-blocked');
    expect(alert).toHaveAttribute('role', 'alert');
    expect(alert).toHaveTextContent('That search could not be processed. Try a different search term.');
    expect(screen.queryByText(/Unable to load job postings|check your connection/i)).not.toBeInTheDocument();
    const search = screen.getByRole('searchbox', { name: 'Search jobs, companies, or skills' });
    expect(search).toBeEnabled();
    expect(search).toHaveValue('union select');
    expect(screen.getByRole('combobox', { name: 'Sort jobs' })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/cloudflare|attention required|ray id/i);
    expect(screen.queryByText(/No jobs match/)).not.toBeInTheDocument();
  });

  it('recovers as soon as the query is cleared or edited', async () => {
    mockApi(blocking as typeof apiClient.getJobs);
    window.history.replaceState(null, '', '/jobs?q=union+select');
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Clear search' }));
    await waitFor(() => expect(screen.queryByTestId('search-blocked')).not.toBeInTheDocument());
    await screen.findAllByRole('button', { name: /View details for/ });
    expect(screen.getByRole('searchbox')).toHaveValue('');
    expect(new URLSearchParams(window.location.search).get('q')).toBeNull();
  });

  it('a 403 without a search term is not blamed on the search; network failures and 500s keep the real error state', async () => {
    for (const failure of [new ApiError(403, '/api/jobs'), new TypeError('Failed to fetch'), new ApiError(500, '/api/jobs')]) {
      mockApi((async () => { throw failure; }) as typeof apiClient.getJobs);
      window.history.replaceState(null, '', '/jobs');
      const view = render(<App />);
      expect(await screen.findByText(/Unable to load job postings\. Please check your connection/)).toBeInTheDocument();
      expect(screen.queryByTestId('search-blocked')).not.toBeInTheDocument();
      view.unmount();
      vi.restoreAllMocks();
    }
    // and a network failure WITH a search term is still a connection error
    mockApi((async () => { throw new TypeError('Failed to fetch'); }) as typeof apiClient.getJobs);
    window.history.replaceState(null, '', '/jobs?q=python');
    render(<App />);
    expect(await screen.findByText(/Unable to load job postings/)).toBeInTheDocument();
    expect(screen.queryByTestId('search-blocked')).not.toBeInTheDocument();
  });

  it('a normal empty result is the normal empty state', async () => {
    mockApi((async () => ({ total: 0, limit: 20, offset: 0, jobs: [] })) as typeof apiClient.getJobs);
    window.history.replaceState(null, '', '/jobs?q=zzzz');
    render(<App />);
    expect(await screen.findByText('No jobs match your current filters')).toBeInTheDocument();
    expect(screen.queryByTestId('search-blocked')).not.toBeInTheDocument();
  });

  it('exposes only the status code of a blocked response, never its body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>Attention Required! | Cloudflare Ray ID: 123</html>', { status: 403 }));
    const error = await apiClient.getJobs({ search: 'x' }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(403);
    expect(error.message).not.toMatch(/cloudflare|attention/i);
  });

  it.each([['C++', 'q=C%2B%2B'], ['C#', 'q=C%23'], ['"machine learning"', 'q=%22machine+learning%22'], ['node.js & react', 'q=node.js+%26+react']])(
    'legitimate search %s is sent intact', async (term, encoded) => {
      const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ total: 0, limit: 20, offset: 0, jobs: [] }), { status: 200 }));
      await apiClient.getJobs({ search: term });
      expect(String(fetchMock.mock.calls[0][0])).toContain(encoded);
    });
});

describe('accessibility cleanup', () => {
  const levels = () => screen.getAllByRole('heading').map((h) => Number(h.tagName.slice(1)));

  it('/jobs has exactly one h1 and no skipped heading levels', async () => {
    mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/software engineering jobs/i);
    const seq = levels();
    expect(seq[0]).toBe(1);
    seq.forEach((level, i) => { if (i) expect(level - seq[i - 1], `${seq.join(',')} at ${i}`).toBeLessThanOrEqual(1); });
    expect(screen.getByRole('heading', { level: 2, name: 'Job listings' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Market overview' })).toBeInTheDocument();
  });

  it('the stats view also has exactly one h1 and no skipped levels', async () => {
    mockApi();
    window.history.replaceState(null, '', '/stats');
    render(<App />);
    await screen.findByRole('heading', { level: 1, name: /Market Intelligence/ });
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    const seq = levels();
    seq.forEach((level, i) => { if (i) expect(level - seq[i - 1], seq.join(',')).toBeLessThanOrEqual(1); });
  });

  it('applies a saved theme and lets the navbar toggle switch and remember it', async () => {
    mockApi();
    localStorage.setItem('roleradar-theme', 'dark');
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    expect(document.documentElement.dataset.theme).toBe('dark');
    await userEvent.click(screen.getByRole('button', { name: 'Switch to light mode' }));
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(localStorage.getItem('roleradar-theme')).toBe('light');
    expect(screen.getByRole('button', { name: 'Switch to dark mode' })).toBeInTheDocument();
  });

  it('a logo has exactly one accessible name', () => {
    const { container } = render(<CompanyLogo company="Wealthsimple" logoUrl="/logos/wealthsimple.svg" />);
    expect(screen.getAllByRole('img')).toHaveLength(1);
    expect(screen.getByRole('img', { name: 'Wealthsimple logo' })).toBeInTheDocument();
    expect(container.querySelector('img')).toHaveAttribute('alt', '');
    expect(screen.queryByAltText(/brand mark/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/brand mark/i)).not.toBeInTheDocument();
  });
});

describe('/stats country presentation', () => {
  const data = [{ country: 'Canada', postings: 120, share_pct: 62.1 }, { country: 'United States', postings: 73, share_pct: 37.9 }];

  it('says the counts overlap, shows the unique headline, and shows no shares of a whole', () => {
    const { container } = render(<CountryChart data={data} totalPostings={150} />);
    expect(screen.getByRole('heading', { name: 'Jobs with locations in each country' })).toBeInTheDocument();
    expect(screen.getByText(new RegExp(OVERLAP_NOTE.replace(/[.]/g, '\\.')))).toBeInTheDocument();
    expect(OVERLAP_NOTE).toBe('Multi-country postings may be counted in more than one country.');
    expect(screen.getByText('150')).toBeInTheDocument();                 // unique postings, smaller than 120 + 73
    expect(container.textContent).toMatch(/Canada:\s*120/);
    expect(container.textContent).toMatch(/United States:\s*73/);
    expect(container.textContent).not.toMatch(/%/);
    expect(container.textContent).not.toMatch(/share/i);
    expect(120 + 73).toBeGreaterThan(150);                               // the overlap the note explains
  });

  it('still renders its empty state', () => {
    render(<CountryChart data={[]} />);
    expect(screen.getByText(OVERLAP_NOTE)).toBeInTheDocument();
    expect(screen.getByText(/No country-specific location data/)).toBeInTheDocument();
  });
});

describe('acronyms in shouted headings', () => {
  it.each([
    ['ICYMI', 'ICYMI'], ['FAQ', 'FAQ'], ['API', 'API'], ['AI', 'AI'], ['ML', 'ML'], ['SQL', 'SQL'], ['AWS', 'AWS'], ['R&D', 'R&D'],
    ['WHAT WE BUILD WITH AI', 'What We Build with AI'], ['AWS AND SQL SKILLS', 'AWS and SQL Skills'], ['R&D AT OUR COMPANY', 'R&D at Our Company'],
    ['ML ENGINEERING FAQ', 'ML Engineering FAQ'],
  ])('%s -> %s', (input, expected) => expect(normalizeAllCapsHeading(input)).toBe(expected));

  it('does not turn ordinary shouted words into acronyms', () => {
    expect(normalizeAllCapsHeading('WHO WE ARE')).toBe('Who We Are');
    expect(normalizeAllCapsHeading('WHY JOIN US')).toBe('Why Join Us');
    expect(normalizeAllCapsHeading('BENEFITS')).toBe('Benefits');
    expect(normalizeAllCapsHeading('OUR NEW TEAM')).toBe('Our New Team');
    expect(normalizeAllCapsHeading('ABOUT THE ROLE')).toBe('About the Role');
  });

  it('leaves mixed-case headings exactly as written, and works inside the description pass', () => {
    expect(normalizeAllCapsHeading('What You’ll Do with AWS')).toBe('What You’ll Do with AWS');
    const html = presentHeadings('<h2>ICYMI</h2><p>Body</p><h2>BENEFITS</h2><p>More</p>');
    expect([...new DOMParser().parseFromString(html, 'text/html').querySelectorAll('h4')].map((h) => h.textContent)).toEqual(['ICYMI', 'Benefits']);
  });
});

describe('within(document) sanity', () => {
  it('keeps the job list h3 titles under the Job listings h2', async () => {
    mockApi();
    window.history.replaceState(null, '', '/jobs');
    render(<App />);
    await screen.findAllByRole('button', { name: /View details for/ });
    const list = screen.getByRole('region', { name: 'Job listings stream' });
    expect(within(list).getAllByRole('heading', { level: 3 }).length).toBe(2);
    expect(within(list).getByRole('heading', { level: 2, name: 'Job listings' })).toBeInTheDocument();
  });
});

describe('dark-mode active/selected controls meet WCAG AA (4.5:1) for their text', () => {
  const css = readCss(path.resolve(__dirname, '..', 'src', 'index.css'));
  const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const lum = (rgb: number[]) => {
    const [r, g, b] = rgb.map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a: number[], b: number[]) => {
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const rule = (selector: string) => css.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}'))?.[1] ?? '';
  // tinted rgba(59,130,246,.15) over the surface the control sits on
  const over = (surface: string) => [59, 130, 246].map((c, i) => Math.round(c * 0.15 + hex(surface)[i] * 0.85));
  const PAGE = '#0b1120'; // --bg-app (filter triggers sit on the page)
  const CARD = '#111827'; // --bg-card (chips, drawer)

  it.each([
    ['filter/sort trigger (active)', '[data-theme="dark"] .filter-dropdown-btn.active', PAGE],
    ['skill chip', '[data-theme="dark"] .skill-chip', CARD],
  ])('%s', (_name, selector, surface) => {
    const body = rule(selector);
    const color = body.match(/(?<![-\w])color:\s*(#[0-9a-f]{6})/i)![1];   // the text colour, not border-color
    expect(ratio(hex(color), over(surface))).toBeGreaterThanOrEqual(4.5);
  });

  it('menu rows and the removable chips are far above AA', () => {
    expect(ratio(hex('#f8fafc'), hex(CARD))).toBeGreaterThan(15);             // menu rows on the popover
    expect(ratio(hex('#60a5fa'), hex(CARD))).toBeGreaterThanOrEqual(4.5);     // selected check mark colour
    expect(ratio(hex('#cbd5e1'), hex('#172033'))).toBeGreaterThanOrEqual(4.5); // active filter chips
  });
});
