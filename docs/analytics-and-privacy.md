# Google Analytics 4: setup, consent and privacy

## What the integration does

- **Nothing without consent.** gtag.js loads only when all of these hold:
  - a production build sets a valid `VITE_GA_MEASUREMENT_ID`;
  - the site is not running on localhost;
  - the visitor has accepted Analytics;
  - the browser sends no Global Privacy Control (GPC) or Do Not Track (DNT) signal.

  Until then no Google request is made and no `_ga` cookie is set.
- **When it's asked:** the consent question appears only when Analytics is configured, and never to visitors
  sending GPC or DNT. If Analytics is not configured, nothing at all is rendered: no prompt and no settings.
- **The choice:**
  - stored in this browser's `localStorage` under `roleradar-analytics-consent`, as
    `{ choice, version, decidedAt }`;
  - expires after 13 months;
  - asked again when `CONSENT_VERSION` in `src/analytics.ts` is raised. **Raise it whenever the notice or what is
    collected changes.**
  - Values in the earlier format (a bare `"accepted"`) are treated as no choice.
- **Withdrawal:** "Turn analytics off" (or Decline):
  1. sets `ga-disable-<ID>`;
  2. sends `consent update` with `analytics_storage: denied`;
  3. deletes `_ga`, `_ga_<stream>` (and legacy `_gid`/`_gat*`) on the host and each parent domain;
  4. saves the choice, then reloads to unload the tag.

  It does not reload if the choice could not be saved, because reloading would restore the old "accepted" choice;
  tracking stays stopped for that visit instead. On every later load without valid consent, any leftover Analytics
  cookies are deleted again. That covers a declined, expired or withdrawn choice, and a privacy signal turned on
  later.
- **Revisiting:** a "Privacy & analytics settings" button in a page footer after the app (a `contentinfo`
  landmark). It shows the current setting and the date it was chosen, and lets the visitor change it.
- **Accessibility:**
  - the first-visit question is a labelled, non-modal region placed before the app in keyboard order;
  - Accept and Decline look identical;
  - every control is at least 44 × 44 px, with a visible focus ring;
  - focus moves into the settings panel when it opens and back to its button on Close or Escape;
  - after a choice in the prompt, focus moves to the main content and a status message announces the result.
- **Page views:** one per page type. `src/analytics.ts` watches the app's history changes and sends `page_view`
  only when the page type changes. GA's own history-based page views are off in the property, and
  `send_page_view: false` stops the automatic first hit.

  | Visitor is on | Sent as `page_location` | `page_title` |
  | --- | --- | --- |
  | `/`, `/jobs` with any search, filter, sort, page or selected job | `/jobs` | Jobs \| RoleRadar |
  | `/stats` with any filter | `/stats` | Market analytics \| RoleRadar |
  | `/company` (directory) | `/company` | Companies \| RoleRadar |
  | `/company?company=…` or `/company/…` | `/company/profile` | Company profile \| RoleRadar |
  | anything else | `/not-found` | Page not found \| RoleRadar |

- **Page details are minimized.** Page location, title and referrer are set from the table above before any hit.
  An external referrer is cut to its origin (for example `https://www.google.com/`).
- **Advertising off:** consent defaults deny `ad_storage`, `ad_user_data` and `ad_personalization`. Google
  signals and ad personalisation are disabled.
- **CSP:** `script-src` gains exactly `https://www.googletagmanager.com`; no `'unsafe-inline'`. The site sets no
  `connect-src`, `img-src` or `default-src`, so GA's hits are not restricted. If one is added later, include
  `https://*.google-analytics.com` and `https://*.analytics.google.com`.

## GA Admin settings this relies on

The notice shown to visitors says Google does not receive searches, filters or the jobs they open. That is true
only with these Enhanced measurement settings, so keep them:

| Setting | Required state | Why |
| --- | --- | --- |
| Page changes based on browser history events | Off | The app sends its own path-only page views. |
| Site search | Off | Would read `?q=` from the address. |
| Outbound clicks | Off (done in GA Admin) | Would send full destination URLs: employer job IDs (`?gh_jid=…`) and office addresses in Maps links. |
| Form interactions | Off (done in GA Admin) | Would report the search form. |
| Scrolls | Either | Sends a scroll-depth event with the same cleaned-up page location. |
| Google signals | Off | Advertising features are off. |
| Data retention | Set (for example 2 months), and state it in the privacy notice | |

If any of these is turned on again, update the notice text in `src/components/AnalyticsPrivacy.tsx` and
`docs/privacy-notice-draft.md`, and raise `CONSENT_VERSION`.

## Trade-offs

- **Lost detail:** company profile views are counted together as `/company/profile`, and searches, job views
  and apply clicks are not reported. To add them, send dedicated events with values from a fixed list. Never send
  free text, and update the notice first.
- **Unreported visitors:** visitors who decline, choose "Not now", or send GPC or DNT are not counted.

## Before enabling for real visitors

1. Complete and publish the privacy notice (`docs/privacy-notice-draft.md`) at a stable URL, and link it from the
   consent prompt and the settings footer. Every item marked **[CONFIRM]** needs an answer, and the questions under
   "For legal review" need review.
2. Confirm the GA Admin settings in the table above.
3. Set `VITE_GA_MEASUREMENT_ID` in the Vercel **Production** environment only (not `VITE_GA_DEBUG`) and redeploy.
4. On production, check in DevTools (Network, filter `collect`) and in GA DebugView that nothing is sent before
   Accept; that `dl`, `dt` and `dr` contain only the paths above; and that after "Turn analytics off" no further
   requests are sent and the `_ga` cookies are gone (Application → Cookies).

This is not legal advice.
