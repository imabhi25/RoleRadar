import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  analyticsRunning, startAnalytics, stopAnalytics, writeAnalyticsConsent,
  type ConsentChoice, type StoredConsent,
} from '../analytics'
import './analytics-privacy.css'

const GOOGLE_INFO_URL = 'https://policies.google.com/technologies/partner-sites'

type Props = {
  /** Set only when Analytics is configured for this build and host; otherwise nothing is rendered. */
  measurementId?: string
  /** Global Privacy Control or Do Not Track: Analytics stays off and the visitor is not asked. */
  privacySignal: boolean
  initialConsent: StoredConsent | null
  debug?: boolean
  // Injectable for tests.
  start?: (measurementId: string) => void
  stop?: (measurementId: string) => void
  isRunning?: () => boolean
  save?: (choice: ConsentChoice) => StoredConsent
  reload?: () => void
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
}

/** A container after the app, so the settings footer sits at the end of the page instead of floating over it. */
function useFooterHost(enabled: boolean): HTMLElement | null {
  const [host, setHost] = useState<HTMLElement | null>(null)
  useEffect(() => {
    if (!enabled) return
    const element = document.createElement('div')
    element.className = 'analytics-privacy-footer-host'
    document.body.appendChild(element)
    setHost(element)
    return () => { element.remove(); setHost(null) }
  }, [enabled])
  return host
}

/** After the prompt closes, put focus somewhere predictable instead of losing it. */
function focusMainContent() {
  const main = document.getElementById('content') ?? document.querySelector('main')
  if (!(main instanceof HTMLElement)) return
  if (!main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1')
  main.focus({ preventScroll: true })
}

export function AnalyticsPrivacy({
  measurementId, privacySignal, initialConsent, debug = false,
  start = (id) => { startAnalytics({ measurementId: id, debug }) },
  stop = (id) => stopAnalytics(id),
  isRunning = () => analyticsRunning(),
  save = (choice) => writeAnalyticsConsent(choice),
  reload = () => window.location.reload(),
}: Props) {
  const configured = Boolean(measurementId)
  const [consent, setConsent] = useState<StoredConsent | null>(initialConsent)
  const [promptDismissed, setPromptDismissed] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const settingsButton = useRef<HTMLButtonElement>(null)
  const settingsHeading = useRef<HTMLHeadingElement>(null)
  const footerHost = useFooterHost(configured)
  const id = useId()
  const promptTitleId = `${id}-prompt-title`
  const panelId = `${id}-settings`
  const panelTitleId = `${id}-settings-title`

  useEffect(() => {
    if (settingsOpen) settingsHeading.current?.focus()
  }, [settingsOpen])

  if (!configured || !measurementId) return null

  const showPrompt = consent === null && !privacySignal && !promptDismissed

  function closeSettings() {
    setSettingsOpen(false)
    settingsButton.current?.focus()
  }

  function accept(fromPrompt: boolean) {
    if (privacySignal) return
    let record: StoredConsent
    try {
      record = save('accepted')
    } catch {
      setError('Your choice could not be saved, so Analytics stays off. Check that this browser allows site storage, then try again.')
      return
    }
    setError('')
    setConsent(record)
    start(measurementId!)
    setStatus('Analytics is on. You can turn it off at any time in Privacy & analytics settings at the bottom of the page.')
    if (fromPrompt) focusMainContent()
  }

  function decline(fromPrompt: boolean) {
    const wasRunning = isRunning()
    // Stop hits and delete cookies now, whether or not the choice can be saved.
    stop(measurementId!)
    let saved = true
    try {
      setConsent(save('declined'))
      setError('')
    } catch {
      saved = false
      setError('Analytics is off for this visit, but your choice could not be saved. Check that this browser allows site storage, then choose again.')
    }
    // Reload to unload the Google tag entirely, but only once the choice is saved: reloading with an old
    // "accepted" choice still stored would start Analytics again.
    if (wasRunning && saved) { reload(); return }
    setStatus('Analytics is off.')
    if (fromPrompt) focusMainContent()
  }

  const decidedOn = consent ? formatDate(consent.decidedAt) : ''
  const currentSetting = privacySignal
    ? 'Analytics is off: your browser is sending a Global Privacy Control or Do Not Track signal, so RoleRadar does not use Analytics and will not ask.'
    : consent?.choice === 'accepted'
      ? `Analytics is on. You accepted${decidedOn ? ` on ${decidedOn}` : ''}.`
      : consent?.choice === 'declined'
        ? `Analytics is off. You declined${decidedOn ? ` on ${decidedOn}` : ''}.`
        : 'Analytics is off. You have not made a choice yet.'

  const whatIsCollected = (
    <>
      <p>
        If you accept, Google receives the type of page you view (such as “Jobs” or “Market analytics”, never your
        searches, filters or the jobs you open), how long you stay, your browser and device details, and your IP
        address, which Google uses to estimate your approximate location. Google Analytics sets cookies (<code>_ga</code>
        {' '}and <code>_ga_…</code>) to recognise repeat visits. Advertising features are off.
      </p>
      <p>
        Google processes this information, which may be stored outside Canada, including in the United States.{' '}
        <a href={GOOGLE_INFO_URL} target="_blank" rel="noopener noreferrer">
          How Google uses information from sites that use its services<span className="analytics-privacy-sr"> (opens in a new tab)</span>
        </a>
      </p>
    </>
  )

  const footer = footerHost && createPortal(
    <footer className="analytics-privacy-footer" aria-label="Privacy">
      <button
        ref={settingsButton}
        type="button"
        className="analytics-privacy-toggle"
        aria-expanded={settingsOpen}
        aria-controls={panelId}
        onClick={() => (settingsOpen ? closeSettings() : setSettingsOpen(true))}
      >
        Privacy &amp; analytics settings
      </button>
      {settingsOpen && (
        <section
          id={panelId}
          className="analytics-privacy-panel"
          aria-labelledby={panelTitleId}
          onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); closeSettings() } }}
        >
          <h2 id={panelTitleId} ref={settingsHeading} tabIndex={-1}>Privacy &amp; analytics</h2>
          <p className="analytics-privacy-current"><strong>Current setting:</strong> {currentSetting}</p>
          {whatIsCollected}
          <p>Your choice is stored in this browser only. RoleRadar asks again after 13 months or if this notice changes.</p>
          {error && <p className="analytics-privacy-error" role="alert">{error}</p>}
          <div className="analytics-privacy-actions">
            {!privacySignal && consent?.choice !== 'declined' && (
              <button type="button" onClick={() => decline(false)}>
                {consent?.choice === 'accepted' ? 'Turn analytics off' : 'Decline analytics'}
              </button>
            )}
            {!privacySignal && consent?.choice !== 'accepted' && (
              <button type="button" onClick={() => accept(false)}>
                {consent?.choice === 'declined' ? 'Turn analytics on' : 'Accept analytics'}
              </button>
            )}
            <button type="button" className="analytics-privacy-secondary" onClick={closeSettings}>Close</button>
          </div>
        </section>
      )}
      <p className="analytics-privacy-sr" role="status" aria-live="polite">{status}</p>
    </footer>,
    footerHost,
  )

  return (
    <>
      {showPrompt && (
        <section className="analytics-privacy-prompt" aria-labelledby={promptTitleId}>
          <p id={promptTitleId} className="analytics-privacy-title">Analytics on RoleRadar</p>
          <p>
            RoleRadar would like to use Google Analytics to count visits and see which pages are used. It is off
            unless you accept, and you can change your choice at any time in Privacy &amp; analytics settings at the
            bottom of the page.
          </p>
          <details className="analytics-privacy-details">
            <summary>What would be collected</summary>
            {whatIsCollected}
          </details>
          {error && <p className="analytics-privacy-error" role="alert">{error}</p>}
          <div className="analytics-privacy-actions">
            <button type="button" onClick={() => decline(true)}>Decline analytics</button>
            <button type="button" onClick={() => accept(true)}>Accept analytics</button>
            <button type="button" className="analytics-privacy-secondary" onClick={() => { setPromptDismissed(true); focusMainContent() }}>
              Not now
            </button>
          </div>
        </section>
      )}
      {footer}
    </>
  )
}
