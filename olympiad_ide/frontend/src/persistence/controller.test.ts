import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkspaceStore, seedFileIds } from '../store/workspaceStore'
import { WorkspaceDatabase } from './database'
import { LocalRepository } from './repository'
import { PersistenceController } from './controller'
import { RequestError, retryDelay, WorkspaceAPI } from './api'
import { usePersistenceStatus } from './status'
import { toDocument } from './types'

let db: WorkspaceDatabase
let repository: LocalRepository
let controller: PersistenceController
let api: WorkspaceAPI

beforeEach(() => {
  useWorkspaceStore.getState().reset()
  usePersistenceStatus.setState({ status: 'Loading', ready: false, online: false, localPending: 0,
    pendingOperations: 0, lastSyncedAt: null, error: null, conflict: null, detailsOpen: false })
  db = new WorkspaceDatabase(`controller-${crypto.randomUUID()}`)
  repository = new LocalRepository(db)
  api = new WorkspaceAPI()
  vi.spyOn(api, 'session').mockRejectedValue(new Error('Backend down'))
  controller = new PersistenceController(repository, api, 400)
})

afterEach(async () => { controller.stop(); vi.restoreAllMocks(); vi.useRealTimers(); await db.delete() })

describe('local autosave and synchronization controller', () => {
  it('commits rapid edits immediately even when debounce timers never fire and auto-save is off', async () => {
    await controller.start()
    useWorkspaceStore.getState().updateSettings({ autoSave: 'off' })
    for (let index = 1; index <= 30; index++) useWorkspaceStore.getState().setFileContent(seedFileIds.main, `revision ${index}`)
    await controller.flush()
    const state = useWorkspaceStore.getState()
    expect((await repository.load(state.workspace.id))?.state.nodes[seedFileIds.main]).toMatchObject({ content: 'revision 30' })
    expect((await repository.pending(state.workspace.id)).at(-1)?.document.nodes[seedFileIds.main]).toMatchObject({ content: 'revision 30' })
    expect(usePersistenceStatus.getState()).toMatchObject({ localPending: 0, status: 'Offline', error: null })
  })

  it('reports a failed local write and recovers current work on Retry', async () => {
    await controller.start()
    const failure = vi.spyOn(repository, 'commit').mockRejectedValue(new Error('Storage quota exceeded'))
    useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'still in memory')
    await expect(controller.flush()).rejects.toThrow('Storage quota exceeded')
    expect(usePersistenceStatus.getState().status).toBe('Save Error')
    expect(useWorkspaceStore.getState().nodes[seedFileIds.main]).toMatchObject({ content: 'still in memory' })
    failure.mockRestore()
    await controller.flush()
    expect((await repository.load(useWorkspaceStore.getState().workspace.id))?.state.nodes[seedFileIds.main]).toMatchObject({ content: 'still in memory' })
  })

  it('does not mark synchronized until the matching server acknowledgement commits', async () => {
    await controller.start()
    vi.mocked(api.session).mockResolvedValue({ identityId: 'development-owner' })
    const send = vi.spyOn(api, 'send').mockImplementation(async (op) => ({ acknowledgements: [{ operationId: op.operationId, revision: op.baseRevision + 1 }] }))
    vi.spyOn(api, 'status').mockResolvedValue({ revision: 1 })
    await controller.syncNow()
    expect(send).toHaveBeenCalledOnce()
    expect(usePersistenceStatus.getState()).toMatchObject({ status: 'Synced', pendingOperations: 0, online: true })
    expect((await db.workspaces.toArray())[0]?.lastSyncedRevision).toBe(1)
  })

  it('keeps stale local text when the server returns a conflict', async () => {
    await controller.start()
    vi.mocked(api.session).mockResolvedValue({ identityId: 'owner' })
    useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'my local branch')
    await controller.flush()
    const serverDoc = structuredClone(toDocument(useWorkspaceStore.getState()))
    const node = serverDoc.nodes[seedFileIds.main]!
    if (node.type === 'file') node.content = 'different server branch'
    const server = { ...repository.asServer(useWorkspaceStore.getState(), 9), document: serverDoc }
    vi.spyOn(api, 'send').mockRejectedValue(new RequestError(409, 'Conflict', server))
    await controller.syncNow()
    const state = usePersistenceStatus.getState()
    expect(state.status).toBe('Conflict')
    expect(state.conflict?.local.nodes[seedFileIds.main]).toMatchObject({ content: 'my local branch' })
    expect(state.conflict?.server.document.nodes[seedFileIds.main]).toMatchObject({ content: 'different server branch' })
    expect(await db.conflicts.count()).toBe(1)
    expect(await db.syncOperations.count()).toBe(1)
  })

  it('refuses a reviewed resolution if the server changed again', async () => {
    await controller.start()
    vi.mocked(api.session).mockResolvedValue({ identityId: 'owner' })
    const server = repository.asServer(useWorkspaceStore.getState(), 3)
    const conflict = await repository.recordConflict(toDocument(useWorkspaceStore.getState()), server)
    usePersistenceStatus.setState({ conflict })
    vi.spyOn(api, 'get').mockResolvedValue({ ...server, revision: 4 })
    await expect(controller.resolve('local')).rejects.toThrow('server changed again')
    expect(usePersistenceStatus.getState().conflict?.server.revision).toBe(4)
  })

  it('uses bounded exponential retry delays with jitter', () => {
    expect(retryDelay(0, () => 0.5)).toBe(1000)
    expect(retryDelay(1, () => 0.5)).toBe(2000)
    expect(retryDelay(100, () => 0)).toBe(24_000)
    expect(retryDelay(100, () => 1)).toBe(36_000)
  })
})
