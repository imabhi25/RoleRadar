import { describe, it, expect, vi, afterEach } from 'vitest';
import { readCss } from './cssTokens';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import path from 'node:path';
import { apiClient, type JobDetail } from '../src/api/client';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { JobDetailModal } from '../src/components/JobDetailModal';
import { JobCard } from '../src/components/JobCard';
import { removeEmptySections } from '../src/utils/descriptionSections';
import { formatExtraLocations, formatPostalAddress, prettyLocationLabel, summarizeLocations } from '../src/utils/locations';

const css = readCss(path.resolve(__dirname, '..', 'src', 'index.css'));

const base: JobDetail = {
  job_id: 'ashby:loc', title: 'Maya Software Developer', company: 'Fixture', location: 'Toronto, ON', country: 'Canada',
  workplace_type: 'remote', role_type: 'full_time', source_name: 'ashby', skills: [],
  company_apply_url: 'https://jobs.ashbyhq.com/fixture/loc/application', description: 'About the role\nBuild things',
};
const SEVEN = [
  'California, USA - Remote', 'AMER - Canada - British Columbia - Remote', 'AMER - Canada - Quebec - Montreal - Remote',
  'AMER - Canada - Ontario - Toronto - Remote', 'New York, NY', 'Seattle, WA', 'Austin, TX',
].map((location) => ({ location, country: location.includes('Canada') ? 'Canada' : 'United States' }));

afterEach(() => vi.restoreAllMocks());

async function renderDetail(job: JobDetail) {
  vi.spyOn(apiClient, 'getJob').mockResolvedValue(job);
  const view = render(<JobDetailContent jobId={job.job_id} variant="pane" onClose={() => {}} />);
  await screen.findByRole('link', { name: /Apply for/ });
  return view;
}
const header = () => document.querySelector('.job-detail-header') as HTMLElement;

describe('location display', () => {
  it('formats labels compactly without touching the data', () => {
    expect(prettyLocationLabel('California, USA - Remote')).toBe('California, USA · Remote');
    expect(prettyLocationLabel('AMER - Canada - British Columbia - Remote')).toBe('Canada, British Columbia · Remote');
    expect(prettyLocationLabel('Remote - Canada')).toBe('Canada · Remote');
    expect(prettyLocationLabel('Remote')).toBe('Remote');
    expect(prettyLocationLabel('Toronto, ON')).toBe('Toronto, ON');
    expect(formatExtraLocations(1)).toBe('+1 location');
    expect(formatExtraLocations(6)).toBe('+6 locations');
    const summary = summarizeLocations({ location: 'x', country: 'Canada', locations: SEVEN });
    expect(summary.all).toHaveLength(7);
    expect(summary.primary).toBe('California, USA · Remote');
  });

  it('shows a single location with no counter', async () => {
    await renderDetail({ ...base, locations: [{ location: 'Toronto, ON', country: 'Canada' }] });
    expect(within(header()).getByText(/Toronto, ON/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /location/i })).not.toBeInTheDocument();
    expect(header().textContent).not.toMatch(/\+0|\+\d+ location/);
  });

  it('shows primary + "+1 location" for two locations and reveals the other on demand', async () => {
    await renderDetail({ ...base, locations: [{ location: 'Toronto, ON', country: 'Canada' }, { location: 'London, UK', country: 'United Kingdom' }] });
    expect(screen.queryByText(/London/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '+1 location' }));
    expect(screen.getByText(/London/)).toBeInTheDocument();
  });

  it('collapses seven locations to primary + count, expands to a list, and collapses again', async () => {
    await renderDetail({ ...base, locations: SEVEN });
    const toggle = screen.getByRole('button', { name: '+6 locations' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(within(header()).getByText('California, USA · Remote')).toBeInTheDocument();
    // never one giant paragraph: nothing but the primary label and the toggle is inline
    expect(header().textContent).not.toMatch(/Montreal|Quebec|Seattle|Austin/);
    expect(document.querySelector('.job-detail-location-list')).toBeNull();

    await userEvent.click(toggle);
    const list = screen.getByRole('list', { name: 'Additional locations' });
    const items = within(list).getAllByRole('listitem').map((li) => li.textContent);
    expect(items).toEqual(['Canada, British Columbia · Remote', 'Canada, Quebec, Montreal · Remote',
      'Canada, Ontario, Toronto · Remote', 'New York, NY', 'Seattle, WA', 'Austin, TX']);
    expect(within(header()).getAllByText('California, USA · Remote')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Hide locations' })).toHaveAttribute('aria-expanded', 'true');

    await userEvent.click(screen.getByRole('button', { name: 'Hide locations' }));
    expect(screen.queryByRole('list', { name: 'Additional locations' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '+6 locations' })).toBeInTheDocument();
  });

  it('never emits the old joined multi-location string', async () => {
    await renderDetail({ ...base, locations: SEVEN });
    expect(header().textContent).not.toContain(' · AMER');
    expect(header().textContent).not.toContain('AMER -');
  });
});

describe('readable employer addresses', () => {
  it('formats an ATS address without repeating the city, retaining the full map address', () => {
    expect(formatPostalAddress('180 WELLINGTON ST W:TORONTO', 'Toronto, Ontario, Canada')).toEqual({ label: '180 Wellington St W', full: '180 Wellington St W, Toronto' });
    expect(formatPostalAddress('777 BAY ST, TH 27:TORONTO', 'Toronto, ON')).toEqual({ label: '777 Bay St, TH 27', full: '777 Bay St, TH 27, Toronto' });
  });
  it('preserves mixed-case street names, postal/unit codes and a different locality', () => {
    expect(formatPostalAddress('5 rue Saint-Jacques, Montréal', 'Toronto, ON')).toEqual({ label: '5 rue Saint-Jacques, Montréal', full: '5 rue Saint-Jacques, Montréal' });
    expect(formatPostalAddress('180 WELLINGTON ST W, SUITE 2A, TORONTO, ON, M5J 2N8').full).toBe('180 Wellington St W, Suite 2A, Toronto, ON, M5J 2N8');
  });
  it('keeps an explicit address accessible when the source has no city label', async () => {
    await renderDetail({ ...base, location: '', country: '', description: '<h2>Address:</h2><p>180 WELLINGTON ST W</p><h2>Responsibilities</h2><p>Build services.</p>' });
    const address = screen.getByRole('group', { name: 'Employer address' });
    expect(within(address).getByRole('link')).toHaveTextContent('180 Wellington St W');
    expect(new URL(within(address).getByRole('link').getAttribute('href')!).searchParams.get('query')).toBe('180 Wellington St W');
  });
});

describe('Apply is a text link with an animated underline', () => {
  it('renders an official anchor without any button styling', async () => {
    await renderDetail(base);
    const apply = screen.getByRole('link', { name: /Apply for Maya Software Developer at Fixture/ });
    expect(apply.tagName).toBe('A');
    expect(apply).toHaveAttribute('href', base.company_apply_url);
    expect(apply).toHaveAttribute('target', '_blank');
    expect(apply).toHaveAttribute('rel', 'noopener noreferrer');
    expect(apply).toHaveTextContent('Apply');
    expect(apply.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    expect(apply).toHaveClass('job-detail-apply-link');
    for (const old of ['job-detail-apply-btn', 'modal-apply-btn', 'modal-header-apply-btn']) expect(apply).not.toHaveClass(old);
    expect(screen.queryByRole('button', { name: /apply/i })).not.toBeInTheDocument();
  });

  it('keeps a 44px hit area, visible keyboard focus and reduced-motion support for the text link', () => {
    const rule = (selector: string) => css.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}'))?.[1] ?? '';
    const link = rule('.job-detail-apply-link');
    expect(link).toMatch(/background:\s*transparent/);
    expect(link).toMatch(/color:\s*var\(--primary-hover\)/);
    expect(link).toMatch(/min-height:\s*44px/);
    expect(css).toMatch(/\.job-detail-apply-link:focus-visible\s*\{[^}]*outline:\s*2px/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.job-detail-apply-link, \.job-detail-apply-link::after\s*\{\s*transition:\s*none/);
    expect(css).not.toMatch(/\.job-detail-apply-btn|\.job-detail-copy-btn/);
  });
});

describe('missing application links', () => {
  it('shows an honest unavailable state and never invents LinkedIn/Simplify/Indeed routes', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...base, company_apply_url: null, source_url: null, linkedin_url: null, simplify_url: null } as JobDetail);
    render(<JobDetailContent jobId={base.job_id} variant="pane" onClose={() => {}} />);
    expect(await screen.findByText('Application link unavailable')).toHaveAttribute('aria-disabled', 'true');
    expect(screen.queryByRole('link', { name: /Apply/ })).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toMatch(/indeed\.com|linkedin\.com\/jobs|simplify\.jobs/i);
  });
});

describe('scrollable description region', () => {
  it('is keyboard reachable and named (axe scrollable-region-focusable)', async () => {
    await renderDetail(base);
    const region = screen.getByRole('region', { name: 'Job description' });
    expect(region).toHaveAttribute('tabindex', '0');
    expect(region).toHaveClass('job-detail-scroll');
  });
});

describe('Copy link is gone everywhere', () => {
  it('does not render in the pane or the mobile overlay', async () => {
    await renderDetail(base);
    expect(screen.queryByText(/copy link|link copied|copy failed/i)).not.toBeInTheDocument();
    vi.restoreAllMocks();
    vi.spyOn(apiClient, 'getJob').mockResolvedValue(base);
    render(<JobDetailModal jobId={base.job_id} onClose={() => {}} />);
    await screen.findAllByRole('link', { name: /Apply for/ });
    expect(screen.queryByText(/copy link|link copied|copy failed/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /copy/i })).not.toBeInTheDocument();
  });
});

describe('empty description fields', () => {
  const clean = (html: string) => removeEmptySections(html);

  it('removes empty Salary Range / Posting End Date / generic headings and keeps populated ones', () => {
    const html = '<h2>Salary Range:</h2><h2>Job Category:</h2><h2>Posting End Date:</h2>';
    expect(clean(html)).toBe('');
    expect(clean('<h2>Requirements</h2><ul><li>Python</li></ul><h2>Salary Range:</h2>')).toBe('<h2>Requirements</h2><ul><li>Python</li></ul>');
    expect(clean('<h2>Salary Range:</h2><p>$100k - $120k</p><h2>Job Category:</h2>')).toBe('<h2>Salary Range:</h2><p>$100k - $120k</p>');
    expect(clean('<h2>Posting End Date:</h2><p>October 15, 2026</p>')).toBe('<h2>Posting End Date:</h2><p>October 15, 2026</p>');
    for (const label of ['Application Deadline', 'Department', 'Employment Type', 'Location', 'Requisition ID', 'Anything At All']) {
      expect(clean(`<h3>${label}:</h3><p>&nbsp;</p><p><br></p><hr><h3>Next</h3><p>real text</p>`)).toBe('<h3>Next</h3><p>real text</p>');
    }
  });

  it('treats whitespace, nbsp and <br> as empty and removes the orphaned divider', () => {
    expect(clean('<h2>Department:</h2>\n<p> </p><p>&nbsp;</p><p><br></p><hr>')).toBe('');
    expect(clean('<h2>Department:</h2><hr><h2>Body</h2><p>Text</p>')).toBe('<h2>Body</h2><p>Text</p>');
    // a heading followed by a divider and then real text keeps its heading: never risk deleting real content
    expect(clean('<h2>About</h2><hr><p>Text</p>')).toBe('<h2>About</h2><hr><p>Text</p>');
    expect(clean('<p>Body</p><hr><h2>Department:</h2><p><br></p>')).toBe('<p>Body</p>');
    expect(clean('<p>One</p><p>&nbsp;</p><p>Two</p>')).toBe('<p>One</p><p>Two</p>');
  });

  it('handles bold "Label:" lines, with and without values', () => {
    expect(clean('<p><strong>Salary Range:</strong></p><p><strong>Job Category:</strong></p><p><strong>Posting End Date:</strong></p>')).toBe('');
    expect(clean('<p><strong>Salary Range:</strong></p><p><strong>Job Category:</strong> Engineering</p>'))
      .toBe('<p><strong>Job Category:</strong> Engineering</p>');
    expect(clean('<p><strong>Location:</strong></p><ul><li>Toronto</li></ul>')).toBe('<p><strong>Location:</strong></p><ul><li>Toronto</li></ul>');
    // a bold sentence without a colon is content, not a label
    expect(clean('<p>Intro</p><p><strong>Apply now!</strong></p>')).toBe('<p>Intro</p><p><strong>Apply now!</strong></p>');
  });

  it('never touches real content: requirements, responsibilities, nested headings, lists, legal text', () => {
    const real = '<h2>About the company</h2><p>We build.</p><h2>Responsibilities</h2><ul><li>Ship</li></ul>' +
      '<h2>Requirements</h2><h3>Must have</h3><ul><li>Python</li></ul><h3>Nice to have</h3><p>Go</p>' +
      '<h2>Qualifications</h2><p>BSc</p><h2>Preferred Qualifications</h2><p>MSc</p><h2>Benefits</h2><p>Dental</p>' +
      '<h2>Compensation</h2><p>$150k</p><h2>Equal Opportunity</h2><p>We are an equal opportunity employer.</p>';
    expect(clean(real)).toBe(real);
    // a parent heading whose only content lives under a sub-heading stays
    expect(clean('<h2>Requirements</h2><h3>Must have</h3><p>Python</p>')).toBe('<h2>Requirements</h2><h3>Must have</h3><p>Python</p>');
    // an empty sub-heading goes, the parent with other content stays
    expect(clean('<h2>Requirements</h2><p>Python</p><h3>Bonus</h3>')).toBe('<h2>Requirements</h2><p>Python</p>');
  });

  it('cleans headings nested inside wrapper blocks and ignores non-empty images/tables', () => {
    expect(clean('<div><h2>Salary Range:</h2><h2>Real</h2><p>Text</p></div>')).toBe('<div><h2>Real</h2><p>Text</p></div>');
    expect(clean('<h2>Diagram</h2><p><img src="x.png" alt="d"></p>')).toBe('<h2>Diagram</h2><p><img src="x.png" alt="d"></p>');
  });

  it('is applied when rendering a job: no empty headings or dividers reach the page', async () => {
    const description = '<h2>Salary Range:</h2><h2>Job Category:</h2><h2>Posting End Date:</h2>' +
      '<h2>Responsibilities</h2><ul><li>Ship code</li></ul><h2>Application Deadline:</h2><p>October 15, 2026</p><h2>Department:</h2>';
    await renderDetail({ ...base, description });
    const body = document.querySelector('.job-description-prose') as HTMLElement;
    const headings = [...body.querySelectorAll('h1,h2,h3,h4,h5,h6')].map((h) => h.textContent);
    expect(headings).toEqual(['Responsibilities']);
    // the explicit deadline moved out of the prose into the header facts
    expect(body.textContent).not.toMatch(/Application Deadline|October 15, 2026/);
    expect(document.querySelector('.job-fact-deadline')).toHaveTextContent('Apply by Oct 15, 2026');
    expect(body.textContent).not.toMatch(/Salary Range|Job Category|Posting End Date|Department/);
  });
});

describe('job card uses the same cleaned location labels', () => {
  const card = (location: string, country: string, extra: { location: string; country: string }[] = []) =>
    render(<JobCard onClick={() => {}} job={{ job_id: 'c1', title: 'Engineer', company: 'Fixture', location, country, workplace_type: 'remote',
      source_name: 'workday', skills: [], locations: [{ location, country }, ...extra] }} />);
  const locationText = () => document.querySelector('.meta-location')?.textContent ?? '';

  it.each([
    ['AMER - Canada - British Columbia - Remote', 'Canada', 'Canada, British Columbia'],
    ['AMER - Canada - Ontario - Toronto', 'Canada', 'Canada, Ontario, Toronto'],
    ['AMER - United States - Oregon - Portland', 'United States', 'Portland, Oregon, United States'],
  ])('shows %s as %s', (raw, country, expected) => {
    card(raw, country);
    expect(locationText()).toBe(expected);
    expect(document.body.textContent).not.toContain('AMER');
  });

  it('keeps the cleaned places and +N location count without workplace metadata', () => {
    const raw = 'AMER - Canada - British Columbia - Remote';
    card(raw, 'Canada', [{ location: 'New York, NY', country: 'United States' }]);
    expect(locationText()).toBe('Canada, British Columbia +1 location');
  });

  it('cleans duplicate Canadian country labels while preserving California state codes', () => {
    expect(prettyLocationLabel('Toronto, ON, CA, Canada', 'Canada')).toBe('Toronto, ON, Canada');
    expect(prettyLocationLabel('Toronto, ON, Canada, CA', 'Canada')).toBe('Toronto, ON, Canada');
    expect(prettyLocationLabel('San Francisco, CA, USA, United States', 'United States')).toBe('San Francisco, CA, United States');
    expect(prettyLocationLabel('San Francisco, CA')).toBe('San Francisco, CA');
    expect(prettyLocationLabel('London, UK, United Kingdom', 'United Kingdom')).toBe('London, United Kingdom');
    expect(prettyLocationLabel('Toronto, ON, CA')).toBe('Toronto, ON, CA'); // ambiguous without country context
  });

  it('only shows place, available salary and age on cards while retaining title/company', () => {
    const salary = { summaryComponents: [{ compensationType: 'Salary', currencyCode: 'CAD', minValue: 100000, maxValue: 150000, interval: 'YEAR' }, { compensationType: 'EquityPercentage', minValue: 0.1, maxValue: 0.2 }] };
    render(<JobCard onClick={() => {}} job={{ ...base, company: 'Scotiabank', location: 'Toronto, ON, CA', posted_at: new Date(Date.now() - 3600_000).toISOString(), skills: ['Python'], academic_term: 'Winter 2027', compensation: salary }} />);
    const items = [...document.querySelectorAll('.meta-detail')].map((item) => item.textContent);
    expect(items).toEqual(['Toronto, ON, Canada', 'CA$100K – CA$150K/yr', '1 hour ago']);
    const card = document.querySelector('.job-card')!;
    expect(card).toHaveTextContent(base.title);
    expect(card).toHaveTextContent('Scotiabank');
    expect(card).not.toHaveTextContent(/Full-time|Remote|Winter 2027|Python|Equity/);
  });

  it('uses the plural for several and shows nothing extra for one', () => {
    card('Toronto, ON', 'Canada', [{ location: 'Ottawa, ON', country: 'Canada' }, { location: 'Waterloo, ON', country: 'Canada' }]);
    expect(locationText()).toMatch(/\+2 locations$/);
    document.body.innerHTML = '';
    card('Toronto, ON', 'Canada');
    expect(locationText()).not.toMatch(/\+\d/);
  });
});
