import type { WorkspaceNode } from '../types/workspace'

export type Integrity = 'Complete' | 'Missing Events' | 'Revision Mismatch' | 'Checkpoint Mismatch' | 'Recording Interrupted' | 'Invalid Event'
export type RecordingStatus = 'Recording' | 'Recording Locally' | 'Uploading' | 'Synced' | 'Recording Interrupted' | 'Recording Error'
export interface RecordedNode { id: string; parentId: string | null; name: string; type: 'file' | 'folder'; content: string | null; revision: number }
export type Snapshot = Record<string, RecordedNode>
export interface Range { startLineNumber: number; startColumn: number; endLineNumber: number; endColumn: number }
export interface Change { offset: number; deletedLength: number; insertedText: string; range: Range }
export interface DocumentTransaction {
  transactionId: string; beforeRevision: number; afterRevision: number; changes: Change[]
  inputEventId: string | null; origin: 'editor' | 'programmatic'; eol: '\n' | '\r\n'
}
export interface KeyPayload { paneId: string; code: string; key: string; ctrl: boolean; alt: boolean; shift: boolean; meta: boolean; repeat: boolean; composing: boolean }
export interface ExecutionCorrelation { jobId: string; snapshotId: string; sourceHash: string; configurationId: string; language: string; status: string; serverTimestamp: string }
export interface EventPayloads {
  CMS_SUBMISSION_INTENT: { intentId: string; snapshotId: string; taskId: number; language: string; submissionId?: string; receivedAt?: string }
  CMS_SUBMISSION_ADMITTED: { intentId: string; snapshotId: string; taskId: number; language: string; submissionId?: string; receivedAt?: string }
  CMS_SUBMISSION_REJECTED: { intentId: string; snapshotId: string; taskId: number; language: string; submissionId?: string; receivedAt?: string }
  KEY_DOWN: KeyPayload; KEY_UP: KeyPayload
  TEXT_INSERT: DocumentTransaction; TEXT_DELETE: DocumentTransaction; TEXT_REPLACE: DocumentTransaction
  DOCUMENT_CHANGE: DocumentTransaction; UNDO: DocumentTransaction; REDO: DocumentTransaction
  PASTE: { paneId: string; transactionId: string | null; range: Range }
  COMPOSITION_START: { paneId: string }; COMPOSITION_END: { paneId: string }
  CURSOR_MOVED: { paneId: string; lineNumber: number; column: number; source: string }
  SELECTION_CHANGED: { paneId: string; selections: Range[]; source: string }
  EDITOR_FOCUS: { paneId: string }; EDITOR_BLUR: { paneId: string }
  ACTIVE_FILE_CHANGED: { paneId: string; previousFileId: string | null }
  TAB_SWITCHED: { paneId: string; previousFileId: string | null }
  PAGE_VISIBLE: Record<string, never>; PAGE_HIDDEN: Record<string, never>
  SPLIT_CHANGED: { enabled: boolean; ratio: number }
  FILE_CREATED: { node: RecordedNode }; FOLDER_CREATED: { node: RecordedNode }
  FILE_RENAMED: { name: string }; FOLDER_RENAMED: { name: string }
  FILE_MOVED: { parentId: string | null }; FOLDER_MOVED: { parentId: string | null }
  FILE_DELETED: { deletedIds: string[] }; FOLDER_DELETED: { deletedIds: string[] }
  WORKSPACE_RECONCILED: { reason: string; nodes: Snapshot }
  SESSION_ENDED: { reason: string; interrupted: boolean }
  RUN_STARTED: { runId: string; language: string; execution?: ExecutionCorrelation }
  RUN_FINISHED: { runId: string; exitCode: number | null; durationMs: number; execution?: ExecutionCorrelation }
  DEBUG_STARTED: { debugId: string }; DEBUG_ACTION: { debugId: string; action: 'step' | 'continue' | 'pause' | 'breakpoint' }
  DEBUG_FINISHED: { debugId: string; reason: string }
}
export type EventType = keyof EventPayloads
export interface Envelope { schemaVersion: 1; eventId: string; sessionId: string; workspaceId: string; fileId: string | null; sequence: number; clientTimestamp: string; monotonicOffsetMs: number }
export type TelemetryEvent = { [K in EventType]: Envelope & { eventType: K; payload: EventPayloads[K] } }[EventType]
export interface Checkpoint { id: string; sessionId: string; sequence: number; workspaceRevision: number; nodes: Snapshot; stateHash: string; createdAt: string; reason: string }
export interface TelemetrySession {
  id: string; workspaceId: string; tabId: string; startedAt: string; completedAt: string | null
  lastSequence: number; lastAck: number; integrity: Integrity; initial: Checkpoint; registered: boolean
  retentionDays: number; error: string | null
}
export interface BatchBody { id: string; sessionId: string; events: TelemetryEvent[]; checkpoints: Checkpoint[] }
export interface DurableBatch { id: string; sessionId: string; firstSequence: number; body: BatchBody; digest: string; acknowledged: boolean }
export interface Acknowledgement { batchId: string; sessionId: string; lastSequence: number; digest: string }
export const documentTypes = new Set<EventType>(['TEXT_INSERT', 'TEXT_DELETE', 'TEXT_REPLACE', 'DOCUMENT_CHANGE', 'UNDO', 'REDO'])
export function recordedNode(node: WorkspaceNode): RecordedNode {
  return { id: node.id, parentId: node.parentId, name: node.name, type: node.type, content: node.type === 'file' ? node.content : null, revision: node.type === 'file' ? node.documentRevision : 0 }
}
export const snapshotOf = (nodes: Record<string, WorkspaceNode>): Snapshot => Object.fromEntries(Object.values(nodes).map(n => [n.id, recordedNode(n)]))
