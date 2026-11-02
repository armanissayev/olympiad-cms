import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { CMSContext } from './types'

const principal = '45b6ea68-30bf-5d34-971d-898a335ad99a'
const context = (): CMSContext => ({ schemaVersion: 1, identity: { installationId: 'local-test', userId: 1, contestId: 2, participationId: 3, principalId: principal }, user: { username: 'alice', firstName: 'Alice', lastName: '' }, contest: { id: 2, name: 'test', description: 'Test contest' }, actualPhase: 0, serverTime: '2026-11-02T09:00:00Z', phaseEnd: '2026-11-02T12:00:00Z', csrfToken: 'csrf-for-test', tasks: [{ id: 7, name: 'sum', title: 'Sum', languages: [{ id: 'CPP17', name: 'C++17', extension: '.cpp' }], submissionFormat: ['main.%l'], supported: true, statements: [], attachments: [], statementUrl: '/tasks/sum', submissionsUrl: '/tasks/sum/submissions' }], links: { login: '/login', logout: '/logout', fallback: '/', announcements: '/communication', clarifications: '/communication' } })
beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_CMS_MODE', 'true'); vi.stubEnv('BASE_URL', '/ide/'); sessionStorage.clear(); localStorage.clear() })
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks() })
it('binds all runtime requests to stable participant and selected task, never stores CSRF in recovery cache', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(context()))))
  const s = await import('./session'); await s.initializeCMS()
  expect(s.runtimeURL('/workspaces')).toBe('/ide/api/runtime/v1/workspaces')
  expect(s.trustedHeaders(true)).toEqual({ 'X-Olympiad-Principal': principal, 'X-Olympiad-Task': '7', 'X-XSRFToken': 'csrf-for-test' })
  expect(s.databaseName()).toContain(`${principal}.task.7`)
  expect(sessionStorage.getItem('olympiad-cms-recovery:/ide/')).not.toContain('csrf-for-test')
})
it('retains the old workspace authority and pauses every transport after a CMS account switch', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(context()))).mockResolvedValueOnce(new Response(JSON.stringify({ ...context(), identity: { ...context().identity, principalId: '55b6ea68-30bf-5d34-971d-898a335ad99a' } })))
  vi.stubGlobal('fetch', fetcher)
  const s = await import('./session'); await s.initializeCMS(); const original = s.databaseName(); await s.checkCMSContext()
  expect(s.useCMSSession.getState().paused).toBe(true); expect(s.databaseName()).toBe(original)
  expect(() => s.trustedHeaders(true)).toThrow('paused')
})
it('allows same-tab offline local recovery without authorizing uploads', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(context()))).mockRejectedValueOnce(new Error('offline')))
  const s = await import('./session'); await s.initializeCMS(); await s.initializeCMS()
  expect(s.useCMSSession.getState().context?.identity.principalId).toBe(principal)
  expect(s.useCMSSession.getState().paused).toBe(true)
  expect(() => s.trustedHeaders()).toThrow('paused')
})
it('does not use cached authority after explicit authentication denial', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(context()))).mockResolvedValueOnce(new Response('{}', { status: 401 })))
  const s = await import('./session'); await s.initializeCMS(); await expect(s.initializeCMS()).rejects.toThrow('Sign in')
  expect(sessionStorage.getItem('olympiad-cms-recovery:/ide/')).toBeNull()
})
it('retains local task storage after deadline while separating receipt access from protected runtime operations', async () => {
  localStorage.setItem(`olympiad-cms-task:${principal}`, '7')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...context(), actualPhase: 4, tasks: [] }))))
  const s = await import('./session'); await s.initializeCMS()
  expect(s.databaseName()).toContain('.task.7')
  expect(() => s.trustedHeaders(true)).toThrow('task is not currently authorized')
  expect(s.trustedHeaders()['X-Olympiad-Principal']).toBe(principal)
})
it('never follows untrusted schemes or cross-origin CMS links', async () => {
  const s = await import('./session')
  expect(s.safeCMSLink('javascript:alert(1)')).toBeUndefined()
  expect(s.safeCMSLink('https://another.invalid/secret')).toBeUndefined()
  expect(s.safeCMSLink('/login')).toBe(`${location.origin}/login`)
})
