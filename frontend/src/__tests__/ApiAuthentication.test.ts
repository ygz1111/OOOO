// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({ request: vi.fn(), post: vi.fn(), defaults: { timeout: 30000 } }))
vi.mock('axios', async importOriginal => {
  const original = await importOriginal<typeof import('axios')>()
  return { ...original, default: { ...original.default, create: () => client } }
})

const TOKEN_KEY = 'smartgrid_access_token'
const REFRESH_KEY = 'smartgrid_refresh_token'
const rejected = (status?: number, detail = '服务暂时不可用', code?: string) => ({
  isAxiosError: true,
  response: status === undefined ? undefined : { status, data: { detail } },
  code,
})
const deferred = () => {
  let resolve!: (value: any) => void
  let reject!: (reason: any) => void
  const promise = new Promise<any>((success, failure) => { resolve = success; reject = failure })
  return { promise, resolve, reject }
}
let service: typeof import('../services/api').apiService
let unauthorized: ReturnType<typeof vi.fn>
let refreshed: ReturnType<typeof vi.fn>
const authorize = (token = 'test-access', refreshToken = 'test-refresh') => {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(REFRESH_KEY, refreshToken)
  service.setAuthToken(token)
}

beforeEach(async () => {
  vi.resetModules()
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  service = (await import('../services/api')).apiService
  unauthorized = vi.fn()
  refreshed = vi.fn()
  service.setOnUnauthorized(unauthorized)
  service.setOnTokenRefreshed(refreshed)
})

it('preserves authenticated requests for ISO-NE solar predictions and model metadata', async () => {
  authorize()
  client.request.mockResolvedValue({ data: { status: 'ready' } })
  await service.getSolarModelInfo()
  await service.getSolarGeneration(true)
  const requests = client.request.mock.calls.map(([config]) => config)
  expect(requests.map(config => config.url)).toEqual(['/solar-generation/model-info', '/solar-generation'])
  expect(requests.every(config => config.headers.Authorization === 'Bearer test-access')).toBe(true)
  expect(requests[1].params).toEqual({ force_refresh: true })
})

it('a rejected login does not trigger logout or block a later authenticated refresh', async () => {
  client.request.mockRejectedValueOnce(rejected(401, '用户名或密码错误'))
  await expect(service.login({ username: 'test-user', password: 'test-password', remember_me: true })).rejects.toThrow('用户名或密码错误')
  expect(unauthorized).not.toHaveBeenCalled()
  authorize()
  client.request.mockRejectedValueOnce(rejected(401)).mockResolvedValueOnce({ data: { status: 'ok' } })
  client.post.mockResolvedValueOnce({ data: { access_token: 'renewed-access', refresh_token: 'test-refresh' } })
  await expect(service.getSystemStatus()).resolves.toEqual({ status: 'ok' })
  expect(client.post).toHaveBeenCalledTimes(1)
  expect(refreshed).toHaveBeenCalledWith('renewed-access')
})

it.each([
  ['network interruption', rejected(), '网络连接中断'],
  ['temporary backend failure', rejected(503), '服务暂时不可用'],
])('preserves credentials after %s during refresh and recovers on retry', async (_label, failure, message) => {
  authorize()
  client.request.mockRejectedValueOnce(rejected(401))
  client.post.mockRejectedValueOnce(failure)
  await expect(service.getSystemStatus()).rejects.toThrow(message as string)
  expect(localStorage.getItem(TOKEN_KEY)).toBe('test-access')
  expect(localStorage.getItem(REFRESH_KEY)).toBe('test-refresh')
  expect(unauthorized).not.toHaveBeenCalled()
  client.request.mockRejectedValueOnce(rejected(401)).mockResolvedValueOnce({ data: { status: 'recovered' } })
  client.post.mockResolvedValueOnce({ data: { access_token: 'renewed-access' } })
  await expect(service.getSystemStatus()).resolves.toEqual({ status: 'recovered' })
  expect(client.post).toHaveBeenCalledTimes(2)
})

it('clears genuinely rejected refresh credentials and invokes logout', async () => {
  authorize()
  client.request.mockRejectedValueOnce(rejected(401))
  client.post.mockRejectedValueOnce(rejected(401, '刷新令牌已失效'))
  await expect(service.getSystemStatus()).rejects.toThrow()
  expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  expect(localStorage.getItem(REFRESH_KEY)).toBeNull()
  expect(unauthorized).toHaveBeenCalledTimes(1)
})

it('a missing refresh token does not leave a completed refresh promise for the next login', async () => {
  service.setAuthToken('access-without-refresh')
  client.request.mockRejectedValueOnce(rejected(401))
  await expect(service.getSystemStatus()).rejects.toThrow()
  authorize('next-session-access', 'next-session-refresh')
  client.request.mockRejectedValueOnce(rejected(401)).mockResolvedValueOnce({ data: { status: 'ok' } })
  client.post.mockResolvedValueOnce({ data: { access_token: 'renewed-access' } })
  await expect(service.getSystemStatus()).resolves.toEqual({ status: 'ok' })
  expect(client.post).toHaveBeenCalledTimes(1)
})

it('keeps a non-remembered session in sessionStorage when refreshing', async () => {
  sessionStorage.setItem(TOKEN_KEY, 'session-access')
  sessionStorage.setItem(REFRESH_KEY, 'session-refresh')
  service.setAuthToken('session-access')
  client.request.mockRejectedValueOnce(rejected(401)).mockResolvedValueOnce({ data: { status: 'ok' } })
  client.post.mockResolvedValueOnce({ data: { access_token: 'renewed-session-access' } })
  await service.getSystemStatus()
  expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  expect(localStorage.getItem(REFRESH_KEY)).toBeNull()
  expect(sessionStorage.getItem(TOKEN_KEY)).toBe('renewed-session-access')
  expect(sessionStorage.getItem(REFRESH_KEY)).toBe('session-refresh')
})

it('does not restore credentials when an old refresh completes after logout', async () => {
  authorize()
  const refresh = deferred()
  client.request.mockRejectedValueOnce(rejected(401))
  client.post.mockReturnValueOnce(refresh.promise)
  const pending = service.getSystemStatus().catch(error => error)
  await vi.waitFor(() => expect(client.post).toHaveBeenCalledTimes(1))
  localStorage.clear()
  service.setAuthToken(null)
  refresh.resolve({ data: { access_token: 'old-session-access', refresh_token: 'old-session-refresh' } })
  expect(await pending).toBeInstanceOf(Error)
  expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  expect(localStorage.getItem(REFRESH_KEY)).toBeNull()
  expect(refreshed).not.toHaveBeenCalled()
  expect(unauthorized).not.toHaveBeenCalled()
  expect(client.request).toHaveBeenCalledTimes(1)
})

it('does not let a late unauthorized response clear or refresh a new login', async () => {
  authorize()
  const oldRequest = deferred()
  client.request.mockReturnValueOnce(oldRequest.promise)
  const pending = service.getSystemStatus().catch(error => error)
  authorize('new-session-access', 'new-session-refresh')
  oldRequest.reject(rejected(401))
  expect(await pending).toBeInstanceOf(Error)
  expect(client.post).not.toHaveBeenCalled()
  expect(unauthorized).not.toHaveBeenCalled()
  expect(localStorage.getItem(TOKEN_KEY)).toBe('new-session-access')
})

it('keeps GET requests separate across sessions and old cleanup cannot remove the new pending request', async () => {
  authorize()
  const oldRequest = deferred()
  const newRequest = deferred()
  client.request.mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(newRequest.promise)
  const old = service.getSystemStatus().catch(error => error)
  authorize('new-session-access', 'new-session-refresh')
  const current = service.getSystemStatus()
  expect(client.request).toHaveBeenCalledTimes(2)
  oldRequest.resolve({ data: { status: 'old-session' } })
  expect(await old).toBeInstanceOf(Error)
  const duplicate = service.getSystemStatus()
  expect(client.request).toHaveBeenCalledTimes(2)
  newRequest.resolve({ data: { status: 'current-session' } })
  await expect(current).resolves.toEqual({ status: 'current-session' })
  await expect(duplicate).resolves.toEqual({ status: 'current-session' })
})

it('normalizes timeout errors from the authenticated retry', async () => {
  authorize()
  client.request.mockRejectedValueOnce(rejected(401)).mockRejectedValueOnce(rejected(undefined, '', 'ECONNABORTED'))
  client.post.mockResolvedValueOnce({ data: { access_token: 'renewed-access' } })
  await expect(service.getSystemStatus()).rejects.toThrow('请求超时（等待超过 30 秒）')
  expect(unauthorized).not.toHaveBeenCalled()
})

it('invokes logout when the renewed access token is still rejected', async () => {
  authorize()
  client.request.mockRejectedValueOnce(rejected(401)).mockRejectedValueOnce(rejected(401, '会话已注销'))
  client.post.mockResolvedValueOnce({ data: { access_token: 'renewed-access' } })
  await expect(service.getSystemStatus()).rejects.toThrow('会话已注销')
  expect(unauthorized).toHaveBeenCalledTimes(1)
})

it('shares a single refresh across different concurrent protected requests', async () => {
  authorize()
  const refresh = deferred()
  client.request.mockRejectedValueOnce(rejected(401)).mockRejectedValueOnce(rejected(401))
    .mockResolvedValue({ data: { status: 'ok' } })
  client.post.mockReturnValueOnce(refresh.promise)
  const pending = Promise.all([service.getSystemStatus(), service.getHealth()])
  await vi.waitFor(() => expect(client.post).toHaveBeenCalledTimes(1))
  refresh.resolve({ data: { access_token: 'renewed-access' } })
  await pending
  expect(client.post).toHaveBeenCalledTimes(1)
  expect(refreshed).toHaveBeenCalledTimes(1)
})
