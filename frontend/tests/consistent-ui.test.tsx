import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';
import { CompanyLogo } from '../src/components/CompanyLogo';
import { StatePanel } from '../src/components/StatePanel';
import { formatPay, getJobCardCompensation, getCompensationExtras } from '../src/utils/compensation';
import { buildJobFacts } from '../src/utils/jobFacts';
import { summarizePosting } from '../src/utils/postingSummary';
import type { JobSummary } from '../src/api/client';

const css = fs.readFileSync(path.resolve(__dirname, '..', 'src', 'index.css'), 'utf-8');

describe('design tokens', () => {
  it('every var(--token) used in the stylesheet is defined (or set from JS)', () => {
    const defined = new Set([...css.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
    const fromScript = new Set(['--pane-height']); // set on the pane element by JobExplorer
    const used = new Set([...css.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]));
    const undefinedTokens = [...used].filter((t) => !defined.has(t) && !fromScript.has(t));
    expect(undefinedTokens).toEqual([]);
  });

  it('keeps the type and radius scales to named tokens', () => {
    const rawSizes = [...css.matchAll(/font-size:\s*(\d+(?:\.\d+)?)px/g)].map((m) => m[1]);
    // Only the token declarations themselves may use raw pixel font sizes.
    expect(rawSizes.length).toBeLessThanOrEqual(12);
    expect(css).toMatch(/--radius-sm:\s*6px/);
    expect(css).toMatch(/--text-md:\s*14px/);
  });

  it('does not use the undefined primary-button class', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '..', 'src', 'components', 'CompanyPageView.tsx'), 'utf-8');
    expect(src).not.toContain('primary-button');
    expect(src).toContain('job-detail-apply-link');
  });
});

describe('formatPay', () => {
  it('uses compact K and an explicit period when the source stated one', () => {
    expect(formatPay(151200, 189000, 'CAD', '1 YEAR')).toBe('CA$151.2K – CA$189K/yr');
    expect(formatPay(191100, 191100, 'CAD', 'year')).toBe('CA$191.1K/yr');
    expect(formatPay(12500, 12500, 'USD', 'month')).toBe('$12.5K/mo');
    expect(formatPay(50, 50, 'USD', 'hour')).toBe('$50/hr');
  });

  it('never invents a pay period from the size of the amount', () => {
    // No period stated: shown as published. A small figure says so, because it could be hourly, weekly or a typo.
    expect(formatPay(152800, 259200, 'USD')).toBe('$152.8K – $259.2K');
    expect(formatPay(60, 60, 'USD')).toBe('$60 (period not stated)');
    expect(formatPay(40, 40, 'CAD')).toBe('CA$40 (period not stated)');
    // Labelled annual but $38 - $58 (Samsara co-op): the label and the amount contradict, so nothing is shown.
    expect(formatPay(38, 58, 'USD', 'year')).toBeNull();
  });

  it('card and detail pane show the same pay, with source notes only in the pane', () => {
    const ashby = {
      summaryComponents: [{ interval: '1 YEAR', minValue: 151200, maxValue: 189000, currencyCode: 'CAD', compensationType: 'Salary' }],
      compensationTierSummary: 'CA$151.2K – CA$189K • Offers Equity',
    };
    const job = { job_id: 'a', title: 'Dev', company: 'Wealthsimple', location: 'Toronto', country: 'Canada', workplace_type: 'remote', source_name: 'ashby', skills: [], compensation: ashby } as unknown as JobSummary;
    const card = getJobCardCompensation(ashby);
    const pane = buildJobFacts(job, { primaryLocation: 'Toronto' }).find((f) => f.key === 'compensation')?.value;
    expect(card).toBe('CA$151.2K – CA$189K/yr');
    expect(pane).toBe('CA$151.2K – CA$189K/yr · Offers Equity');
    expect(getCompensationExtras(ashby)).toBe('Offers Equity');

    const greenhouse = { min: 12500, max: 12500, currency: 'USD', interval: 'month', compensationTierSummary: '$12.5K per month' };
    const gj = { ...job, compensation: greenhouse } as unknown as JobSummary;
    expect(getJobCardCompensation(greenhouse)).toBe('$12.5K/mo');
    expect(buildJobFacts(gj, { primaryLocation: 'Toronto' }).find((f) => f.key === 'compensation')?.value).toBe('$12.5K/mo');
  });
});

describe('summarizePosting line breaks', () => {
  it('does not fuse a trailing bold heading onto the previous paragraph', () => {
    const html =
      '<p>Lessons from these deployments inform OpenAI’s product and research teams.<br/><br/><strong>About the role</strong></p>' +
      '<p>You will combine deep technical expertise with customer empathy.</p>' +
      '<h4>Responsibilities</h4><ul><li>Embed with our most sophisticated customers.</li></ul>';
    const text = new DOMParser().parseFromString(summarizePosting(html), 'text/html').body.textContent ?? '';
    expect(text).not.toMatch(/teams\.About/);
    expect(text).toContain('research teams.');
  });

  it('turns a single <br> into a space and keeps both lines', () => {
    const html = '<p>Toronto, ON<br/>Hybrid role</p><h4>Requirements</h4><ul><li>3 years</li></ul>';
    const text = new DOMParser().parseFromString(summarizePosting(html), 'text/html').body.textContent ?? '';
    expect(text).toContain('Toronto, ON Hybrid role');
  });
});

describe('StatePanel', () => {
  it('announces errors, names its actions, and spaces them', () => {
    render(
      <StatePanel variant="error" title="Job details unavailable" actions={[{ label: 'Retry', onClick: () => {} }, { label: 'Close', onClick: () => {}, kind: 'secondary' }]}>
        Unable to load.
      </StatePanel>
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Job details unavailable');
    expect(screen.getByRole('button', { name: 'Retry' })).toHaveClass('retry-button');
    expect(screen.getByRole('button', { name: 'Close' })).toHaveClass('secondary-button');
    expect(css).toMatch(/\.state-actions\s*\{[^}]*gap:\s*8px/);
  });

  it('an empty result is a polite status, not an alert', () => {
    render(<StatePanel variant="empty" title="No jobs" />);
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('CompanyLogo loading placeholder', () => {
  it('shows the generic icon (never an empty white box) until the picture loads', async () => {
    const { container } = render(<CompanyLogo company="Scotiabank" logoUrl="/logos/scotiabank.png" size="card" />);
    await act(async () => {});
    const img = container.querySelector('img.company-logo-img') as HTMLImageElement;
    expect(container.querySelector('.company-logo-fallback-icon')).not.toBeNull();
    expect(img.className).toContain('logo-img-loading');
    fireEvent.load(img);
    expect(container.querySelector('.company-logo-fallback-icon')).toBeNull();
    expect((container.querySelector('img.company-logo-img') as HTMLImageElement).className).toContain('logo-img-visible');
  });
});

describe('date-only postings keep the employer day without a precision hint', () => {
  it('formats an exact-midnight-UTC posting as that calendar day in any timezone', async () => {
    const { formatPostingDate } = await import('../src/utils/formatters');
    expect(formatPostingDate('2026-09-28T00:00:00Z')).toBe('Sep 28, 2026');
  });
});
