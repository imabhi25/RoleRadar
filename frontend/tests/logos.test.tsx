import { describe, it, expect, vi, afterEach } from 'vitest';
import { readCss } from './cssTokens';
import { render, screen, fireEvent, within, waitFor, act } from '@testing-library/react';
import fs from 'node:fs';
import path from 'node:path';
import { CompanyLogo } from '../src/components/CompanyLogo';
import { JobCard } from '../src/components/JobCard';
import { JobDetailContent } from '../src/components/JobDetailContent';
import { apiClient, type JobDetail, type JobSummary } from '../src/api/client';
import { COMPANY_LOGOS, getCompanyFaviconUrl, getCompanyLogoSources, getCompanyLogoUrl, isDarkMonochromeLogo, normalizeCompanyName } from '../src/utils/companyLogos';

const root = path.resolve(__dirname, '..', '..');
const targets: { name: string }[] = JSON.parse(fs.readFileSync(path.join(root, 'config', 'target_companies.json'), 'utf-8'));

const summary: JobSummary = {
  job_id: 'x1', title: 'Software Engineer', company: 'RBC', location: 'Toronto, ON', country: 'Canada',
  workplace_type: 'hybrid', source_name: 'workday', skills: [],
};
const detail: JobDetail = { ...summary, description: 'About the role\nBuild', skills: [] };

const fallbackIn = (el: HTMLElement) => el.querySelector('.company-logo-fallback-icon');
const imgIn = (el: HTMLElement) => el.querySelector('img.company-logo-img') as HTMLImageElement | null;
// CompanyLogo resets its error flag in a mount effect. In a browser an image error can only arrive after that effect has run;
// in a test the effect may still be pending, so flush it before simulating the load failure.
const failImage = async (img: HTMLImageElement) => {
  await act(async () => {});
  fireEvent.error(img);
};

afterEach(() => vi.restoreAllMocks());

const failAllImages = async (container: HTMLElement) => {
  for (let attempts = 0; attempts < 5 && imgIn(container); attempts += 1) await failImage(imgIn(container)!);
};

describe('company logos', () => {
  it('advances through favicon, API, local logo, then generic without loops', async () => {
    const { container } = render(<CompanyLogo company="RBC" logoUrl="/api/company-logos/5" />);
    const expected = getCompanyLogoSources('RBC', '/api/company-logos/5');
    for (const source of expected) {
      expect(imgIn(container)!.getAttribute('src')).toMatch(source.startsWith('/') ? new RegExp(source+'$') : source);
      await failImage(imgIn(container)!);
    }
    expect(imgIn(container)).toBeNull();
    expect(fallbackIn(container)).not.toBeNull();
  });
  it('resets source failures when switching employers and never carries the old logo over', async () => {
    const { container, rerender } = render(<CompanyLogo company="Wealthsimple" />);
    await failImage(imgIn(container)!);
    expect(imgIn(container)).toHaveAttribute('src', expect.stringContaining('/logos/wealthsimple.svg'));
    rerender(<CompanyLogo company="Manulife" />);
    expect(imgIn(container)).toHaveAttribute('src', getCompanyFaviconUrl('Manulife'));
    expect(container.textContent).not.toContain('Wealthsimple');
  });

  it('every configured employer has an official-domain favicon and only verified stored fallback files', () => {
    const missing = targets
      .map((t) => t.name)
      .filter((name) => {
        // Braze's retired file was another employer's artwork; no replacement is asserted verified.
        if (normalizeCompanyName(name) === 'braze') return false;
        // Added before an official logo file was vendored: they use the official-domain favicon, then the generic icon.
        if (['instacart', 'affirm', 'dialpad', 'asana', 'twilio'].includes(normalizeCompanyName(name))) return false;
        const url = COMPANY_LOGOS[normalizeCompanyName(name)];
        return !url || !fs.existsSync(path.join(root, 'frontend', 'public', url.replace(/^\//, ''))) ;
      });
    expect(missing).toEqual([]);
    for (const target of targets) expect(getCompanyFaviconUrl(target.name)).toMatch(/^https:\/\/www\.google\.com\/s2\/favicons\?/);
  });

  it('never displays the retired Braze artwork, including an old API cache, when favicon loading fails', async () => {
    const { container } = render(<CompanyLogo company="Braze" logoUrl="/api/company-logos/75" />);
    expect(imgIn(container)).toHaveAttribute('src', getCompanyFaviconUrl('Braze'));
    await failImage(imgIn(container)!);
    expect(imgIn(container)).toBeNull();
    expect(fallbackIn(container)).not.toBeNull();
    expect(getCompanyLogoUrl('Braze', '/logos/braze.svg')).toBeNull();
    expect(fs.existsSync(path.join(root, 'frontend', 'public', 'logos', 'braze.svg'))).toBe(false);
  });

  it.each(['/logos/braze.svg', '/logos/braze.svg?v=1', '/api/company-logos/75', 'https://roleradar-api.example/api/company-logos/75'])('quarantines the rejected Braze fallback %s', (url) => {
    expect(getCompanyLogoSources('Braze, Inc.', url)).toEqual([getCompanyFaviconUrl('Braze')]);
  });

  it('accepts an independently sourced Braze replacement without affecting other employers', () => {
    expect(getCompanyLogoSources('Braze', 'https://www.braze.com/brand/replacement.png')).toEqual([
      getCompanyFaviconUrl('Braze'), 'https://www.braze.com/brand/replacement.png',
    ]);
    expect(getCompanyLogoUrl('RBC', '/api/company-logos/5')).toBe('/api/company-logos/5');
  });

  it('a malformed Braze API asset URL cannot crash logo lookup or render', async () => {
    const malformed = '/\\';
    expect(getCompanyLogoUrl('Braze', malformed)).toBeNull();
    expect(getCompanyLogoSources('Braze', malformed)).toEqual([getCompanyFaviconUrl('Braze')]);
    const { container } = render(<CompanyLogo company="Braze" logoUrl={malformed} />);
    await failImage(imgIn(container)!);
    expect(fallbackIn(container)).not.toBeNull();
  });

  it('uses the official-domain favicon before the stored logo', () => {
    const { container } = render(<CompanyLogo company="RBC" logoUrl="/api/company-logos/5" />);
    const img = imgIn(container)!;
    expect(img).toBeTruthy();
    expect(img.getAttribute('src')).toBe(getCompanyFaviconUrl('RBC'));
    expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
    // The generic icon holds the box until the picture has loaded; then it steps aside.
    expect(fallbackIn(container)).not.toBeNull();
    fireEvent.load(img);
    expect(fallbackIn(container)).toBeNull();
  });

  it('falls back to the honest company icon when the logo is missing or broken', async () => {
    const missing = render(<CompanyLogo company="Totally Unknown Corp" />);
    expect(imgIn(missing.container)).toBeNull();
    expect(fallbackIn(missing.container)).not.toBeNull();
    missing.unmount();

    const broken = render(<CompanyLogo company="RBC" logoUrl="/api/company-logos/999" />);
    await failAllImages(broken.container);
    // onError sets React state; wait for the render that swaps the <img> for the fallback
    await waitFor(() => {
      expect(imgIn(broken.container)).toBeNull();
      expect(fallbackIn(broken.container)).not.toBeNull();
    });
    expect(screen.getByRole('img', { name: 'RBC logo' })).toBeInTheDocument();
  });

  it('job card and detail header resolve and render the same logo, and fall back the same way', async () => {
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...detail, company_logo_url: '/logos/rbc.svg' });
    const card = render(<JobCard job={{ ...summary, company_logo_url: '/logos/rbc.svg' }} onClick={() => {}} />);
    const cardSrc = imgIn(card.container)!.getAttribute('src');
    card.unmount();

    const pane = render(<JobDetailContent jobId="x1" variant="pane" onClose={() => {}} />);
    const header = await waitFor(() => {
      const el = pane.container.querySelector('.jd-company') as HTMLElement;
      expect(imgIn(el)).toBeTruthy();
      return el;
    });
    expect(imgIn(header)!.getAttribute('src')).toBe(cardSrc);
    // the company name sits beside the logo
    expect(within(header).getByText('RBC')).toBeInTheDocument();
    await failAllImages(header);
    await waitFor(() => {
      const row = pane.container.querySelector('.jd-company') as HTMLElement;
      expect(imgIn(row)).toBeNull();
      expect(fallbackIn(row)).not.toBeNull();
    });
    pane.unmount();

    const brokenCard = render(<JobCard job={{ ...summary, company_logo_url: '/logos/missing.svg' }} onClick={() => {}} />);
    await failAllImages(brokenCard.container);
    await waitFor(() => {
      expect(imgIn(brokenCard.container)).toBeNull();
      expect(fallbackIn(brokenCard.container)).not.toBeNull();
    });
  });

  it('detail header and card use the fallback when no logo exists for the company', async () => {
    const unknown = { ...summary, company: 'Nowhere Inc', company_logo_url: null };
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({ ...detail, company: 'Nowhere Inc', company_logo_url: null });
    const card = render(<JobCard job={unknown} onClick={() => {}} />);
    expect(fallbackIn(card.container)).not.toBeNull();
    card.unmount();
    const pane = render(<JobDetailContent jobId="x1" variant="pane" onClose={() => {}} />);
    const header = await waitFor(() => {
      const el = pane.container.querySelector('.jd-company') as HTMLElement;
      expect(el).toBeTruthy();
      return el;
    });
    expect(fallbackIn(header)).not.toBeNull();
  });

  it('stored dark marks retain their backplate when favicon loading fails', async () => {
    for (const company of ['Amazon', 'Autodesk', 'NVIDIA', 'Manulife', 'Geotab', 'Sun Life']) {
      expect(isDarkMonochromeLogo(company)).toBe(true);
      const { container, unmount } = render(<CompanyLogo company={company} />);
      // marks are only "dark" when an image is shown
      unmount();
      const shown = render(<CompanyLogo company={company} logoUrl={getCompanyLogoUrl(company)} />);
      await failImage(imgIn(shown.container)!); // Favicon failure reveals the stored monochrome mark.
      expect(shown.container.querySelector('.company-logo-container')).toHaveClass('logo-dark-mark');
      shown.unmount();
      expect(container).toBeTruthy();
    }
    const css = readCss(path.join(root, 'frontend', 'src', 'index.css'));
    const rule = css.match(/\[data-theme="dark"\] \.company-logo-container\.logo-dark-mark \.company-logo-img,[^{]*\{([^}]*)\}/);
    expect(rule?.[1]).toMatch(/background-color:\s*#ffffff/);
    // multicolor marks are never inverted or filtered
    expect(css).not.toMatch(/\.company-logo-img\s*\{[^}]*(invert|brightness)/);
  });
});
