import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { parseAppRoute } from '../src/utils/appRoute';

const ORIGIN = 'https://roleradar-jobs.vercel.app';
const VERIFICATION_FILE = 'google907a2d17d4884ed2.html';
const frontend = path.resolve(__dirname, '..');
const publicFile = (name: string) => fs.readFileSync(path.join(frontend, 'public', name), 'utf-8');
const vercel = JSON.parse(fs.readFileSync(path.join(frontend, 'vercel.json'), 'utf-8'));
const shell = vercel.rewrites.find((r: { destination: string }) => r.destination === '/index.html');
const rewrittenToShell = (pathname: string) => new RegExp(`^${shell.source}$`).test(pathname);

describe('Google Search Console ownership file', () => {
  it('ships the exact token Search Console verified', () => {
    expect(publicFile(VERIFICATION_FILE).trim()).toBe(`google-site-verification: ${VERIFICATION_FILE}`);
  });
  it('is served as itself, never replaced by the app shell', () => {
    expect(rewrittenToShell(`/${VERIFICATION_FILE}`)).toBe(false);
    // Only that exact file is exempt; other google*.html addresses still get the app (and its not-found page).
    expect(rewrittenToShell('/google0000000000000000.html')).toBe(true);
    expect(rewrittenToShell(`/${VERIFICATION_FILE}.bak`)).toBe(true);
  });
});

describe('sitemap.xml', () => {
  const xml = publicFile('sitemap.xml');
  const locs = [...xml.matchAll(/<loc>([^<]*)<\/loc>/g)].map((m) => m[1]);

  it('is a sitemaps.org urlset with one <loc> per <url>', () => {
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(xml).toMatch(/<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/);
    expect((xml.match(/<url>/g) ?? []).length).toBe(locs.length);
    expect(locs.length).toBeGreaterThanOrEqual(1);
  });
  it('lists only the canonical public pages, each once', () => {
    expect(locs).toEqual([`${ORIGIN}/jobs`, `${ORIGIN}/stats`, `${ORIGIN}/company`]);
  });
  it('every URL is an absolute production URL that the app renders as a real page', () => {
    for (const loc of locs) {
      const url = new URL(loc);
      expect(url.origin).toBe(ORIGIN);
      // No query-string views (filters, single jobs) and no fragments: those are states of /jobs, not pages.
      expect(url.search).toBe('');
      expect(url.hash).toBe('');
      // Not the dev-only logo sheet, not the not-found page (which is noindex), and served the app shell.
      const route = parseAppRoute(url.pathname, '', false);
      expect(['jobs', 'stats', 'company']).toContain(route.view);
      expect(route.company).toBeNull();
      expect(rewrittenToShell(url.pathname)).toBe(true);
    }
  });
  it('does not claim modification dates the static file cannot know', () => {
    expect(xml).not.toMatch(/<lastmod>|<changefreq>|<priority>/);
  });
  it('is served as itself, never replaced by the app shell', () => {
    expect(rewrittenToShell('/sitemap.xml')).toBe(false);
  });
});

describe('robots.txt', () => {
  const robots = publicFile('robots.txt');
  it('still allows crawling the whole site', () => {
    expect(robots).toMatch(/^User-agent: \*$/m);
    expect(robots).toMatch(/^Allow: \/$/m);
    expect(robots).not.toMatch(/^Disallow:\s*\/\s*$/m);
  });
  it('points crawlers at the production sitemap', () => {
    expect(robots).toMatch(new RegExp(`^Sitemap: ${ORIGIN.replace(/\./g, '\\.')}/sitemap\\.xml$`, 'm'));
  });
});
