import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { SourceStatusNote } from '../src/components/SourceStatusNote';
import { apiClient, type SourceStatus } from '../src/api/client';

const source = (over: Partial<SourceStatus>): SourceStatus => ({
  source_name: 'lever', status: 'healthy', companies_tracked: 6, companies_ok: 6, companies_degraded: 0,
  active_jobs: 10, last_success_at: '2026-09-30T12:00:00Z', last_attempt_at: '2026-09-30T12:00:00Z', ...over,
});

describe('per-source refresh status', () => {
  it('names degraded sources instead of implying every employer refreshed', async () => {
    vi.spyOn(apiClient, 'getSourceStatus').mockResolvedValue([source({}), source({ source_name: 'workday', status: 'degraded', companies_degraded: 2 })]);
    render(<SourceStatusNote />);
    expect(await screen.findByTestId('source-degraded')).toHaveTextContent(/2 employers could not be refreshed.*workday/);
  });
  it('renders nothing when all healthy or when the status endpoint fails', async () => {
    const spy = vi.spyOn(apiClient, 'getSourceStatus').mockResolvedValue([source({})]);
    const { container, rerender } = render(<SourceStatusNote />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
    spy.mockRejectedValue(new Error('500'));
    rerender(<SourceStatusNote key="again" />);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(container).toBeEmptyDOMElement();
  });
});
