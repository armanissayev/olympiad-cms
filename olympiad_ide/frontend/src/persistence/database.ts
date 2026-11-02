import Dexie, { type Table } from 'dexie'
import { databaseName } from '../cms/session'
import type { StoredIntent } from '../cms/types'
import type { WorkspaceMetadata, WorkspaceNode, EditorSettings } from '../types/workspace'
import type { Conflict, EditorSession, RecoverySnapshot, SyncOperation, WorkspaceDocument } from './types'
import type { TelemetrySession, TelemetryEvent, DurableBatch, Checkpoint, Acknowledgement } from '../telemetry/types'
import type { LocalResource, ResourceOperation, Submission, JobEvent } from '../execution/types'

export interface LocalWorkspace {
  id: string
  metadata: WorkspaceMetadata
  localVersion: number
  lastSyncedRevision: number
  lastSyncedAt: string | null
  serverDocument: WorkspaceDocument | null
}

export type LocalNode = { workspaceId: string; id: string; node: WorkspaceNode; deletedAt: string | null }

export class WorkspaceDatabase extends Dexie {
  officialSubmissionIntents!: Table<StoredIntent, string>
  workspaces!: Table<LocalWorkspace, string>
  fileNodes!: Table<LocalNode, [string, string]>
  editorSessions!: Table<{ workspaceId: string; state: EditorSession }, string>
  workspaceSettings!: Table<{ workspaceId: string; settings: EditorSettings }, string>
  syncOperations!: Table<SyncOperation, number>
  recoverySnapshots!: Table<RecoverySnapshot, string>
  conflicts!: Table<Conflict, string>
  testCases!: Table<LocalResource, string>
  runConfigurations!: Table<LocalResource, string>
  executionResourceOperations!: Table<ResourceOperation, number>
  executionSubmissions!: Table<Submission & { acknowledged: boolean }, string>
  executionEvents!: Table<JobEvent & { jobId: string }, [string, number]>
  metadata!: Table<{ key: string; value: string }, string>
  telemetrySessions!: Table<TelemetrySession, string>
  telemetryEvents!: Table<TelemetryEvent, [string, number]>
  telemetryBatches!: Table<DurableBatch, string>
  telemetryCheckpoints!: Table<Checkpoint, string>
  telemetryAcknowledgements!: Table<Acknowledgement, string>

  constructor(name = databaseName()) {
    super(name)
    this.version(1).stores({
      workspaces: 'id',
      fileNodes: '[workspaceId+id], workspaceId',
      editorSessions: 'workspaceId',
      workspaceSettings: 'workspaceId',
      syncOperations: '++sequence, &operationId, workspaceId, status',
      recoverySnapshots: 'snapshotId, workspaceId, [workspaceId+fileId], createdAt',
      testCases: 'id, workspaceId',
      metadata: 'key',
    })
    this.version(2).stores({ conflicts: 'workspaceId' }).upgrade(async (tx) => {
      // A request interrupted by reload remains immutable and is replayed by operationId.
      await tx.table('syncOperations').toCollection().modify((op: SyncOperation) => {
        op.retryCount ??= 0
      })
    })
    this.version(3).stores({
      telemetrySessions: 'id, workspaceId, tabId, startedAt',
      telemetryEvents: '[sessionId+sequence], &eventId, sessionId',
      telemetryBatches: 'id, sessionId, [sessionId+firstSequence]',
      telemetryCheckpoints: 'id, sessionId, [sessionId+sequence]',
      telemetryAcknowledgements: 'batchId, sessionId',
    })
    this.version(5).stores({ officialSubmissionIntents: 'intentId, taskId, state, createdAt' })
    this.version(4).stores({
      runConfigurations: 'id, workspaceId',
      executionResourceOperations: '++sequence, &operationId, resourceId, workspaceId',
      executionSubmissions: 'id, workspaceId',
      executionEvents: '[jobId+sequence], jobId',
    }).upgrade(async tx => {
      await tx.table('testCases').toCollection().modify(row => {
        row.value ??= { kind: 'test', id: row.id, name: row.name, stdin: row.stdin, expectedStdout: row.expectedStdout ?? null }
        row.revision ??= 0; row.localVersion ??= 0; row.deleted ??= false
      })
    })
  }
}

export let database = new WorkspaceDatabase()
/** Rebind only after the old task's writers and transports have drained. */
export function bindDatabase(next: WorkspaceDatabase) { database = next }
