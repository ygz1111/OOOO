// @vitest-environment jsdom
import type { ReactNode } from 'react'
import { act } from 'react-dom/test-utils'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, useNavigate, type NavigateFunction } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from '../App'
import { ThemeProvider } from '../contexts/ThemeContext'

vi.mock('../contexts/AuthContext', () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => ({ isAuthenticated: true, isLoading: false, user: { username: 'operator' }, logout: vi.fn() }),
}))
vi.mock('../contexts/ApiContext', () => ({
  ApiProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useApi: () => ({ systemStatus: { status: 'healthy' }, errors: {}, prediction: null, isLoading: {}, refreshAll: vi.fn() }),
}))
vi.mock('../pages/Dashboard', () => ({ default: () => <h2>综合总览</h2> }))
vi.mock('../pages/PriceForecast', () => ({ default: () => <h2>电价预测</h2> }))
vi.mock('../pages/SolarGeneration', () => ({ default: () => <h2>ISO-NE 光伏预测</h2> }))

let root: Root
let host: HTMLDivElement
let navigate: NavigateFunction
const Harness = () => {
  navigate = useNavigate()
  return <App />
}
const menuButton = () => host.querySelector<HTMLButtonElement>('button[aria-label="打开菜单"]')!
const closeButton = () => host.querySelector<HTMLButtonElement>('button[aria-label="关闭菜单"]')!
const sidebar = () => host.querySelector('aside')!
const main = () => host.querySelector('main')!
const userMenuButton = () => host.querySelector<HTMLButtonElement>('button[aria-label="用户菜单"]')!

beforeEach(async () => {
  ;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => root.render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ThemeProvider><Harness /></ThemeProvider>
    </MemoryRouter>,
  ))
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
})

it('returns the main scroll container to the top on route changes and back/forward navigation', async () => {
  expect(document.activeElement).not.toBe(menuButton())
  main().scrollTop = 812
  await act(async () => navigate('/price-forecast'))
  expect(main().scrollTop).toBe(0)

  main().scrollTop = 476
  await act(async () => navigate(-1))
  expect(main().scrollTop).toBe(0)

  main().scrollTop = 230
  await act(async () => navigate(1))
  expect(main().scrollTop).toBe(0)
})

it('closes an open mobile menu with Escape and restores focus to its opener', async () => {
  await act(async () => menuButton().click())
  expect(sidebar().classList.contains('translate-x-0')).toBe(true)
  expect(document.activeElement).toBe(closeButton())

  await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Escape', bubbles: true, cancelable: true,
  })))
  expect(sidebar().classList.contains('-translate-x-full')).toBe(true)
  expect(document.activeElement).toBe(menuButton())
})

it('closes the menu for both navigation links and browser history changes', async () => {
  await act(async () => menuButton().click())
  main().scrollTop = 640
  await act(async () => host.querySelector<HTMLAnchorElement>('a[href="/price-forecast"]')!.click())
  expect(sidebar().classList.contains('-translate-x-full')).toBe(true)
  expect(document.activeElement).toBe(menuButton())
  expect(main().scrollTop).toBe(0)

  await act(async () => menuButton().click())
  main().scrollTop = 480
  await act(async () => navigate(-1))
  expect(sidebar().classList.contains('-translate-x-full')).toBe(true)
  expect(document.activeElement).toBe(menuButton())
  expect(main().scrollTop).toBe(0)
})

it('removes a closed mobile sidebar from layout while retaining the desktop display override', async () => {
  expect(sidebar().classList.contains('hidden')).toBe(true)
  expect(sidebar().classList.contains('lg:flex')).toBe(true)
  // CSS display:none removes the mobile subtree from Tab order and the accessibility tree.
  // Avoid a static aria-hidden value that would also hide the visible desktop navigation.
  expect(sidebar().getAttribute('aria-hidden')).toBeNull()

  await act(async () => menuButton().click())
  expect(sidebar().classList.contains('hidden')).toBe(false)
  expect(sidebar().classList.contains('flex')).toBe(true)

  await act(async () => closeButton().click())
  expect(sidebar().classList.contains('hidden')).toBe(true)
  expect(document.activeElement).toBe(menuButton())
})

it('closes the account menu with Escape and restores focus to its trigger', async () => {
  await act(async () => userMenuButton().click())
  expect(userMenuButton().getAttribute('aria-expanded')).toBe('true')
  expect(userMenuButton().getAttribute('aria-controls')).toBe('account-menu')
  const logoutButton = host.querySelector<HTMLButtonElement>('[role="menuitem"]')!
  logoutButton.focus()

  await act(async () => logoutButton.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Escape', bubbles: true, cancelable: true,
  })))
  expect(host.querySelector('[role="menu"]')).toBeNull()
  expect(userMenuButton().getAttribute('aria-expanded')).toBe('false')
  expect(document.activeElement).toBe(userMenuButton())
})

it('closes the account menu on page changes and browser history navigation', async () => {
  await act(async () => userMenuButton().click())
  await act(async () => navigate('/price-forecast'))
  expect(host.querySelector('[role="menu"]')).toBeNull()

  await act(async () => userMenuButton().click())
  await act(async () => navigate(-1))
  expect(host.querySelector('[role="menu"]')).toBeNull()
})

it('closes the account menu on outside clicks without taking focus back', async () => {
  await act(async () => userMenuButton().click())
  menuButton().focus()
  await act(async () => menuButton().dispatchEvent(new MouseEvent('mousedown', { bubbles: true })))
  expect(host.querySelector('[role="menu"]')).toBeNull()
  expect(document.activeElement).toBe(menuButton())
})

it('rejects the removed CAISO route while preserving the ISO-NE solar menu and Eastern context', async () => {
  expect(host.querySelector('a[href="/caiso-solar-generation"]')).toBeNull()
  expect(sidebar().textContent).not.toContain('CAISO')
  await act(async () => navigate('/caiso-solar-generation'))
  expect(main().textContent).toContain('404')
  expect(main().textContent).toContain('页面不存在或已被移除')
  expect(host.textContent).toContain('本地运行 · 美国东部时间')
  expect(host.querySelector('[aria-label="当前时间（新英格兰）"]')).not.toBeNull()
  await act(async () => host.querySelector<HTMLAnchorElement>('a[href="/solar-generation"]')!.click())
  expect(main().textContent).toContain('ISO-NE 光伏预测')
})
