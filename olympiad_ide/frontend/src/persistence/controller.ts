import { cmsEnabled, currentTask, useCMSSession } from '../cms/session'
import { useWorkspaceStore, type WorkspaceData } from '../store/workspaceStore'
import { modelRegistry } from '../editor/modelRegistry'
import { database } from './database'
import { LocalRepository } from './repository'
import { RequestError, retryDelay, WorkspaceAPI } from './api'
import { usePersistenceStatus } from './status'
import { savedContents, semanticKey, toDocument, type WorkspaceDocument } from './types'

export class PersistenceController {
  private version = 0
  private applying = false
  private tail: Promise<void> = Promise.resolve()
  private unsubscribe?: () => void
  private syncTimer?: ReturnType<typeof setTimeout>
  private pollTimer?: ReturnType<typeof setTimeout>
  private snapshotTimer?: ReturnType<typeof setInterval>
  private branchKey = ''
  private syncing = false
  private retryAttempt = 0
  private stopped = false
  private startPromise?: Promise<void>
  readonly uploadDelayMs: number

  constructor(readonly repository = new LocalRepository(database), readonly api = new WorkspaceAPI(), uploadDelayMs = 400) {
    this.uploadDelayMs = uploadDelayMs
  }

  start(): Promise<void> {
    this.startPromise ??= this.initialize()
    return this.startPromise
  }

  private async initialize() {
    try {
      if (cmsEnabled) {
        const context = useCMSSession.getState().context!
        useWorkspaceStore.setState(state => ({ workspace: { ...state.workspace, ownerId: context.identity.principalId, name: currentTask()?.title ?? context.contest.name } }))
      }
      const restored = await this.repository.initialize(cmsEnabled ? null : localStorage.getItem('olympiad-ide-phase1'), useWorkspaceStore.getState())
      this.apply(restored)
      const loaded = await this.repository.load(restored.workspace.id)
      this.version = loaded!.metadata.localVersion
      const conflict = await this.repository.db.conflicts.get(restored.workspace.id)
      if (conflict) this.apply(this.repository.stateFromDocument(conflict.local, restored))
      this.branchKey = semanticKey(toDocument(useWorkspaceStore.getState()))
      usePersistenceStatus.setState({ ready: true, conflict: conflict ?? null })
      await this.refreshStatus()
    } catch (error) {
      this.saveError(error)
      usePersistenceStatus.setState({ ready: true })
    }
    this.unsubscribe = useWorkspaceStore.subscribe((state, previous) => {
      if (this.applying) return
      const currentDocument = toDocument(state)
      const previousDocument = toDocument(previous)
      if (state.nodes === previous.nodes && state.settings === previous.settings && state.workspace.name === previous.workspace.name &&
        Object.entries(currentDocument.editorState).every(([key, value]) => previousDocument.editorState[key as keyof typeof previousDocument.editorState] === value)) return
      this.enqueue(this.capture())
    })
    this.snapshotTimer = setInterval(() => {
      this.tail = this.tail.then(() => this.repository.checkpoint(this.capture())).catch((error: unknown) => this.saveError(error))
    }, this.repository.snapshotIntervalMs)
    this.scheduleSync(0)
  }

  private enqueue(state: WorkspaceData): void {
    usePersistenceStatus.setState((s) => ({ localPending: s.localPending + 1,
      status: s.conflict ? 'Conflict' : 'Saving' }))
    this.tail = this.tail.then(async () => {
      try {
        const result = await this.repository.commit(state, this.version, false, undefined, this.branchKey)
        this.version = result.version
        this.branchKey = semanticKey(toDocument(state))
        if (result.conflict) usePersistenceStatus.setState({ conflict: result.conflict })
        this.applying = true
        useWorkspaceStore.setState({ savedContents: savedContents(state.nodes) })
        this.applying = false
        usePersistenceStatus.setState({ error: null })
      } catch (error) {
        this.saveError(error)
      } finally {
        usePersistenceStatus.setState((s) => ({ localPending: Math.max(0, s.localPending - 1) }))
        await this.refreshStatus().catch((error: unknown) => this.saveError(error))
      }
    })
    // Timer controls uploads only; no local edit depends on the timer firing.
    this.scheduleSync(this.uploadDelayMs)
  }

  private apply(state: WorkspaceData, origin = 'hydration'): void {
    withDocumentOrigin(origin, () => {
      this.applying = true
      try {
        // Reconcile existing models in place, once per file, so split views keep a shared model.
        for (const node of Object.values(state.nodes)) {
          if (node.type !== 'file') continue
          const model = modelRegistry.get(node.id)
          if (model && model.getValue() !== node.content) {
            model.pushEditOperations([], [{ range: model.getFullModelRange(), text: node.content }], () => null)
          }
        }
        useWorkspaceStore.setState(state)
      } finally {
        this.applying = false
      }
    })
  }

  private saveError(error: unknown) {
    usePersistenceStatus.setState({ status: 'Save Error', error: error instanceof Error ? error.message : String(error) })
  }

  async flush(): Promise<void> {
    await this.tail
    if (usePersistenceStatus.getState().error) {
      // Retrying a failed write captures the complete current work, including edits after the failure.
      this.enqueue(this.capture())
      await this.tail
    }
    if (usePersistenceStatus.getState().error) throw new Error(usePersistenceStatus.getState().error!)
  }

  private capture(): WorkspaceData {
    const state = useWorkspaceStore.getState()
    const { nodes, settings, editorState } = toDocument(state)
    return structuredClone({ ...editorState, workspace: state.workspace, nodes, settings, savedContents: state.savedContents }) as WorkspaceData
  }

  async refreshStatus(): Promise<void> {
    const id = useWorkspaceStore.getState().workspace.id
    const queue = await this.repository.pending(id)
    const workspace = await this.repository.db.workspaces.get(id)
    const current = usePersistenceStatus.getState()
    const status = current.error ? 'Save Error' : current.conflict ? 'Conflict' : current.localPending ? 'Saving'
      : this.syncing ? 'Syncing' : !current.online ? 'Offline' : queue.length ? 'Saved locally' : 'Synced'
    usePersistenceStatus.setState({ pendingOperations: queue.length, lastSyncedAt: workspace?.lastSyncedAt ?? null, status })
  }

  private scheduleSync(delay: number) {
    if (this.stopped) return
    clearTimeout(this.syncTimer)
    this.syncTimer = setTimeout(() => { void this.syncNow() }, delay)
  }

  async syncNow(forceUpload = false): Promise<void> {
    if (this.stopped || this.syncing || usePersistenceStatus.getState().error) return
    this.syncing = true
    try {
      await this.tail
      const work = () => this.synchronize(forceUpload)
      // Cross-tab HTTP replay is also safe without Web Locks: operation IDs are idempotent.
      if (navigator.locks) await navigator.locks.request('olympiad-sync', work)
      else await work()
      this.retryAttempt = 0
    } catch (error) {
      if (cmsEnabled && useCMSSession.getState().paused) {
        usePersistenceStatus.setState({ online: false })
      } else if (error instanceof RequestError && error.status < 500) {
        usePersistenceStatus.setState({ online: true, error: error.message, status: 'Save Error' })
      } else {
        usePersistenceStatus.setState({ online: false })
        this.scheduleSync(retryDelay(this.retryAttempt++))
      }
    } finally {
      this.syncing = false
      await this.refreshStatus().catch((error: unknown) => this.saveError(error))
      clearTimeout(this.pollTimer)
      if (!this.stopped) this.pollTimer = setTimeout(() => { void this.syncNow() }, 10_000)
    }
  }

  private async synchronize(forceUpload: boolean): Promise<void> {
    const identity = await this.api.session()
    usePersistenceStatus.setState({ online: true })
    const id = useWorkspaceStore.getState().workspace.id
    const existingConflict = await this.repository.db.conflicts.get(id)
    if (existingConflict) {
      usePersistenceStatus.setState({ conflict: existingConflict })
      return
    }
    await this.refreshStatus()
    let operation = (await this.repository.pending(id))[0]
    if (operation && !forceUpload && useWorkspaceStore.getState().settings.autoSave === 'off') return
    while (operation && !this.stopped) {
      const conflict = await this.repository.db.conflicts.get(id)
      if (conflict) { usePersistenceStatus.setState({ conflict }); return }
      // Claim inside a transaction; a pending payload may have been compacted since it was read.
      operation = await this.repository.db.transaction('rw', this.repository.db.syncOperations, async () => {
        const first = (await this.repository.pending(id))[0]
        if (first) await this.repository.db.syncOperations.update(first.sequence!, { status: 'sending' })
        return first
      })
      if (!operation) break
      try {
        const result = await this.api.send(operation)
        const ack = result.acknowledgements.find((a) => a.operationId === operation!.operationId)
        if (!ack) throw new Error('Server did not acknowledge the operation')
        await this.repository.acknowledge(operation.sequence!, ack.revision)
      } catch (error) {
        if (error instanceof RequestError && error.status === 409 && error.server) {
          await this.tail
          const conflict = await this.repository.recordConflict(toDocument(useWorkspaceStore.getState()), error.server)
          usePersistenceStatus.setState({ conflict })
          return
        }
        await this.repository.db.syncOperations.update(operation.sequence!, { retryCount: operation.retryCount + 1 })
        throw error
      }
      operation = (await this.repository.pending(id))[0]
    }
    await this.tail
    if (await this.repository.db.conflicts.get(id)) return
    if ((await this.repository.pending(id)).length || usePersistenceStatus.getState().localPending) return
    const loaded = await this.repository.load(id)
    if (!loaded) return
    const status = await this.api.status(id)
    if (status.revision !== loaded.metadata.lastSyncedRevision) {
      const server = await this.api.get(id)
      const before = semanticKey(toDocument(useWorkspaceStore.getState()))
      const adopted = await this.repository.adoptServer(server, loaded.state, this.version)
      if (adopted && before === semanticKey(toDocument(useWorkspaceStore.getState())) && !usePersistenceStatus.getState().localPending) {
        this.apply(adopted, 'server-sync')
        this.version = (await this.repository.db.workspaces.get(id))!.localVersion
      }
    }
    useWorkspaceStore.setState((state) => ({ workspace: { ...state.workspace, ownerId: identity.identityId } }))
  }

  async resolve(choice: 'local' | 'server' | 'copy'): Promise<void> {
    await this.flush()
    const conflict = usePersistenceStatus.getState().conflict
    if (!conflict) return
    await this.api.session()
    const reviewedVersion = (await this.repository.db.workspaces.get(conflict.workspaceId))?.localVersion
    if (conflict.kind === 'local') {
      // The canonical IndexedDB head contains the other tab's durable branch. Commit it
      // remotely before offering to replace it with the explicitly selected branch.
      for (const operation of await this.repository.pending(conflict.workspaceId)) {
        try {
          await this.repository.db.syncOperations.update(operation.sequence!, { status: 'sending' })
          const response = await this.api.send(operation)
          const ack = response.acknowledgements.find((item) => item.operationId === operation.operationId)
          if (!ack) throw new Error('Missing acknowledgement while preserving the other tab’s work')
          await this.repository.acknowledge(operation.sequence!, ack.revision)
        } catch (error) {
          if (error instanceof RequestError && error.server) {
            const updated = await this.repository.recordConflict(toDocument(useWorkspaceStore.getState()), error.server)
            usePersistenceStatus.setState({ conflict: updated })
          }
          throw error
        }
      }
    }
    const latest = await this.api.get(conflict.workspaceId)
    if (conflict.kind === 'server' && latest.revision !== conflict.server.revision) {
      const updated = await this.repository.recordConflict(toDocument(useWorkspaceStore.getState()), latest)
      usePersistenceStatus.setState({ conflict: updated })
      throw new Error('The server changed again. Review the refreshed comparison before resolving.')
    }
    const local = toDocument(useWorkspaceStore.getState())
    let document: WorkspaceDocument = choice === 'local' ? local : latest.document
    if (choice === 'copy') {
      document = structuredClone(latest.document)
      const folderId = crypto.randomUUID()
      const now = new Date().toISOString()
      const folderName = `Recovered ${now.replace(/[:.]/g, '-')}`
      document.nodes[folderId] = { id: folderId, parentId: null, type: 'folder', name: folderName, createdAt: now, updatedAt: now }
      const mappedIds = new Map(Object.keys(local.nodes).map((id) => [id, crypto.randomUUID()]))
      for (const node of Object.values(local.nodes)) {
        const id = mappedIds.get(node.id)!
        document.nodes[id] = { ...node, id, parentId: node.parentId ? mappedIds.get(node.parentId)! : folderId }
      }
    }
    const state = this.repository.stateFromDocument(document, useWorkspaceStore.getState())
    this.version = await this.repository.resolve(state, latest, reviewedVersion)
    this.branchKey = semanticKey(document)
    this.apply(state, 'conflict-resolution')
    usePersistenceStatus.setState({ conflict: null, error: null })
    await this.refreshStatus()
    this.scheduleSync(0)
  }

  async restoreSnapshot(snapshotId: string): Promise<void> {
    const snapshot = await this.repository.db.recoverySnapshots.get(snapshotId)
    if (!snapshot) throw new Error('Snapshot is no longer available.')
    const store = useWorkspaceStore.getState()
    const current = store.nodes[snapshot.fileId]
    if (current?.type === 'file') withDocumentOrigin('recovery-snapshot', () => store.setFileContent(snapshot.fileId, snapshot.content))
    else store.createFile(null, `Recovered-${Date.now()}-${snapshot.name}`, snapshot.content)
    this.apply(this.capture(), 'recovery-snapshot')
    await this.flush()
  }

  async restoreArchive(key: string): Promise<void> {
    const archive = await this.repository.db.metadata.get(key)
    if (!archive) throw new Error('Recovery archive is unavailable.')
    const conflict = JSON.parse(archive.value) as { local: WorkspaceDocument }
    const current = this.capture()
    const now = new Date().toISOString()
    const folderId = crypto.randomUUID()
    const nodes = { ...current.nodes }
    nodes[folderId] = { id: folderId, parentId: null, name: `Recovered archive ${Date.now()}`, type: 'folder', createdAt: now, updatedAt: now }
    const ids = new Map(Object.keys(conflict.local.nodes).map((id) => [id, crypto.randomUUID()]))
    for (const node of Object.values(conflict.local.nodes)) {
      const id = ids.get(node.id)!
      nodes[id] = { ...node, id, parentId: node.parentId ? ids.get(node.parentId)! : folderId }
    }
    const next = { ...current, nodes }
    this.apply(next, 'recovery-archive')
    this.enqueue(next)
    await this.flush()
  }

  async retry() {
    usePersistenceStatus.setState({ error: null })
    this.enqueue(this.capture())
    await this.flush()
    await this.syncNow(true)
  }

  async checkpoint() {
    await this.flush()
    await this.repository.checkpoint(this.capture())
    await this.syncNow(true)
  }

  stop() {
    this.stopped = true
    this.unsubscribe?.()
    clearTimeout(this.syncTimer)
    clearTimeout(this.pollTimer)
    clearInterval(this.snapshotTimer)
  }
}

export const persistence = new PersistenceController()
import { withDocumentOrigin } from '../telemetry/origin'
