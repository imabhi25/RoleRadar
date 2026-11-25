/**
 * Google Analytics 4 for RoleRadar.
 *
 * Privacy rules, enforced here rather than left to GA defaults:
 * - Nothing loads until the visitor accepts Analytics, and only in a production build that sets a valid
 *   VITE_GA_MEASUREMENT_ID. Visitors whose browser sends Global Privacy Control or Do Not Track are never tracked,
 *   and are not asked.
 * - Consent is stored with a notice version and a date; it expires, and changing CONSENT_VERSION asks again.
 * - Withdrawing consent disables the tag, tells it consent was denied, and deletes the Analytics cookies.
 * - Page views use a fixed, path-only page identity and title; page referrers are sanitized too.
 *   Other GA events can collect additional data and must be reviewed before enabling analytics.
 * - A page view is sent when the page changes, not when the query string does, so typing a search or changing a
 *   filter is not a new page view.
 * - Advertising features are off: no ads storage, no Google signals, no ad personalisation.
 */
import { parseAppRoute } from "./utils/appRoute";

const GTAG_ORIGIN = "https://www.googletagmanager.com";
const MEASUREMENT_ID = /^G-[A-Z0-9]{4,16}$/;
const LOCAL_HOSTS = /^(?:localhost|127(?:\.\d{1,3}){3}|\[::1\]|0\.0\.0\.0)$|\.local$/;
export const CONSENT_KEY = 'roleradar-analytics-consent';
/** Bump when the analytics notice or what is collected changes: every visitor is asked again. */
export const CONSENT_VERSION = 1;
/** Ask again after about 13 months, in line with common regulator guidance on consent lifetimes. */
export const CONSENT_MAX_AGE_MS = 395 * 24 * 60 * 60 * 1000;

export type ConsentChoice = 'accepted' | 'declined';
export interface StoredConsent { choice: ConsentChoice; version: number; decidedAt: string }

type ConsentStorage = Pick<Storage, 'getItem' | 'setItem'>;

function browserStorage(): ConsentStorage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** The visitor's current, unexpired choice for the current notice version, if any. */
export function readStoredConsent(storage: ConsentStorage | null = browserStorage(), now = Date.now()): StoredConsent | null {
  try {
    const raw = storage?.getItem(CONSENT_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<StoredConsent>;
    if (value.choice !== 'accepted' && value.choice !== 'declined') return null;
    if (value.version !== CONSENT_VERSION || typeof value.decidedAt !== 'string') return null;
    const decided = Date.parse(value.decidedAt);
    if (!Number.isFinite(decided) || decided > now + 60_000 || now - decided > CONSENT_MAX_AGE_MS) return null;
    return { choice: value.choice, version: value.version, decidedAt: value.decidedAt };
  } catch {
    // Unreadable storage, or a value from an older format (such as a bare "accepted"): ask again.
    return null;
  }
}

export function readAnalyticsConsent(storage?: ConsentStorage | null, now?: number): ConsentChoice | null {
  return readStoredConsent(storage, now)?.choice ?? null;
}

/** Saves the choice. Throws when the browser refuses storage, so callers can tell the visitor. */
export function writeAnalyticsConsent(choice: ConsentChoice, storage: ConsentStorage | null = browserStorage(), now = Date.now()): StoredConsent {
  if (!storage) throw new Error('Browser storage is unavailable');
  const record: StoredConsent = { choice, version: CONSENT_VERSION, decidedAt: new Date(now).toISOString() };
  storage.setItem(CONSENT_KEY, JSON.stringify(record));
  return record;
}

type PrivacyNavigator = { globalPrivacyControl?: boolean; doNotTrack?: string | null };

/** Global Privacy Control or Do Not Track: Analytics stays off and the visitor is not asked. */
export function hasPrivacySignal(nav: PrivacyNavigator | undefined, win?: { doNotTrack?: string | null }): boolean {
  const dnt = nav?.doNotTrack ?? win?.doNotTrack;
  return nav?.globalPrivacyControl === true || dnt === '1' || dnt === 'yes';
}

/** Whether this build and host can run Analytics at all; consent is only asked for when this is true. */
export function isAnalyticsConfigured(env: { measurementId: string | undefined; hostname: string; production: boolean }): boolean {
  return env.production && Boolean(env.measurementId) && MEASUREMENT_ID.test(env.measurementId!) && !LOCAL_HOSTS.test(env.hostname);
}

export interface AnalyticsPage {
  /** Path sent to Google: fixed per page type, never derived from free text. */
  path: string;
  title: string;
}

/** The page identity for a location. Only the page type matters; every query parameter is ignored. */
export function analyticsPage(pathname: string, search: string): AnalyticsPage {
  const route = parseAppRoute(pathname, search, false);
  switch (route.view) {
    case "jobs":
      return { path: "/jobs", title: "Jobs | RoleRadar" };
    case "stats":
      return { path: "/stats", title: "Market analytics | RoleRadar" };
    case "company":
      // The company name comes from the address bar and can be anything a visitor typed, so it is not sent.
      return route.company
        ? { path: "/company/profile", title: "Company profile | RoleRadar" }
        : { path: "/company", title: "Companies | RoleRadar" };
    default:
      return { path: "/not-found", title: "Page not found | RoleRadar" };
  }
}

/** External referrers are reduced to their origin; their paths and queries can carry other sites' search terms. */
export function sanitizeReferrer(referrer: string, origin: string): string {
  if (!referrer) return "";
  try {
    const url = new URL(referrer);
    if (url.protocol !== "https:" && url.protocol !== "http:") return "";
    if (url.origin === origin) return `${origin}${analyticsPage(url.pathname, url.search).path}`;
    return `${url.origin}/`;
  } catch {
    return "";
  }
}

export interface AnalyticsEnvironment {
  measurementId: string | undefined;
  hostname: string;
  globalPrivacyControl?: boolean;
  doNotTrack?: string | null;
  consent?: 'accepted' | 'declined' | null;
}

/** Whether tracking may run at all for this visitor and build. */
export function analyticsAllowed(env: AnalyticsEnvironment): boolean {
  if (env.consent !== 'accepted') return false;
  if (!env.measurementId || !MEASUREMENT_ID.test(env.measurementId)) return false;
  if (LOCAL_HOSTS.test(env.hostname)) return false;
  return !hasPrivacySignal({ globalPrivacyControl: env.globalPrivacyControl, doNotTrack: env.doNotTrack });
}

/** First-party cookies set by gtag.js for GA4 (and the legacy _gid/_gat names, should any exist). */
const ANALYTICS_COOKIE = /^(?:_ga(?:_[A-Za-z0-9]+)?|_gid|_gat(?:_[A-Za-z0-9_-]+)?)$/;

/**
 * Deletes Analytics cookies. gtag.js sets them on the widest domain the browser accepts, which can be a parent of
 * the host, so each is expired on the host and on every parent domain; the browser ignores the ones that do not apply.
 * Returns the cookie names that were present.
 */
export function clearAnalyticsCookies(doc: Pick<Document, 'cookie'> = document, hostname = window.location.hostname): string[] {
  const names = doc.cookie.split(';').map((part) => part.split('=')[0].trim()).filter((name) => ANALYTICS_COOKIE.test(name));
  const labels = hostname.split('.');
  const domains = labels.slice(0, -1).map((_, i) => labels.slice(i).join('.'));
  for (const name of new Set(names)) {
    const expired = `${name}=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/; SameSite=Lax`;
    doc.cookie = expired;
    for (const domain of domains) doc.cookie = `${expired}; Domain=.${domain}`;
  }
  return [...new Set(names)];
}

/**
 * Withdraws Analytics on this page: no further hits, consent marked denied, cookies removed.
 * The loaded gtag.js stays in memory until the page is reloaded, but it no longer sends or stores anything.
 */
export function stopAnalytics(measurementId: string, win: AnalyticsWindow = window as AnalyticsWindow, doc: Pick<Document, 'cookie'> = document): void {
  (win as unknown as Record<string, unknown>)[`ga-disable-${measurementId}`] = true;
  win.gtag?.('consent', 'update', { analytics_storage: 'denied' });
  clearAnalyticsCookies(doc, win.location.hostname);
}

/** True once startAnalytics() has run on this page. */
export function analyticsRunning(win: AnalyticsWindow = window as AnalyticsWindow): boolean {
  return win.__roleradarAnalytics === true;
}

type Gtag = (...args: unknown[]) => void;
type AnalyticsWindow = Window & { dataLayer?: unknown[]; gtag?: Gtag; __roleradarAnalytics?: boolean };

export interface AnalyticsOptions {
  measurementId: string;
  /** Adds debug_mode so hits appear in GA DebugView. For preview testing only. */
  debug?: boolean;
  win?: AnalyticsWindow;
  doc?: Document;
}

/**
 * Loads gtag.js and reports page views. Returns false when it did nothing (already started).
 * Callers must check analyticsAllowed() first.
 */
export function startAnalytics({ measurementId, debug = false, win = window as AnalyticsWindow, doc = document }: AnalyticsOptions): boolean {
  if (win.__roleradarAnalytics) return false;
  win.__roleradarAnalytics = true;

  const dataLayer = (win.dataLayer = win.dataLayer || []);
  // gtag.js reads the Arguments object, not an array, so this must be a plain function.
  const gtag: Gtag = function gtag() {
    // eslint-disable-next-line prefer-rest-params
    dataLayer.push(arguments);
  };
  win.gtag = gtag;

  const origin = win.location.origin;
  let current = analyticsPage(win.location.pathname, win.location.search);
  let pageLocation = `${origin}${current.path}`;

  gtag("consent", "default", {
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    analytics_storage: "granted",
  });
  gtag("js", new Date());
  // "set" applies to every later hit, including Enhanced measurement events (outbound clicks, scrolls, engagement),
  // so none of them fall back to the real address bar or document.title.
  gtag("set", { page_location: pageLocation, page_title: current.title, page_referrer: sanitizeReferrer(doc.referrer, origin) });
  gtag("config", measurementId, {
    send_page_view: false,
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
    ...(debug ? { debug_mode: true } : {}),
  });
  gtag("event", "page_view");

  const onLocationChange = () => {
    const next = analyticsPage(win.location.pathname, win.location.search);
    if (next.path === current.path) return; // same page: a search, filter, sort or selected job changed
    const referrer = pageLocation;
    current = next;
    pageLocation = `${origin}${next.path}`;
    gtag("set", { page_location: pageLocation, page_title: next.title, page_referrer: referrer });
    gtag("event", "page_view");
  };

  // The app changes pages with history.pushState/replaceState, which fire no event, so observe them here.
  const browserHistory = win.history;
  for (const method of ["pushState", "replaceState"] as const) {
    const original = browserHistory[method];
    browserHistory[method] = function (this: History, ...args: Parameters<History["pushState"]>) {
      const result = original.apply(this, args);
      onLocationChange();
      return result;
    };
  }
  win.addEventListener("popstate", onLocationChange);

  const script = doc.createElement("script");
  script.async = true;
  script.src = `${GTAG_ORIGIN}/gtag/js?id=${encodeURIComponent(measurementId)}`;
  doc.head.appendChild(script);
  return true;
}
