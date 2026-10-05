import { describe, expect, it, vi, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';
import { COMPANY_DOMAIN_MAP } from '../src/utils/companyLogos';
import { getCompanyProfile } from '../src/utils/companyProfiles';
import { useCompanyBackground } from '../src/hooks/useCompanyBackground';
import { extractSiteBackground, isPublicAddress, lookupCompanyBackground, officialUrl } from '../api/company-background.mjs';

const targets = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../config/target_companies.json'), 'utf8')) as { name: string }[];
afterEach(() => vi.unstubAllGlobals());

describe('company background coverage independent of job descriptions', () => {
  it.each(targets.map(({ name }) => name))('%s has reusable company background before any job loads', (name) => {
    const profile = getCompanyProfile(name);
    expect(profile.description?.length).toBeGreaterThan(40);
    expect(profile.tagline?.length).toBeGreaterThan(5);
    expect(profile.sourceUrl).toMatch(/^https:\/\//);
  });
  it('covers every known employer alias and broad-feed company', () => {
    for (const name of Object.keys(COMPANY_DOMAIN_MAP)) expect(getCompanyProfile(name).description, name).toBeTruthy();
  });
  it('does not fabricate headcounts, founding dates, or employee benefits for Spotify', () => {
    const profile = getCompanyProfile('Spotify');
    expect(profile.description).toMatch(/music, podcasts, and audiobooks/);
    expect(profile.size).toBeUndefined();
    expect(profile.founded).toBeUndefined();
    expect(profile.benefits).toBeUndefined();
  });
});

describe('official website enrichment for new employers', () => {
  it('reads an official site description, regardless of meta attribute order or quote style', async () => {
    const loadPage = vi.fn().mockResolvedValue({ html: '<meta content="NewCo builds scheduling software &amp; collaboration tools." name="description">', sourceUrl: 'https://newco.example/' });
    expect(await lookupCompanyBackground('NewCo', 'https://newco.example/careers?x=1', loadPage)).toEqual({ description: 'NewCo builds scheduling software & collaboration tools.', sourceUrl: 'https://newco.example/' });
    expect(loadPage.mock.calls[0][0].href).toBe('https://newco.example/');
    expect(extractSiteBackground("<meta property='og:description' content='Software for planning and collaboration.'>")).toBe('Software for planning and collaboration.');
  });
  it('rejects credentials, IP literals, localhost and non-HTTPS destinations', () => {
    for (const url of ['http://example.com', 'https://127.0.0.1', 'https://[::1]', 'https://localhost', 'https://x.internal', 'https://user:pass@example.com', 'https://example.com:8443']) expect(() => officialUrl(url), url).toThrow();
  });
  it('rejects private DNS results, including IPv4-mapped IPv6 and link-local addresses', () => {
    for (const value of ['127.0.0.1', '10.1.2.3', '172.16.0.1', '192.168.0.1', '169.254.169.254', '100.64.0.1', '::1', '::ffff:127.0.0.1', 'fe80::1', 'fc00::1']) expect(isPublicAddress(value), value).toBe(false);
    expect(isPublicAddress('8.8.8.8')).toBe(true);
    expect(isPublicAddress('2606:4700:4700::1111')).toBe(true);
  });
  it('does not invent text from a page that provides no descriptive content', async () => {
    expect(await lookupCompanyBackground('NewCo', 'https://newco.example', async () => ({ html: '<title>NewCo</title>', sourceUrl: 'https://newco.example/' }))).toBeNull();
  });
  it('loads future-company background independently and reuses it for subsequent postings', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ description: 'NewCo develops planning and collaboration software.', sourceUrl: 'https://future-company.example/' }), { headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetcher);
    const base = getCompanyProfile('Future Company', 'https://future-company.example/');
    const view = renderHook(() => useCompanyBackground(base));
    await waitFor(() => expect(view.result.current?.description).toMatch(/planning and collaboration/));
    view.unmount();
    const next = renderHook(() => useCompanyBackground(base));
    expect(next.result.current?.description).toMatch(/planning and collaboration/);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('never applies a previous company’s late response to the next selected employer', async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>((done) => { resolve = done; })));
    const first = getCompanyProfile('Late Company', 'https://late-company.example/');
    const next = getCompanyProfile('Spotify');
    const view = renderHook(({ base }) => useCompanyBackground(base), { initialProps: { base: first } });
    view.rerender({ base: next });
    await act(async () => resolve(new Response(JSON.stringify({ description: 'Old company makes other products.', sourceUrl: 'https://late-company.example/' }), { headers: { 'Content-Type': 'application/json' } })));
    expect(view.result.current?.name).toBe('Spotify');
    expect(view.result.current?.description).not.toMatch(/Old company/);
  });
});
