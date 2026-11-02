import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { editor } from 'monaco-editor'
import { WorkspaceDatabase } from '../persistence/database'
import { MonacoModelRegistry } from '../editor/modelRegistry'
import { initialData, seedFileIds, useWorkspaceStore } from '../store/workspaceStore'
import { TelemetryCollector, telemetryConfig, useTelemetryStatus } from './collector'
import { applyEvent, digest, IntegrityError, replay, verifyCheckpoint } from './replayEngine'
import { keyboardPayload } from './keyboardTracker'
import { TelemetrySync, uploadConfig } from './telemetrySync'
import { withDocumentOrigin } from './origin'
import type { DocumentTransaction, Snapshot } from './types'

class FakeModel {
  text: string
  version = 1
  changes = new Set<(event: editor.IModelContentChangedEvent) => void>()
  disposals = new Set<() => void>()
  disposed = false
  constructor(text: string) { this.text = text }
  getValue() { return this.text }
  getVersionId() { return this.version }
  isDisposed() { return this.disposed }
  onDidChangeContent(listener: (event: editor.IModelContentChangedEvent) => void) { this.changes.add(listener); return { dispose: () => this.changes.delete(listener) } }
  onWillDispose(listener: () => void) { this.disposals.add(listener); return { dispose: () => this.disposals.delete(listener) } }
  dispose() { this.disposed = true; [...this.disposals].forEach(f => f()) }
  change(changes: { rangeOffset: number; rangeLength: number; text: string }[], undo = false, redo = false) {
    for (const change of [...changes].sort((a, b) => b.rangeOffset - a.rangeOffset)) this.text = this.text.slice(0, change.rangeOffset) + change.text + this.text.slice(change.rangeOffset + change.rangeLength)
    this.version++
    this.changes.forEach(f => f({ changes: changes.map(c => ({ ...c, range: { startLineNumber: 1, startColumn: c.rangeOffset + 1, endLineNumber: 1, endColumn: c.rangeOffset + c.rangeLength + 1 } })), eol: '\n', versionId: this.version, isUndoing: undo, isRedoing: redo, isFlush: false, isEolChange: false }))
  }
}

let db: WorkspaceDatabase, registry: MonacoModelRegistry, collector: TelemetryCollector
beforeEach(async () => {
  sessionStorage.clear()
  useWorkspaceStore.setState(initialData())
  db = new WorkspaceDatabase(`telemetry-${crypto.randomUUID()}`)
  registry = new MonacoModelRegistry()
  collector = new TelemetryCollector(db, registry)
  await collector.start()
})
afterEach(async () => { collector.stop(); vi.restoreAllMocks(); await db.delete() })
const events = () => db.telemetryEvents.where('sessionId').equals(collector.session.id).sortBy('sequence')
const fid = seedFileIds.main
function attach(text?: string) {
  const file = useWorkspaceStore.getState().nodes[fid]!
  if (file.type !== 'file') throw new Error('Missing seed file')
  const model = new FakeModel(text ?? file.content)
  registry.adopt(file, model as unknown as editor.ITextModel)
  return model
}

describe('scoped keyboard contracts', () => {
  it.each(['a', 'Backspace', 'Delete', 'ArrowLeft', 'Enter', 'Tab', 'Escape', 'Ω', 'Process'])('retains key/code, modifiers, repeat and composition: %s', async key => {
    const payload = keyboardPayload(new KeyboardEvent('keydown', { key, code: key === 'a' ? 'KeyA' : key, ctrlKey: true, altKey: true, shiftKey: true, metaKey: true, repeat: true, isComposing: key === 'Process' }), 'secondary')
    collector.key('KEY_DOWN', fid, payload); collector.key('KEY_UP', fid, payload)
    await collector.flush()
    expect((await events()).map(e => e.eventType)).toEqual(['KEY_DOWN', 'KEY_UP'])
    expect(payload).toMatchObject({ key, repeat: true, ctrl: true, alt: true, shift: true, meta: true, composing: key === 'Process' })
  })
})

describe('model authority and replay', () => {
  it('one listener for a shared split model; tabs, rename and undo preserve revision continuity', async () => {
    const model = attach()
    const file = useWorkspaceStore.getState().nodes[fid]!
    if (file.type !== 'file') throw new Error('file')
    registry.adopt(file, model as unknown as editor.ITextModel)
    collector.trackModel(fid, model as unknown as editor.ITextModel)
    expect(model.changes.size).toBe(1)
    model.change([{ rangeOffset: 0, rangeLength: 0, text: 'Ω😀' }])
    useWorkspaceStore.getState().openFile(seedFileIds.solution)
    useWorkspaceStore.getState().renameNode(fid, 'renamed.cpp')
    useWorkspaceStore.getState().openFile(fid)
    model.change([{ rangeOffset: 0, rangeLength: 3, text: '' }], true)
    model.change([{ rangeOffset: 0, rangeLength: 0, text: 'Ω😀' }], false, true)
    await collector.checkpoint('test')
    const recorded = await events()
    expect(recorded.filter(e => ['TEXT_INSERT', 'UNDO', 'REDO'].includes(e.eventType))).toHaveLength(3)
    expect(replay(collector.session.initial.nodes, recorded)[fid]).toMatchObject({ name: 'renamed.cpp', content: model.text, revision: file.documentRevision + 3 })
    const checkpoint = (await db.telemetryCheckpoints.where('sessionId').equals(collector.session.id).sortBy('sequence')).at(-1)!
    await verifyCheckpoint(replay(collector.session.initial.nodes, recorded), checkpoint)
    model.dispose(); expect(model.changes.size).toBe(0)
  })
  it('multi-cursor changes use BEFORE offsets; a large insert is not inferred to be paste', async () => {
    const model = attach()
    model.change([{ rangeOffset: 10, rangeLength: 2, text: 'XYZ' }, { rangeOffset: 0, rangeLength: 1, text: 'Ω' }])
    model.change([{ rangeOffset: 0, rangeLength: 0, text: 'x'.repeat(300_000) }])
    await collector.flush()
    const recorded = await events()
    expect(recorded.map(e => e.eventType)).toEqual(['DOCUMENT_CHANGE', 'TEXT_INSERT'])
    expect(replay(collector.session.initial.nodes, recorded)[fid]?.content).toBe(model.text)
  })
  it('explicit reconciliation labels recovery and never emits participant typing', async () => {
    const model = attach()
    withDocumentOrigin('recovery-snapshot', () => {
      model.change([{ rangeOffset: 0, rangeLength: model.text.length, text: 'restored' }])
      useWorkspaceStore.getState().setFileContent(fid, 'restored')
    })
    await collector.flush()
    expect((await events()).map(e => e.eventType)).toEqual(['WORKSPACE_RECONCILED'])
    expect(replay(collector.session.initial.nodes, await events())[fid]?.content).toBe('restored')
  })
  it('reconstructs multi-file structure at every intermediate sequence in a seeded randomized trace', async () => {
    let seed = 1234
    const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 2 ** 32 }
    const expected: Snapshot[] = [structuredClone(collector.nodes)]
    // All operations go through normal store/model observation, not the replay implementation.
    const folder = useWorkspaceStore.getState().createFolder(null, 'generated')
    const files = Array.from({ length: 3 }, (_, i) => useWorkspaceStore.getState().createFile(folder, `${i}.cpp`, 'start😀'))
    await collector.flush()
    let trace = await events()
    for (const e of trace) expected.push(applyEvent(expected.at(-1)!, e))
    const models = files.map(id => {
      const file = useWorkspaceStore.getState().nodes[id]!
      if (file.type !== 'file') throw new Error('file')
      const model = new FakeModel(file.content); registry.adopt(file, model as unknown as editor.ITextModel); return model
    })
    for (let step = 0; step < 150; step++) {
      const index = Math.floor(random() * 3), id = files[index]!, model = models[index]!
      const before = collector.session.lastSequence
      const offset = Math.floor(random() * (model.text.length + 1))
      model.change([{ rangeOffset: offset, rangeLength: Math.min(model.text.length - offset, Math.floor(random() * 3)), text: ['x', '😀', '\n', 'Ω', ''][Math.floor(random() * 5)]! }], step % 7 === 0, step % 11 === 0)
      expect(collector.session.lastSequence).toBe(before + 1)
      expected.push({ ...structuredClone(collector.nodes), [id]: { ...collector.nodes[id]!, content: model.text } })
    }
    useWorkspaceStore.getState().moveNode(files[0]!, null)
    useWorkspaceStore.getState().renameNode(folder, 'renamed')
    useWorkspaceStore.getState().deleteNode(folder)
    await collector.flush(); trace = await events()
    for (let sequence = 0; sequence < expected.length; sequence++) expect(replay(collector.session.initial.nodes, trace, sequence)).toEqual(expected[sequence])
    const final = replay(collector.session.initial.nodes, trace)
    expect(final[files[0]!]?.content).toBe(models[0]!.text)
    expect(final[files[1]!]).toBeUndefined()
  })
  it('reports gaps, revision mismatches, invalid offsets and checkpoint mismatches', async () => {
    attach().change([{ rangeOffset: 0, rangeLength: 0, text: 'a' }]); await collector.flush()
    const event = (await events())[0]!
    expect(() => replay(collector.session.initial.nodes, [{ ...event, sequence: 2 }])).toThrow(IntegrityError)
    const bad = structuredClone(event); (bad.payload as DocumentTransaction).beforeRevision = 900
    expect(() => replay(collector.session.initial.nodes, [bad])).toThrow('Revision mismatch')
    const offsets = structuredClone(event); (offsets.payload as DocumentTransaction).changes[0]!.offset = 99999
    expect(() => replay(collector.session.initial.nodes, [offsets])).toThrow('UTF-16')
    await expect(verifyCheckpoint(collector.nodes, { ...collector.session.initial, nodes: collector.nodes })).rejects.toThrow('Checkpoint')
  })
})

describe('durability and transport', () => {
  it('checkpoints use exact boundaries at the configured change threshold and completion', async () => {
    const old = telemetryConfig.checkpointChanges; telemetryConfig.checkpointChanges = 3
    try {
      const model = attach()
      for (let i = 0; i < 3; i++) model.change([{ rangeOffset: 0, rangeLength: 0, text: 'x' }])
      await collector.flush()
      const checkpoints = await db.telemetryCheckpoints.where('sessionId').equals(collector.session.id).toArray()
      expect(checkpoints.find(c => c.reason === 'change-limit')?.sequence).toBe(3)
      await collector.complete()
      expect(collector.record('PAGE_VISIBLE', null, {})).toBeNull()
      const final = await db.telemetryCheckpoints.where('sessionId').equals(collector.session.id).filter(c => c.reason === 'completion').first()
      expect(final?.sequence).toBe(4)
      await verifyCheckpoint(replay(collector.session.initial.nodes, await events()), final!)
    } finally { telemetryConfig.checkpointChanges = old }
  })
  it('the active-editing timer checkpoints only when documents changed', async () => {
    collector.stop()
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      collector = new TelemetryCollector(db, registry); await collector.start()
      await vi.advanceTimersByTimeAsync(60_000); await collector.flush()
      expect(await db.telemetryCheckpoints.where('sessionId').equals(collector.session.id).count()).toBe(1)
      attach().change([{ rangeOffset: 0, rangeLength: 0, text: 'timer' }])
      await vi.advanceTimersByTimeAsync(60_000); await collector.flush()
      const checkpoint = await db.telemetryCheckpoints.where('sessionId').equals(collector.session.id).filter(c => c.reason === 'active-interval').first()
      expect(checkpoint?.sequence).toBe(1)
    } finally { collector.stop(); vi.useRealTimers() }
  })
  it.each(['QuotaExceededError', 'UnknownError'])('failed IndexedDB transaction retains exact events and a sticky incomplete flag: %s', async name => {
    const spy = vi.spyOn(db.telemetryEvents, 'bulkAdd').mockRejectedValueOnce(new DOMException('Storage failure', name))
    collector.record('PAGE_VISIBLE', null, {})
    await expect(collector.flush()).rejects.toThrow('Storage failure')
    expect(collector.queue.pending).toHaveLength(1)
    expect(useTelemetryStatus.getState().status).toBe('Recording Error')
    expect((await collector.export()).events).toHaveLength(1)
    spy.mockRestore(); await collector.flush()
    expect(await events()).toHaveLength(1)
    expect((await db.telemetrySessions.get(collector.session.id))?.integrity).toBe('Recording Interrupted')
  })
  it('reload uses a fresh session/clock and keeps immutable pending batches', async () => {
    collector.record('PAGE_VISIBLE', null, {}); await collector.flush()
    const sync = new TelemetrySync(db, collector)
    const batch = await sync.buildBatch(collector.session)
    const firstId = collector.session.id
    collector.stop()
    collector = new TelemetryCollector(db, registry); await collector.start()
    expect(collector.session.id).not.toBe(firstId)
    expect(collector.session.lastSequence).toBe(0)
    expect(await db.telemetryBatches.get(batch!.id)).toEqual(batch)
    expect((await db.telemetrySessions.get(firstId))?.integrity).toBe('Recording Interrupted')
  })
  it('batch byte limits take priority over count; reload retries identical digest/body', async () => {
    attach().change([{ rangeOffset: 0, rangeLength: 0, text: 'x'.repeat(uploadConfig.maxBodyBytes + 100) }])
    collector.record('PAGE_VISIBLE', null, {}); await collector.flush()
    const sync = new TelemetrySync(db, collector)
    const batch = await sync.buildBatch(collector.session)
    expect(batch?.body.events).toHaveLength(1)
    expect(batch?.digest).toBe(await digest(batch!.body))
    expect(await new TelemetrySync(db, collector).buildBatch(collector.session)).toEqual(batch)
  })
  it('backpressure explicitly interrupts instead of silently dropping a required prefix', async () => {
    const old = telemetryConfig.maxBufferedEvents; telemetryConfig.maxBufferedEvents = 2
    try {
      for (let i = 0; i < 10; i++) collector.record('PAGE_VISIBLE', null, {})
      expect(collector.queue.pending).toHaveLength(3)
      expect(collector.session.integrity).toBe('Recording Interrupted')
      expect(useTelemetryStatus.getState().status).toBe('Recording Interrupted')
      await collector.flush(); expect(await events()).toHaveLength(3)
    } finally { telemetryConfig.maxBufferedEvents = old }
  })
})
