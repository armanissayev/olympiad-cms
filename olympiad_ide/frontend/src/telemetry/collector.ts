import { create } from 'zustand'
import type { editor } from 'monaco-editor'
import { database, type WorkspaceDatabase } from '../persistence/database'
import { modelRegistry, type MonacoModelRegistry } from '../editor/modelRegistry'
import { useWorkspaceStore, type WorkspaceState } from '../store/workspaceStore'
import { applyEvent, canonical, digest } from './replayEngine'
import { documentOrigin } from './origin'
import { EventQueue } from './eventQueue'
import { recordedNode, snapshotOf, type Checkpoint, type EventPayloads, type EventType, type RecordingStatus, type Snapshot, type TelemetryEvent, type TelemetrySession } from './types'

export const telemetryConfig = { checkpointMs: 60_000, checkpointChanges: 500, maxBufferedEvents: 20_000, maxBufferedBytes: 32_000_000, retentionDays: 30 }
interface Diagnostics { status: RecordingStatus; sessionId: string; sequence: number; pending: number; lastAck: number; gaps: number; checkpoint: number; error: string | null; retentionDays: number }
export const useTelemetryStatus = create<Diagnostics>(() => ({ status: 'Recording Locally', sessionId: '', sequence: 0, pending: 0, lastAck: 0, gaps: 0, checkpoint: 0, error: null, retentionDays: telemetryConfig.retentionDays }))

export class TelemetryCollector {
  session!: TelemetrySession
  queue!: EventQueue
  nodes: Snapshot = {}
  private origin = performance.now()
  private halted = false
  private bytes = 0
  private changes = 0
  private checkpointTail: Promise<void> = Promise.resolve()
  private subscriptions: (() => void)[] = []
  private models = new Map<editor.ITextModel, { dispose: () => void }>()
  private checkpointTimer?: ReturnType<typeof setInterval>
  private releaseTabLock?: () => void
  private initialized = false
  private lastInput: { eventId: string; fileId: string; time: number } | null = null
  readonly transactions = new Map<string, { transactionId: string; version: number }>()
  uplinkAvailable = false
  constructor(readonly db: WorkspaceDatabase = database, readonly registry: MonacoModelRegistry = modelRegistry) {}

  async start(state = useWorkspaceStore.getState()) {
    if (this.session) return
    this.nodes = snapshotOf(state.nodes)
    this.origin = performance.now()
    let tabId: string
    try { tabId = sessionStorage.getItem('olympiad-telemetry-tab') ?? crypto.randomUUID(); sessionStorage.setItem('olympiad-telemetry-tab', tabId) } catch { tabId = crypto.randomUUID() }
    // window.open may clone sessionStorage. An active tab lock prevents closing its recording as a "reload".
    if (navigator.locks) {
      const claim = () => new Promise<boolean>(resolve => {
        void navigator.locks.request(`olympiad-telemetry-tab:${tabId}`, { ifAvailable: true }, lock => {
          if (!lock) { resolve(false); return }
          return new Promise<void>(release => { this.releaseTabLock = release; resolve(true) })
        }).catch(() => resolve(false))
      })
      const acquired = await claim()
      if (!acquired) {
        tabId = crypto.randomUUID()
        try { sessionStorage.setItem('olympiad-telemetry-tab', tabId); sessionStorage.removeItem('olympiad-telemetry-session') } catch { /* Unique session IDs still isolate this runtime. */ }
        await claim()
      }
    }
    const id = crypto.randomUUID(), timestamp = new Date().toISOString()
    const initial: Checkpoint = { id: crypto.randomUUID(), sessionId: id, sequence: 0, workspaceRevision: state.workspace.revision, nodes: structuredClone(this.nodes), stateHash: await digest(this.nodes), createdAt: timestamp, reason: 'initial' }
    this.session = { id, workspaceId: state.workspace.id, tabId, startedAt: timestamp, completedAt: null, lastSequence: 0, lastAck: 0, integrity: 'Complete', initial, registered: false, retentionDays: telemetryConfig.retentionDays, error: null }
    this.queue = new EventQueue(this.db, this.session, () => this.refresh(), error => this.fail(error))
    try {
      await this.queue.initialize()
      // Reload creates a NEW clock/sequence domain. Never append a reset browser clock to an old session.
      const previousId = sessionStorage.getItem('olympiad-telemetry-session')
      if (previousId) {
        const previous = await this.db.telemetrySessions.get(previousId)
        if (previous && !previous.completedAt) await this.db.telemetrySessions.update(previousId, { integrity: 'Recording Interrupted', completedAt: timestamp, error: 'Page runtime ended without a committed completion marker' })
      }
      sessionStorage.setItem('olympiad-telemetry-session', id)
    } catch (error) { this.fail(error) }
    useTelemetryStatus.setState({ sessionId: id, sequence: 0, lastAck: 0, pending: 0, checkpoint: 0 })
    this.subscriptions.push(this.registry.observe((file, model) => this.trackModel(file.id, model)))
    this.subscriptions.push(useWorkspaceStore.subscribe((next, previous) => this.workspaceChanged(next, previous)))
    this.checkpointTimer = setInterval(() => { if (this.changes) void this.checkpoint('active-interval') }, telemetryConfig.checkpointMs)
    this.refresh()
    this.initialized = true
  }
  record<K extends EventType>(eventType: K, fileId: string | null, payload: EventPayloads[K]): TelemetryEvent | null {
    if (!this.session || this.halted || !this.initialized) return null
    const event = { schemaVersion: 1, eventId: crypto.randomUUID(), sessionId: this.session.id, workspaceId: this.session.workspaceId, fileId, sequence: this.session.lastSequence + 1, clientTimestamp: new Date().toISOString(), monotonicOffsetMs: Math.max(0, performance.now() - this.origin), eventType, payload } as TelemetryEvent
    try { this.nodes = applyEvent(this.nodes, event) } catch (error) { this.fail(error); this.halted = true; return null }
    this.session.lastSequence = event.sequence
    this.queue.append(event)
    this.bytes += JSON.stringify(event).length * 2
    if (this.queue.pending.length > telemetryConfig.maxBufferedEvents || (this.queue.failed && this.bytes > telemetryConfig.maxBufferedBytes)) {
      this.fail(new Error('Recording buffer exhausted. Further capture stopped; export retained data.'))
      this.halted = true
      useTelemetryStatus.setState({ status: 'Recording Interrupted' })
    }
    return event
  }
  key<K extends 'KEY_DOWN' | 'KEY_UP'>(type: K, fileId: string, payload: EventPayloads[K]) {
    const event = this.record(type, fileId, payload)
    if (event && type === 'KEY_DOWN') this.lastInput = { eventId: event.eventId, fileId, time: performance.now() }
  }
  trackModel(fileId: string, model: editor.ITextModel) {
    if (this.models.has(model)) return
    const change = model.onDidChangeContent(event => {
      if (documentOrigin() || !this.nodes[fileId]) return
      const node = this.nodes[fileId]
      const first = event.changes[0]
      const type = event.isUndoing ? 'UNDO' : event.isRedoing ? 'REDO' : !first || event.changes.length !== 1 ? 'DOCUMENT_CHANGE' : first.rangeLength === 0 ? 'TEXT_INSERT' : !first.text ? 'TEXT_DELETE' : 'TEXT_REPLACE'
      const transactionId = crypto.randomUUID()
      const recorded = this.record(type, fileId, {
        transactionId, beforeRevision: node.revision, afterRevision: node.revision + 1,
        changes: event.changes.map(c => ({ offset: c.rangeOffset, deletedLength: c.rangeLength, insertedText: c.text, range: { startLineNumber: c.range.startLineNumber, startColumn: c.range.startColumn, endLineNumber: c.range.endLineNumber, endColumn: c.range.endColumn } })),
        inputEventId: this.lastInput?.fileId === fileId && performance.now() - this.lastInput.time < 1000 ? this.lastInput.eventId : null,
        origin: 'editor', eol: event.eol as '\n' | '\r\n',
      })
      if (recorded) {
        this.transactions.set(fileId, { transactionId, version: event.versionId })
        if (this.nodes[fileId].content !== model.getValue()) this.fail(new Error('Recorded transaction differs from Monaco content'))
        this.changes++
        if (this.changes >= telemetryConfig.checkpointChanges) void this.checkpoint('change-limit')
      }
    })
    const dispose = () => { change.dispose(); disposal.dispose(); this.models.delete(model) }
    const disposal = model.onWillDispose(dispose)
    this.models.set(model, { dispose })
  }
  private workspaceChanged(next: WorkspaceState, previous: WorkspaceState) {
    if (next.workspace.id !== this.session.workspaceId) { this.fail(new Error('Workspace identity changed; reload to start a new recording')); this.halted = true; return }
    if (next.nodes !== previous.nodes) {
      const origin = documentOrigin()
      if (origin) {
        const snapshot = snapshotOf(next.nodes)
        if (canonical(snapshot) !== canonical(this.nodes)) this.record('WORKSPACE_RECONCILED', null, { reason: origin, nodes: snapshot })
      } else {
        // Parents are created before children; deleted subtrees are recorded atomically at their root.
        const created = Object.values(next.nodes).filter(n => !previous.nodes[n.id])
        while (created.length) {
          const index = created.findIndex(n => !n.parentId || !!this.nodes[n.parentId])
          if (index < 0) { this.fail(new Error('Invalid created tree')); break }
          const node = created.splice(index, 1)[0]!
          this.record(node.type === 'file' ? 'FILE_CREATED' : 'FOLDER_CREATED', node.id, { node: recordedNode(node) })
        }
        const removed = Object.values(previous.nodes).filter(n => !next.nodes[n.id])
        if (removed.length) void this.checkpoint('before-delete')
        for (const node of removed.filter(n => !n.parentId || next.nodes[n.parentId])) {
          const deletedIds = removed.filter(n => { let p: string | null = n.id; while (p) { if (p === node.id) return true; p = previous.nodes[p]?.parentId ?? null } return false }).map(n => n.id)
          this.record(node.type === 'file' ? 'FILE_DELETED' : 'FOLDER_DELETED', node.id, { deletedIds })
        }
        for (const node of Object.values(next.nodes)) {
          const old = previous.nodes[node.id]
          if (!old) continue
          if (node.name !== old.name) this.record(node.type === 'file' ? 'FILE_RENAMED' : 'FOLDER_RENAMED', node.id, { name: node.name })
          if (node.parentId !== old.parentId) this.record(node.type === 'file' ? 'FILE_MOVED' : 'FOLDER_MOVED', node.id, { parentId: node.parentId })
          // Non-Monaco source changes (recovery/import) are explicit, never inferred keyboard input.
          if (node.type === 'file' && old.type === 'file' && node.content !== old.content && !this.registry.get(node.id)) this.record('WORKSPACE_RECONCILED', null, { reason: 'programmatic-store-update', nodes: snapshotOf(next.nodes) })
        }
        if (created.length === 0 && Object.keys(next.nodes).length > Object.keys(previous.nodes).length) void this.checkpoint('file-created')
      }
    }
    for (const paneId of ['primary', 'secondary'] as const) {
      if (next.groups[paneId].activeFileId !== previous.groups[paneId].activeFileId) {
        const fileId = next.groups[paneId].activeFileId
        const payload = { paneId, previousFileId: previous.groups[paneId].activeFileId }
        this.record('TAB_SWITCHED', fileId, payload); this.record('ACTIVE_FILE_CHANGED', fileId, payload)
      }
    }
    if (next.activeGroupId !== previous.activeGroupId) this.record('ACTIVE_FILE_CHANGED', next.groups[next.activeGroupId].activeFileId, { paneId: next.activeGroupId, previousFileId: previous.groups[previous.activeGroupId].activeFileId })
    if (next.splitEnabled !== previous.splitEnabled || next.splitRatio !== previous.splitRatio) this.record('SPLIT_CHANGED', null, { enabled: next.splitEnabled, ratio: next.splitRatio })
  }
  checkpoint(reason: string): Promise<void> {
    if (!this.session) return Promise.resolve()
    const nodes = structuredClone(this.nodes), sequence = this.session.lastSequence
    this.changes = 0
    this.checkpointTail = this.checkpointTail.catch(() => undefined).then(async () => {
      const checkpoint: Checkpoint = { id: crypto.randomUUID(), sessionId: this.session.id, sequence, workspaceRevision: useWorkspaceStore.getState().workspace.revision, nodes, stateHash: await digest(nodes), createdAt: new Date().toISOString(), reason }
      await this.queue.checkpoint(checkpoint)
      useTelemetryStatus.setState({ checkpoint: sequence })
    }).catch(error => this.fail(error))
    return this.checkpointTail
  }
  async flush() { await this.checkpointTail; await this.queue?.flush() }
  async complete(reason = 'participant-completed') {
    this.record('SESSION_ENDED', null, { reason, interrupted: false })
    this.halted = true
    this.session.completedAt = new Date().toISOString()
    await this.checkpoint('completion'); await this.flush()
  }
  fail(error: unknown) {
    if (!this.session) return
    this.session.integrity = 'Recording Interrupted'
    this.session.error = error instanceof Error ? error.message : String(error)
    useTelemetryStatus.setState({ status: 'Recording Error', error: this.session.error })
  }
  refresh() {
    if (!this.queue?.pending.length) this.bytes = 0
    useTelemetryStatus.setState({ sequence: this.session.lastSequence, pending: this.session.lastSequence - this.session.lastAck,
      ...(this.session.error ? { status: this.halted ? 'Recording Interrupted' as const : 'Recording Error' as const, error: this.session.error } : { status: !this.uplinkAvailable || !navigator.onLine ? 'Recording Locally' as const : 'Recording' as const }) })
  }
  async export() {
    const sessions = await this.db.telemetrySessions.toArray().catch(() => [])
    const events = await this.db.telemetryEvents.toArray().catch(() => [])
    const checkpoints = await this.db.telemetryCheckpoints.toArray().catch(() => [])
    const batches = await this.db.telemetryBatches.toArray().catch(() => [])
    return { sessions, currentSession: this.session, events: [...new Map([...events, ...this.queue.pending].map(e => [e.eventId, e])).values()], checkpoints: [...new Map([...checkpoints, ...this.queue.checkpoints].map(c => [c.id, c])).values()], batches, interrupted: this.session.integrity !== 'Complete' }
  }
  stop() { this.subscriptions.forEach(dispose => dispose()); this.models.forEach(model => model.dispose()); this.queue?.dispose(); clearInterval(this.checkpointTimer); this.releaseTabLock?.() }
}
export const telemetry = new TelemetryCollector()
