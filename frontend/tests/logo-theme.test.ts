import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { COMPANY_LOGOS, isDarkMonochromeLogo } from '../src/utils/companyLogos';

describe('theme-independent logos', () => {
  it('gives dark-mark logos a light backplate in dark mode', () => {
    for (const name of ['Wealthsimple', 'Flexport', 'Sentry']) expect(isDarkMonochromeLogo(name)).toBe(true);
  });

  it('Wealthsimple resolves to a fixed-colour SVG that does not follow the OS theme', () => {
    const url = COMPANY_LOGOS['wealthsimple'];
    expect(url).toBe('/logos/wealthsimple.svg');
    const svg = readFileSync(`public${url}`, 'utf8');
    expect(svg).not.toMatch(/prefers-color-scheme|<style/);
    expect(svg).toMatch(/fill="#1c1b1b"/);
  });
});

describe('RBC brand mark', () => {
  it('serves the current blue/gold shield, not the retired green wordmark', () => {
    expect(COMPANY_LOGOS['rbc']).toBe('/logos/rbc.svg');
    const svg = readFileSync('public/logos/rbc.svg', 'utf8');
    expect(svg).toContain('#0059b3');
    expect(svg).toContain('#ffdf01');
    expect(svg).not.toContain('#22821e');
  });
});
