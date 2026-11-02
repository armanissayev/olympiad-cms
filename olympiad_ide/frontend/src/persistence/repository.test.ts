import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import Dexie from 'dexie'
import { initialData, seedFileIds } from '../store/workspaceStore'
import { WorkspaceDatabase } from './database'
import { LocalRepository, contentHash } from './repository'
import { migratePhase1 } from './migration'
import { toDocument } from './types'

let db: WorkspaceDatabase
let repository: LocalRepository
beforeEach(() => {
  db = new WorkspaceDatabase(`test-${crypto.randomUUID()}`)
  repository = new LocalRepository(db, 0, 3)
})
afterEach(async () => { await db.delete() })

describe('IndexedDB durability and migration', () => {
  it('initializes all tables and migrates Phase 1 exactly once without deleting its backup', async () => {
    const seed = initialData()
    seed.splitEnabled = true
    seed.groups.secondary = { id: 'secondary', activeFileId: seedFileIds.main, tabIds: [seedFileIds.main] }
    seed.settings.theme = 'light'
    const raw = JSON.stringify({ state: seed, version: 1 })
    localStorage.setItem('olympiad-ide-phase1', raw)
    await repository.initialize(raw, initialData())
    const restored = await repository.initialize(raw, initialData())
    expect(restored).toMatchObject({ workspace: { id: seed.workspace.id }, splitEnabled: true, settings: { theme: 'light' } })
    expect(restored.groups.secondary.activeFileId).toBe(restored.groups.primary.activeFileId)
    expect(await db.workspaces.count()).toBe(1)
    expect(await db.syncOperations.count()).toBe(1)
    expect(await db.metadata.get('phase1Migration')).toMatchObject({ value: 'verified-v2' })
    expect(localStorage.getItem('olympiad-ide-phase1')).toBe(raw)
    expect(db.tables.map((table) => table.name)).toContain('testCases')
  })

  it.each([1, 2])('upgrades existing IndexedDB v%i without deleting Phase 2 data or queued operations', async (version) => {
    const old = new Dexie(db.name)
    old.version(1).stores({
      workspaces: 'id', fileNodes: '[workspaceId+id], workspaceId', editorSessions: 'workspaceId',
      workspaceSettings: 'workspaceId', syncOperations: '++sequence, &operationId, workspaceId, status',
      recoverySnapshots: 'snapshotId, workspaceId, [workspaceId+fileId], createdAt', testCases: 'id, workspaceId', metadata: 'key',
    })
    if (version === 2) old.version(2).stores({ conflicts: 'workspaceId' })
    await old.open()
    const seed = initialData()
    await old.table('fileNodes').bulkPut(Object.values(seed.nodes).map(node => ({ workspaceId: seed.workspace.id, id: node.id, node, deletedAt: null })))
    await old.table('workspaceSettings').put({ workspaceId: seed.workspace.id, settings: seed.settings })
    await old.table('editorSessions').put({ workspaceId: seed.workspace.id, state: { groups: seed.groups, splitEnabled: true } })
    await old.table('syncOperations').add({ operationId: 'retained', workspaceId: 'w', status: 'sending' })
    old.close()
    await db.open()
    expect(db.verno).toBe(5)
    expect(await db.officialSubmissionIntents.count()).toBe(0)
    expect(await db.syncOperations.toArray()).toMatchObject([{ operationId: 'retained', status: 'sending', ...(version === 1 ? { retryCount: 0 } : {}) }])
    expect(Object.fromEntries((await db.fileNodes.toArray()).map(row => [row.id, row.node]))).toEqual(seed.nodes)
    expect((await db.workspaceSettings.get(seed.workspace.id))?.settings).toEqual(seed.settings)
    expect((await db.editorSessions.get(seed.workspace.id))?.state).toMatchObject({ groups: seed.groups, splitEnabled: true })
    expect(await db.telemetryEvents.count()).toBe(0)
  })

  it('rejects malformed legacy data and never overwrites it with a seed', async () => {
    await expect(repository.initialize('{broken', initialData())).rejects.toThrow()
    expect(await db.workspaces.count()).toBe(0)
    expect(() => migratePhase1(JSON.stringify({ state: { workspace: { id: 'bad' } } }))).toThrow()
  })

  it('atomically recovers files, queue, settings and layout after the database connection closes', async () => {
    const seed = await repository.initialize(null, initialData())
    const version = (await repository.load(seed.workspace.id))!.metadata.localVersion
    const next = structuredClone(seed)
    const node = next.nodes[seedFileIds.main]!
    if (node.type === 'file') node.content = 'Unicode: Ω你好\nexact trailing spaces  \n'
    next.settings.fontSize = 19
    next.splitEnabled = true
    await repository.commit(next, version)
    db.close()
    await db.open()
    const recovered = await repository.load(seed.workspace.id)
    expect(recovered?.state.nodes[seedFileIds.main]).toEqual(next.nodes[seedFileIds.main])
    expect(recovered?.state).toMatchObject({ splitEnabled: true, settings: { fontSize: 19 } })
    expect((await repository.pending(seed.workspace.id)).at(-1)?.document.nodes).toEqual(next.nodes)
  })

  it('rolls back file writes together with the journal on a transaction failure', async () => {
    const seed = await repository.initialize(null, initialData())
    const version = (await repository.load(seed.workspace.id))!.metadata.localVersion
    const original = seed.nodes[seedFileIds.main]
    const changed = structuredClone(seed)
    const node = changed.nodes[seedFileIds.main]!
    if (node.type === 'file') node.content = 'must not commit'
    const hook = () => { throw new Error('QuotaExceededError') }
    db.fileNodes.hook('updating', hook)
    await expect(repository.commit(changed, version)).rejects.toThrow('QuotaExceededError')
    db.fileNodes.hook('updating').unsubscribe(hook)
    expect((await repository.load(seed.workspace.id))?.state.nodes[seedFileIds.main]).toEqual(original)
    expect((await repository.pending(seed.workspace.id))[0]?.document.nodes[seedFileIds.main]).toEqual(original)
  })
})

describe('journal ordering, conflict preservation and recovery snapshots', () => {
  it('compacts unsent work but never changes a sending/retried operation', async () => {
    const seed = await repository.initialize(null, initialData())
    const first = (await repository.pending(seed.workspace.id))[0]!
    await db.syncOperations.update(first.sequence!, { status: 'sending' })
    let version = (await repository.load(seed.workspace.id))!.metadata.localVersion
    for (const content of ['second edit', 'third edit']) {
      const node = seed.nodes[seedFileIds.main]!
      if (node.type === 'file') node.content = content
      version = (await repository.commit(seed, version)).version
    }
    const queue = await repository.pending(seed.workspace.id)
    expect(queue).toHaveLength(2)
    expect(queue[0]?.document).toEqual(first.document)
    expect(queue.map((op) => op.baseRevision)).toEqual([0, 1])
    expect(queue[1]?.document.nodes[seedFileIds.main]).toMatchObject({ content: 'third edit' })
    await repository.acknowledge(first.sequence!, 1)
    expect((await repository.pending(seed.workspace.id))[0]?.baseRevision).toBe(1)
  })

  it('preserves both same-browser branches instead of overwriting another tab', async () => {
    const seed = await repository.initialize(null, initialData())
    const version = (await repository.load(seed.workspace.id))!.metadata.localVersion
    const a = structuredClone(seed)
    const b = structuredClone(seed)
    const an = a.nodes[seedFileIds.main]!
    const bn = b.nodes[seedFileIds.main]!
    if (an.type === 'file') an.content = 'tab A'
    if (bn.type === 'file') bn.content = 'tab B'
    await repository.commit(a, version)
    const result = await repository.commit(b, version)
    expect(result.conflict?.local.nodes[seedFileIds.main]).toMatchObject({ content: 'tab B' })
    expect(result.conflict?.server.document.nodes[seedFileIds.main]).toMatchObject({ content: 'tab A' })
    expect((await repository.load(seed.workspace.id))?.state.nodes[seedFileIds.main]).toMatchObject({ content: 'tab A' })
    expect((await db.conflicts.get(seed.workspace.id))?.local.nodes[seedFileIds.main]).toMatchObject({ content: 'tab B' })
  })

  it('hashes bounded snapshots and retains text before deletion', async () => {
    const seed = await repository.initialize(null, initialData())
    let version = (await repository.load(seed.workspace.id))!.metadata.localVersion
    for (const text of ['revision 1', 'revision 2', 'revision 3', 'revision 4']) {
      const file = seed.nodes[seedFileIds.main]!
      if (file.type === 'file') file.content = text
      version = (await repository.commit(seed, version)).version
    }
    delete seed.nodes[seedFileIds.main]
    await repository.commit(seed, version)
    const snapshots = await db.recoverySnapshots.where('[workspaceId+fileId]').equals([seed.workspace.id, seedFileIds.main]).toArray()
    expect(snapshots).toHaveLength(3)
    expect(snapshots.some((snapshot) => snapshot.content === 'revision 4')).toBe(true)
    expect((await db.fileNodes.get([seed.workspace.id, seedFileIds.main]))?.deletedAt).not.toBeNull()
    for (const snapshot of snapshots) expect(snapshot.contentHash).toBe(await contentHash(snapshot.content))
  })

  it('rebases explicit conflict resolution on the reviewed server revision', async () => {
    const seed = await repository.initialize(null, initialData())
    const server = repository.asServer(seed, 10)
    await repository.recordConflict(toDocument(seed), server)
    await repository.resolve(seed, server)
    const queue = await repository.pending(seed.workspace.id)
    expect(queue).toHaveLength(1)
    expect(queue[0]?.baseRevision).toBe(10)
    expect(await db.conflicts.get(seed.workspace.id)).toBeUndefined()
  })
})
