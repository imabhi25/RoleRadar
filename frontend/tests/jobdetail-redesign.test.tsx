import userEvent from '@testing-library/user-event';
import { readCss } from './cssTokens';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import path from 'node:path';
import { apiClient, type JobDetail } from '../src/api/client';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { JobCard } from '../src/components/JobCard';
import { buildJobFacts } from '../src/utils/jobFacts';
import { separateCompanyIntro, structureDescription, presentHeadings, normalizeAllCapsHeading } from '../src/utils/descriptionSections';
import { COMPANY_SOCIAL_HANDLES, getCompanySocials, getCompanyProfile } from '../src/utils/companyProfiles';
import { COMPANY_DOMAIN_MAP } from '../src/utils/companyLogos';
import { resolveApplyRoutes } from '../src/utils/applyUrls';

const css = readCss(path.resolve(__dirname, '..', 'src', 'index.css'));
const rule = (selector: string) =>
  css.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}'))?.[1] ?? '';

const base: JobDetail = {
  job_id: 'ashby:1', title: 'Senior Software Developer, Build Platform', company: 'Wealthsimple', location: 'Toronto, ON', country: 'Canada',
  workplace_type: 'hybrid', role_type: 'full_time', source_name: 'ashby', skills: [], posted_at: '2026-09-28T12:00:00Z',
  company_apply_url: 'https://jobs.ashbyhq.com/wealthsimple/abc/application', description: '<p>Role text</p>',
};
afterEach(() => vi.restoreAllMocks());
async function renderDetail(job: JobDetail) {
  vi.spyOn(apiClient, 'getJob').mockResolvedValue(job);
  const view = render(<JobDetailContent jobId={job.job_id} variant="pane" onClose={() => {}} />);
  await screen.findByRole('link', { name: /^Apply for/ });
  return view;
}
const header = () => document.querySelector('.job-detail-header') as HTMLElement;
const text = (html: string) => (new DOMParser().parseFromString(html, 'text/html').body.textContent || '').replace(/\s+/g, ' ').trim();

describe('header: company row, links and Apply', () => {
  it('puts company identity and Apply in the desktop header; company links sit beside its name', async () => {
    await renderDetail(base);
    const grid = header().querySelector('.jd-grid')!;
    const kids = Array.from(grid.children).map((c) => c.className.toString().split(' ')[0]);
    expect(kids.slice(0, 2)).toEqual(['jd-company', 'jd-apply']);
    expect(header().querySelector('.jd-close')).toBeNull();
    expect(rule('.jd-grid')).toMatch(/grid-template-columns:\s*minmax\(0, 1fr\) auto auto/);
    // company name is clearly larger than the secondary link text
    const size = (selector: string) => {
      const all = [...css.matchAll(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}', 'g'))].map((m) => m[1]);
      return parseFloat(all.map((body) => body.match(/font-size:\s*([\d.]+)px/)?.[1]).find(Boolean)!);
    };
    const name = size('.jd-company-name');
    const link = size('.company-link');
    expect(name).toBeGreaterThanOrEqual(18);
    expect(name).toBeLessThanOrEqual(20);
    expect(name).toBeGreaterThan(link + 4);
    expect(css).toMatch(/\.jd-company-name \{[^}]*font-weight:\s*7\d\d/);
    // narrow panes stack: company + close, socials, title, location, facts, Apply
    expect(css).toMatch(/@container \(max-width: 480px\) \{\s*\.jd-grid \{[^}]*"company close"[^}]*"title title"[^}]*"apply apply"/);
  });

  it('renders only verified social links as real, safe, labelled anchors', async () => {
    await renderDetail(base);
    const links = screen.getAllByRole('link').filter((a) => a.classList.contains('company-link'));
    expect(links.map((a) => a.className.replace('company-link ', ''))).toEqual(['company-link-linkedin', 'company-link-x', 'company-link-website']);
    for (const a of links) {
      expect(a.tagName).toBe('A');
      expect(a).toHaveAttribute('target', '_blank');
      expect(a).toHaveAttribute('rel', 'noopener noreferrer');
      expect(a.getAttribute('aria-label')).toMatch(/^Wealthsimple (on \w+|website) \(opens in a new tab\)$/);
      expect(a.getAttribute('title')).toBeTruthy();
      expect(a.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    }
    expect(links[0]).toHaveAttribute('href', 'https://www.linkedin.com/company/wealthsimple');
    expect(links[1]).toHaveAttribute('href', 'https://x.com/Wealthsimple');
    expect(links[2]).toHaveAttribute('href', expect.stringMatching(/^https:\/\/wealthsimple\.com/));
  });

  it('collapses to icon-only when tight and shows labels only with room', () => {
    expect(rule('.company-link-label')).toMatch(/display:\s*none/);
    expect(css).toMatch(/@container \(min-width: 600px\) \{[^}]*data-count="3"\] \.company-link-label \{ display: inline; \}/);
    expect(css).toMatch(/@container \(min-width: 780px\) \{\s*\.company-links \.company-link-label \{ display: inline; \}/);
  });

  it('omits every network that is not verified, and never guesses', async () => {
    await renderDetail({ ...base, company: 'Linear', job_id: 'l' });
    const kinds = screen.getAllByRole('link').map((a) => a.className);
    expect(kinds.some((c) => c.includes('company-link-linkedin'))).toBe(false); // Linear has no verified LinkedIn
    expect(kinds.some((c) => c.includes('company-link-x'))).toBe(true);
    expect(kinds.some((c) => c.includes('company-link-github'))).toBe(true);
    const nothing = getCompanySocials('Definitely Not A Company');
    expect(nothing).toEqual({ x: null, github: null, youtube: null });
    expect(getCompanyProfile('Spotify').x).toBeNull(); // two different official X accounts: ambiguous, omitted
  });

  it('only stores well-formed handles for known companies', () => {
    for (const [key, entry] of Object.entries(COMPANY_SOCIAL_HANDLES)) {
      expect(COMPANY_DOMAIN_MAP[key], key).toBeTruthy();
      const s = getCompanySocials(key);
      if (entry.x) expect(s.x).toMatch(/^https:\/\/x\.com\/[A-Za-z0-9_]{1,15}$/);
      if (entry.github) expect(s.github).toMatch(/^https:\/\/github\.com\/[A-Za-z0-9-]+$/);
      if (entry.youtube) expect(s.youtube).toMatch(/^https:\/\/www\.youtube\.com\/(@[\w.-]+|channel\/[\w-]+|c\/[\w.-]+|user\/[\w.-]+)$/);
    }
    expect(Object.keys(COMPANY_SOCIAL_HANDLES).length).toBeGreaterThan(40);
  });
});

describe('Apply keeps the official job-specific URL and says only "Apply"', () => {
  const cases: Array<[string, string]> = [
    ['Ashby', 'https://jobs.ashbyhq.com/wealthsimple/c6dfa59f-cf09-4a11-9e35-a0cf4ab23cd0/application'],
    ['Greenhouse', 'https://boards.greenhouse.io/robinhood/jobs/8199744'],
    ['Lever', 'https://jobs.lever.co/acme/1234-abcd/apply'],
    ['Workday', 'https://rbc.wd3.myworkdayjobs.com/RBCGLOBAL1/job/Toronto/Senior-Data-Engineer_R-0000184832'],
    ['Amazon', 'https://www.amazon.jobs/en/jobs/10561786/software-development-engineer-ii'],
  ];
  it.each(cases)('%s URL stays exactly as the employer posted it', async (_name, url) => {
    expect(resolveApplyRoutes({ company_apply_url: url }).primaryUrl).toBe(url);
    expect(resolveApplyRoutes({ company_apply_url: url }).primaryLabel).toBe('Apply ↗');
    await renderDetail({ ...base, company_apply_url: url });
    const apply = within(header()).getByRole('link', { name: /^Apply for/ });
    expect(apply).toHaveAttribute('href', url);
    expect(apply).toHaveTextContent('Apply');
    expect(apply.textContent).not.toMatch(/company website/i);
    expect(apply.getAttribute('aria-label')).not.toMatch(/company website/i);
    expect(apply).toHaveAttribute('target', '_blank');
    expect(apply).toHaveAttribute('rel', 'noopener noreferrer');
  });
});

describe('job facts grid', () => {
  it('renders labelled facts and explicit title seniority without match checks', async () => {
    await renderDetail({ ...base, workplace_type: 'onsite', academic_term: 'Summer 2027', role_type: 'internship', compensation: { compensationTierSummary: 'CA$152K – CA$189K • Offers Equity' } });
    const facts = screen.getByLabelText('Job facts');
    expect(facts.textContent!.replace(/\s+/g, ' ').trim()).toBe('Compensation CA$152K – CA$189K · Offers Equity Role Internship Posted Sep 28, 2026 Experience level Senior Term Summer 2027 Workplace On-site');
    expect([...facts.querySelectorAll('dt')].map((d) => d.textContent)).toEqual(['Compensation', 'Role', 'Posted', 'Experience level', 'Term', 'Workplace']);
    expect(rule('.job-fact dt')).not.toMatch(/uppercase/);
  });

  it('never shows a relative age on the detail page, but the job card keeps it', async () => {
    const recent = new Date(Date.now() - 5 * 3600_000).toISOString();
    await renderDetail({ ...base, posted_at: recent });
    expect(screen.getByLabelText('Job facts').textContent).toMatch(/Posted\s*\w{3} \d{1,2}, \d{4}/);
    expect(header().textContent).not.toMatch(/hours? ago|days? ago|minutes? ago|just now|today/i);
    expect(document.body.textContent).not.toMatch(/\d+ hours? ago/);
    document.body.innerHTML = '';
    render(<JobCard job={{ ...base, posted_at: recent }} onClick={() => {}} />);
    expect(screen.getByText('5 hours ago')).toBeInTheDocument();
  });

  it('omits absent facts and does not repeat Remote when the location already says it', () => {
    expect(buildJobFacts({ ...base, posted_at: null, role_type: 'unknown', workplace_type: 'unspecified' })).toEqual([]);
    const facts = buildJobFacts({ ...base, workplace_type: 'remote' }, { primaryLocation: 'Canada · Remote' });
    expect(facts.map((f) => f.key)).toEqual(['posted', 'role']);
  });
});

const COMPANY = 'Wealthsimple';
const POSTING = `
<h2>Build something people love</h2>
<p>Wealthsimple is Canada's leading financial innovator. We help Canadians invest.</p>
<h2>About the Build Platform Team</h2><p>The team owns the platform.</p>
<h2>What you'll do</h2><ul><li>Ship code</li></ul>
<h2>Requirements</h2><ul><li>Python</li></ul>`;

describe('About the Company / About the Job', () => {
  it('moves a confidently detected leading company intro and keeps the employer tagline as a sub-heading', () => {
    const structured = structureDescription(POSTING, COMPANY);
    const { companyHtml, jobHtml } = separateCompanyIntro(structured, COMPANY);
    expect(text(companyHtml)).toContain("Wealthsimple is Canada's leading financial innovator.");
    expect(text(companyHtml)).toContain('Build something people love');
    expect(text(jobHtml)).not.toContain('leading financial innovator');
    expect(text(jobHtml)).toContain('About the Build Platform Team');
    // nothing lost, nothing duplicated
    expect(text(companyHtml + jobHtml)).toBe(text(structured));
    expect(text(companyHtml + jobHtml).match(/leading financial innovator/g)).toHaveLength(1);
  });

  it('absorbs a generic company heading ("Who are we?") into the About the Company heading', () => {
    const html = structureDescription('<h2>Who are we?</h2><p>We build things.</p><h2>Requirements</h2><ul><li>A</li></ul>', 'Acme');
    const { companyHtml, jobHtml } = separateCompanyIntro(html, 'Acme');
    expect(text(companyHtml)).toBe('We build things.');
    expect(text(jobHtml)).toBe('RequirementsA');
  });

  it('leaves ambiguous structure exactly in source order', () => {
    const cases = [
      '<p>You are as unique as your background.</p><h2>About the role</h2><p>Build.</p><h2>Requirements</h2><ul><li>A</li></ul>',  // loose intro first
      '<h2>Requirements</h2><ul><li>A</li></ul><h2>About us</h2><p>Acme is a company.</p>',                                        // company text is not leading
      '<h2>Something else</h2><p>We value people.</p><h2>Requirements</h2><ul><li>A</li></ul>',                                      // leading unknown, no company signal
      '<h2>About us</h2><p>Acme is a company.</p>',                                                                              // nothing else left
    ];
    for (const raw of cases) {
      const structured = structureDescription(raw, 'Acme');
      const result = separateCompanyIntro(structured, 'Acme');
      expect(result.companyHtml, raw).toBe('');
      expect(result.jobHtml, raw).toBe(structured);
    }
    expect(separateCompanyIntro('', 'Acme')).toEqual({ companyHtml: '', jobHtml: '' });
    expect(separateCompanyIntro('<p>x</p>', null)).toEqual({ companyHtml: '', jobHtml: '<p>x</p>' });
  });

  it('puts About the job first and company background last', async () => {
    await renderDetail({ ...base, description: POSTING });
    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(['About the job', 'About the company']);
    const company = screen.getByRole('heading', { name: 'About the company' }).closest('section')!;
    const job = screen.getByRole('heading', { name: 'About the job' }).closest('section')!;
    expect(job.compareDocumentPosition(company) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(company.textContent).toContain('provides digital financial services in Canada');
    expect(job.textContent).not.toContain('leading financial innovator');
    expect(job.textContent).toContain('Responsibilities');
    expect(job.textContent).toContain('Ship code');
    expect(company.textContent!.match(/provides digital financial services in Canada/g)).toHaveLength(1);
  });

  it('shows the job and explains when company background is unavailable', async () => {
    await renderDetail({ ...base, description: '<p>Short plain posting.</p>' });
    expect(screen.getByRole('heading', { name: 'About the company' })).toBeInTheDocument();
    const job = screen.getByRole('heading', { level: 3, name: 'About the job' }).closest('section')!;
    expect(job).toHaveTextContent('Short plain posting.');
    document.body.innerHTML = '';
    await renderDetail({ ...base, description: '' , job_id: 'e' });
    expect(screen.getByRole('heading', { name: 'About the job' })).toBeInTheDocument();
    expect(screen.getByText(/No additional description/)).toBeInTheDocument();
  });
});

describe('heading typography and hierarchy', () => {
  it('title-cases shouted headings without touching other headings', () => {
    expect(normalizeAllCapsHeading('ABOUT THE BUILD PLATFORM TEAM')).toBe('About the Build Platform Team');
    expect(normalizeAllCapsHeading('WHAT YOU’LL DO')).toBe('What You’ll Do');
    expect(normalizeAllCapsHeading('FAQ')).toBe('FAQ');
    expect(normalizeAllCapsHeading('What You’ll Do')).toBe('What You’ll Do');
    expect(normalizeAllCapsHeading('Benefits at AWS')).toBe('Benefits at AWS');
  });

  it('renders one semantic level (h2 title, h3 parts, h4 employer sections) with the same words', async () => {
    const raw = '<h2>BENEFITS</h2><ul><li>Health</li></ul><h2>Requirements</h2><ul><li>Python</li></ul>';
    expect(text(presentHeadings(raw))).toBe('BenefitsHealthRequirementsPython');
    await renderDetail({ ...base, description: raw });
    await userEvent.click(screen.getByRole('button', { name: 'Full Posting' }));
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(1);
    const sub = [...document.querySelectorAll('.job-description-prose h4.job-section-heading')].map((h) => h.textContent);
    expect(sub).toEqual(['Benefits', 'Requirements']);
    expect(document.querySelectorAll('.job-description-prose h1, .job-description-prose h2, .job-description-prose h3')).toHaveLength(0);
  });

  it('uses larger, bolder, title-case headings instead of small letter-spaced capitals', () => {
    const part = rule('.job-part-heading');
    expect(parseFloat(part.match(/font-size:\s*([\d.]+)px/)![1])).toBeGreaterThanOrEqual(21);
    expect(parseFloat(part.match(/font-size:\s*([\d.]+)px/)![1])).toBeLessThanOrEqual(24);
    const sub = rule('.job-detail .job-description-prose .job-section-heading');
    expect(sub).toMatch(/font-size:\s*20px/);
    expect(sub).toMatch(/text-transform:\s*none/);
    expect(sub).toMatch(/font-weight:\s*6\d\d/);
    expect(sub).not.toMatch(/letter-spacing:\s*0\.0[3-9]/);
    expect(part).not.toMatch(/uppercase/);
  });
});

describe('body typography and link wrapping', () => {
  it('has readable body text and never breaks words mid-link', () => {
    expect(rule('.job-detail .job-description-prose')).toMatch(/font-size:\s*16px/);
    expect(rule('.job-detail .job-description-prose')).toMatch(/line-height:\s*1\.6/);
    expect(rule('.job-detail-inpane .job-description-prose')).toMatch(/font-size:\s*15\.5px/);
    expect(css).not.toMatch(/word-break:\s*break-all/);
    const link = css.match(/\.job-description-prose a\s*\{([^}]*)\}/)?.[1] ?? '';
    expect(link).toMatch(/word-break:\s*normal/);
    expect(link).toMatch(/overflow-wrap:\s*break-word/);
    const prose = css.match(/\.job-description-prose\s*\{([^}]*)\}/)?.[1] ?? '';
    expect(prose).toMatch(/word-break:\s*normal/);
    expect(prose).not.toMatch(/word-break:\s*break-word/);
  });
});
