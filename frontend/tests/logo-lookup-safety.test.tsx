import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  getCompanyLogoUrl, getCompanyFaviconUrl, getCompanyLogoSources, getCompanyWebsite, isDarkMonochromeLogo, isLightMonochromeLogo, normalizeCompanyName,
} from '../src/utils/companyLogos';
import { getCompanyLinkedIn, getCompanyProfile, getCompanySocials } from '../src/utils/companyProfiles';
import { CompanyLogo } from '../src/components/CompanyLogo';

const PROTOTYPE_NAMES = [
  'Constructor', 'constructor', 'toString', 'valueOf', 'hasOwnProperty', '__proto__', '__defineGetter__',
  'isPrototypeOf', 'propertyIsEnumerable', 'toLocaleString', 'prototype',
];

describe('company lookups ignore Object.prototype members', () => {
  it.each(PROTOTYPE_NAMES)('%s resolves to nothing (not a function, not a crash)', (name) => {
    expect(getCompanyLogoUrl(name)).toBeNull();
    expect(getCompanyFaviconUrl(name)).toBeNull();
    expect(getCompanyWebsite(name)).toBeNull();
    expect(getCompanyLinkedIn(name)).toBeNull();
    expect(getCompanySocials(name)).toEqual({ x: null, github: null, youtube: null });
    const profile = getCompanyProfile(name);
    expect(profile.website).toBeNull();
    expect(profile.linkedin).toBeNull();
    expect(isDarkMonochromeLogo(name)).toBe(false);
    expect(isLightMonochromeLogo(name)).toBe(false);
    expect(typeof normalizeCompanyName(name)).toBe('string');
  });

  it.each(PROTOTYPE_NAMES)('%s renders the honest generic icon instead of blanking the app', (name) => {
    render(<CompanyLogo company={name} />);
    expect(screen.getByRole('img', { name: `${name} logo` })).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
  });

  it('non-string inputs are tolerated', () => {
    expect(getCompanyLogoUrl(undefined as unknown as string)).toBeNull();
    expect(getCompanyLogoUrl(42 as unknown as string)).toBeNull();
    expect(getCompanyWebsite(null)).toBeNull();
  });

  it('real companies still resolve', () => {
    expect(getCompanyWebsite('Stripe')?.url).toMatch(/^https:\/\//);
  });
});

describe('official-domain favicon sourcing', () => {
  it.each(['Google', 'Manulife', 'Wealthsimple'])('%s uses its official domain even with another supplied website', (company) => {
    const url = new URL(getCompanyFaviconUrl(company, 'https://other.example/')!);
    expect(url.hostname).toBe('www.google.com');
    expect(url.searchParams.get('domain')).toBe(getCompanyWebsite(company)?.domain);
    expect(url.searchParams.get('sz')).toBe('128');
  });
  it('supports a future employer with an explicit official website, without guessing its name', () => {
    expect(getCompanyFaviconUrl('Future Employer')).toBeNull();
    expect(getCompanyFaviconUrl('Future Employer', 'https://www.future-employer.example/about?x=1')).toBe('https://www.google.com/s2/favicons?domain=www.future-employer.example&sz=128');
  });
  it.each(['javascript:alert(1)', '//evil.example/logo', 'https://127.0.0.1/', 'https://user:pass@company.example/', 'https://localhost/', 'https://company.internal/', 'https://company.example:8443/', 'https://jobs.lever.co/employer', 'https://employer.myworkdayjobs.com/'])('does not treat %s as an official company domain', (website) => {
    expect(getCompanyFaviconUrl('Future Employer', website)).toBeNull();
  });
  it('deduplicates the fallback when the API supplies the same stored logo', () => {
    expect(getCompanyLogoSources('Wealthsimple', '/logos/wealthsimple.svg')).toEqual([getCompanyFaviconUrl('Wealthsimple'), '/logos/wealthsimple.svg']);
  });
});

describe('API-supplied logo URLs are validated', () => {
  it.each([
    [{ toString: () => 'https://x' }, null],
    [123, null],
    ['javascript:alert(1)', null],
    ['data:text/html,<script>', null],
    ['//evil.example/logo.png', null],
    ['', null],
    ['https://cdn.example.com/logo.png', 'https://cdn.example.com/logo.png'],
    ['/logos/acme.svg', '/logos/acme.svg'],
  ])('%j', (input, expected) => {
    expect(getCompanyLogoUrl('No Such Employer', input as unknown as string)).toBe(expected);
  });
});

describe('dim logos get a backplate in dark mode', () => {
  it('Datadog (low-luminance purple) is treated as a dark mark', () => {
    expect(isDarkMonochromeLogo('Datadog')).toBe(true);
  });
});
