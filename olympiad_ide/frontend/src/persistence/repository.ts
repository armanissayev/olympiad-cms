import type { WorkspaceData } from '../store/workspaceStore'
import { initialData } from '../store/workspaceStore'
import { WorkspaceDatabase, type LocalWorkspace } from './database'
import { migratePhase1 } from './migration'
import { savedContents, semanticKey, stableJSON, toDocument, type Conflict, type RecoverySnapshot, type ServerWorkspace, type WorkspaceDocument } from './types'

const timestamp = () => new Date().toISOString()

export const contentHash = async (content: string): Promise<string> => {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content))
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export class LocalRepository {
  constructor(readonly db: WorkspaceDatabase, readonly snapshotIntervalMs = 60_000, readonly retention = 20) {}

  async initialize(legacy: string | null, seed: WorkspaceData): Promise<WorkspaceData> {
    await this.db.open()
    const active = await this.db.metadata.get('activeWorkspace')
    if (active && await this.db.workspaces.get(active.value)) return (await this.load(active.value))!.state
    const state = legacy ? migratePhase1(legacy) : seed
    await this.commit(state, 0, true)
    const verified = await this.load(state.workspace.id)
    if (!verified || semanticKey(toDocument(verified.state)) !== semanticKey(toDocument(state))) {
      throw new Error('IndexedDB migration verification failed; legacy data was retained.')
    }
    await this.db.metadata.put({ key: 'phase1Migration', value: 'verified-v2' })
    return verified.state
  }

  async load(workspaceId: string): Promise<{ state: WorkspaceData; metadata: LocalWorkspace } | null> {
    return this.db.transaction('r', this.db.workspaces, this.db.fileNodes, this.db.editorSessions, this.db.workspaceSettings, async () => {
      const record = await this.db.workspaces.get(workspaceId)
      if (!record) return null
      const nodes = Object.fromEntries((await this.db.fileNodes.where('workspaceId').equals(workspaceId).toArray())
        .filter((entry) => entry.deletedAt === null).map((entry) => [entry.id, entry.node]))
      const editor = await this.db.editorSessions.get(workspaceId)
      const settings = await this.db.workspaceSettings.get(workspaceId)
      return {
        metadata: record,
        state: {
          ...initialData(), ...editor?.state,
          workspace: record.metadata,
          nodes,
          settings: settings?.settings ?? initialData().settings,
          savedContents: savedContents(nodes),
        },
      }
    })
  }

  private async prepareHashes(state: WorkspaceData): Promise<Map<string, string>> {
    const previous = await this.load(state.workspace.id)
    const texts = new Set([...Object.values(state.nodes), ...Object.values(previous?.state.nodes ?? {})]
      .flatMap((file) => file.type === 'file' ? [file.content] : []))
    return new Map(await Promise.all(Array.from(texts, async (text) => [text, await contentHash(text)] as const)))
  }

  async commit(state: WorkspaceData, expectedVersion: number, force = false, preparedHashes?: Map<string, string>, branchKey?: string): Promise<{ version: number; conflict?: Conflict }> {
    const document = toDocument(state)
    const hashes = preparedHashes ?? await this.prepareHashes(state)
    const id = state.workspace.id
    return this.db.transaction('rw', this.db.tables, async () => {
      const current = await this.load(id)
      const previousConflict = await this.db.conflicts.get(id)
      if (previousConflict && !force) {
        if (current && semanticKey(toDocument(current.state)) === semanticKey(document)) {
          await this.db.editorSessions.put({ workspaceId: id, state: document.editorState as WorkspaceData })
          return { version: expectedVersion, conflict: previousConflict }
        }
        if (branchKey && branchKey !== semanticKey(previousConflict.local)) await this.archive(previousConflict)
        const conflict = { ...previousConflict, local: document }
        await this.db.conflicts.put(conflict)
        return { version: expectedVersion, conflict }
      }
      const semanticChanged = !current || semanticKey(toDocument(current.state)) !== semanticKey(document)
      if (current && current.metadata.localVersion !== expectedVersion && semanticChanged && !force) {
        const conflict: Conflict = {
          workspaceId: id, kind: 'local', local: document, createdAt: timestamp(),
          server: this.asServer(current.state, current.metadata.lastSyncedRevision),
        }
        await this.db.conflicts.put(conflict)
        return { version: expectedVersion, conflict }
      }
      const version = (current?.metadata.localVersion ?? 0) + (semanticChanged ? 1 : 0)
      // UI state is a device preference; stale tabs may save navigation but never replace text.
      await this.db.editorSessions.put({ workspaceId: id, state: document.editorState as WorkspaceData })
      if (!semanticChanged && !force) {
        if (current && current.metadata.localVersion === expectedVersion &&
          stableJSON(toDocument(current.state).editorState) !== stableJSON(document.editorState)) {
          await this.queueDocument(id, document, current.metadata.lastSyncedRevision)
        }
        return { version }
      }
      await this.db.workspaces.put({
        id, metadata: { ...state.workspace, updatedAt: timestamp() }, localVersion: version,
        lastSyncedRevision: current?.metadata.lastSyncedRevision ?? 0,
        lastSyncedAt: current?.metadata.lastSyncedAt ?? null,
        serverDocument: current?.metadata.serverDocument ?? null,
      })
      const oldNodes = current?.state.nodes ?? {}
      for (const node of Object.values(oldNodes)) {
        const next = state.nodes[node.id]
        if (node.type === 'file' && (!next || node.name !== next.name || node.parentId !== next.parentId)) {
          await this.addSnapshot({ workspaceId: id, fileId: node.id, name: node.name,
            content: node.content, contentHash: hashes.get(node.content)!,
            revision: node.documentRevision, reason: next ? 'before_structure' : 'before_delete' })
        }
        if (!next) await this.db.fileNodes.put({ workspaceId: id, id: node.id, node, deletedAt: timestamp() })
      }
      for (const node of Object.values(state.nodes)) {
        await this.db.fileNodes.put({ workspaceId: id, id: node.id, node, deletedAt: null })
        if (node.type === 'file') {
          const last = await this.db.recoverySnapshots.where('[workspaceId+fileId]').equals([id, node.id]).sortBy('createdAt')
          const latest = last.at(-1)
          if (!latest || (Date.now() - Date.parse(latest.createdAt) >= this.snapshotIntervalMs && latest.contentHash !== hashes.get(node.content))) {
            await this.addSnapshot({ workspaceId: id, fileId: node.id, name: node.name, content: node.content,
              contentHash: hashes.get(node.content)!, revision: node.documentRevision, reason: latest ? 'periodic' : 'initial' })
          }
        }
      }
      await this.db.workspaceSettings.put({ workspaceId: id, settings: state.settings })
      await this.queueDocument(id, document, current?.metadata.lastSyncedRevision ?? 0)
      await this.db.metadata.put({ key: 'activeWorkspace', value: id })
      return { version }
    })
  }

  private async queueDocument(id: string, document: WorkspaceDocument, baseRevision: number) {
    const last = (await this.pending(id)).at(-1)
    if (last?.status === 'pending') {
      await this.db.syncOperations.update(last.sequence!, { document })
    } else {
      await this.db.syncOperations.add({ operationId: crypto.randomUUID(), workspaceId: id,
        baseRevision: last ? last.baseRevision + 1 : baseRevision,
        document, status: 'pending', retryCount: 0, createdAt: timestamp() })
    }
  }

  async checkpoint(state: WorkspaceData): Promise<void> {
    const hashes = await this.prepareHashes(state)
    await this.db.transaction('rw', this.db.recoverySnapshots, async () => {
      for (const file of Object.values(state.nodes)) {
        if (file.type !== 'file') continue
        await this.addSnapshot({ workspaceId: state.workspace.id, fileId: file.id, name: file.name,
          content: file.content, contentHash: hashes.get(file.content)!, revision: file.documentRevision, reason: 'checkpoint' })
      }
    })
  }

  private async archive(conflict: Conflict) {
    await this.db.metadata.put({ key: `resolved:${conflict.workspaceId}:${timestamp()}:${crypto.randomUUID()}`, value: JSON.stringify(conflict) })
    const archives = await this.db.metadata.where('key').startsWith(`resolved:${conflict.workspaceId}:`).sortBy('key')
    for (const old of archives.slice(0, Math.max(0, archives.length - this.retention))) await this.db.metadata.delete(old.key)
  }

  private async addSnapshot(input: Omit<RecoverySnapshot, 'snapshotId' | 'createdAt'>): Promise<void> {
    const snapshots = await this.db.recoverySnapshots.where('[workspaceId+fileId]').equals([input.workspaceId, input.fileId]).sortBy('createdAt')
    if (snapshots.at(-1)?.contentHash === input.contentHash && snapshots.at(-1)?.name === input.name) return
    await this.db.recoverySnapshots.add({ ...input, snapshotId: crypto.randomUUID(), createdAt: timestamp() })
    for (const old of snapshots.slice(0, Math.max(0, snapshots.length - this.retention + 1))) {
      await this.db.recoverySnapshots.delete(old.snapshotId)
    }
  }

  pending(id: string) {
    return this.db.syncOperations.where('workspaceId').equals(id).sortBy('sequence')
  }

  asServer(state: WorkspaceData, revision: number): ServerWorkspace {
    return { id: state.workspace.id, ownerId: state.workspace.ownerId, revision,
      createdAt: state.workspace.createdAt, updatedAt: state.workspace.updatedAt, document: toDocument(state) }
  }

  async acknowledge(sequence: number, revision: number): Promise<void> {
    await this.db.transaction('rw', this.db.syncOperations, this.db.workspaces, async () => {
      const operation = await this.db.syncOperations.get(sequence)
      if (!operation) return
      await this.db.workspaces.update(operation.workspaceId, { lastSyncedRevision: revision,
        lastSyncedAt: timestamp(), serverDocument: operation.document })
      await this.db.syncOperations.delete(sequence)
    })
  }

  async recordConflict(local: WorkspaceDocument, server: ServerWorkspace, kind: Conflict['kind'] = 'server'): Promise<Conflict> {
    const conflict: Conflict = { workspaceId: server.id, kind, local, server, createdAt: timestamp() }
    await this.db.transaction('rw', this.db.conflicts, this.db.metadata, async () => {
      const previous = await this.db.conflicts.get(server.id)
      if (previous) {
        await this.archive(previous)
        if (previous.kind === 'local') await this.archive({ ...previous, local: previous.server.document })
      }
      await this.db.conflicts.put(conflict)
    })
    return conflict
  }

  stateFromDocument(document: WorkspaceDocument, base: WorkspaceData): WorkspaceData {
    const nodes = Object.fromEntries(Object.entries(document.nodes).map(([id, node]) => [id, node.type === 'file' ? node : {
      id: node.id, type: 'folder' as const, parentId: node.parentId, name: node.name, createdAt: node.createdAt, updatedAt: node.updatedAt,
    }]))
    const ui = { ...base, ...document.editorState }
    const groups = { ...ui.groups }
    for (const groupId of ['primary', 'secondary'] as const) {
      const group = groups[groupId]
      const tabIds = group.tabIds.filter((id) => nodes[id]?.type === 'file')
      groups[groupId] = { ...group, tabIds, activeFileId: group.activeFileId && tabIds.includes(group.activeFileId) ? group.activeFileId : tabIds[0] ?? null }
    }
    return { ...ui, groups, nodes, workspace: { ...base.workspace, name: document.name },
      settings: document.settings, savedContents: savedContents(nodes) }
  }

  async adoptServer(server: ServerWorkspace, base: WorkspaceData, expectedVersion: number): Promise<WorkspaceData | null> {
    const state = this.stateFromDocument(server.document, base)
    state.workspace = { id: server.id, ownerId: server.ownerId, name: server.document.name,
      revision: server.revision, createdAt: server.createdAt, updatedAt: server.updatedAt }
    const hashes = await this.prepareHashes(state)
    return this.db.transaction('rw', this.db.tables, async () => {
      const current = await this.db.workspaces.get(server.id)
      if (!current || current.localVersion !== expectedVersion || (await this.pending(server.id)).length) return null
      const result = await this.commit(state, expectedVersion, true, hashes)
      await this.db.syncOperations.where('workspaceId').equals(server.id).delete()
      await this.db.workspaces.update(server.id, { lastSyncedRevision: server.revision,
        lastSyncedAt: timestamp(), serverDocument: server.document, localVersion: result.version })
      return state
    })
  }

  async resolve(state: WorkspaceData, server: ServerWorkspace, expectedVersion?: number): Promise<number> {
    // Keep both complete versions available for export even after explicit resolution.
    const hashes = await this.prepareHashes(state)
    return this.db.transaction('rw', this.db.tables, async () => {
      const reviewed = await this.db.workspaces.get(server.id)
      if (expectedVersion !== undefined && reviewed?.localVersion !== expectedVersion) {
        throw new Error('Another tab changed this workspace during resolution. Review the current conflict again.')
      }
      const conflict = await this.db.conflicts.get(server.id)
      if (conflict) await this.archive(conflict)
      await this.db.syncOperations.where('workspaceId').equals(server.id).delete()
      await this.db.conflicts.delete(server.id)
      await this.db.workspaces.update(server.id, { lastSyncedRevision: server.revision, serverDocument: server.document })
      const current = await this.db.workspaces.get(server.id)
      const result = await this.commit(state, current?.localVersion ?? 0, true, hashes)
      return result.version
    })
  }
}
