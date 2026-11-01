import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { JobCard } from '../src/components/JobCard';
import { CompanyPageView } from '../src/components/CompanyPageView';
import { apiClient, type JobSummary, type CompanyInfo } from '../src/api/client';
import jobPageHandler from '../api/job-page.mjs';

const mockJob: JobSummary = {
  job_id: 'workday:td.wd3/TD_Bank_Careers/Software-Engineer-II_R_1516370',
  title: 'Software Engineer II',
  company: 'TD Bank',
  location: 'Toronto, Ontario, Canada',
  country: 'Canada',
  workplace_type: 'hybrid',
  role_type: 'full_time',
  posted_at: '2026-11-01T00:00:00Z',
  posted_at_precision: 'date',
  locations: [{ country: 'Canada', location: 'Toronto, Ontario, Canada' }]
};

describe('JobCard crawlable links and interactions', () => {
  it('renders a crawlable anchor tag with properly encoded href while maintaining button accessibility', () => {
    const onClick = vi.fn();
    render(<JobCard job={mockJob} onClick={onClick} />);

    const control = screen.getByRole('button', {
      name: /View details for Software Engineer II at TD Bank/i
    });

    expect(control).toBeDefined();
    expect(control.tagName).toBe('A');
    expect(control.getAttribute('href')).toBe(
      '/jobs/workday%3Atd.wd3%2FTD_Bank_Careers%2FSoftware-Engineer-II_R_1516370'
    );
  });

  it('intercepts standard primary click to preserve in-app split-view and mobile overlay', () => {
    const onClick = vi.fn();
    render(<JobCard job={mockJob} onClick={onClick} />);

    const control = screen.getByRole('button', {
      name: /View details for Software Engineer II at TD Bank/i
    });

    // fireEvent.click returns false if preventDefault() was called
    const allowed = fireEvent.click(control, { button: 0 });

    expect(allowed).toBe(false);
    expect(onClick).toHaveBeenCalledWith(mockJob.job_id);
  });

  it('allows native open-in-new-tab on Cmd+click (metaKey)', () => {
    const onClick = vi.fn();
    render(<JobCard job={mockJob} onClick={onClick} />);

    const control = screen.getByRole('button', {
      name: /View details for Software Engineer II at TD Bank/i
    });

    const allowed = fireEvent.click(control, { metaKey: true, button: 0 });

    // Browser default behavior is NOT prevented so new tab opens
    expect(allowed).toBe(true);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('allows native open-in-new-tab on Ctrl+click (ctrlKey)', () => {
    const onClick = vi.fn();
    render(<JobCard job={mockJob} onClick={onClick} />);

    const control = screen.getByRole('button', {
      name: /View details for Software Engineer II at TD Bank/i
    });

    const allowed = fireEvent.click(control, { ctrlKey: true, button: 0 });

    expect(allowed).toBe(true);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('allows native open-in-new-window on Shift+click', () => {
    const onClick = vi.fn();
    render(<JobCard job={mockJob} onClick={onClick} />);

    const control = screen.getByRole('button', {
      name: /View details for Software Engineer II at TD Bank/i
    });

    const allowed = fireEvent.click(control, { shiftKey: true, button: 0 });

    expect(allowed).toBe(true);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('supports Space and Enter key activation like a native button', () => {
    const onClick = vi.fn();
    render(<JobCard job={mockJob} onClick={onClick} />);

    const control = screen.getByRole('button', {
      name: /View details for Software Engineer II at TD Bank/i
    });

    fireEvent.keyDown(control, { key: ' ' });
    expect(onClick).toHaveBeenCalledWith(mockJob.job_id);

    fireEvent.keyDown(control, { key: 'Enter' });
    expect(onClick).toHaveBeenCalledTimes(2);
  });
});

describe('CompanyPageView crawlable links', () => {
  const mockCompanyInfo: CompanyInfo[] = [
    {
      name: 'TD Bank',
      logo_url: '/logos/td.svg',
      logo_source_url: null,
      logo_status: 'verified',
      website_url: 'https://td.com',
      active_jobs_count: 1
    }
  ];

  beforeEach(() => {
    vi.spyOn(apiClient, 'getCompanies').mockResolvedValue(mockCompanyInfo);
    vi.spyOn(apiClient, 'getJobs').mockResolvedValue({
      jobs: [mockJob],
      total: 1,
      limit: 50,
      offset: 0
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders company job titles as crawlable anchor links with open-in-new-tab support', async () => {
    const onSelectJob = vi.fn();

    render(
      <CompanyPageView
        initialCompany="TD Bank"
        onBackToJobs={() => {}}
        onSelectJob={onSelectJob}
      />
    );

    // Wait for the company jobs to load
    const link = await waitFor(() => {
      const el = screen.getByRole('link', { name: /Software Engineer II/i });
      expect(el).toBeDefined();
      return el;
    });

    expect(link.tagName).toBe('A');
    expect(link.getAttribute('href')).toBe(
      '/jobs/workday%3Atd.wd3%2FTD_Bank_Careers%2FSoftware-Engineer-II_R_1516370'
    );

    // Primary click triggers in-app selection
    const normalAllowed = fireEvent.click(link, { button: 0 });
    expect(normalAllowed).toBe(false);
    expect(onSelectJob).toHaveBeenCalledWith(mockJob.job_id);

    // Meta+click allows native new tab
    const metaAllowed = fireEvent.click(link, { metaKey: true, button: 0 });
    expect(metaAllowed).toBe(true);
  });
});

describe('Unavailable / closed jobs in job-page serverless handler', () => {
  it('returns HTTP 404 and noindex for inactive or closed jobs', async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn(async () => ({
      status: 200,
      json: async () => ({
        ...mockJob,
        is_active: false,
        status: 'closed'
      })
    }));

    try {
      const req = {
        headers: { host: 'roleradar.com', 'x-forwarded-proto': 'https' },
        url: '/jobs/closed-job'
      };

      const headers: Record<string, string> = {};
      let responseBody = '';
      const res = {
        statusCode: 0,
        setHeader(name: string, val: string) {
          headers[name] = val;
        },
        end(chunk: string) {
          responseBody = chunk;
        }
      };

      await jobPageHandler(req, res);

      expect(res.statusCode).toBe(404);
      expect(headers['X-Robots-Tag']).toBe('noindex, nofollow');
      expect(responseBody).toContain('Job No Longer Available');
      // Crucial: Must NOT emit JobPosting structured data
      expect(responseBody).not.toContain('application/ld+json');
      expect(responseBody).not.toContain('schema.org');
    } finally {
      global.fetch = originalFetch;
    }
  });

  it('returns HTTP 404 and noindex when upstream returns 404 or 410', async () => {
    const originalFetch = global.fetch;
    global.fetch = vi.fn(async () => ({
      status: 404,
      json: async () => ({ detail: 'Not found' })
    }));

    try {
      const req = {
        headers: { host: 'roleradar.com', 'x-forwarded-proto': 'https' },
        url: '/jobs/nonexistent'
      };

      const headers: Record<string, string> = {};
      let responseBody = '';
      const res = {
        statusCode: 0,
        setHeader(name: string, val: string) {
          headers[name] = val;
        },
        end(chunk: string) {
          responseBody = chunk;
        }
      };

      await jobPageHandler(req, res);

      expect(res.statusCode).toBe(404);
      expect(headers['X-Robots-Tag']).toBe('noindex, nofollow');
      expect(responseBody).toContain('Job No Longer Available');
      expect(responseBody).not.toContain('application/ld+json');
    } finally {
      global.fetch = originalFetch;
    }
  });
});
