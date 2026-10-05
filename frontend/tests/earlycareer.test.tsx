import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { parseUrlSearch, serializeUrlSearch } from '../src/utils/urlState';
import { apiClient } from '../src/api/client';
import { formatRoleType } from '../src/utils/formatters';
import { JobFilters, type SelectedFilters } from '../src/components/JobFilters';

const base: SelectedFilters = {
  sort: 'recommended', search: '', country: [], company: '', skill: '',
  workplace_type: [], role_type: [], term: [], freshness: 'recent',
};

afterEach(() => vi.restoreAllMocks());

describe('Canada-first early-career filters', () => {
  it('defaults to the recommended (Canada-first) sort and keeps the URL clean', () => {
    expect(parseUrlSearch('').filters.sort).toBe('recommended');
    expect(serializeUrlSearch(base, 1)).toBe('');
    expect(serializeUrlSearch({ ...base, sort: 'newest' }, 1)).toBe('?sort=newest');
    expect(parseUrlSearch('?sort=newest').filters.sort).toBe('newest');
  });

  it('round-trips entry-level roles and academic terms, dropping invalid values', () => {
    const parsed = parseUrlSearch('?role=entry-level,co-op,bogus&term=Summer,winter,spring,summer&country=canada');
    expect(parsed.filters.role_type).toEqual(['entry_level', 'co_op']);
    expect(parsed.filters.term).toEqual(['summer', 'winter']);
    expect(parsed.filters.country).toEqual(['Canada']);
    expect(parseUrlSearch(serializeUrlSearch(parsed.filters, 1))).toEqual(parsed);
  });

  it('sends term and role filters to the API', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ total: 0, limit: 25, offset: 0, jobs: [] }), { status: 200 })
    );
    await apiClient.getJobs({ sort: 'recommended', term: ['summer', 'fall'], role_type: ['entry_level'], country: ['Canada'] });
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain('term=summer%2Cfall');
    expect(url).toContain('role_type=entry_level');
    expect(url).toContain('country=Canada');
    expect(url).toContain('sort=recommended');
  });

  it('formats the entry-level role type', () => {
    expect(formatRoleType('entry_level')).toBe('Entry Level');
  });

  it('keeps early-career experience separate from employment type', async () => {
    const onFilterChange = vi.fn();
    render(<JobFilters filterOptions={{ countries: ['Canada'], companies: [], skills: [], workplace_types: [] }} selectedFilters={base} onFilterChange={onFilterChange} onReset={() => {}} />);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Experience' }), 'entry');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...base, experience_level: ['entry'] }, true);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Job type' }), 'internship');
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...base, role_type: ['internship'], term: [] }, true);
  });
});
