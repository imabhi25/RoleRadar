import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SourceStatusNote } from '../src/components/SourceStatusNote';
import { apiClient, type SourceStatus } from '../src/api/client';

const source = (over: Partial<SourceStatus>): SourceStatus => ({
  source_name: 'lever', status: 'healthy', companies_tracked: 6, companies_ok: 6, companies_degraded: 0,
  active_jobs: 10, last_success_at: '2026-11-25T14:00:00Z', last_attempt_at: '2026-11-25T14:00:00Z', ...over,
});

describe('per-source refresh status', () => {
  beforeEach(() => { vi.setSystemTime(new Date('2026-11-25T15:00:00Z')); });
  afterEach(() => { vi.useRealTimers(); });

  it('shows the latest successful refresh and names failed employer sources', async () => {
    vi.spyOn(apiClient, 'getSourceStatus').mockResolvedValue([
      source({}),
      source({ source_name: 'workday', status: 'degraded', companies_degraded: 2, last_success_at: '2026-11-25T12:00:00Z' }),
    ]);
    render(<SourceStatusNote />);
    expect(await screen.findByTestId('source-degraded')).toHaveTextContent(/2 employers could not be fully refreshed.*workday/);
    expect(screen.getByRole('time')).toHaveAttribute('datetime', '2026-11-25T14:00:00.000Z');
    expect(screen.queryByText(/last 12 hours/)).not.toBeInTheDocument();
  });

  it('flags a source after 12 hours without a success even if its last attempt passed', async () => {
    vi.spyOn(apiClient, 'getSourceStatus').mockResolvedValue([
      source({}),
      source({ source_name: 'shopify', last_success_at: '2026-11-24T20:00:00Z' }),
      source({ source_name: 'greenhouse', last_success_at: null }),
    ]);
    render(<SourceStatusNote />);
    expect(await screen.findByText('No successful refresh in the last 12 hours for shopify, greenhouse.')).toBeInTheDocument();
    expect(screen.queryByTestId('source-degraded')).not.toBeInTheDocument();
  });

  it('shows when no refresh has been recorded or the status endpoint is unavailable', async () => {
    const getStatus = vi.spyOn(apiClient, 'getSourceStatus').mockResolvedValue([]);
    const { rerender } = render(<SourceStatusNote />);
    expect(await screen.findByText('No successful source refresh recorded yet.')).toBeInTheDocument();
    getStatus.mockRejectedValue(new Error('500'));
    rerender(<SourceStatusNote key="again" />);
    expect(await screen.findByText('Source refresh status unavailable.')).toBeInTheDocument();
  });
});
