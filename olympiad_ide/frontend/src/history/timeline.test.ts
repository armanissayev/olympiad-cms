import { describe, expect, it } from 'vitest'
import { digest, replay } from '../telemetry/replayEngine'
import type { Checkpoint, Snapshot, TelemetryEvent, TelemetrySession } from '../telemetry/types'
import { describeEvent, historicalPath, HistoryTimeline } from './timeline'

const sessionId = 'history-session', workspaceId = 'history-workspace', timestamp = '2026-11-03T00:00:00Z'
const initial: Snapshot = { folder: { id: 'folder', type: 'folder', parentId: null, name: 'solutions', content: null, revision: 0 }, a: { id: 'a', type: 'file', parentId: 'folder', name: 'main.cpp', content: 'A😀\n', revision: 1 } }
async function checkpoint(sequence: number, nodes: Snapshot): Promise<Checkpoint> { return { id: crypto.randomUUID(), sessionId, sequence, nodes: structuredClone(nodes), stateHash: await digest(nodes), createdAt: timestamp, reason: sequence ? 'periodic' : 'initial', workspaceRevision: 1 } }
function event(sequence: number, type: string, fileId: string | null, payload: unknown, clock = sequence * 100): TelemetryEvent { return { schemaVersion: 1, eventId: crypto.randomUUID(), sessionId, workspaceId, sequence, fileId, eventType: type, payload, clientTimestamp: timestamp, monotonicOffsetMs: clock } as TelemetryEvent }
async function session(lastSequence: number): Promise<TelemetrySession> { return { id: sessionId, workspaceId, tabId: 'tab', startedAt: timestamp, completedAt: timestamp, lastSequence, lastAck: lastSequence, integrity: 'Complete', initial: await checkpoint(0, initial), registered: true, retentionDays: 30, error: null } }
function edit(sequence: number, beforeRevision: number, insertedText: string, deletedLength = 0, type = 'TEXT_INSERT') { return event(sequence, type, 'a', { transactionId: crypto.randomUUID(), beforeRevision, afterRevision: beforeRevision + 1, changes: [{ offset: 3, deletedLength, insertedText, range: { startLineNumber: 1, startColumn: 4, endLineNumber: 1, endColumn: 4 + deletedLength } }], origin: 'editor', inputEventId: null, eol: '\n' }) }

describe('Phase 5 checkpoint-backed history', () => {
  it('reconstructs Unicode, large insert, undo/redo and multi-file operations in either direction without mutating history', async () => {
    const large = 'λ'.repeat(2000), events = [edit(1, 1, large), edit(2, 2, '', large.length, 'UNDO'), edit(3, 3, large, 0, 'REDO'), event(4, 'FILE_CREATED', 'b', { node: { id: 'b', parentId: 'folder', name: 'helper.py', type: 'file', content: 'print(7)', revision: 1 } }), event(5, 'ACTIVE_FILE_CHANGED', 'b', { paneId: 'primary', previousFileId: 'a' }), event(6, 'FOLDER_RENAMED', 'folder', { name: 'src' }), event(7, 'FILE_MOVED', 'b', { parentId: null }), event(8, 'FILE_DELETED', 'a', { deletedIds: ['a'] })]
    const cp = await checkpoint(3, replay(initial, events, 3)), originalEvents = structuredClone(events), originalCheckpoint = structuredClone(cp)
    const timeline = await HistoryTimeline.create(await session(8), events, [cp])
    expect(timeline.issues).toEqual([])
    expect(timeline.seek(1).nodes.a?.content).toBe('A😀' + large + '\n')
    expect(timeline.seek(2).nodes.a?.content).toBe('A😀\n')
    expect(describeEvent(events[0]!)).toContain('large insert'); expect(describeEvent(events[1]!)).toContain('Undo'); expect(describeEvent(events[2]!)).toContain('Redo')
    expect(timeline.seek(5).activeFileId).toBe('b')
    expect(historicalPath(timeline.seek(6).nodes, 'b')).toBe('src/helper.py')
    expect(historicalPath(timeline.seek(7).nodes, 'b')).toBe('helper.py')
    expect(timeline.seek(8).nodes.a).toBeUndefined()
    const displayed = timeline.seek(3); displayed.nodes.a!.content = 'attempted historical edit'
    expect(timeline.seek(3).nodes.a?.content).toBe('A😀' + large + '\n')
    expect(timeline.seek(0).nodes).toEqual(initial)
    expect(events).toEqual(originalEvents); expect(cp).toEqual(originalCheckpoint)
  })
  it('seeks from the nearest verified checkpoint rather than replaying the whole stream', async () => {
    const events = Array.from({ length: 3000 }, (_, i) => event(i + 1, 'PAGE_VISIBLE', null, {}))
    const timeline = await HistoryTimeline.create(await session(3000), events, [await checkpoint(1000, initial), await checkpoint(2000, initial)])
    expect(timeline.seek(2300)).toMatchObject({ available: true, checkpointSequence: 2000, appliedEvents: 300 })
    expect(timeline.seek(1001)).toMatchObject({ checkpointSequence: 1000, appliedEvents: 1 })
  })
  it('stops at missing data, discloses interruption and resumes only from a real recorded checkpoint', async () => {
    const events = [event(1, 'ACTIVE_FILE_CHANGED', 'a', { paneId: 'primary', previousFileId: null }), event(3, 'FILE_RENAMED', 'a', { name: 'later.cpp' })]
    const recovered: Snapshot = structuredClone(initial); recovered.a!.name = 'later.cpp'; recovered.a!.content = 'actual later checkpoint'
    const data = await session(4); data.integrity = 'Recording Interrupted'; data.error = 'Browser closed without completion'
    const timeline = await HistoryTimeline.create(data, events, [await checkpoint(3, recovered)])
    expect(timeline.seek(2)).toMatchObject({ available: false, verifiedThrough: 1, checkpointSequence: 0 })
    expect(timeline.seek(2).nodes).toEqual(initial)
    expect(timeline.seek(3)).toMatchObject({ available: true, activeFileId: null, checkpointSequence: 3, appliedEvents: 0 })
    expect(timeline.seek(3).nodes.a?.content).toBe('actual later checkpoint')
    expect(timeline.seek(4).available).toBe(false)
    expect(timeline.issues.some(i => i.integrity === 'Missing Events')).toBe(true)
    expect(timeline.issues.some(i => i.integrity === 'Recording Interrupted')).toBe(true)
  })
  it('rejects a corrupt checkpoint and never substitutes its state for valid events', async () => {
    const events = [edit(1, 1, 'ok')], wrong = structuredClone(initial); wrong.a!.content = 'unrelated data'; wrong.a!.revision = 2
    const timeline = await HistoryTimeline.create(await session(1), events, [await checkpoint(1, wrong)])
    expect(timeline.checkpoints).toHaveLength(1)
    expect(timeline.issues[0]?.integrity).toBe('Checkpoint Mismatch')
    expect(timeline.seek(1).nodes.a?.content).toBe('A😀ok\n')
  })
  it('does not hide a revision failure behind a later checkpoint', async () => {
    const events = [edit(1, 90, 'invalid')]
    const timeline = await HistoryTimeline.create(await session(1), events, [await checkpoint(1, initial)])
    expect(timeline.issues.some(issue => issue.message.includes('Revision Mismatch'))).toBe(true)
    expect(timeline.seek(1).checkpointSequence).toBe(1)
  })
  it.each(['scope', 'clock', 'duplicate'])('identifies invalid %s envelopes without fabricating a frame', async type => {
    const events = [event(1, 'PAGE_VISIBLE', null, {}), event(2, 'PAGE_HIDDEN', null, {})]
    if (type === 'scope') events[1]!.workspaceId = 'another-workspace'
    if (type === 'clock') events[1]!.monotonicOffsetMs = 1
    if (type === 'duplicate') events[1]!.eventId = events[0]!.eventId
    const timeline = await HistoryTimeline.create(await session(2), events, [])
    expect(timeline.seek(2)).toMatchObject({ available: false, verifiedThrough: 1 })
    expect(timeline.issues.some(i => i.integrity === 'Invalid Event')).toBe(true)
  })
  it('requires a valid initial snapshot and permits repeated equal periodic checkpoints', async () => {
    const data = await session(1), cp = await checkpoint(1, initial)
    const good = await HistoryTimeline.create(data, [event(1, 'PAGE_VISIBLE', null, {})], [cp, { ...cp, id: 'also-manual' }])
    expect(good.issues).toEqual([])
    data.initial.stateHash = 'incorrect'
    await expect(HistoryTimeline.create(data, [], [])).rejects.toThrow('hash mismatch')
  })
  it('advances dense event streams by recorded monotonic time and stops on a gap', async () => {
    const events = Array.from({ length: 500 }, (_, i) => event(i + 1, 'PAGE_VISIBLE', null, {}, i + 1))
    const timeline = await HistoryTimeline.create(await session(500), events, [])
    expect(timeline.advance(0, 250)).toBe(250)
    expect(timeline.advance(250, 500)).toBe(500)
    const missing = await HistoryTimeline.create(await session(3), [events[0]!, { ...events[2]!, sequence: 3 }], [])
    expect(missing.advance(1, 500)).toBe(2)
  })
})
