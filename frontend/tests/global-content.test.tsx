import userEvent from '@testing-library/user-event';
import { readCss } from './cssTokens';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import path from 'node:path';
import { apiClient, type JobDetail } from '../src/api/client';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { CompanyLinks } from '../src/components/CompanyInfo';
import { buildJobFacts } from '../src/utils/jobFacts';
import { collapseRepeatedRange, formatCompensationRange, getJobCardCompensation } from '../src/utils/compensation';
import { removeTitleHeadings, separateCompanyIntro, splitPolicySections, structureDescription } from '../src/utils/descriptionSections';

const css = readCss(path.resolve(__dirname, '..', 'src', 'index.css'));
const cssRule = (selector: string) =>
  css.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}'))?.[1] ?? '';
const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const split = (raw: string, company = 'ExampleCorp', title = 'Software Engineer II') =>
  separateCompanyIntro(structureDescription(removeTitleHeadings(raw, title), company), company, title);

const base: JobDetail = {
  job_id: 'x:1', title: 'Software Engineer II', company: 'ExampleCorp', location: 'Toronto, ON', country: 'Canada',
  workplace_type: 'hybrid', role_type: 'full_time', source_name: 'greenhouse', skills: [], posted_at: '2026-09-28T12:00:00Z',
  company_apply_url: 'https://boards.greenhouse.io/examplecorp/jobs/1', description: '<p>Role text</p>',
};
afterEach(() => vi.restoreAllMocks());

describe('A. company intro', () => {
  it.each([
    ['At <Company>, ...', '<p>At ExampleCorp, we build payments.</p><p>We\'re hiring an engineer.</p><h2>Requirements</h2><ul><li>A</li></ul>'],
    ['<Company> is ...', '<p>ExampleCorp is a payments company.</p><p>In this role, you will ship.</p>'],
    ['<Company> has ...', '<p>ExampleCorp has offices worldwide.</p><p>You will ship.</p>'],
    ['Who we are', '<h2>Who we are</h2><p>We build payments.</p><h2>What you\'ll do</h2><ul><li>Ship</li></ul>'],
    ['About us (bold line)', '<p><strong>About us</strong></p><p>We build payments.</p><h2>Responsibilities</h2><ul><li>Ship</li></ul>'],
  ])('%s -> About the Company', (_name, raw) => {
    const { companyHtml, jobHtml } = split(raw);
    expect(companyHtml).not.toBe('');
    expect(text(companyHtml)).toMatch(/payments|offices/);
    expect(text(jobHtml)).not.toMatch(/build payments|offices worldwide|payments company/);
    expect(text(companyHtml + jobHtml).replace(/Who we are|About us/, '').length).toBeGreaterThan(10);
  });

  it('keeps a lead-in hook and company-wide "we/our" follow-ups with the company, nothing lost', () => {
    const raw = '<p>Ready to build the future?</p><p>At ExampleCorp, our mission is open finance.</p><p>We believe in ownership.</p><p>We\'re hiring a backend engineer.</p><h2>Responsibilities</h2><ul><li>Ship</li></ul>';
    const { companyHtml, jobHtml } = split(raw);
    expect(text(companyHtml)).toBe('Ready to build the future? At ExampleCorp, our mission is open finance. We believe in ownership.');
    expect(text(jobHtml)).toBe("We're hiring a backend engineer. Responsibilities Ship");
  });

  it('stops at team / role / title-specific content', () => {
    const { companyHtml, jobHtml } = split('<p>ExampleCorp is a bank.</p><h2>About the Team</h2><p>Platform team.</p><h2>Requirements</h2><ul><li>A</li></ul>');
    expect(text(companyHtml)).toBe('ExampleCorp is a bank.');
    expect(text(jobHtml)).toContain('About the Team');
    const titled = split('<p>ExampleCorp is a bank.</p><p>The Software Engineer II builds services.</p>');
    expect(text(titled.companyHtml)).toBe('ExampleCorp is a bank.');
  });
});

describe('B. job transition', () => {
  it.each([
    "<p>We're hiring a Software Engineer.</p><h2>Requirements</h2><ul><li>A</li></ul>",
    '<p>In this role, you will build APIs.</p>',
    '<p>You will own services end to end.</p><h2>Requirements</h2><ul><li>A</li></ul>',
    '<p>As a Software Engineer, you will build.</p>',
  ])('%s stays under About the Job', (raw) => {
    const { companyHtml, jobHtml } = split(raw);
    expect(companyHtml).toBe('');
    expect(text(jobHtml)).toBe(text(raw));
  });
});

describe('C. ambiguous intro', () => {
  it.each([
    '<p>Great work happens here every day.</p><p>Build APIs for customers.</p>',
    '<p>Our culture matters to candidates.</p><h2>Requirements</h2><ul><li>A</li></ul>',
    '<h2>Something else</h2><p>We value people.</p><h2>Requirements</h2><ul><li>A</li></ul>',
  ])('%s is not moved', (raw) => {
    const out = separateCompanyIntro(structureDescription(raw, 'ExampleCorp'), 'ExampleCorp', 'Software Engineer II');
    expect(out.companyHtml).toBe('');
    expect(text(out.jobHtml)).toBe(text(raw));
  });
});

describe('D. duplicate job-title heading', () => {
  it.each([
    ['<h2>Software Engineer II</h2><p>Body</p>', 'Software Engineer II'],
    ['<h3>  software   engineer ii </h3><p>Body</p>', 'Software Engineer II'],
    ['<h2>Software Engineer II:</h2><p>Body</p>', 'Software Engineer II'],
    ['<p><strong>Software Engineer II</strong></p><p>Body</p>', 'Software Engineer II'],
  ])('suppresses the heading only: %s', (raw, title) => {
    const out = removeTitleHeadings(raw, title);
    expect(text(out)).toBe('Body');
  });

  it.each([
    ['<h2>About the Software Engineering Team</h2><p>Body</p>', 'Software Engineer II'],
    ['<h2>Senior Data Scientist - Risk</h2><p>Body</p>', 'Senior Data Scientist'],
  ])('keeps a genuinely different heading: %s', (raw, title) => {
    expect(removeTitleHeadings(raw, title)).toBe(raw);
  });

  it('renders no heading that repeats the page title but keeps the content beneath', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...base, description: '<h2>Software Engineer II</h2><p>Build things.</p><h2>Requirements</h2><ul><li>Python</li></ul>' });
    render(<JobDetailContent jobId="x:1" variant="pane" onClose={() => {}} />);
    await screen.findByText('Build things.');
    const titles = screen.getAllByText('Software Engineer II');
    expect(titles).toHaveLength(1); // the pane's own h2
    expect(screen.getByRole('heading', { name: 'Requirements' })).toBeInTheDocument();
  });
});

describe('E. emphasis is display-only normal/bold', () => {
  const both = ['.job-description-prose strong em', '.job-description-prose em strong'];
  it('<em> is normal, <strong> bold, <strong><em> bold and not italic, blockquote not italic', () => {
    expect(css).toMatch(/\.job-description-prose em,\s*\.job-description-prose i\s*\{\s*font-style:\s*normal/);
    expect(css).toMatch(/\.job-description-prose strong,[^{]*\{[^}]*font-weight:\s*600/);
    for (const selector of both) expect(css).toContain(selector);
    expect(css).toMatch(/\.job-description-prose strong em,[^{]*\{[^}]*font-style:\s*normal;[^}]*font-weight:\s*600/);
    expect(cssRule('.job-description-prose blockquote')).not.toMatch(/italic/);
  });

  it('never rewrites the stored/source HTML', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...base, description: '<p><strong><em>Application Limit:</em></strong> <em>Apply once.</em></p>' });
    render(<JobDetailContent jobId="x:1" variant="pane" onClose={() => {}} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Full Posting' }));
    await screen.findByText(/Apply once\./);
    expect(document.querySelector('.job-description-prose strong em')).not.toBeNull();
  });
});

describe('F. compensation', () => {
  it('shows supplied salary without confusing benefits or equity percentages for pay', () => {
    expect(getJobCardCompensation({ summaryComponents: [
      { description: 'Health benefits' },
      { compensationType: 'EquityPercentage', minValue: 1, maxValue: 2 },
      { compensationType: 'Salary', minValue: 100000, maxValue: 150000, currencyCode: 'CAD', interval: 'YEAR' },
    ] })).toBe('CA$100K – CA$150K/yr');
    expect(getJobCardCompensation({ summaryComponents: [{ compensationType: 'EquityPercentage', minValue: 1, maxValue: 2 }] })).toBeNull();
    expect(getJobCardCompensation({ compensationTierSummary: 'CA$151,200 – CA$189,000/yr • Equity • Bonus' })).toBe('CA$151,200 – CA$189,000/yr');
    expect(getJobCardCompensation({ compensationTierSummary: '$32 – $43/hr plus equity' })).toBe('$32 – $43/hr');
    expect(getJobCardCompensation({ compensationTierSummary: 'Offers equity of 2%' })).toBeNull();
    expect(getJobCardCompensation(null)).toBeNull();
  });

  it('equal bounds show one value; different bounds show a range; invalid shows nothing', () => {
    expect(formatCompensationRange(100000, 100000, 'CAD')).toBe('CA$100,000');
    expect(formatCompensationRange(150000, 190000, 'CAD')).toBe('CA$150K – CA$190K');
    expect(formatCompensationRange(150000, 100000, 'CAD')).toBeNull();
    expect(formatCompensationRange(null, undefined)).toBeNull();
    expect(formatCompensationRange(0, NaN)).toBeNull();
    expect(formatCompensationRange(120000, null, 'USD')).toBe('From $120,000');
    expect(formatCompensationRange(undefined, 120000, 'USD')).toBe('Up to $120,000');
  });

  it('collapses repeated source ranges but keeps real ranges and other words', () => {
    expect(collapseRepeatedRange('CA$191,100 – CA$191,100')).toBe('CA$191,100');
    expect(collapseRepeatedRange('$150K – $150K • Offers Equity')).toBe('$150K • Offers Equity');
    expect(collapseRepeatedRange('USD 100k–USD 100k')).toBe('USD 100k');
    expect(collapseRepeatedRange('CA$150K – CA$190K')).toBe('CA$150K – CA$190K');
    expect(collapseRepeatedRange('$166k–$195k CAD')).toBe('$166k–$195k CAD');
    expect(collapseRepeatedRange('Canada: CAD 130,000–180,000')).toBe('Canada: CAD 130,000–180,000');
  });

  it('the shared facts builder applies it', () => {
    const facts = buildJobFacts({ ...base, compensation: { compensationTierSummary: 'CA$191,100 – CA$191,100' } });
    expect(facts.find((f) => f.key === 'compensation')?.value).toBe('CA$191,100');
  });
});

describe('G. social links', () => {
  const profile = { name: 'ExampleCorp', x: 'https://x.com/example', linkedin: 'https://www.linkedin.com/company/example', github: 'https://github.com/example', youtube: 'https://www.youtube.com/@example', website: 'https://example.com' };
  it('X is icon-only with an accessible name, tooltip and verified URL; others keep their labels', () => {
    render(<CompanyLinks profile={profile as never} />);
    const x = screen.getByRole('link', { name: 'ExampleCorp on X (opens in a new tab)' });
    expect(x).toHaveAttribute('href', 'https://x.com/example');
    expect(x).toHaveAttribute('title', 'ExampleCorp on X');
    expect(x.querySelector('.company-link-label')).toBeNull();
    expect(x.textContent).toBe('');
    expect(screen.getByRole('link', { name: 'ExampleCorp on LinkedIn (opens in a new tab)' }).querySelector('.company-link-label')?.textContent).toBe('LinkedIn');
    expect(screen.getByRole('link', { name: 'ExampleCorp on GitHub (opens in a new tab)' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /YouTube/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ExampleCorp website (opens in a new tab)' }).querySelector('.company-link-label')?.textContent).toBe('Website');
  });
});

describe('no lost text', () => {
  it('splitPolicySections keeps bare top-level text (Amazon/Workday style) on both sides of a boilerplate heading', () => {
    const raw = 'Opening text with no tag.<br><h3>Basic Qualifications</h3><p>Java</p><h3>Equal Opportunity</h3>Policy text.';
    const out = splitPolicySections(raw);
    expect(out.mainHtml).toContain('Opening text with no tag.');
    expect(out.mainHtml).toContain('Java');
    expect(out.policiesHtml).toContain('Policy text.');
  });
});
