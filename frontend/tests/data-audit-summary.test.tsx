/**
 * Public-data audit: Summary versus Full Posting. A condition that decides whether a reader can take the job (office days,
 * relocation, language, who may apply, work authorization) is kept in the Summary wherever the employer put it, even inside a
 * company-description section that is otherwise left out. Equal-opportunity boilerplate is not mistaken for a condition.
 * The sentences are the ones quoted in the audit (Brex, Samsara, TD, Bell, Sun Life, CIBC, BMO, RBC, Datadog).
 */
import { describe, expect, it } from 'vitest';
import { summarizePosting, isApplicantCondition } from '../src/utils/postingSummary';
import { extractMetadata } from '../src/utils/descriptionMetadata';
import { buildJobFacts } from '../src/utils/jobFacts';
import type { JobSummary } from '../src/api/client';

const text = (html: string) => new DOMParser().parseFromString(html, 'text/html').body.textContent?.replace(/\s+/g, ' ').trim() ?? '';
// Enough generic requirements and responsibilities that the 4,000-character Summary has to choose.
const filler = (n: number) => Array.from({ length: n }, (_, i) => `<li>Generic requirement number ${i + 1} that describes working with teams and delivering software reliably.</li>`).join('');
const posting = (middle: string) =>
  `<p>We build software for customers.</p><h2>Requirements</h2><ul>${filler(30)}</ul>${middle}<h2>Responsibilities</h2><ul>${filler(30)}</ul>`;

describe('conditions that must reach the Summary', () => {
  it.each([
    ['Brex: office the role is based in', '<h3>Where you’ll work</h3><p>This role will be based in our San Francisco office.</p>', 'This role will be based in our San Francisco office.'],
    ['TD: days in the office', '<p>The Workplace Model for this position is "Primarily Onsite" and requires 4 days/week in the Toronto office</p>', 'requires 4 days/week in the Toronto office'],
    ['TD: in-office requirements', '<p>Employees must comply with the bank’s in-office requirements.</p>', 'in-office requirements'],
    ['BMO: hybrid days', '<p>Hybrid role 2 days per week at Scarborough Computing Center (4100 Gordon Baker Road)</p>', 'Hybrid role 2 days per week'],
    ['CIBC: hybrid days', '<p>Work Environment: Hybrid, 2 days in office, 3 days remote</p>', '2 days in office, 3 days remote'],
    ['Bell: language of work', '<p>Adequate knowledge of French is required for positions in Quebec.</p>', 'Adequate knowledge of French is required for positions in Quebec.'],
    ['CIBC: language assessment', '<p>We may ask you to complete an attribute-based assessment and other skills test (such as simulation, coding, French proficiency).</p>', 'French proficiency'],
    ['Sun Life: graduation date', '<p>This opportunity is available to students with a December 2027 or later graduation date</p>', 'December 2027 or later graduation date'],
    ['RBC: enrolment and graduation window', '<ul><li>Must be currently enrolled in a post-secondary institution, graduating between August 2027 and June 2028.</li></ul>', 'graduating between August 2027 and June 2028'],
    ['Samsara co-op: relocation', '<p>Relocation and housing assistance will be included as part of the co-op.</p>', 'Relocation and housing assistance will be included as part of the co-op.'],
    ['Datadog: export control', '<p>To conform to US export control regulations, candidates should be eligible for any required authorizations from the US government.</p>', 'export control regulations'],
    ['CIBC: visa sponsorship', '<p><b>This position does not offer visa sponsorship.</b></p>', 'does not offer visa sponsorship'],
  ])('%s', (_name, middle, expected) => {
    const summary = summarizePosting(posting(middle));
    expect(summary).not.toBe('');
    expect(text(summary)).toContain(expected);
    expect(text(summary).length).toBeLessThanOrEqual(4100);
  });

  it('keeps a condition buried in a company section, and only that sentence, not the company boilerplate', () => {
    const summary = summarizePosting(posting(
      '<h2>About the company</h2><p>Samsara is the pioneer of the Connected Operations Cloud and serves many industries. ' +
      'This is a hybrid position requiring 3 days per week in our San Francisco, CA headquarter office and 2 days working remotely. ' +
      'We are proud of our culture and our customers.</p>',
    ));
    expect(text(summary)).toContain('requiring 3 days per week in our San Francisco, CA headquarter office and 2 days working remotely.');
    expect(text(summary)).not.toContain('pioneer of the Connected Operations Cloud');
    expect(text(summary)).not.toContain('We are proud of our culture');
  });

  it('does not treat equal-opportunity boilerplate as a condition', () => {
    const eeo = 'We are committed to equal employment opportunity regardless of race, color, ancestry, religion, sex, national origin, age, citizenship, marital status, disability status or gender identity.';
    expect(isApplicantCondition(eeo)).toBe(false);
    expect(isApplicantCondition('We provide reasonable accommodations and value diversity and an inclusive workplace.')).toBe(false);
    expect(text(summarizePosting(posting(`<h2>About us</h2><p>${eeo}</p>`)))).not.toContain('equal employment opportunity');
    // …while a real eligibility statement that mentions the same word still counts
    expect(isApplicantCondition('Applicants must be U.S. citizens or permanent residents to comply with export control regulations.')).toBe(true);
    expect(isApplicantCondition('This position does not offer visa sponsorship.')).toBe(true);
  });

  it('is not triggered by ordinary company prose', () => {
    expect(isApplicantCondition('Thomson Reuters is proud to be an Equal Employment Opportunity Employer providing a drug-free workplace.')).toBe(false);
    expect(isApplicantCondition('Our spaces and technological toolkit will make it simple to bring together great minds.')).toBe(false);
    expect(isApplicantCondition('We are a customer engagement platform with offices around the world.')).toBe(false);
  });
});

describe('the employer-named work term', () => {
  const html = '<p>Role Type:</p><p>Internship/Co-op</p><p>Work Term:</p><p>Winter/Term 2</p><p>Hours:</p><p>40</p><p>Pay Details:</p><p>$30.74 - $30.74 USD</p><p>Join our co-op program.</p>';
  it('is lifted out of the prose as written, never converted into a season and year', () => {
    const { meta, html: rest } = extractMetadata(html);
    expect(meta.workTerm).toBe('Winter/Term 2');
    expect(text(rest)).not.toContain('Work Term');
  });
  it('becomes a "Work term" fact beside the parsed term, only when it adds something', () => {
    const job = { job_id: 'x', title: '2027 Spring Co-op', company: 'TD', location: 'T', country: 'United States', workplace_type: 'onsite', role_type: 'co_op', source_name: 'workday', skills: [], academic_term: null } as unknown as JobSummary;
    expect(buildJobFacts(job, { workTerm: 'Winter/Term 2' }).find((f) => f.key === 'workTerm')).toEqual({ key: 'workTerm', label: 'Work term', value: 'Winter/Term 2' });
    const parsed = { ...job, academic_term: 'Winter 2027' } as JobSummary;
    expect(buildJobFacts(parsed, { workTerm: 'winter 2027' }).some((f) => f.key === 'workTerm')).toBe(false);
  });
});
