// @vitest-environment jsdom
import { act } from 'react-dom/test-utils'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { initializeWorkspaceTheme, THEME_STORAGE_KEY, ThemeProvider, useWorkspaceTheme } from '../contexts/ThemeContext'

let root: Root
let host: HTMLDivElement
const Harness = () => {
  const { theme, setTheme } = useWorkspaceTheme()
  return (
    <>
      <output>{theme}</output>
      <button onClick={() => setTheme('business')} aria-pressed={theme === 'business'}>正式工作台</button>
      <button onClick={() => setTheme('monitor')} aria-pressed={theme === 'monitor'}>深色监控</button>
    </>
  )
}
const render = () => act(async () => root.render(<ThemeProvider><Harness /></ThemeProvider>))
const choose = (label: string) => act(async () => Array.from(host.querySelectorAll('button')).find(button => button.textContent === label)!.click())

beforeEach(() => {
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  delete document.documentElement.dataset.theme
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})

it('defaults to the formal workspace without writing unrelated preferences', async () => {
  await render()
  expect(host.querySelector('output')!.textContent).toBe('business')
  expect(document.documentElement.dataset.theme).toBe('business')
  expect(localStorage.length).toBe(0)
})

it('restores the saved monitor theme before React mounts', async () => {
  localStorage.setItem(THEME_STORAGE_KEY, 'monitor')
  expect(initializeWorkspaceTheme()).toBe('monitor')
  expect(document.documentElement.dataset.theme).toBe('monitor')
  expect(host.children.length).toBe(0)
  await render()
  expect(host.querySelector('output')!.textContent).toBe('monitor')
  expect(host.querySelectorAll('button')[1].getAttribute('aria-pressed')).toBe('true')
})

it('switches both modes and only persists the theme preference', async () => {
  localStorage.setItem('existing-preference', 'preserve')
  await render()
  await choose('深色监控')
  expect(document.documentElement.dataset.theme).toBe('monitor')
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('monitor')
  expect(host.querySelectorAll('button')[0].getAttribute('aria-pressed')).toBe('false')

  await choose('正式工作台')
  expect(document.documentElement.dataset.theme).toBe('business')
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('business')
  expect(localStorage.getItem('existing-preference')).toBe('preserve')
  expect(localStorage.length).toBe(2)
})

it('retains the selected theme after a fresh application mount', async () => {
  await render()
  await choose('深色监控')
  await act(async () => root.unmount())
  root = createRoot(host)
  await render()
  expect(document.documentElement.dataset.theme).toBe('monitor')
  expect(host.querySelector('output')!.textContent).toBe('monitor')
})

it('falls back to business for an invalid stored value', async () => {
  localStorage.setItem(THEME_STORAGE_KEY, 'unknown-mode')
  await render()
  expect(document.documentElement.dataset.theme).toBe('business')
  expect(host.querySelector('output')!.textContent).toBe('business')
})

it('keeps theme switching usable when browser storage is blocked', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new DOMException('Blocked', 'SecurityError') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Blocked', 'SecurityError') })
  await render()
  expect(document.documentElement.dataset.theme).toBe('business')
  await choose('深色监控')
  expect(document.documentElement.dataset.theme).toBe('monitor')
  expect(host.querySelector('output')!.textContent).toBe('monitor')
})
