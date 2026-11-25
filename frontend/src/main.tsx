import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/inter'
import '@fontsource-variable/inter/wght-italic.css'
import './index.css'
import App from './App.tsx'
import { clearAnalyticsCookies, hasPrivacySignal, isAnalyticsConfigured, readStoredConsent, startAnalytics } from './analytics'
import { AnalyticsPrivacy } from './components/AnalyticsPrivacy'

// Google Analytics runs only in production builds that set a valid VITE_GA_MEASUREMENT_ID, and only after the
// visitor accepts. Start it before the first render so the app's own address changes (such as / becoming /jobs)
// are seen.
const measurementId = (import.meta.env.VITE_GA_MEASUREMENT_ID as string | undefined)?.trim()
const debug = import.meta.env.VITE_GA_DEBUG === 'true'
const configured = isAnalyticsConfigured({ measurementId, hostname: window.location.hostname, production: import.meta.env.PROD })
const privacySignal = hasPrivacySignal(navigator, window as Window & { doNotTrack?: string | null })
const consent = configured ? readStoredConsent() : null
if (configured && consent?.choice === 'accepted' && !privacySignal) {
  startAnalytics({ measurementId: measurementId!, debug })
} else if (configured) {
  // Declined, withdrawn, expired, never asked, or a privacy signal is now on: remove any Analytics cookies left behind.
  clearAnalyticsCookies(document, window.location.hostname)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Before the app in reading and keyboard order, so the first-visit question is reached first. */}
    <AnalyticsPrivacy
      measurementId={configured ? measurementId : undefined}
      privacySignal={privacySignal}
      initialConsent={consent}
      debug={debug}
    />
    <App />
  </StrictMode>,
)
