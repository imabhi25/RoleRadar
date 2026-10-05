import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';
import { apiClient, type JobDetail } from '../src/api/client';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { JobDetailModal } from '../src/components/JobDetailModal';
import { CompanyDetails } from '../src/components/CompanyInfo';
import { prettyLocationLabel, summarizeLocations } from '../src/utils/locations';
import { classifySectionHeading, removeEmptySections, structureDescription } from '../src/utils/descriptionSections';
import { buildJobFacts } from '../src/utils/jobFacts';
import { COMPANY_DOMAIN_MAP, normalizeCompanyName } from '../src/utils/companyLogos';
import { COMPANY_LINKEDIN_URLS, getCompanyLinkedIn, getCompanyProfile, hasCompanyProfileContent } from '../src/utils/companyProfiles';
import { parseAndSanitizeJobDescription } from '../src/utils/sanitizeDescription';

const APPLY = 'https://jobs.ashbyhq.com/wealthsimple/abc/application';
const base: JobDetail = {
  job_id: 'ashby:1', title: 'Senior Software Developer, Build Platform', company: 'Wealthsimple', location: 'Toronto, ON', country: 'Canada',
  workplace_type: 'hybrid', role_type: 'full_time', source_name: 'ashby', skills: [], posted_at: '2026-09-28T12:00:00Z',
  company_apply_url: APPLY, description: '<p>Intro</p>',
};

afterEach(() => vi.restoreAllMocks());

async function renderDetail(job: JobDetail) {
  vi.spyOn(apiClient, 'getJob').mockResolvedValue(job);
  const view = render(<JobDetailContent jobId={job.job_id} variant="pane" onClose={() => {}} />);
  await screen.findByRole('link', { name: /Apply for/ });
  return view;
}
const header = () => document.querySelector('.job-detail-header') as HTMLElement;
const text = (html: string) => (new DOMParser().parseFromString(html, 'text/html').body.textContent || '').replace(/\s+/g, ' ').trim();

describe('header', () => {
  it('shows company identity, full title, location and Apply, with company links beside its name', async () => {
    await renderDetail(base);
    const h = within(header());
    expect(h.getByText('Wealthsimple')).toBeInTheDocument();
    expect(header().querySelector('img, .company-logo-container')).not.toBeNull();
    const website = screen.getByRole('link', { name: /Wealthsimple website/ });
    const linkedin = screen.getByRole('link', { name: /Wealthsimple on LinkedIn/ });
    expect(website).toHaveAttribute('href', expect.stringMatching(/^https:\/\/wealthsimple\.com/));
    expect(linkedin).toHaveAttribute('href', 'https://www.linkedin.com/company/wealthsimple');
    for (const a of [website, linkedin]) {
      expect(a).toHaveAttribute('target', '_blank');
      expect(a).toHaveAttribute('rel', 'noopener noreferrer');
    }
    expect(h.getByRole('heading', { level: 2, name: base.title.replace(/\s*,\s*/g, ' – ') })).toBeInTheDocument();
    const apply = h.getByRole('link', { name: /Apply for Senior Software Developer/ });
    expect(apply).toHaveAttribute('href', APPLY);
    expect(apply).toHaveTextContent('Apply');
    expect(apply.textContent).not.toMatch(/company website/i);
    // one top row: company, its links, Apply, close; then title, location, facts
    const order = ['.jd-company', '.jd-apply', '.job-detail-title', '.job-detail-location']
      .map((sel) => header().querySelector(sel)!);
    order.forEach((el, i) => { expect(el, String(i)).not.toBeNull(); if (i) expect(order[i - 1].compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); });
  });

  it('omits company links that are unavailable and never renders placeholders', async () => {
    await renderDetail({ ...base, company: 'Palantir Nonexistent Co', job_id: 'x' });
    expect(within(header()).queryByRole('link', { name: /^Palantir Nonexistent Co website/ })).not.toBeInTheDocument();
    expect(within(header()).queryByRole('link', { name: /LinkedIn/ })).not.toBeInTheDocument();
    expect(header().textContent).not.toMatch(/undefined|null|N\/A|unknown/i);
  });

  it('shows a website but no LinkedIn when only the website is verified', async () => {
    await renderDetail({ ...base, company: 'Linear', job_id: 'y' });
    expect(screen.getByRole('link', { name: /Linear website/ })).toBeInTheDocument();
    expect(within(header()).queryByRole('link', { name: /LinkedIn/ })).not.toBeInTheDocument();
  });

  it('prefers the verified website from the API and works in the mobile overlay', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...base, company_website_url: 'https://www.wealthsimple.com/en-ca' });
    render(<JobDetailModal jobId={base.job_id} onClose={() => {}} />);
    const links = await screen.findAllByRole('link', { name: /^Wealthsimple website/ });
    expect(links.length).toBeGreaterThanOrEqual(1);
    links.forEach((link) => expect(link).toHaveAttribute('href', 'https://www.wealthsimple.com/en-ca'));
    expect(screen.getByRole('link', { name: /Apply for/ })).toHaveAttribute('href', APPLY);
  });
});

describe('job facts', () => {
  it('renders only facts that exist; workplace is not repeated when the location already says it', () => {
    const facts = buildJobFacts({ ...base, compensation: { compensationTierSummary: 'CA$120k–CA$150k' }, academic_term: 'Winter 2027', role_type: 'co_op' } as JobDetail);
    expect(facts.map((f) => [f.key, f.value])).toEqual([
      ['posted', 'Sep 28, 2026'], ['role', 'Co-op'], ['term', 'Winter 2027'], ['workplace', 'Hybrid'], ['compensation', 'CA$120k–CA$150k'],
    ]);
    expect(buildJobFacts({ ...base, workplace_type: 'remote' }, { primaryLocation: 'Canada · Remote' }).map((f) => f.key)).toEqual(['posted', 'role']);
    expect(buildJobFacts({ ...base, workplace_type: 'remote' }, { primaryLocation: 'Toronto, ON' }).map((f) => f.key)).toContain('workplace');
  });

  it('drops absent, unknown and empty compensation values', () => {
    const facts = buildJobFacts({ ...base, posted_at: null, role_type: 'unknown', workplace_type: 'unspecified', compensation: { compensationTierSummary: '  ' } } as JobDetail);
    expect(facts).toEqual([]);
  });

  it('does not render an empty facts area or a Compensation label without a value', async () => {
    await renderDetail({ ...base, title: 'Software Developer', posted_at: null, role_type: 'unknown', workplace_type: 'unspecified', compensation: null });
    expect(screen.queryByLabelText('Job facts')).not.toBeInTheDocument();
    expect(header().textContent).not.toMatch(/compensation|salary|unknown|n\/a|not provided/i);
  });
});

const POSTING = `
<p>We build the future of money.</p>
<h2>About the Role</h2><p>You will own the platform.</p>
<h2>What You'll Do</h2><ul><li>Ship code</li><li>Review code</li></ul>
<h2>Requirements</h2><ul><li>5 years experience</li></ul>
<h2>Nice to Have:</h2><ul><li>Rust</li></ul>
<h2>Benefits</h2><ul><li>20 vacation days</li></ul>`;

describe('description structure', () => {
  it('classifies the common section titles and nothing that is merely prose', () => {
    const cases: Array<[string, string | null]> = [
      ['ABOUT THE ROLE', 'about-role'], ['Summary', 'about-role'], ["What You'll Do", 'responsibilities'], ['Responsibilities', 'responsibilities'],
      ['Requirements', 'requirements'], ['Minimum Qualifications', 'requirements'], ['Preferred Qualifications', 'preferred'],
      ['Desired Qualifications', 'preferred'], ['Nice to have', 'preferred'], ['Skills', 'skills'], ['Compensation', 'compensation'],
      ['Benefits & Perks', 'benefits'], ['About the Team', 'team'], ['About the Build Platform Team', 'team'], ['In this role you’ll have the opportunity to:', 'responsibilities'], ['About the Company', 'company'],
      ['What will you do:', 'responsibilities'], ['What you need to succeed', 'requirements'], ['You may be a good fit if:', 'requirements'], ['Who are we?', 'company'], ['What’s in it for you?', 'benefits'],
      ['Our engineering culture is great and we like to talk about it', null], ['Apply now', null], ['', null],
    ];
    for (const [heading, kind] of cases) expect(classifySectionHeading(heading), heading).toBe(kind);
    expect(classifySectionHeading('About Wealthsimple', 'Wealthsimple')).toBe('company');
    expect(classifySectionHeading('About Wealthsimple')).toBeNull();
  });

  it('groups recognized sections in source order without changing any text', () => {
    const structured = structureDescription(POSTING, 'Wealthsimple');
    const doc = new DOMParser().parseFromString(structured, 'text/html');
    const kinds = [...doc.querySelectorAll('section.job-section')].map((s) => s.getAttribute('data-section'));
    expect(kinds).toEqual(['about-role', 'responsibilities', 'requirements', 'preferred', 'benefits']);
    // intro before the first heading stays an ungrouped intro, no heading invented
    expect(doc.body.firstElementChild!.tagName).toBe('P');
    expect(doc.querySelectorAll('h4.job-section-heading')).toHaveLength(5);
    expect(doc.querySelectorAll('h1,h2,h3')).toHaveLength(0);
    expect(text(structured)).toBe(text(POSTING));
    expect(doc.querySelectorAll('section[data-section="requirements"] li')).toHaveLength(1);
  });

  it('falls back to the untouched description when nothing is confidently a known section', () => {
    const unknown = '<h2>Our culture is unique</h2><p>Body</p><h2>Random stuff</h2><p>More</p>';
    expect(structureDescription(unknown)).toBe(unknown);
    const noHeadings = '<p>Just a paragraph.</p><ul><li>a</li></ul>';
    expect(structureDescription(noHeadings)).toBe(noHeadings);
    expect(structureDescription('')).toBe('');
  });

  it('keeps unfamiliar headings as their own sections when others are recognized, losing no content', () => {
    const html = '<h2>Requirements</h2><ul><li>A</li></ul><h2>Interview process</h2><p>Three rounds</p>';
    const out = structureDescription(html);
    const kinds = [...new DOMParser().parseFromString(out, 'text/html').querySelectorAll('section')].map((s) => s.getAttribute('data-section'));
    expect(kinds).toEqual(['requirements', 'other']);
    expect(text(out)).toBe(text(html));
  });

  it('unwraps a single wrapper div and still preserves everything', () => {
    const html = `<div>${POSTING}</div>`;
    expect(text(structureDescription(html, 'Wealthsimple'))).toBe(text(html));
    expect(structureDescription(html)).toContain('data-section="requirements"');
  });

  it('removes empty sections and stray dividers but keeps populated fields', () => {
    const html = '<h2>Requirements</h2><ul><li>A</li></ul><hr><h2>Benefits</h2><p>Health</p><p><strong>Salary Range:</strong></p><p><strong>Posting End Date:</strong> October 15, 2026</p><h2>Empty</h2><hr>';
    const cleaned = removeEmptySections(html);
    expect(cleaned).toContain('October 15, 2026');
    expect(cleaned).not.toContain('Salary Range');
    expect(cleaned).not.toContain('Empty');
    const out = structureDescription(cleaned);
    expect(out).not.toMatch(/<hr>\s*<\/section>/);
  });

  it('renders structured sections in the pane with no decorative emoji and every original text', async () => {
    const raw = '<h2>🌴 Benefits</h2><ul><li>✈️ 90 days away</li></ul><h2>Requirements</h2><ul><li>Python</li></ul>';
    await renderDetail({ ...base, description: raw });
    await userEvent.click(screen.getByRole('button', { name: 'Full Posting' }));
    const prose = document.querySelector('.job-description-prose') as HTMLElement;
    const headings = [...prose.querySelectorAll('h4.job-section-heading')].map((h) => h.textContent);
    expect(headings).toEqual(['Benefits', 'Requirements']);
    expect(prose.textContent).toContain('90 days away');
    expect(prose.textContent).not.toMatch(/[\u{1F300}-\u{1FAFF}✈]/u);
    expect(prose.querySelector('section[data-section="benefits"]')).not.toBeNull();
    // parser output for the same input has the same words (nothing lost)
    expect(text(prose.innerHTML)).toBe(text(parseAndSanitizeJobDescription(raw).html));
  });

  it('shows a plain description safely when it has no recognizable structure', async () => {
    await renderDetail({ ...base, description: '<p>Short plain posting with no headings.</p>' });
    expect(screen.getByText('Short plain posting with no headings.')).toBeInTheDocument();
    expect(document.querySelector('section.job-section')).toBeNull();
  });
});

describe('About the Company (verified facts) and header links', () => {
  it('shows company links once beside its name without inventing company facts', async () => {
    await renderDetail(base);
    expect(screen.getByRole('heading', { name: 'About the company' })).toBeInTheDocument();
    expect(screen.getByTestId('company-details')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /^Wealthsimple website/ })).toHaveLength(1);
    expect(screen.getAllByRole('link', { name: /^Wealthsimple on LinkedIn/ })).toHaveLength(1);
  });

  it('shows an honest fallback when company background is missing', async () => {
    await renderDetail({ ...base, company: 'Palantir Nonexistent Co', job_id: 'z' });
    expect(screen.getByRole('heading', { name: 'About the company' })).toBeInTheDocument();
  });

  it('renders every available verified field and omits missing ones', () => {
    const { rerender } = render(<CompanyDetails profile={{ name: 'Acme', website: 'https://acme.com/', linkedin: null, description: 'Makes anvils.', headquarters: 'Toronto, Canada', size: '1,000–5,000', founded: '2014' }} />);
    expect(screen.getByText('Makes anvils.')).toBeInTheDocument();
    expect(screen.getByText('Headquarters').nextElementSibling).toHaveTextContent('Toronto, Canada');
    expect(screen.getByText('Company size').nextElementSibling).toHaveTextContent('1,000–5,000');
    expect(screen.getByText('Founded').nextElementSibling).toHaveTextContent('2014');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    rerender(<CompanyDetails profile={{ name: 'Acme', website: null, linkedin: null, headquarters: 'Toronto, Canada' }} />);
    expect(screen.queryByText('Company size')).not.toBeInTheDocument();
    expect(screen.queryByText('Founded')).not.toBeInTheDocument();
    rerender(<CompanyDetails profile={{ name: 'Acme', website: 'https://acme.com/', linkedin: null }} />);
    expect(screen.queryByTestId('company-details')).not.toBeInTheDocument();
  });

  it('has no invented company facts in the shipped data', () => {
    const profile = getCompanyProfile('Wealthsimple');
    expect(profile).toMatchObject({ name: 'Wealthsimple', website: 'https://wealthsimple.com/', linkedin: 'https://www.linkedin.com/company/wealthsimple' });
    expect(profile.description).toMatch(/provides digital financial services/);
    expect(profile.headquarters ?? profile.size ?? profile.founded).toBeUndefined();
    expect(hasCompanyProfileContent(profile)).toBe(true);
    expect(hasCompanyProfileContent({ name: 'X', website: 'https://x.com/', linkedin: 'https://www.linkedin.com/company/x' })).toBe(false);
    expect(hasCompanyProfileContent({ name: 'X', website: null, linkedin: null, founded: '2014' })).toBe(true);
    expect(hasCompanyProfileContent({ name: 'X', website: null, linkedin: null, description: 'Makes anvils.' })).toBe(true);
  });
});

describe('verified company LinkedIn data', () => {
  it('only holds well-formed LinkedIn company URLs for companies RoleRadar knows', () => {
    const keys = Object.keys(COMPANY_LINKEDIN_URLS);
    expect(keys.length).toBeGreaterThan(40);
    for (const [key, url] of Object.entries(COMPANY_LINKEDIN_URLS)) {
      expect(url, key).toMatch(/^https:\/\/www\.linkedin\.com\/company\/[A-Za-z0-9_.%-]+$/);
      expect(COMPANY_DOMAIN_MAP[key], `${key} must be a registry company`).toBeTruthy();
      expect(getCompanyLinkedIn(key)).toBe(url);
    }
  });

  it('returns null (never a guessed URL) for companies without a verified page', () => {
    for (const name of ['Palantir', 'Linear', 'Notion', 'Manulife', 'BMO', 'Unknown Startup', '', null, undefined]) {
      expect(getCompanyLinkedIn(name as string)).toBeNull();
    }
    expect(normalizeCompanyName('Palantir')).toBe('palantir');
  });

  it('is sourced from the file that documents its provenance', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '..', 'src', 'utils', 'companyProfiles.ts'), 'utf-8');
    expect(src).toMatch(/official website/i);
  });
});

describe('display-only location cleanup', () => {
  it('drops clear street-address noise before a recognizable city', () => {
    expect(prettyLocationLabel('745 THURLOW ST:VANCOUVER, Canada')).toBe('Vancouver, Canada');
    expect(prettyLocationLabel('200 Bay Street, Toronto, Ontario, Canada')).toBe('Toronto, Ontario, Canada');
    expect(prettyLocationLabel('1 Yonge St. - Toronto - Remote')).toBe('Toronto · Remote');
  });
  it('title-cases all-caps places but keeps codes and normal casing', () => {
    expect(prettyLocationLabel('TORONTO, Ontario, Canada')).toBe('Toronto, Ontario, Canada');
    expect(prettyLocationLabel('SAINT-JEAN-SUR-RICHELIEU, QC')).toBe('Saint-Jean-Sur-Richelieu, QC');
    expect(prettyLocationLabel('NEW YORK, NY')).toBe('New York, NY');
    expect(prettyLocationLabel('San Francisco, CA')).toBe('San Francisco, CA');
    expect(prettyLocationLabel('McLean, VA')).toBe('McLean, VA');
  });
  it('keeps the AMER prefix cleanup, work modes and already-clean labels', () => {
    expect(prettyLocationLabel('AMER - Canada - Ontario - Toronto')).toBe('Canada, Ontario, Toronto');
    expect(prettyLocationLabel('AMER - Canada - British Columbia - Remote')).toBe('Canada, British Columbia · Remote');
    expect(prettyLocationLabel('Toronto, ON')).toBe('Toronto, ON');
    expect(prettyLocationLabel('Remote')).toBe('Remote');
    expect(prettyLocationLabel('Hybrid - VANCOUVER, Canada')).toBe('Vancouver, Canada · Hybrid');
  });
  it('does not invent a city: a lone address is kept, digits-only names are untouched', () => {
    expect(prettyLocationLabel('745 THURLOW ST')).toBe('745 Thurlow St');
    expect(prettyLocationLabel('Route 66 Hub, Canada')).toBe('Route 66 Hub, Canada');
  });
  it('cleans each location of a mixed multi-location posting', () => {
    const s = summarizeLocations({ location: 'x', country: 'Canada', locations: [
      { location: '745 THURLOW ST:VANCOUVER', country: 'Canada' }, { location: 'TORONTO, Ontario', country: 'Canada' }, { location: 'Remote - Canada', country: 'Canada' },
    ] });
    expect(s.all).toEqual(['Vancouver, Canada', 'Toronto, Ontario, Canada', 'Canada · Remote']);
  });
});
