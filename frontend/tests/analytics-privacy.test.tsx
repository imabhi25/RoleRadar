import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { AnalyticsPrivacy } from '../src/components/AnalyticsPrivacy'
import { CONSENT_KEY, CONSENT_VERSION, readStoredConsent, writeAnalyticsConsent, type ConsentChoice, type StoredConsent } from '../src/analytics'

const ID = 'G-TEST1234'
const record = (choice: ConsentChoice, decidedAt = '2026-10-15T09:00:00.000Z'): StoredConsent => ({ choice, version: CONSENT_VERSION, decidedAt })

afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.replaceChildren() })

/** Renders with spies for every side effect; `running` says whether the Google tag is already loaded on the page. */
function setup(props: Partial<Parameters<typeof AnalyticsPrivacy>[0]> = {}, running = false) {
  const spies = {
    start: vi.fn(),
    stop: vi.fn(),
    reload: vi.fn(),
    save: vi.fn((choice: ConsentChoice) => writeAnalyticsConsent(choice)),
    isRunning: vi.fn(() => running),
  }
  const main = document.createElement('main')
  main.id = 'content'
  document.body.appendChild(main)
  render(<AnalyticsPrivacy measurementId={ID} privacySignal={false} initialConsent={null} {...spies} {...props} />)
  return { ...spies, main }
}
const prompt = () => screen.queryByRole('region', { name: 'Analytics on RoleRadar' })
const settingsButton = () => screen.getByRole('button', { name: 'Privacy & analytics settings' })
const openSettings = () => { fireEvent.click(settingsButton()); return screen.getByRole('region', { name: 'Privacy & analytics' }) }

describe('when Analytics cannot run', () => {
  it('renders nothing at all when Analytics is not configured', () => {
    render(<AnalyticsPrivacy measurementId={undefined} privacySignal={false} initialConsent={null} />)
    expect(prompt()).toBeNull()
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByRole('contentinfo')).toBeNull()
  })
  it.each(['Global Privacy Control', 'Do Not Track'])('does not ask when %s is on, and explains why in settings', () => {
    const { start } = setup({ privacySignal: true })
    expect(prompt()).toBeNull()
    const panel = openSettings()
    expect(within(panel).getByText(/Global Privacy Control or Do Not Track signal/)).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: /accept|turn analytics on/i })).toBeNull()
    expect(start).not.toHaveBeenCalled()
  })
})

describe('first visit', () => {
  it('asks with equal Accept and Decline choices and loads nothing until one is made', () => {
    const { start } = setup()
    const region = prompt()!
    const accept = within(region).getByRole('button', { name: 'Accept analytics' })
    const decline = within(region).getByRole('button', { name: 'Decline analytics' })
    expect(accept.className).toBe(decline.className)
    expect(start).not.toHaveBeenCalled()
    expect(document.querySelector('script[src*="googletagmanager"]')).toBeNull()
  })
  it('Accept saves a dated, versioned choice, starts Analytics without reloading, and announces it', () => {
    const { start, reload, main } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Accept analytics' }))
    expect(readStoredConsent()).toMatchObject({ choice: 'accepted', version: CONSENT_VERSION })
    expect(start).toHaveBeenCalledWith(ID)
    expect(reload).not.toHaveBeenCalled()
    expect(prompt()).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('Analytics is on')
    expect(document.activeElement).toBe(main)
  })
  it('Decline before the tag ran stops tracking and deletes cookies without reloading', () => {
    const { stop, start, reload, main } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Decline analytics' }))
    expect(readStoredConsent()).toMatchObject({ choice: 'declined' })
    expect(stop).toHaveBeenCalledWith(ID)
    expect(start).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('Analytics is off')
    expect(document.activeElement).toBe(main)
  })
  it('"Not now" hides the question for this visit without starting or saving anything', () => {
    const { start, save, main } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(prompt()).toBeNull()
    expect(start).not.toHaveBeenCalled()
    expect(save).not.toHaveBeenCalled()
    expect(localStorage.getItem(CONSENT_KEY)).toBeNull()
    expect(document.activeElement).toBe(main)
  })
  it('if the choice cannot be saved, Analytics stays off and the visitor is told', () => {
    const { start } = setup({ save: vi.fn(() => { throw new Error('blocked') }) })
    fireEvent.click(screen.getByRole('button', { name: 'Accept analytics' }))
    expect(start).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Analytics stays off')
  })
})

describe('revisiting the choice', () => {
  it('shows the current choice and when it was made', () => {
    setup({ initialConsent: record('accepted') })
    expect(prompt()).toBeNull()
    expect(openSettings()).toHaveTextContent(/Current setting: Analytics is on\. You accepted on .*2026/)
  })
  it('withdrawing stops tracking, deletes cookies, saves the choice, then reloads to unload the tag', () => {
    localStorage.setItem(CONSENT_KEY, JSON.stringify(record('accepted')))
    const { stop, reload } = setup({ initialConsent: record('accepted') }, true)
    fireEvent.click(within(openSettings()).getByRole('button', { name: 'Turn analytics off' }))
    expect(stop).toHaveBeenCalledWith(ID)
    expect(readStoredConsent()).toMatchObject({ choice: 'declined' })
    expect(reload).toHaveBeenCalledOnce()
    expect(stop.mock.invocationCallOrder[0]).toBeLessThan(reload.mock.invocationCallOrder[0])
  })
  it('if withdrawal cannot be saved, tracking still stops and the page is not reloaded into the old choice', () => {
    const { stop, reload } = setup({ initialConsent: record('accepted'), save: vi.fn(() => { throw new Error('blocked') }) }, true)
    fireEvent.click(within(openSettings()).getByRole('button', { name: 'Turn analytics off' }))
    expect(stop).toHaveBeenCalledWith(ID)
    expect(reload).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Analytics is off for this visit')
  })
  it('a declined visitor can turn Analytics on again', () => {
    const { start } = setup({ initialConsent: record('declined') })
    const panel = openSettings()
    expect(panel).toHaveTextContent('Analytics is off. You declined')
    fireEvent.click(within(panel).getByRole('button', { name: 'Turn analytics on' }))
    expect(start).toHaveBeenCalledWith(ID)
    expect(readStoredConsent()).toMatchObject({ choice: 'accepted' })
  })
  it('asks again when the stored choice is from an older format', () => {
    localStorage.setItem(CONSENT_KEY, 'accepted')
    setup({ initialConsent: readStoredConsent() })
    expect(prompt()).not.toBeNull()
  })
})

describe('keyboard and screen readers', () => {
  it('the settings button reports its state and moves focus into and out of the panel', async () => {
    setup({ initialConsent: record('declined') })
    expect(settingsButton()).toHaveAttribute('aria-expanded', 'false')
    await act(async () => { fireEvent.click(settingsButton()) })
    expect(settingsButton()).toHaveAttribute('aria-expanded', 'true')
    expect(settingsButton()).toHaveAttribute('aria-controls', screen.getByRole('region', { name: 'Privacy & analytics' }).id)
    expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Privacy & analytics' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.queryByRole('region', { name: 'Privacy & analytics' })).toBeNull()
    expect(document.activeElement).toBe(settingsButton())
  })
  it('Escape closes the panel and returns focus to the button', async () => {
    setup({ initialConsent: record('accepted') })
    await act(async () => { fireEvent.click(settingsButton()) })
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(screen.queryByRole('region', { name: 'Privacy & analytics' })).toBeNull()
    expect(document.activeElement).toBe(settingsButton())
  })
  it('settings live in a footer landmark after the app, not over it', () => {
    setup({ initialConsent: record('accepted') })
    const footer = screen.getByRole('contentinfo', { name: 'Privacy' })
    expect(footer.parentElement?.parentElement).toBe(document.body)
    expect(footer.contains(settingsButton())).toBe(true)
  })
  it('the Google link says it opens a new tab', () => {
    setup()
    fireEvent.click(screen.getByText('What would be collected'))
    expect(screen.getAllByRole('link', { name: /opens in a new tab/ }).length).toBeGreaterThan(0)
  })
})
