import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { apiClient, type JobDetail } from '../src/api/client';
import { JobDetailContent } from '../src/components/JobDetailContent';

const job: JobDetail = {
  job_id: 'facts-accessibility', title: 'Senior Software Engineer', company: 'Fixture',
  location: 'Toronto, ON', country: 'Canada', workplace_type: 'hybrid', role_type: 'full_time',
  source_name: 'ashby', skills: [], posted_at: '2026-09-28T12:00:00Z',
  company_apply_url: 'https://jobs.ashbyhq.com/fixture/application',
  description: '<h2>Responsibilities</h2><ul><li>Build accessible software.</li></ul>',
};

afterEach(() => vi.restoreAllMocks());

describe.each(['pane', 'modal'] as const)('job facts in the %s', (variant) => {
  it('exposes valid term/definition groups with decorative icons inside the terms', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue(job);
    render(<JobDetailContent jobId={job.job_id} variant={variant} onClose={() => {}} />);
    await screen.findByRole('link', { name: /Apply for/ });
    const facts = screen.getByLabelText('Job facts');
    expect(facts.tagName).toBe('DL');
    const groups = [...facts.children];
    expect(groups.length).toBeGreaterThan(0);
    for (const group of groups) {
      expect(group.tagName).toBe('DIV');
      expect([...group.children].map((child) => child.tagName)).toEqual(['DT', 'DD']);
      expect(group.querySelector('dt svg')).toHaveAttribute('aria-hidden', 'true');
      expect(within(group as HTMLElement).getByRole('term')).not.toHaveTextContent(/^\s*$/);
      expect(within(group as HTMLElement).getByRole('definition')).not.toHaveTextContent(/^\s*$/);
    }
    expect(within(facts).getAllByRole('term').length).toBe(groups.length);
    expect(within(facts).getAllByRole('definition').length).toBe(groups.length);
  });
});
