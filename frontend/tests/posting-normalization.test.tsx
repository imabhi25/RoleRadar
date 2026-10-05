import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { renderDescription } from '../src/utils/descriptionPipeline';
import { buildJobFacts } from '../src/utils/jobFacts';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { apiClient, type JobDetail } from '../src/api/client';

const td = '<h2>Work Location:</h2><p>Toronto, Ontario, Canada</p><h2>Hours:</h2><p>37.5</p><h2>Line of Business:</h2><p>Analytics, Insights, &amp; Artificial Intelligence</p><h2>Pay Details:</h2><p>$81,600 - $115,200 CAD</p><p>TD is committed to fair and equitable compensation. Growth opportunities depend on role and experience.</p><h2>Job Description:</h2><p>Build models and partner with engineering teams.</p><h2>Responsibilities</h2><ul><li>Validate models.</li></ul>';
const job: JobDetail = { job_id: 'workday:td-example', title: 'Data Scientist II', company: 'TD', location: 'Toronto, Ontario, Canada', country: 'Canada', workplace_type: 'onsite', role_type: 'full_time', source_name: 'workday', skills: [], company_apply_url: 'https://td.wd3.myworkdayjobs.com/job/example', description: td };
afterEach(() => vi.restoreAllMocks());

describe('one metadata normalization pipeline for existing and future postings', () => {
  it.each([
    td,
    '<div><p><strong>Work Location:</strong> Toronto, Ontario, Canada</p><p><strong>Hours:</strong> 37.5</p><p><strong>Line of Business:</strong> Analytics, Insights, &amp; Artificial Intelligence</p><p><strong>Pay Details:</strong> $81,600 - $115,200 CAD</p><p>Build models.</p></div>',
    '<div><h3>Work Location:</h3><p>Toronto, Ontario, Canada</p></div><div><h3>Hours:</h3><p>37.5</p></div><div><h3>Line of Business:</h3><p>Analytics, Insights, &amp; Artificial Intelligence</p></div><div><h3>Pay Details:</h3><p>$81,600 - $115,200 CAD</p></div><p>Build models.</p>',
    '<p><strong>Work Location</strong><br>Toronto, Ontario, Canada</p><p><strong>Hours</strong><br>37.5</p><p><strong>Line of Business</strong><br>Analytics, Insights, &amp; Artificial Intelligence</p><p><strong>Pay Details</strong><br>$81,600 - $115,200 CAD</p><p>Build models.</p>',
  ])('lifts Workday field blocks without losing the actual description', (description) => {
    const result = renderDescription(description, 'TD', job.title);
    expect(result.meta).toMatchObject({ workLocation: job.location, hours: '37.5', businessLine: 'Analytics, Insights, & Artificial Intelligence', compensation: '$81,600 - $115,200 CAD' });
    expect(result.mainHtml).not.toMatch(/Work Location:|Hours:|Line of Business:|Pay Details:/);
    expect(result.mainHtml).toContain('Build models');
    const facts = buildJobFacts(job, { primaryLocation: job.location, ...result.meta });
    expect(facts.find((fact) => fact.key === 'compensation')?.value).toBe('$81,600 - $115,200 CAD');
    expect(facts.find((fact) => fact.key === 'hours')?.value).toBe('37.5');
    expect(facts.filter((fact) => fact.key === 'workLocation')).toHaveLength(0);
  });
  it('preserves compensation explanations and ambiguous or conflicting values', () => {
    const result = renderDescription(td, 'TD', job.title);
    expect(result.meta.compensationNotesHtml).toContain('fair and equitable compensation');
    expect(result.mainHtml).not.toContain('fair and equitable compensation');
    expect(renderDescription('<p>Hours: Flexible depending on your location</p><p>Build models.</p>', 'TD', job.title).mainHtml).toContain('Flexible depending');
    const conflict = renderDescription('<p>Hours: 37.5</p><p>Hours: 40</p><p>Build models.</p>', 'TD', job.title);
    expect(conflict.meta.hours).toBeUndefined();
    expect(conflict.mainHtml).toContain('37.5');
    expect(conflict.mainHtml).toContain('40');
  });
  it('renders reusable company background and clean role text for the TD posting', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue(job);
    render(<JobDetailContent jobId={job.job_id} variant="pane" onClose={() => {}} />);
    const about = await screen.findByRole('heading', { name: 'About the job', exact: true });
    const section = about.closest('section')!;
    expect(section).not.toHaveTextContent(/Work Location:|Hours:|Line of Business:|Pay Details:/);
    expect(screen.getByLabelText('Job facts')).toHaveTextContent('$81,600 - $115,200 CAD');
    const company = screen.getByRole('heading', { name: 'About the company', exact: true }).closest('section')!;
    expect(within(company).getByText(/provides banking and financial services in Canada/)).toBeInTheDocument();
    expect(screen.queryByText('The source posting does not include company background.')).not.toBeInTheDocument();
  });
});
