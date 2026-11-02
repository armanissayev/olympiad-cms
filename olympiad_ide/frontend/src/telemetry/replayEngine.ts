import { documentTypes, type Checkpoint, type DocumentTransaction, type Integrity, type Snapshot, type TelemetryEvent } from './types'
const passiveTypes = new Set(['KEY_DOWN', 'KEY_UP', 'PASTE', 'COMPOSITION_START', 'COMPOSITION_END', 'CURSOR_MOVED', 'SELECTION_CHANGED', 'EDITOR_FOCUS', 'EDITOR_BLUR', 'ACTIVE_FILE_CHANGED', 'PAGE_VISIBLE', 'PAGE_HIDDEN', 'TAB_SWITCHED', 'SPLIT_CHANGED', 'SESSION_ENDED', 'RUN_STARTED', 'RUN_FINISHED', 'DEBUG_STARTED', 'DEBUG_ACTION', 'DEBUG_FINISHED', 'CMS_SUBMISSION_INTENT', 'CMS_SUBMISSION_ADMITTED', 'CMS_SUBMISSION_REJECTED'])

export class IntegrityError extends Error {
  constructor(readonly integrity: Integrity, message: string) { super(message) }
}
function invalid(message: string): never { throw new IntegrityError('Invalid Event', message) }
// Canonical ASCII JSON makes hashes portable across JS/Python, including astral and lone surrogates.
export function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value).replace(/[\u0080-\uffff]/g, c => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`)
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0).map(([key, item]) => `${canonical(key)}:${canonical(item)}`).join(',')}}`
}
export async function digest(value: unknown): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonical(value)))
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('')
}
export function validateTree(nodes: Snapshot): void {
  for (const [id, node] of Object.entries(nodes)) {
    if (id !== node.id || !node.name || !['file', 'folder'].includes(node.type) || !Number.isInteger(node.revision) || (node.type === 'file' ? typeof node.content !== 'string' || node.revision < 1 : node.content !== null || node.revision !== 0)) invalid('Invalid node')
    const seen = new Set([id])
    let parent = node.parentId
    while (parent) {
      if (seen.has(parent) || nodes[parent]?.type !== 'folder') invalid('Invalid parent/cycle')
      seen.add(parent); parent = nodes[parent]!.parentId
    }
  }
}
export function applyEvent(previous: Snapshot, event: TelemetryEvent): Snapshot {
  const nodes = { ...previous }
  const node = event.fileId ? nodes[event.fileId] : undefined
  const type = event.eventType
  if (documentTypes.has(type)) {
    if (!node || node.type !== 'file' || node.content === null) invalid('Document file missing')
    const payload = event.payload as DocumentTransaction
    if (payload.beforeRevision !== node.revision || payload.afterRevision !== node.revision + 1) throw new IntegrityError('Revision Mismatch', `Revision mismatch at ${event.sequence}`)
    const content = node.content!
    let text = content, boundary = content.length
    // Monaco offsets refer to the BEFORE document. Descending offsets, stable ties, no overlapping edits.
    for (const change of payload.changes.map((change, index) => ({ ...change, index })).sort((a, b) => b.offset - a.offset || a.index - b.index)) {
      if (!Number.isInteger(change.offset) || !Number.isInteger(change.deletedLength) || change.offset < 0 || change.deletedLength < 0 || change.offset + change.deletedLength > boundary) invalid('Invalid/overlapping UTF-16 edit range')
      text = text.slice(0, change.offset) + change.insertedText + text.slice(change.offset + change.deletedLength)
      boundary = change.offset
    }
    // Monaco setEOL can emit an empty transaction; normalization is part of that transaction.
    text = text.replace(/\r\n|\r|\n/g, payload.eol)
    nodes[node.id] = { ...node, content: text, revision: payload.afterRevision }
  } else if (type === 'WORKSPACE_RECONCILED') {
    validateTree(event.payload.nodes)
    return structuredClone(event.payload.nodes)
  } else if (type === 'FILE_CREATED' || type === 'FOLDER_CREATED') {
    if (node || event.fileId !== event.payload.node.id) invalid('Duplicate node identity')
    nodes[event.payload.node.id] = { ...event.payload.node }
  } else if (type === 'FILE_RENAMED' || type === 'FOLDER_RENAMED') {
    if (!node) invalid('Missing renamed node')
    nodes[node.id] = { ...node, name: event.payload.name }
  } else if (type === 'FILE_MOVED' || type === 'FOLDER_MOVED') {
    if (!node) invalid('Missing moved node')
    nodes[node.id] = { ...node, parentId: event.payload.parentId }
  } else if (type === 'FILE_DELETED' || type === 'FOLDER_DELETED') {
    if (!node || !event.payload.deletedIds.includes(node.id)) invalid('Missing deleted node')
    for (const id of event.payload.deletedIds) { if (!nodes[id]) invalid('Unknown deleted ID'); delete nodes[id] }
  } else {
    if (!passiveTypes.has(type)) invalid('Unknown event type')
    if (event.fileId && !node) invalid('Unknown event file')
  }
  validateTree(nodes)
  return nodes
}
export function replay(initial: Snapshot, events: TelemetryEvent[], through = Infinity): Snapshot {
  validateTree(initial)
  let nodes = structuredClone(initial), sequence = 0, clock = 0
  const ids = new Set<string>()
  const sessionId = events[0]?.sessionId, workspaceId = events[0]?.workspaceId
  for (const event of events) {
    if (event.sequence > through) break
    if (event.sequence !== ++sequence) throw new IntegrityError('Missing Events', `Expected sequence ${sequence}`)
    if (event.schemaVersion !== 1 || event.sessionId !== sessionId || event.workspaceId !== workspaceId || !Number.isFinite(event.monotonicOffsetMs) || !Number.isFinite(Date.parse(event.clientTimestamp))) invalid('Invalid envelope/session')
    if (ids.has(event.eventId) || event.monotonicOffsetMs < clock) invalid('Duplicate ID or clock regression')
    ids.add(event.eventId); clock = event.monotonicOffsetMs
    nodes = applyEvent(nodes, event)
  }
  if (Number.isFinite(through) && sequence !== through) throw new IntegrityError('Missing Events', `History ends at ${sequence}`)
  return nodes
}
export async function verifyCheckpoint(nodes: Snapshot, checkpoint: Checkpoint): Promise<void> {
  if (await digest(nodes) !== checkpoint.stateHash || await digest(checkpoint.nodes) !== checkpoint.stateHash) throw new IntegrityError('Checkpoint Mismatch', `Checkpoint ${checkpoint.sequence}`)
}
