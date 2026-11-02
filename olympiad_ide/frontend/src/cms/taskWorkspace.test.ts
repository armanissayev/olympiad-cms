import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Dexie from 'dexie'
import type { LocalRepository } from '../persistence/repository'
import type { CMSContext } from './types'
const debug = vi.hoisted(() => ({ stop: vi.fn(), assert: vi.fn(), reset: vi.fn() }))
vi.mock('../debug/controller', () => ({ debugging: { stop: debug.stop }, assertDebugStopped: debug.assert, resetDebugController: debug.reset }))
let modules: {
  session: typeof import('./session'); workspace: typeof import('../store/workspaceStore'); db: typeof import('../persistence/database');
  save: typeof import('../persistence/controller'); resources: typeof import('../execution/resources'); runs: typeof import('../execution/controller');
  recording: typeof import('../telemetry/collector'); sync: typeof import('../telemetry/telemetrySync'); api: typeof import('../persistence/api');
  switching: typeof import('./taskWorkspace'); repository: typeof import('../persistence/repository')
}
let installation: string
const context = (): CMSContext => ({ schemaVersion: 1, identity: { installationId: installation, userId: 1, contestId: 1, participationId: 1, principalId: '45b6ea68-30bf-5d34-971d-898a335ad99a' }, user: { username: 'test', firstName: '', lastName: '' }, contest: { id: 1, name: 'test', description: 'Test contest' }, actualPhase: 0, serverTime: new Date().toISOString(), phaseEnd: null, csrfToken: 'test-only', tasks: [1, 2].map(id => ({ id, name: `task${id}`, title: `Task ${id}`, languages: [{ id: 'CPP', name: 'C++', extension: '.cpp' }], submissionFormat: ['main.%l'], supported: true, statements: [], attachments: [], statementUrl: '/', submissionsUrl: '/' })), links: { login: '/login', logout: '/logout', fallback: '/', announcements: '/', clarifications: '/' } })
beforeEach(async () => {
  vi.resetModules(); vi.stubEnv('VITE_CMS_MODE', 'true'); vi.stubEnv('BASE_URL', '/ide/')
  debug.stop.mockReset().mockResolvedValue(undefined); debug.assert.mockReset(); debug.reset.mockReset().mockResolvedValue(undefined)
  installation = 'scope-switch-' + crypto.randomUUID()
  const session = await import('./session'); session.useCMSSession.setState({ context: context(), taskId: 1, paused: false, switching: false })
  modules = { session, workspace: await import('../store/workspaceStore'), db: await import('../persistence/database'), save: await import('../persistence/controller'), resources: await import('../execution/resources'), runs: await import('../execution/controller'), recording: await import('../telemetry/collector'), sync: await import('../telemetry/telemetrySync'), api: await import('../persistence/api'), switching: await import('./taskWorkspace'), repository: await import('../persistence/repository') }
  modules.workspace.useWorkspaceStore.setState(modules.workspace.initialData())
  modules.workspace.useWorkspaceStore.getState().updateSettings({ autoSave: 'off' })
  vi.spyOn(modules.api.WorkspaceAPI.prototype, 'session').mockRejectedValue(new Error('Offline test backend'))
  vi.spyOn(modules.api.WorkspaceAPI.prototype, 'request').mockImplementation(async (path, init) => {
    let result: unknown = {}
    if (path === '/execution-capacity') result = { workers: 1 }
    else if (path.endsWith('/executions') || path.endsWith('/execution-resources')) result = []
    else if (path === '/telemetry/policy') result = { retentionDays: 30 }
    else if (path === '/telemetry/batches') {
      const body = JSON.parse(init!.body as string)
      result = { batchId: body.id, sessionId: body.sessionId, digest: body.digest, lastSequence: body.events.at(-1)?.sequence ?? 0, serverTimestamp: new Date().toISOString() }
    }
    return result as never
  })
  await modules.save.persistence.start(); await modules.recording.telemetry.start()
  modules.workspace.useWorkspaceStore.getState().setFileContent(modules.workspace.seedFileIds.main, 'task-one-source')
  modules.resources.executionResources.select({ stdin: 'input-one' })
  await modules.save.persistence.flush(); await modules.resources.executionResources.flush()
})
afterEach(async () => {
  await Promise.allSettled([modules.save.persistence.suspend(), modules.runs.executions.suspend(), modules.resources.executionResources.suspend(), modules.sync.telemetrySync.suspend()])
  await modules.recording.telemetry.flush(); modules.recording.telemetry.stop()
  modules.db.database.close()
  for (const name of await Dexie.getDatabaseNames()) if (name.includes(installation)) await Dexie.delete(name)
  vi.restoreAllMocks(); vi.unstubAllEnvs()
})
it('switches in the same document and restores independent source, workspace identity and stdin when returning', async () => {
  const href = location.href, oldName = modules.db.database.name, oldId = modules.workspace.useWorkspaceStore.getState().workspace.id
  const opening = vi.spyOn(window, 'open')
  await modules.switching.switchTaskWorkspace(2)
  expect(location.href).toBe(href); expect(opening).not.toHaveBeenCalled()
  expect(modules.session.useCMSSession.getState()).toMatchObject({ taskId: 2, switching: false })
  expect(modules.db.database.name).not.toBe(oldName)
  expect(modules.workspace.useWorkspaceStore.getState().workspace.id).not.toBe(oldId)
  modules.workspace.useWorkspaceStore.getState().setFileContent(modules.workspace.seedFileIds.main, 'task-two-source')
  await vi.waitFor(() => expect(modules.resources.useExecutionResources.getState().stdin).toBe(''))
  modules.resources.executionResources.select({ stdin: 'input-two' })
  await modules.switching.switchTaskWorkspace(1)
  expect(modules.db.database.name).toBe(oldName)
  expect(modules.workspace.useWorkspaceStore.getState().workspace.id).toBe(oldId)
  expect(modules.workspace.useWorkspaceStore.getState().nodes[modules.workspace.seedFileIds.main]).toMatchObject({ content: 'task-one-source' })
  await vi.waitFor(() => expect(modules.resources.useExecutionResources.getState().stdin).toBe('input-one'))
  await modules.switching.switchTaskWorkspace(2)
  expect(modules.workspace.useWorkspaceStore.getState().nodes[modules.workspace.seedFileIds.main]).toMatchObject({ content: 'task-two-source' })
  await vi.waitFor(() => expect(modules.resources.useExecutionResources.getState().stdin).toBe('input-two'))
})
it('keeps old task authority until an in-flight old workspace upload has committed', async () => {
  vi.mocked(modules.api.WorkspaceAPI.prototype.session).mockResolvedValue({ identityId: context().identity.principalId })
  const oldId = modules.workspace.useWorkspaceStore.getState().workspace.id, calls: { task: number | null; id: string }[] = []
  let release!: () => void
  vi.spyOn(modules.api.WorkspaceAPI.prototype, 'send').mockImplementation(async operation => {
    calls.push({ task: modules.session.useCMSSession.getState().taskId, id: operation.workspaceId })
    await new Promise<void>(resolve => { release = resolve })
    return { acknowledgements: [{ operationId: operation.operationId, revision: 1 }] }
  })
  vi.spyOn(modules.api.WorkspaceAPI.prototype, 'status').mockResolvedValue({ revision: 1 })
  const uploading = modules.save.persistence.syncNow(true)
  await vi.waitFor(() => expect(calls).toHaveLength(1))
  const changing = modules.switching.switchTaskWorkspace(2)
  await vi.waitFor(() => expect(modules.session.useCMSSession.getState().switching).toBe(true))
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(modules.session.useCMSSession.getState().taskId).toBe(1)
  release(); await uploading; await changing
  expect(calls).toEqual([{ task: 1, id: oldId }])
  expect(modules.session.useCMSSession.getState().taskId).toBe(2)
})
it('keeps current source and recording when the next problem database cannot be prepared', async () => {
  const original = modules.repository.LocalRepository.prototype.initialize
  vi.spyOn(modules.repository.LocalRepository.prototype, 'initialize').mockImplementation(function (this: LocalRepository, legacy, seed) {
    if (this.db.name.endsWith('.task.2')) return Promise.reject(new Error('Storage unavailable'))
    return original.call(this, legacy, seed)
  })
  const id = modules.recording.telemetry.session.id, db = modules.db.database
  await expect(modules.switching.switchTaskWorkspace(2)).rejects.toThrow('Storage unavailable')
  expect(modules.db.database).toBe(db); expect(modules.session.useCMSSession.getState()).toMatchObject({ taskId: 1, switching: false })
  expect(modules.recording.telemetry.session.id).toBe(id)
  expect(modules.workspace.useWorkspaceStore.getState().nodes[modules.workspace.seedFileIds.main]).toMatchObject({ content: 'task-one-source' })
  expect(debug.stop).not.toHaveBeenCalled()
})
it('rolls back a failed handoff and retains both task databases without losing the original source', async () => {
  const oldName = modules.db.database.name, oldId = modules.workspace.useWorkspaceStore.getState().workspace.id
  debug.reset.mockRejectedValueOnce(new Error('Breakpoint storage unavailable')).mockResolvedValue(undefined)
  await expect(modules.switching.switchTaskWorkspace(2)).rejects.toThrow('Breakpoint storage unavailable')
  expect(modules.session.useCMSSession.getState()).toMatchObject({ taskId: 1, switching: false })
  expect(modules.db.database.name).toBe(oldName); expect(modules.workspace.useWorkspaceStore.getState().workspace.id).toBe(oldId)
  expect(modules.workspace.useWorkspaceStore.getState().nodes[modules.workspace.seedFileIds.main]).toMatchObject({ content: 'task-one-source' })
  expect((await Dexie.getDatabaseNames()).filter(name => name.includes(installation))).toHaveLength(2)
  expect(modules.recording.telemetry.session.completedAt).toBeNull()
})
it('refuses to change scope while stopping a debugger remains unconfirmed', async () => {
  debug.assert.mockImplementation(() => { throw new Error('Stop unconfirmed') })
  const db = modules.db.database
  await expect(modules.switching.switchTaskWorkspace(2)).rejects.toThrow('Stop unconfirmed')
  expect(modules.db.database).toBe(db); expect(modules.session.useCMSSession.getState().taskId).toBe(1)
  expect(modules.recording.telemetry.session.completedAt).toBeNull()
})

it('restores local source with remote operations paused if the old task disappears during a failed handoff', async () => {
  const oldName = modules.db.database.name, oldId = modules.workspace.useWorkspaceStore.getState().workspace.id
  debug.reset.mockImplementationOnce(async () => {
    const current = modules.session.useCMSSession.getState().context!
    modules.session.useCMSSession.setState({ context: { ...current, tasks: current.tasks.filter(task => task.id !== 1) } })
    throw new Error('Handoff interrupted after roster change')
  }).mockResolvedValue(undefined)
  vi.mocked(modules.api.WorkspaceAPI.prototype.session).mockImplementation(async () => {
    modules.session.trustedHeaders(true)
    return { identityId: context().identity.principalId }
  })
  const remoteWhilePaused: string[] = []
  vi.mocked(modules.api.WorkspaceAPI.prototype.request).mockImplementation(async path => {
    if (modules.session.useCMSSession.getState().paused) remoteWhilePaused.push(path)
    return [] as never
  })
  await expect(modules.switching.switchTaskWorkspace(2)).rejects.toThrow('Handoff interrupted after roster change')
  expect(modules.db.database.name).toBe(oldName)
  expect(modules.workspace.useWorkspaceStore.getState().workspace.id).toBe(oldId)
  expect(modules.workspace.useWorkspaceStore.getState().nodes[modules.workspace.seedFileIds.main]).toMatchObject({ content: 'task-one-source' })
  const restored = modules.session.useCMSSession.getState()
  expect(restored).toMatchObject({ taskId: 1, paused: true, switching: false })
  expect(restored.context?.tasks.map(task => task.id)).toEqual([2])
  expect(restored.context?.identity.principalId).toBe(context().identity.principalId)
  expect(() => modules.session.trustedHeaders(true)).toThrow('paused')
  const recovery = JSON.parse(sessionStorage.getItem('olympiad-cms-recovery:/ide/')!)
  expect(recovery.taskId).toBe(1); expect(recovery.context.csrfToken).toBe('')
  expect(localStorage.getItem(`olympiad-cms-task:${context().identity.principalId}`)).toBe('1')
  await new Promise(resolve => setTimeout(resolve, 20))
  expect(remoteWhilePaused).toEqual([])
})
