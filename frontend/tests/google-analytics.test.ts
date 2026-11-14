import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import {
  CONSENT_KEY, CONSENT_MAX_AGE_MS, CONSENT_VERSION, analyticsAllowed, analyticsPage, analyticsRunning, clearAnalyticsCookies,
  hasPrivacySignal, isAnalyticsConfigured, readAnalyticsConsent, readStoredConsent, sanitizeReferrer, startAnalytics, stopAnalytics,
  writeAnalyticsConsent,
} from '../src/analytics';

const ORIGIN = 'https://roleradar-jobs.vercel.app';
const ID = 'G-H4Y8WYE4XS';

/** A minimal browser stand-in: history calls update location, as in a real browser, without firing events. */
function fakeBrowser(start: string, referrer = '') {
  const listeners: Record<string, (() => void)[]> = {};
  const location = { origin: ORIGIN, pathname: '/', search: '' };
  const go = (url: string) => {
    const next = new URL(url, `${ORIGIN}${location.pathname}${location.search}`);
    location.pathname = next.pathname;
    location.search = next.search;
  };
  go(start);
  const scripts: { async: boolean; src: string }[] = [];
  const win = {
    location,
    history: {
      pushState(_state: unknown, _unused: string, url?: string | URL | null) { if (url) go(String(url)); },
      replaceState(_state: unknown, _unused: string, url?: string | URL | null) { if (url) go(String(url)); },
    },
    addEventListener(type: string, fn: () => void) { (listeners[type] ??= []).push(fn); },
  } as unknown as Window & { dataLayer: IArguments[] };
  const doc = {
    referrer,
    createElement: () => ({ async: false, src: '' }),
    head: { appendChild: (el: { async: boolean; src: string }) => scripts.push(el) },
  } as unknown as Document;
  /** Browser back/forward: the address changes, then popstate fires. */
  const back = (url: string) => { go(url); (listeners.popstate ?? []).forEach((fn) => fn()); };
  const commands = () => win.dataLayer.map((args) => Array.from(args));
  const pageViews = () => {
    // Each page_view is reported with the page_location most recently "set" before it.
    let state: Record<string, string> = {};
    const views: Record<string, string>[] = [];
    for (const [command, a, b] of commands()) {
      if (command === 'set') state = { ...state, ...(a as Record<string, string>) };
      if (command === 'event' && a === 'page_view') views.push({ ...state, ...(b as Record<string, string> | undefined) });
    }
    return views;
  };
  return { win, doc, scripts, back, commands, pageViews };
}

describe('page identity sent to Google', () => {
  it.each([
    ['/', '', '/jobs'],
    ['/jobs', '?q=jane%40example.com&country=Canada&page=3&job=ashby%3Aabc', '/jobs'],
    ['/jobs/greenhouse%3A8900232002', '', '/jobs'],
    ['/jobs/workday%3Aashby-secret-id', '?ref=confidential', '/jobs'],
    ['/job/ashby%3A123', '', '/jobs'],
    ['/stats', '?country=Canada', '/stats'],
    ['/company', '', '/company'],
    ['/company', '?company=Jane%20Doe%20personal%20search', '/company/profile'],
    ['/company/My%20Private%20Note', '', '/company/profile'],
    ['/anything-else', '?q=secret', '/not-found'],
    ['/logos', '', '/not-found'],
  ])('%s%s is reported as %s', (pathname, search, expected) => {
    const page = analyticsPage(pathname, search);
    expect(page.path).toBe(expected);
    expect(page.title).toMatch(/\| RoleRadar$/);
    expect(`${page.path} ${page.title}`).not.toMatch(/jane|example|secret|private|note|canada|ashby|greenhouse|workday|confidential/i);
  });
});

describe('referrers', () => {
  it('keeps only the origin of other sites, whose URLs can hold their own search terms', () => {
    expect(sanitizeReferrer('https://www.google.com/search?q=jane+doe+resume', ORIGIN)).toBe('https://www.google.com/');
    expect(sanitizeReferrer('https://news.ycombinator.com/item?id=1', ORIGIN)).toBe('https://news.ycombinator.com/');
  });
  it('reduces an internal referrer to its page identity', () => {
    expect(sanitizeReferrer(`${ORIGIN}/jobs?q=private`, ORIGIN)).toBe(`${ORIGIN}/jobs`);
  });
  it.each(['', 'not a url', 'javascript:alert(1)', 'android-app://com.example/x'])('drops %j', (value) => {
    expect(sanitizeReferrer(value, ORIGIN)).toBe('');
  });
});

describe('when tracking may run', () => {
  const base = { measurementId: ID, hostname: 'roleradar-jobs.vercel.app', consent: 'accepted' as const };
  it('runs for a configured production host', () => {
    expect(analyticsAllowed(base)).toBe(true);
  });
  it('requires explicit consent', () => {
    expect(analyticsAllowed({ ...base, consent: null })).toBe(false);
    expect(analyticsAllowed({ ...base, consent: 'declined' })).toBe(false);
  });
  it.each([undefined, '', 'UA-12345-1', 'G-', 'g-h4y8wye4xs', 'G-H4Y8WYE4XS"><script>'])('needs a valid GA4 ID, not %j', (measurementId) => {
    expect(analyticsAllowed({ ...base, measurementId })).toBe(false);
  });
  it.each(['localhost', '127.0.0.1', '[::1]', 'roleradar.local'])('never runs on %s', (hostname) => {
    expect(analyticsAllowed({ ...base, hostname })).toBe(false);
  });
  it('respects Global Privacy Control and Do Not Track', () => {
    expect(analyticsAllowed({ ...base, globalPrivacyControl: true })).toBe(false);
    expect(analyticsAllowed({ ...base, doNotTrack: '1' })).toBe(false);
    expect(analyticsAllowed({ ...base, doNotTrack: '0', globalPrivacyControl: false })).toBe(true);
  });
});

describe('Google tag setup', () => {
  it('loads gtag.js from Google with the measurement ID, asynchronously', () => {
    const b = fakeBrowser('/jobs');
    startAnalytics({ measurementId: ID, win: b.win, doc: b.doc });
    expect(b.scripts).toEqual([{ async: true, src: `https://www.googletagmanager.com/gtag/js?id=${ID}` }]);
  });
  it('turns off automatic page views and every advertising feature', () => {
    const b = fakeBrowser('/jobs');
    startAnalytics({ measurementId: ID, win: b.win, doc: b.doc });
    const consent = b.commands().find(([c, a]) => c === 'consent' && a === 'default')![2];
    expect(consent).toEqual({ ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied', analytics_storage: 'granted' });
    const config = b.commands().find(([c]) => c === 'config')!;
    expect(config[1]).toBe(ID);
    expect(config[2]).toEqual({ send_page_view: false, allow_google_signals: false, allow_ad_personalization_signals: false });
    // gtag.js requires real Arguments objects in the dataLayer, not arrays.
    expect(Object.prototype.toString.call(b.win.dataLayer[0])).toBe('[object Arguments]');
  });
  it('sets the page before configuring, so even the first hit never uses the real address', () => {
    const b = fakeBrowser('/jobs?q=private+search');
    startAnalytics({ measurementId: ID, win: b.win, doc: b.doc });
    const order = b.commands().map(([c]) => c);
    expect(order.indexOf('set')).toBeLessThan(order.indexOf('config'));
    expect(order.indexOf('config')).toBeLessThan(order.indexOf('event'));
  });
  it('adds debug_mode only when asked (for preview checks in DebugView)', () => {
    const b = fakeBrowser('/jobs');
    startAnalytics({ measurementId: ID, debug: true, win: b.win, doc: b.doc });
    expect(b.commands().find(([c]) => c === 'config')![2]).toMatchObject({ debug_mode: true });
  });
  it('starts only once', () => {
    const b = fakeBrowser('/jobs');
    expect(startAnalytics({ measurementId: ID, win: b.win, doc: b.doc })).toBe(true);
    expect(startAnalytics({ measurementId: ID, win: b.win, doc: b.doc })).toBe(false);
    expect(b.pageViews()).toHaveLength(1);
    expect(b.scripts).toHaveLength(1);
  });
});

describe('page views in the single-page app', () => {
  it('counts page changes, not searches, filters, sorting, paging or job selection', () => {
    const b = fakeBrowser('/', 'https://www.google.com/search?q=jane+doe');
    startAnalytics({ measurementId: ID, win: b.win, doc: b.doc });
    const h = b.win.history;
    h.replaceState(null, '', '/jobs');                                  // the app's own / -> /jobs rewrite
    h.pushState(null, '', '/jobs?q=jane.doe%40example.com');            // typing a search
    h.replaceState(null, '', '/jobs?q=jane.doe%40example.com&country=Canada&workplace=remote');
    h.pushState(null, '', '/jobs?q=jane.doe%40example.com&sort=newest&page=2');
    h.replaceState({ autoJob: true }, '', '/jobs?q=x&job=ashby%3Asecret-id');   // auto-selected job
    h.pushState(null, '', '/jobs?q=x&job=greenhouse%3Aother');                // job opened by the visitor
    h.pushState(null, '', '/stats?country=Canada');                     // page change
    h.pushState(null, '', '/stats?country=United%20States');            // filter on that page
    h.pushState(null, '', '/company?company=My%20Private%20Note');     // page change
    b.back('/stats?country=Canada');                                    // back button: page change
    b.back('/stats');                                                   // back again, same page
    h.pushState(null, '', '/jobs/workday%3Asome-job-id');               // individual job route
    expect(b.pageViews()).toEqual([
      { page_location: `${ORIGIN}/jobs`, page_title: 'Jobs | RoleRadar', page_referrer: 'https://www.google.com/' },
      { page_location: `${ORIGIN}/stats`, page_title: 'Market analytics | RoleRadar', page_referrer: `${ORIGIN}/jobs` },
      { page_location: `${ORIGIN}/company/profile`, page_title: 'Company profile | RoleRadar', page_referrer: `${ORIGIN}/stats` },
      { page_location: `${ORIGIN}/stats`, page_title: 'Market analytics | RoleRadar', page_referrer: `${ORIGIN}/company/profile` },
      { page_location: `${ORIGIN}/jobs`, page_title: 'Jobs | RoleRadar', page_referrer: `${ORIGIN}/stats` },
    ]);
  });
  it('never puts anything typed by the visitor into data sent to Google', () => {
    const b = fakeBrowser('/jobs?q=Jane%20Doe%20jane.doe%40example.com', `${ORIGIN}/jobs?q=previous+secret`);
    startAnalytics({ measurementId: ID, win: b.win, doc: b.doc });
    for (const url of ['/jobs?q=416-555-0199', '/company/Jane%20Doe%20Consulting', '/company?company=secret-co',
      '/stats?skill=privateskill', '/jobs?job=ashby%3Aprivate-job-id', '/jobs/ashby%3Aprivate-job-id', '/nowhere?q=secret']) {
      b.win.history.pushState(null, '', url);
    }
    const sent = JSON.stringify(b.commands());
    for (const secret of ['Jane', 'jane', 'example.com', '416', '555', 'secret', 'private', 'Consulting', '?', 'q=']) {
      expect(sent).not.toContain(secret);
    }
  });
  it('keeps passing history calls through to the browser unchanged', () => {
    const b = fakeBrowser('/jobs');
    startAnalytics({ measurementId: ID, win: b.win, doc: b.doc });
    b.win.history.pushState(null, '', '/stats?x=1');
    expect(b.win.location.pathname).toBe('/stats');
    expect(b.win.location.search).toBe('?x=1');
  });
});

describe('wiring', () => {
  const main = fs.readFileSync(path.resolve(__dirname, '..', 'src', 'main.tsx'), 'utf-8');
  it('starts only in a configured build, after acceptance, without a privacy signal, and before the app renders', () => {
    expect(main).toMatch(/isAnalyticsConfigured\(\{[^}]*production: import\.meta\.env\.PROD/);
    expect(main).toMatch(/if \(configured && consent\?\.choice === 'accepted' && !privacySignal\) \{\s*startAnalytics\(/);
    expect(main).toMatch(/VITE_GA_MEASUREMENT_ID/);
    expect(main.indexOf('startAnalytics(')).toBeLessThan(main.indexOf('createRoot('));
  });
  it('removes leftover Analytics cookies whenever it does not start', () => {
    expect(main).toMatch(/\} else if \(configured\) \{[\s\S]*?clearAnalyticsCookies\(/);
  });
  it('places the consent question before the app and passes no ID when Analytics is not configured', () => {
    expect(main.indexOf('<AnalyticsPrivacy')).toBeLessThan(main.indexOf('<App />'));
    expect(main).toMatch(/measurementId=\{configured \? measurementId : undefined\}/);
  });
  it('does not hard-code the measurement ID or an inline tag in the page', () => {
    const html = fs.readFileSync(path.resolve(__dirname, '..', 'index.html'), 'utf-8');
    expect(html).not.toMatch(/googletagmanager|gtag|G-[A-Z0-9]{6,}/);
    expect(main).not.toMatch(/G-[A-Z0-9]{6,}/);
  });
});

/** In-memory stand-in for localStorage. */
const memoryStorage = (initial: Record<string, string> = {}) => {
  const data = new Map(Object.entries(initial));
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => { data.set(k, v); }, data };
};
const NOW = Date.parse('2026-11-01T12:00:00Z');

describe('stored consent', () => {
  it('round-trips a choice with the notice version and date', () => {
    const storage = memoryStorage();
    const record = writeAnalyticsConsent('accepted', storage, NOW);
    expect(JSON.parse(storage.data.get(CONSENT_KEY)!)).toEqual({ choice: 'accepted', version: CONSENT_VERSION, decidedAt: '2026-11-01T12:00:00.000Z' });
    expect(readStoredConsent(storage, NOW)).toEqual(record);
    expect(readAnalyticsConsent(storage, NOW)).toBe('accepted');
  });
  it.each([
    ['a bare value from the earlier format', 'accepted'],
    ['malformed JSON', '{"choice":'],
    ['an unknown choice', JSON.stringify({ choice: 'maybe', version: CONSENT_VERSION, decidedAt: '2026-10-01T00:00:00Z' })],
    ['an older notice version', JSON.stringify({ choice: 'accepted', version: CONSENT_VERSION - 1, decidedAt: '2026-10-01T00:00:00Z' })],
    ['a missing date', JSON.stringify({ choice: 'accepted', version: CONSENT_VERSION })],
    ['a date in the future', JSON.stringify({ choice: 'accepted', version: CONSENT_VERSION, decidedAt: '2027-01-01T00:00:00Z' })],
  ])('treats %s as no choice, so the visitor is asked again', (_label, raw) => {
    expect(readAnalyticsConsent(memoryStorage({ [CONSENT_KEY]: raw }), NOW)).toBeNull();
  });
  it('expires a choice after 13 months', () => {
    const storage = memoryStorage();
    writeAnalyticsConsent('accepted', storage, NOW);
    expect(readAnalyticsConsent(storage, NOW + CONSENT_MAX_AGE_MS - 1000)).toBe('accepted');
    expect(readAnalyticsConsent(storage, NOW + CONSENT_MAX_AGE_MS + 1000)).toBeNull();
  });
  it('reports unreadable storage as no choice and refuses to pretend a write succeeded', () => {
    const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
    expect(readAnalyticsConsent(broken, NOW)).toBeNull();
    expect(() => writeAnalyticsConsent('declined', broken, NOW)).toThrow();
    expect(() => writeAnalyticsConsent('declined', null, NOW)).toThrow();
  });
});

describe('privacy signals and configuration', () => {
  it.each([
    [{ globalPrivacyControl: true }, true],
    [{ doNotTrack: '1' }, true],
    [{ doNotTrack: 'yes' }, true],
    [{ doNotTrack: '0', globalPrivacyControl: false }, false],
    [{ doNotTrack: 'unspecified' }, false],
    [{}, false],
  ])('%j -> %s', (nav, expected) => {
    expect(hasPrivacySignal(nav)).toBe(expected);
  });
  it('falls back to the older window.doNotTrack', () => {
    expect(hasPrivacySignal({}, { doNotTrack: '1' })).toBe(true);
  });
  it('is configured only for a production build, a valid GA4 ID and a non-local host', () => {
    const base = { measurementId: ID, hostname: 'roleradar-jobs.vercel.app', production: true };
    expect(isAnalyticsConfigured(base)).toBe(true);
    expect(isAnalyticsConfigured({ ...base, production: false })).toBe(false);
    expect(isAnalyticsConfigured({ ...base, measurementId: undefined })).toBe(false);
    expect(isAnalyticsConfigured({ ...base, measurementId: 'UA-1-1' })).toBe(false);
    expect(isAnalyticsConfigured({ ...base, hostname: 'localhost' })).toBe(false);
  });
});

/** Records every cookie write the way document.cookie receives it. */
const fakeCookies = (initial: string) => {
  const writes: string[] = [];
  return { writes, doc: { get cookie() { return initial; }, set cookie(value: string) { writes.push(value); } } };
};

describe('withdrawing consent', () => {
  it('expires every Analytics cookie on the host and each parent domain, and nothing else', () => {
    const { writes, doc } = fakeCookies('theme=dark; _ga=GA1.1.123.456; _ga_H4Y8WYE4XS=GS2.1.s1; _gid=GA1.1.9; roleradar-x=1');
    expect(clearAnalyticsCookies(doc, 'roleradar-jobs.vercel.app')).toEqual(['_ga', '_ga_H4Y8WYE4XS', '_gid']);
    for (const name of ['_ga', '_ga_H4Y8WYE4XS', '_gid']) {
      const forName = writes.filter((w) => w.startsWith(`${name}=;`));
      expect(forName).toHaveLength(3);
      expect(forName.every((w) => /Max-Age=0/.test(w) && /Path=\//.test(w))).toBe(true);
      expect(forName.some((w) => !/Domain=/.test(w))).toBe(true);
      expect(forName.some((w) => /Domain=\.roleradar-jobs\.vercel\.app/.test(w))).toBe(true);
      expect(forName.some((w) => /Domain=\.vercel\.app/.test(w))).toBe(true);
    }
    expect(writes.some((w) => /^(theme|roleradar-x)=/.test(w))).toBe(false);
    expect(writes.some((w) => /Domain=\.app(;|$)/.test(w))).toBe(false);
  });
  it('does nothing when there are no Analytics cookies', () => {
    const { writes, doc } = fakeCookies('theme=dark');
    expect(clearAnalyticsCookies(doc, 'roleradar-jobs.vercel.app')).toEqual([]);
    expect(writes).toEqual([]);
  });
  it('disables the tag, tells it consent was denied, and deletes the cookies', () => {
    const b = fakeBrowser('/jobs');
    (b.win.location as unknown as { hostname: string }).hostname = 'roleradar-jobs.vercel.app';
    startAnalytics({ measurementId: ID, win: b.win, doc: b.doc });
    expect(analyticsRunning(b.win)).toBe(true);
    const { writes, doc } = fakeCookies('_ga=GA1.1.1.1');
    stopAnalytics(ID, b.win, doc);
    expect((b.win as unknown as Record<string, unknown>)[`ga-disable-${ID}`]).toBe(true);
    expect(b.commands().at(-1)).toEqual(['consent', 'update', { analytics_storage: 'denied' }]);
    expect(writes.length).toBeGreaterThan(0);
  });
  it('works when the tag never started', () => {
    const b = fakeBrowser('/jobs');
    (b.win.location as unknown as { hostname: string }).hostname = 'roleradar-jobs.vercel.app';
    const { doc } = fakeCookies('');
    expect(() => stopAnalytics(ID, b.win, doc)).not.toThrow();
    expect((b.win as unknown as Record<string, unknown>)[`ga-disable-${ID}`]).toBe(true);
    expect(analyticsRunning(b.win)).toBe(false);
  });
});
