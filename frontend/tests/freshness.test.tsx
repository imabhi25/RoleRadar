import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { parseUrlSearch, serializeUrlSearch } from '../src/utils/urlState';
import { apiClient } from '../src/api/client';
import { JobFilters, type SelectedFilters } from '../src/components/JobFilters';

const base: SelectedFilters = {
  sort: 'recommended', search: '', country: [], company: '', skill: '',
  workplace_type: [], role_type: [], term: [], freshness: 'recent',
};

afterEach(() => vi.restoreAllMocks());

describe('30-day public window in the UI', () => {
  it('defaults to the recent window and never turns legacy/unknown URL values into an unbounded view', () => {
    for (const search of ['', '?date=all', '?date=garbage', '?date=recent']) {
      expect(parseUrlSearch(search).filters.freshness).toBe('recent');
    }
    expect(serializeUrlSearch(base, 1)).toBe('');
  });

  it('round-trips the narrower windows', () => {
    for (const [param, value] of [['today', 'today'], ['week', 'week'], ['7d', 'week'], ['14d', '14d'], ['30d', 'recent']] as const) {
      const parsed = parseUrlSearch(`?date=${param}`);
      expect(parsed.filters.freshness).toBe(value);
      expect(parseUrlSearch(serializeUrlSearch(parsed.filters, 1))).toEqual(parsed);
    }
    // the old 30-day option is now the default window itself, so its link stays valid and the URL stays clean
    expect(serializeUrlSearch(parseUrlSearch('?date=30d').filters, 1)).toBe('');
  });

  it('only sends a freshness parameter for the narrower windows, never "all"', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async () =>
      new Response(JSON.stringify({ total: 0, limit: 25, offset: 0, jobs: [] }), { status: 200 }));
    await apiClient.getJobs({ freshness: 'recent' });
    await apiClient.getJobs({ freshness: '14d' });
    await apiClient.getJobs({});
    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls[0]).not.toContain('freshness');
    expect(urls[1]).toContain('freshness=14d');
    expect(urls[2]).not.toContain('freshness');
    expect(urls.join(' ')).not.toContain('freshness=all');
  });

  it('offers Today, 7 and 14 days and the 30-day default, and selecting one updates the filter', async () => {
    const onFilterChange = vi.fn();
    render(
      <JobFilters
        filterOptions={{ countries: [], companies: [], skills: [], workplace_types: [], role_types: [] }}
        selectedFilters={base}
        onFilterChange={onFilterChange}
        onReset={() => {}}
      />
    );
    const user = userEvent.setup();
    const list = screen.getByRole('combobox', { name: 'Date posted' });
    expect(within(list).getAllByRole('option').map((o) => o.textContent)).toEqual(['Date posted', 'Today (UTC)', 'Last 7 days', 'Last 14 days']);
    expect(list).toHaveValue('recent');
    await user.selectOptions(list, '14d');
    expect(onFilterChange).toHaveBeenCalledWith({ ...base, freshness: '14d' }, true);
  });
});
