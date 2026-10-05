import { describe, it, expect } from 'vitest';
import { renderDescription } from '../src/utils/descriptionPipeline';
import { extractMetadata, looksLikeStreetAddress, parseUnambiguousDate } from '../src/utils/descriptionMetadata';
import { buildJobFacts } from '../src/utils/jobFacts';
import { BMO_SRE } from './fixtures/descriptions';

const text = (html: string) => new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html').body.textContent!.replace(/\s+/g, ' ').trim();
const shown = (r: ReturnType<typeof renderDescription>) => text(r.companyHtml + r.teamHtml + r.mainHtml + r.policiesHtml);

describe('BMO SRE (workday:Senior-Lead--Site-Reliability-Engineering--SRE-_R260027120)', () => {
  const r = renderDescription(BMO_SRE, 'BMO', 'Senior Lead, Site Reliability Engineering (SRE)');

  it('lifts the explicit deadline, address and job family out of the prose', () => {
    expect(r.meta).toMatchObject({ deadline: '2026-10-30', address: '4100 Gordon Baker Road', jobFamily: 'Technology', compensation: '$70,000.00 - $150,000.00' });
    expect(shown(r)).not.toMatch(/Application Deadline|10\/30\/2026|Address:|Gordon Baker|Job Family Group/);
  });

  it('keeps the role prose, responsibilities and lists intact and starting with the role summary', () => {
    expect(text(r.mainHtml).startsWith('We are seeking a highly motivated and technically strong Senior Lead')).toBe(true);
    expect(text(r.mainHtml)).toContain('Lead and advance SRE practices across critical production platforms.');
    expect(r.mainHtml).toContain('<li>');
  });

  it('shows "Apply by: Oct 30, 2026" and "Job family: Technology" beside Posted in the header facts', () => {
    const job = { job_id: 'x', title: 'Senior Lead, SRE', company: 'BMO', location: 'Toronto, Ontario, Canada', country: 'Canada', workplace_type: 'hybrid', role_type: 'full_time', source_name: 'workday', skills: [], posted_at: '2026-09-28T00:00:00Z' };
    const facts = buildJobFacts(job, { deadline: r.meta.deadline, jobFamily: r.meta.jobFamily }).map((f) => `${f.label}: ${f.value}`);
    expect(facts.slice(0, 2)).toEqual(['Posted: Sep 28, 2026', 'Apply by: Oct 30, 2026']);
    expect(facts).toContain('Job family: Technology');
  });
});

describe('a start-date requirement is never an application deadline', () => {
  it("Stripe's start requirement stays in the text and creates no deadline", () => {
    const raw = '<h2>This role is for applicants actively looking to start before December 1, 2026.</h2><h2>What you\'ll do</h2><ul><li>Ship</li></ul><h3>Minimum requirements</h3><ul><li>Able to start before December 1, 2026</li></ul>';
    const r = renderDescription(raw, 'Stripe', 'Software Engineer');
    expect(r.meta.deadline).toBeUndefined();
    expect(shown(r)).toContain('start before December 1, 2026');
    expect(buildJobFacts({ job_id: 'x', title: 't', company: 'Stripe', location: 'Toronto', country: 'Canada', workplace_type: 'remote', role_type: 'new_grad', source_name: 'greenhouse', skills: [] }, {}).map((f) => f.key)).not.toContain('deadline');
  });

  it('a "Start Date:" label is not a deadline label', () => {
    const r = renderDescription('<p>Start Date: 2026-12-01</p><p>Real content here.</p>', 'Acme', 'Eng');
    expect(r.meta.deadline).toBeUndefined();
    expect(shown(r)).toContain('Start Date: 2026-12-01');
  });
});

describe('deadline dates are never guessed', () => {
  it('parses only unambiguous formats', () => {
    expect(parseUnambiguousDate('10/30/2026')).toBe('2026-10-30');
    expect(parseUnambiguousDate('30/10/2026')).toBe('2026-10-30');
    expect(parseUnambiguousDate('2026-10-30')).toBe('2026-10-30');
    expect(parseUnambiguousDate('October 30, 2026')).toBe('2026-10-30');
    expect(parseUnambiguousDate('Oct 30th, 2026')).toBe('2026-10-30');
    expect(parseUnambiguousDate('30 octobre 2026')).toBe('2026-10-30');
    expect(parseUnambiguousDate('1er novembre 2026')).toBe('2026-11-01');
    expect(parseUnambiguousDate('10/10/2026')).toBe('2026-10-10');
    // ambiguous or invalid: null
    expect(parseUnambiguousDate('03/04/2026')).toBeNull();
    expect(parseUnambiguousDate('02/30/2026')).toBeNull();
    expect(parseUnambiguousDate('Open until filled')).toBeNull();
    expect(parseUnambiguousDate('ASAP')).toBeNull();
  });

  it('leaves an ambiguous numeric deadline in the prose', () => {
    const r = renderDescription('<p>Application Deadline:</p><p>03/04/2026</p><p>Real content here.</p>', 'Acme', 'Eng');
    expect(r.meta.deadline).toBeUndefined();
    expect(shown(r)).toMatch(/Application Deadline:\s*03\/04\/2026/);
  });

  it('extracts nothing when the same field appears with conflicting values', () => {
    const { meta, html } = extractMetadata('<p>Application Deadline: October 30, 2026</p><p>Date limite de candidature : 31 octobre 2026</p><p>Body.</p>');
    expect(meta.deadline).toBeUndefined();
    expect(html).toContain('October 30, 2026');
  });

  it('removes duplicate bilingual labels that agree and supports French labels', () => {
    const { meta, html } = extractMetadata('<p>Application Deadline: October 30, 2026</p><p>Date limite de candidature : 30 octobre 2026</p><p>Body.</p>');
    expect(meta.deadline).toBe('2026-10-30');
    expect(html).toBe('<p>Body.</p>');
  });
});

describe('addresses and compact metadata', () => {
  it('only explicit street addresses move; a bare city or ambiguous text stays', () => {
    expect(looksLikeStreetAddress('4100 Gordon Baker Road')).toBe(true);
    expect(looksLikeStreetAddress('777 BAY ST, TH 27:TORONTO')).toBe(true);
    expect(looksLikeStreetAddress('1000 rue De La Gauchetière Ouest, bureau 500')).toBe(true);
    expect(looksLikeStreetAddress('Toronto')).toBe(false);
    expect(looksLikeStreetAddress('Canada')).toBe(false);
    expect(extractMetadata('<p>Address:</p><p>Toronto</p><p>Body.</p>').meta.address).toBeUndefined();
    expect(extractMetadata('<p>Address:</p><p>Toronto</p><p>Body.</p>').html).toContain('Toronto');
  });

  it('label-only text without a value, or an address that is part of prose, is not touched', () => {
    expect(extractMetadata('<p>Our address is 100 King Street West, come visit.</p>').meta).toEqual({});
    expect(extractMetadata('<p>Job Family Group:</p>').html).toContain('Job Family Group:');
  });

  it('moves metadata only: the rest of the description keeps its order and content', () => {
    const raw = '<p>Intro paragraph.</p><p><strong>Job Family Group:</strong> Technology</p><h2>Responsibilities</h2><ul><li>Ship</li></ul>';
    const r = renderDescription(raw, 'Acme', 'Eng');
    expect(r.meta.jobFamily).toBe('Technology');
    expect(shown(r)).toBe('Intro paragraph.ResponsibilitiesShip'); // blocks are concatenated without separators here
    expect(shown(r)).not.toMatch(/Job Family|Technology/);
  });
});
