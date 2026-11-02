import { flushSync } from 'react-dom'
import { assertDebugStopped, debugging, resetDebugController } from '../debug/controller'
import { modelRegistry } from '../editor/modelRegistry'
import { bindExecutions, ExecutionController, executions, useExecution } from '../execution/controller'
import { bindExecutionResources, executionResources, ResourceController, useExecutionResources } from '../execution/resources'
import { bindDatabase, database, WorkspaceDatabase } from '../persistence/database'
import { bindPersistence, persistence, PersistenceController } from '../persistence/controller'
import { LocalRepository } from '../persistence/repository'
import { usePersistenceStatus } from '../persistence/status'
import { toDocument } from '../persistence/types'
import { initialData, useWorkspaceStore, type WorkspaceData } from '../store/workspaceStore'
import { bindTelemetry, telemetry, TelemetryCollector, useTelemetryStatus } from '../telemetry/collector'
import { bindTelemetrySync, telemetrySync, TelemetrySync } from '../telemetry/telemetrySync'
import { drainSubmissionRequests } from './submissions'
import { restoreTaskRecovery, scopedDatabaseName, selectTask, useCMSSession } from './session'

const snapshot = (): WorkspaceData => {
  const state = useWorkspaceStore.getState(), document = toDocument(state)
  return structuredClone({ ...document.editorState, workspace: state.workspace, nodes: document.nodes, settings: document.settings, savedContents: state.savedContents }) as WorkspaceData
}
function bindScope(db: WorkspaceDatabase) {
  bindDatabase(db)
  const saving = new PersistenceController(new LocalRepository(db)); saving.stop(); bindPersistence(saving)
  const resources = new ResourceController(db); resources.stop(); bindExecutionResources(resources)
  const running = new ExecutionController(db); running.stop(); bindExecutions(running)
  bindTelemetry(new TelemetryCollector(db))
  const uploading = new TelemetrySync(db, telemetry); uploading.stop(); bindTelemetrySync(uploading)
  usePersistenceStatus.setState({ status: 'Loading', ready: false, online: false, localPending: 0, pendingOperations: 0, lastSyncedAt: null, error: null, conflict: null, detailsOpen: false })
  useExecution.setState({ job: null, history: [], events: [], partialResults: [], error: null, submitting: false, workers: 0, transport: 'Polling', clearAfter: 0 })
  useExecutionResources.setState({ items: [], activeConfigurationId: null, selectedTestId: null, stdin: '', error: null, pending: 0 })
  useTelemetryStatus.setState({ status: 'Recording Locally', sessionId: '', sequence: 0, pending: 0, lastAck: 0, gaps: 0, checkpoint: 0, error: null })
}
async function beginScope() {
  await persistence.start(false)
  if (usePersistenceStatus.getState().error) throw new Error('The problem workspace could not be opened. Your previous work is preserved.')
  await resetDebugController(database)
  await telemetry.start()
  persistence.resume(); telemetrySync.start()
  void executions.start()
}
let switching: Promise<void> | null = null
/** Keep the same document and React root; only the authorized task's storage changes. */
export function switchTaskWorkspace(id: number): Promise<void> {
  if (switching) return switching
  const previous = useCMSSession.getState(), context = previous.context
  if (!context || previous.paused || !context.tasks.some(task => task.id === id)) return Promise.reject(new Error('This problem is currently unavailable.'))
  if (previous.taskId === id) return Promise.resolve()
  const task = context.tasks.find(item => item.id === id)!, original = snapshot()
  const old = { db: database, persistence, executions, resources: executionResources, telemetry, sync: telemetrySync }
  let next: WorkspaceDatabase | null = null, handedOff = false, recordingClosed = false
  switching = (async () => {
    // Unmount the editor before clearing models. Header/sidebar shell stays mounted.
    flushSync(() => useCMSSession.setState({ switching: true }))
    try {
      next = new WorkspaceDatabase(scopedDatabaseName(context, id))
      const seed = initialData()
      seed.workspace.ownerId = context.identity.principalId; seed.workspace.name = task.title
      seed.settings = structuredClone(original.settings)
      await new LocalRepository(next).initialize(null, seed)
      await debugging.stop(); assertDebugStopped()
      await old.executions.cancel()
      // Requests still in flight keep both the old database and old task headers.
      const drains = await Promise.allSettled([old.persistence.suspend(), old.executions.suspend(), old.resources.suspend(), old.sync.suspend(), drainSubmissionRequests()])
      const failed = drains.find(result => result.status === 'rejected')
      if (failed?.status === 'rejected') throw failed.reason
      await old.telemetry.complete('task-switch'); old.telemetry.stop(); recordingClosed = true
      const current = useCMSSession.getState()
      if (current.paused || current.context?.identity.principalId !== context.identity.principalId) throw new Error('Sign in again before changing problems. Your work is saved.')
      handedOff = true
      selectTask(id)
      modelRegistry.disposeAll()
      bindScope(next)
      useWorkspaceStore.setState(initialData())
      await beginScope()
      old.db.close()
    } catch (error) {
      if (handedOff) {
        // New-scope work must also drain before restoring the previous headers.
        await Promise.allSettled([persistence.suspend(), executions.suspend(), executionResources.suspend(), telemetrySync.suspend()])
        await telemetry.flush().catch(() => undefined); telemetry.stop()
        const authorized = useCMSSession.getState().context?.tasks.some(task => task.id === previous.taskId)
        if (previous.taskId !== null && authorized) selectTask(previous.taskId)
        else restoreTaskRecovery(previous.taskId)
        modelRegistry.disposeAll(); bindScope(old.db); useWorkspaceStore.setState(original)
        await beginScope()
      } else {
        // Failed local writes stay in their original controller/queue for recovery.
        old.persistence.resume(); old.executions.resume()
        if (recordingClosed) {
          bindTelemetry(new TelemetryCollector(old.db)); bindTelemetrySync(new TelemetrySync(old.db, telemetry))
          await telemetry.start(); telemetrySync.start()
        } else old.sync.start()
      }
      next?.close()
      throw error
    } finally {
      useCMSSession.setState({ switching: false })
    }
  })().finally(() => { switching = null })
  return switching
}
