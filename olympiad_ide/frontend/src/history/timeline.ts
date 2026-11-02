import { applyEvent, digest, IntegrityError, validateTree } from '../telemetry/replayEngine'
import { documentTypes, type Checkpoint, type Integrity, type Snapshot, type TelemetryEvent, type TelemetrySession } from '../telemetry/types'

export interface HistoryIssue { sequence: number; integrity: Integrity; message: string }
export interface HistoryFrame {
  requestedSequence: number
  verifiedThrough: number
  available: boolean
  nodes: Snapshot
  activeFileId: string | null
  event: TelemetryEvent | null
  checkpointSequence: number
  appliedEvents: number
  error: string | null
}

/** Historical snapshots are separate from live editor models. Missing events never become inferred edits. */
export class HistoryTimeline {
  readonly events: TelemetryEvent[]
  readonly checkpoints: Checkpoint[] = []
  readonly issues: HistoryIssue[] = []
  readonly session: TelemetrySession
  readonly lastSequence: number
  private readonly bySequence = new Map<number, TelemetryEvent>()
  private readonly invalid = new Map<number, string>()

  private constructor(session: TelemetrySession, events: TelemetryEvent[]) {
    this.session = structuredClone(session)
    this.events = structuredClone(events).sort((a, b) => a.sequence - b.sequence)
    this.lastSequence = Math.max(session.lastSequence, this.events.at(-1)?.sequence ?? 0)
  }

  static async create(session: TelemetrySession, events: TelemetryEvent[], checkpoints: Checkpoint[]): Promise<HistoryTimeline> {
    const timeline = new HistoryTimeline(session, events)
    if (!Number.isSafeInteger(timeline.lastSequence) || timeline.lastSequence < 0) throw new Error('Invalid recording length')
    if (session.initial.sequence !== 0 || session.initial.sessionId !== session.id) throw new Error('Initial recording snapshot is unavailable')
    validateTree(session.initial.nodes)
    if (await digest(session.initial.nodes) !== session.initial.stateHash) throw new Error('Initial checkpoint hash mismatch')
    timeline.checkpoints.push(structuredClone(session.initial))
    let expected = 1, clock = 0
    const ids = new Set<string>()
    for (const event of timeline.events) {
      if (!Number.isSafeInteger(event.sequence) || event.sequence < 1) throw new Error('Invalid event sequence')
      if (event.sequence > expected) timeline.issue(expected, 'Missing Events', `Events ${expected}–${event.sequence - 1} are unavailable`)
      expected = Math.max(expected, event.sequence + 1)
      if (timeline.bySequence.has(event.sequence) || ids.has(event.eventId)) timeline.invalidate(event.sequence, 'Duplicate event identity or sequence')
      if (event.schemaVersion !== 1 || event.sessionId !== session.id || event.workspaceId !== session.workspaceId || !Number.isFinite(Date.parse(event.clientTimestamp)) || !Number.isFinite(event.monotonicOffsetMs) || event.monotonicOffsetMs < clock) timeline.invalidate(event.sequence, 'Invalid event envelope, scope or monotonic clock')
      ids.add(event.eventId); clock = Math.max(clock, event.monotonicOffsetMs)
      timeline.bySequence.set(event.sequence, event)
    }
    if (expected <= timeline.lastSequence) timeline.issue(expected, 'Missing Events', `Recording ends before advertised event ${timeline.lastSequence}`)
    if (session.integrity !== 'Complete') timeline.issue(session.lastSequence, session.integrity, session.error ?? 'This recording ended with an interruption; no missing activity is invented')
    const seen = new Set<number>([0])
    for (const checkpoint of [...checkpoints].sort((a, b) => a.sequence - b.sequence)) {
      if (checkpoint.id === session.initial.id) continue
      if (checkpoint.sessionId !== session.id || !Number.isSafeInteger(checkpoint.sequence) || checkpoint.sequence < 0 || checkpoint.sequence > timeline.lastSequence || seen.has(checkpoint.sequence)) {
        // Repeated snapshots at the same sequence are normal (manual + periodic checkpoint).
        if (seen.has(checkpoint.sequence) && checkpoint.sessionId === session.id && await digest(checkpoint.nodes) === checkpoint.stateHash && checkpoint.stateHash === timeline.checkpoints.find(c => c.sequence === checkpoint.sequence)?.stateHash) continue
        timeline.issue(checkpoint.sequence, 'Checkpoint Mismatch', 'Checkpoint identity, sequence or duplicate snapshot is inconsistent'); continue
      }
      try {
        validateTree(checkpoint.nodes)
        if (await digest(checkpoint.nodes) !== checkpoint.stateHash) throw new Error('Stored checkpoint hash differs')
        const preceding = timeline.seek(checkpoint.sequence)
        if (preceding.available && await digest(preceding.nodes) !== checkpoint.stateHash) throw new Error('Checkpoint differs from reconstructed event history')
        if (!preceding.available && !timeline.issues.some(issue => issue.sequence === preceding.verifiedThrough + 1)) timeline.issue(preceding.verifiedThrough + 1, 'Invalid Event', preceding.error ?? 'History cannot reach this checkpoint')
        // A self-consistent recorded checkpoint can recover a later state after a gap.
        // The gap remains disclosed and intermediate states remain unavailable.
        timeline.checkpoints.push(structuredClone(checkpoint)); seen.add(checkpoint.sequence)
      } catch (error) { timeline.issue(checkpoint.sequence, 'Checkpoint Mismatch', error instanceof Error ? error.message : 'Invalid checkpoint') }
    }
    const final = timeline.seek(timeline.lastSequence)
    if (!final.available && !timeline.issues.some(issue => issue.sequence === final.verifiedThrough + 1)) timeline.issue(final.verifiedThrough + 1, 'Invalid Event', final.error ?? 'Recording cannot be reconstructed')
    return timeline
  }

  private issue(sequence: number, integrity: Integrity, message: string) { this.issues.push({ sequence, integrity, message }) }
  private invalidate(sequence: number, message: string) { this.invalid.set(sequence, message); this.issue(sequence, 'Invalid Event', message) }

  seek(sequence: number): HistoryFrame {
    if (!Number.isSafeInteger(sequence) || sequence < 0 || sequence > this.lastSequence) throw new Error('History position is outside the recorded session')
    const checkpoint = [...this.checkpoints].reverse().find(c => c.sequence <= sequence)!
    let nodes = structuredClone(checkpoint.nodes), verifiedThrough = checkpoint.sequence, appliedEvents = 0, error: string | null = null
    for (let next = checkpoint.sequence + 1; next <= sequence; next++) {
      const event = this.bySequence.get(next)
      if (!event || this.invalid.has(next)) { error = this.invalid.get(next) ?? `Missing event ${next}; the requested state cannot be reconstructed`; break }
      try { nodes = applyEvent(nodes, event); verifiedThrough = next; appliedEvents++ }
      catch (failure) { error = `${failure instanceof IntegrityError ? failure.integrity : 'Invalid Event'} at event ${next}: ${failure instanceof Error ? failure.message : 'Cannot reconstruct this event'}`; break }
    }
    let activeFileId: string | null = null
    for (let index = this.events.length - 1; index >= 0; index--) {
      const event = this.events[index]!
      if (event.sequence <= verifiedThrough && event.eventType === 'ACTIVE_FILE_CHANGED') {
        if (!this.issues.some(issue => issue.integrity === 'Missing Events' && issue.sequence > event.sequence && issue.sequence <= verifiedThrough)) activeFileId = event.fileId
        break
      }
    }
    if (activeFileId && nodes[activeFileId]?.type !== 'file') activeFileId = null
    return { requestedSequence: sequence, verifiedThrough, available: verifiedThrough === sequence, nodes, activeFileId, event: this.bySequence.get(verifiedThrough) ?? null, checkpointSequence: checkpoint.sequence, appliedEvents, error }
  }

  elapsed(sequence: number): number { return this.bySequence.get(sequence)?.monotonicOffsetMs ?? 0 }
  advance(sequence: number, throughOffset: number): number {
    while (sequence < this.lastSequence) {
      const next = this.bySequence.get(sequence + 1)
      if (!next || this.invalid.has(sequence + 1)) return sequence + 1
      if (next.monotonicOffsetMs > throughOffset) break
      sequence++
    }
    return sequence
  }

}

export function describeEvent(event: TelemetryEvent | null): string {
  if (!event) return 'Initial recorded workspace'
  if (documentTypes.has(event.eventType) && 'changes' in event.payload) {
    const inserted = event.payload.changes.reduce((n, change) => n + change.insertedText.length, 0)
    const removed = event.payload.changes.reduce((n, change) => n + change.deletedLength, 0)
    const label = event.eventType === 'UNDO' ? 'Undo' : event.eventType === 'REDO' ? 'Redo' : 'Edit'
    return `${label}: +${inserted} / −${removed} UTF-16 units${inserted >= 1000 ? ' · large insert' : ''}`
  }
  if ((event.eventType === 'FILE_CREATED' || event.eventType === 'FOLDER_CREATED') && 'node' in event.payload) return `Created ${event.payload.node.name}`
  if ((event.eventType === 'FILE_RENAMED' || event.eventType === 'FOLDER_RENAMED') && 'name' in event.payload) return `Renamed to ${event.payload.name}`
  return event.eventType.toLowerCase().replaceAll('_', ' ')
}

export function historicalPath(nodes: Snapshot, id: string): string {
  const node = nodes[id]
  if (!node) return '(file unavailable)'
  const parts = [node.name]; let parent = node.parentId
  while (parent && nodes[parent]) { parts.unshift(nodes[parent]!.name); parent = nodes[parent]!.parentId }
  return parts.join('/')
}
