import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { JobFilters, type SelectedFilters } from '../src/components/JobFilters';

const base: SelectedFilters = {
  sort: 'recommended', search: '', country: [], company: '', skill: '',
  workplace_type: [], role_type: [], term: [], freshness: 'recent',
};
const options = { countries: ['Canada'], companies: [], skills: [], workplace_types: [] };

afterEach(() => vi.restoreAllMocks());

function setPointer(fine: boolean) {
  window.matchMedia = vi.fn((query: string) => ({
    matches: fine && query.includes('pointer: fine'), media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

describe('filter dropdowns on a wide screen with a mouse', () => {
  it('open a menu that lists the choices and apply the picked one', async () => {
    setPointer(true);
    const onFilterChange = vi.fn();
    render(<JobFilters filterOptions={options} selectedFilters={base} onFilterChange={onFilterChange} onReset={() => {}} />);
    expect(screen.queryByRole('combobox', { name: 'Experience' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Experience' }));
    const list = screen.getByRole('listbox', { name: 'Experience' });
    expect(within(list).getAllByRole('option').map((option) => option.textContent)).toEqual([
      '✓Experience', 'Entry Level / New Grad', 'Mid Level', 'Senior / Staff / Lead',
    ]);
    await userEvent.click(within(list).getByRole('option', { name: 'Mid Level' }));
    expect(onFilterChange).toHaveBeenLastCalledWith({ ...base, experience_level: ['mid'] }, true);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('shows the chosen value on the control', () => {
    setPointer(true);
    render(<JobFilters filterOptions={options} selectedFilters={{ ...base, experience_level: ['senior'] }} onFilterChange={() => {}} onReset={() => {}} />);
    expect(screen.getByRole('button', { name: 'Experience: Senior / Staff / Lead' })).toBeInTheDocument();
  });

  it('keep the native select without a mouse', () => {
    setPointer(false);
    render(<JobFilters filterOptions={options} selectedFilters={base} onFilterChange={() => {}} onReset={() => {}} />);
    expect(screen.getByRole('combobox', { name: 'Experience' })).toBeInTheDocument();
  });
});
