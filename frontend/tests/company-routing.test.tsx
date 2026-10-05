import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../src/App';
import { apiClient } from '../src/api/client';
import { parseAppRoute } from '../src/utils/appRoute';

vi.mock('../src/components/JobExplorer', () => ({ JobExplorer: () => <p>Job list ready</p> }));
vi.mock('../src/components/CompanyPageView', () => ({
  default: ({ initialCompany }: { initialCompany: string | null }) => <h1>{initialCompany ?? 'Hiring companies'}</h1>,
}));

beforeEach(() => {
  vi.stubEnv('DEV', false);
  vi.spyOn(apiClient, 'getOverview').mockResolvedValue({ total_postings: 0, total_companies: 0, total_locations: 0, total_skills: 0 });
});

describe('company routes', () => {
  it.each(['/company/%ZZ', '/company/%E0%A4%A', '/company/%'])('recovers from an invalid initial link: %s', async (path) => {
    window.history.replaceState(null, '', path);
    render(<App />);
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    expect(document.title).toBe('Page not found — RoleRadar');
    await userEvent.click(screen.getByRole('button', { name: 'Return to jobs' }));
    expect(screen.getByText('Job list ready')).toBeVisible();
    expect(window.location.pathname).toBe('/jobs');
  });

  it('handles malformed history entries and can then open a valid company', async () => {
    window.history.replaceState(null, '', '/company/TD');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'TD' })).toBeInTheDocument();

    for (const path of ['/company/%ZZ', '/company/%E0%A4%A']) {
      act(() => {
        window.history.pushState(null, '', path);
        window.dispatchEvent(new PopStateEvent('popstate'));
      });
      expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    }

    act(() => {
      window.history.pushState(null, '', '/company/Caf%C3%A9%20%26%20Co');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(await screen.findByRole('heading', { name: 'Café & Co' })).toBeInTheDocument();
    expect(document.title).toBe('Café & Co — Company Profile & Jobs — RoleRadar');
  });

  it('preserves valid encoded company names and legacy query links', () => {
    expect(parseAppRoute('/company/Braze%20%25', '')).toEqual({ view: 'company', company: 'Braze %' });
    expect(parseAppRoute('/company', '?company=Warner%20Bros.')).toEqual({ view: 'company', company: 'Warner Bros.' });
    expect(parseAppRoute('/company/', '')).toEqual({ view: 'company', company: null });
    expect(parseAppRoute('/jobs', '?q=%ZZ')).toEqual({ view: 'jobs', company: null });
  });
});
