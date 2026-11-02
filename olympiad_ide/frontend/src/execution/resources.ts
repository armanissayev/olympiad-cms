import { create } from 'zustand'
import { database, type WorkspaceDatabase } from '../persistence/database'
import { RequestError, WorkspaceAPI } from '../persistence/api'
import { useWorkspaceStore } from '../store/workspaceStore'
import type { LocalResource, RemoteResource, ResourceValue } from './types'

interface ResourceState { items: LocalResource[]; activeConfigurationId: string | null; selectedTestId: string | null; stdin: string; error: string | null; pending: number }
export const useExecutionResources = create<ResourceState>(() => ({ items: [], activeConfigurationId: null, selectedTestId: null, stdin: '', error: null, pending: 0 }))
export class ResourceController {
  private tail: Promise<void> = Promise.resolve()
  private timer?: ReturnType<typeof setInterval>
  private syncing = false
  private stopped = false
  private failedResources = new Set<string>()
  constructor(readonly db: WorkspaceDatabase = database, readonly api = new WorkspaceAPI()) {}
  private table(kind: ResourceValue['kind']) { return kind === 'test' ? this.db.testCases : this.db.runConfigurations }
  private id() { return useWorkspaceStore.getState().workspace.id }
  async load() {
    const id = this.id()
    const items = [...await this.db.testCases.where('workspaceId').equals(id).toArray(), ...await this.db.runConfigurations.where('workspaceId').equals(id).toArray()]
    const optimistic = useExecutionResources.getState().items.filter(r => r.workspaceId === id)
    const merged = items.map(row => {
      const local = optimistic.find(r => r.id === row.id)
      return local && (this.failedResources.has(local.id) || local.localVersion > row.localVersion) ? { ...local, revision: row.revision, ...(row.conflict ? { conflict: row.conflict } : {}) } : row
    })
    merged.push(...optimistic.filter(r => !items.some(row => row.id === r.id)))
    useExecutionResources.setState({ items: merged, pending: await this.db.executionResourceOperations.where('workspaceId').equals(id).count() })
  }
  async start() {
    try {
      await this.load()
      const preferences = await this.db.metadata.get(`execution-ui:${this.id()}`)
      if (preferences) useExecutionResources.setState(JSON.parse(preferences.value) as Partial<ResourceState>)
    } catch (error) { this.error(error) }
    this.resume()
  }
  resume() { this.stopped = false; clearInterval(this.timer); this.timer = setInterval(() => void this.sync(), 3000); void this.sync() }
  stop() { this.stopped = true; clearInterval(this.timer) }
  async suspend() { this.stop(); await this.tail; while (this.syncing) await new Promise(resolve => setTimeout(resolve, 10)); await this.tail }
  async flush() { await this.tail }
  error(error: unknown) { useExecutionResources.setState({ error: error instanceof Error ? error.message : String(error) }) }
  select(preferences: Partial<Pick<ResourceState, 'activeConfigurationId' | 'selectedTestId' | 'stdin'>>) {
    useExecutionResources.setState(preferences)
    const state = useExecutionResources.getState()
    const key = `execution-ui:${this.id()}`, value = JSON.stringify({ activeConfigurationId: state.activeConfigurationId, selectedTestId: state.selectedTestId, stdin: state.stdin })
    this.tail = this.tail.catch(() => undefined).then(() => this.db.metadata.put({ key, value })).then(() => undefined).catch(error => { this.error(error); throw error })
    void this.tail.catch(() => undefined)
  }
  save(value: ResourceValue, deleted = false): Promise<void> {
    const existing = useExecutionResources.getState().items.find(r => r.id === value.id)
    const row: LocalResource = { id: value.id, workspaceId: this.id(), revision: existing?.revision ?? 0, localVersion: (existing?.localVersion ?? 0) + 1, value: structuredClone(value), deleted, ...(existing?.conflict ? { conflict: existing.conflict } : {}) }
    useExecutionResources.setState(s => ({ items: [...s.items.filter(r => r.id !== row.id), row] }))
    const write = this.tail.catch(() => undefined).then(async () => {
      await this.db.transaction('rw', this.table(value.kind), this.db.executionResourceOperations, async () => {
        const previous = await this.table(value.kind).get(row.id)
        if (previous && previous.localVersion > (existing?.localVersion ?? 0)) {
          throw new Error('Another tab changed this resource; export local data and reload before reconciling')
        }
        const pending = await this.db.executionResourceOperations.where('resourceId').equals(row.id).sortBy('sequence')
        const last = pending.at(-1)
        if (last?.status === 'pending') await this.db.executionResourceOperations.update(last.sequence!, { value: row.value, deleted, localVersion: row.localVersion })
        else await this.db.executionResourceOperations.add({ operationId: crypto.randomUUID(), resourceId: row.id, workspaceId: row.workspaceId, baseRevision: last ? last.baseRevision + 1 : previous?.revision ?? 0, value: row.value, deleted, localVersion: row.localVersion, status: 'pending' })
        await this.table(value.kind).put({ ...row, revision: previous?.revision ?? row.revision })
      })
      useExecutionResources.setState({ pending: await this.db.executionResourceOperations.where('workspaceId').equals(this.id()).count() })
      this.failedResources.delete(row.id)
    }).catch(error => {
      this.failedResources.add(row.id)
      this.error(error)
      throw error
    })
    this.tail = write
    return write
  }
  async sync() {
    if (this.stopped || this.syncing || !navigator.onLine) return
    this.syncing = true
    try {
      await this.tail
      const work = async () => {
        await this.api.session()
        let operations = await this.db.executionResourceOperations.where('workspaceId').equals(this.id()).sortBy('sequence')
        for (const listed of operations) {
          if (this.stopped) break
          const table = this.table(listed.value.kind), local = await table.get(listed.resourceId)
          if (local?.conflict || this.failedResources.has(listed.resourceId)) continue
          // Claim the latest compacted payload atomically before it becomes immutable in flight.
          const operation = await this.db.transaction('rw', this.db.executionResourceOperations, async () => {
            const current = await this.db.executionResourceOperations.get(listed.sequence!)
            if (current) await this.db.executionResourceOperations.update(current.sequence!, { status: 'sending' })
            return current
          })
          if (!operation) continue
          try {
            const remote = await this.api.request<RemoteResource>(`/workspaces/${this.id()}/execution-resources`, { method: 'POST', body: JSON.stringify({ operationId: operation.operationId, baseRevision: operation.baseRevision, value: operation.value, deleted: operation.deleted }) })
            await this.db.transaction('rw', table, this.db.executionResourceOperations, async () => {
              const current = await table.get(operation.resourceId)
              if (current) await table.update(current.id, { revision: Math.max(current.revision, remote.revision) })
              await this.db.executionResourceOperations.delete(operation.sequence!)
            })
          } catch (error) {
            if (error instanceof RequestError && error.status === 409 && error.server) await table.update(operation.resourceId, { conflict: error.server as unknown as RemoteResource })
            throw error
          }
        }
        const remote = await this.api.request<RemoteResource[]>(`/workspaces/${this.id()}/execution-resources`)
        operations = await this.db.executionResourceOperations.where('workspaceId').equals(this.id()).toArray()
        for (const row of remote) {
          if (operations.some(o => o.resourceId === row.id)) continue
          const table = this.table(row.value.kind), local = await table.get(row.id)
          if (!local || row.revision > local.revision) await table.put({ ...row, localVersion: (local?.localVersion ?? 0) + 1 })
        }
        await this.load(); useExecutionResources.setState({ error: null })
      }
      if (navigator.locks) await navigator.locks.request('olympiad-execution-resources', work)
      else await work()
    } catch (error) { this.error(error); await this.load().catch(() => undefined) }
    finally { this.syncing = false }
  }
  async resolve(id: string, choice: 'local' | 'server') {
    await this.tail.catch(() => undefined)
    const row = useExecutionResources.getState().items.find(r => r.id === id)
    if (!row?.conflict) return
    const server = row.conflict
    // Archive both versions before applying the explicit decision; a fresh server revision still guards upload.
    await this.db.transaction('rw', this.table(row.value.kind), this.db.executionResourceOperations, this.db.metadata, async () => {
      await this.db.metadata.put({ key: `execution-conflict:${id}:${Date.now()}`, value: JSON.stringify({ local: row, server }) })
      await this.db.executionResourceOperations.where('resourceId').equals(id).delete()
      await this.table(row.value.kind).put({ ...server, localVersion: row.localVersion + 1 })
    })
    this.failedResources.delete(id)
    useExecutionResources.setState(s => ({ items: s.items.filter(r => r.id !== id) }))
    await this.load()
    if (choice === 'local') await this.save(row.value, row.deleted)
    void this.sync()
  }
}
export let executionResources = new ResourceController()
export function bindExecutionResources(next: ResourceController) { executionResources = next }
