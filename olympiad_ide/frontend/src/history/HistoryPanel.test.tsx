import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { database } from '../persistence/database'
import { initialData, useWorkspaceStore } from '../store/workspaceStore'
import { digest } from '../telemetry/replayEngine'
import type { Snapshot, TelemetrySession } from '../telemetry/types'

vi.mock('@monaco-editor/react', () => ({ default: ({ value, options }: { value: string; options: { readOnly: boolean; ariaLabel: string } }) => <textarea aria-label={options.ariaLabel} value={value} readOnly={options.readOnly} /> }))
vi.mock('../editor/monaco', () => ({ monacoThemeName: () => 'vs-dark' }))
import { HistoryPanel } from './HistoryPanel'
let host: HTMLDivElement, root: Root, recording: TelemetrySession
const snapshot: Snapshot = { source: { id: 'source', parentId: null, name: 'original.py', type: 'file', content: 'print(1)', revision: 1 } }
beforeEach(async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  useWorkspaceStore.setState(initialData())
  await database.telemetrySessions.clear(); await database.telemetryEvents.clear(); await database.telemetryCheckpoints.clear()
  const id = crypto.randomUUID(), at = '2026-11-03T12:00:00Z'
  const initial = { id: crypto.randomUUID(), sessionId: id, sequence: 0, workspaceRevision: 1, nodes: structuredClone(snapshot), stateHash: await digest(snapshot), createdAt: at, reason: 'initial' }
  recording = { id, workspaceId: useWorkspaceStore.getState().workspace.id, tabId: 'tab', startedAt: at, completedAt: at, lastSequence: 1, lastAck: 1, integrity: 'Complete', initial, registered: true, retentionDays: 30, error: null }
  await database.telemetrySessions.add(recording); await database.telemetryCheckpoints.add(initial)
  await database.telemetryEvents.add({ schemaVersion: 1, sessionId: id, workspaceId: recording.workspaceId, eventId: crypto.randomUUID(), fileId: 'source', sequence: 1, clientTimestamp: at, monotonicOffsetMs: 10, eventType: 'FILE_RENAMED', payload: { name: 'renamed.py' } })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); await database.telemetrySessions.clear(); await database.telemetryEvents.clear(); await database.telemetryCheckpoints.clear(); vi.useRealTimers() })
async function render() { await act(async () => { root.render(<HistoryPanel />); await new Promise(resolve => setTimeout(resolve, 30)) }); await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)) }) }
async function click(label: string) {
 const button = [...host.querySelectorAll('button')].find(b => b.textContent === label || b.getAttribute('aria-label') === label)
 expect(button).toBeTruthy(); await act(async () => button!.click())
}
it('opens real saved history, seeks in both directions and keeps source and recording read-only', async () => {
 const nodes = structuredClone(useWorkspaceStore.getState().nodes), events = await database.telemetryEvents.toArray()
 await render(); expect(host.textContent).toContain('print(1)')
 await click('Next history event'); expect(host.querySelector('[aria-label="History preview file"]')?.textContent).toContain('renamed.py')
 await click('Previous history event'); expect(host.querySelector('[aria-label="History preview file"]')?.textContent).toContain('original.py')
 await click('Open replay'); const source = host.querySelector<HTMLTextAreaElement>('[aria-label="History replay source"]')!
 expect(source.value).toBe('print(1)'); expect(source.readOnly).toBe(true)
 await click('Close replay'); expect(useWorkspaceStore.getState().nodes).toEqual(nodes)
 expect(await database.telemetryEvents.toArray()).toEqual(events); expect(await database.telemetrySessions.get(recording.id)).toEqual(recording)
})
it('identifies a missing event without displaying a fabricated later state', async () => {
 await database.telemetryEvents.clear(); await render(); await click('Next history event')
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('Missing event 1')
 expect(host.textContent).toContain('last verified state at event 0')
 expect(host.querySelector('[aria-label="History source preview"]')?.textContent).toBe('print(1)')
})

it('plays real recording time at selected speed, pauses and leaves historical/live files unchanged', async () => {
 await database.telemetryEvents.update([recording.id, 1], { monotonicOffsetMs: 1000 })
 await database.telemetrySessions.update(recording.id, { lastSequence: 3 })
 for (const sequence of [2, 3]) await database.telemetryEvents.add({ schemaVersion: 1, sessionId: recording.id, workspaceId: recording.workspaceId, eventId: crypto.randomUUID(), fileId: null, sequence, clientTimestamp: recording.startedAt, monotonicOffsetMs: sequence * 1000, eventType: 'PAGE_VISIBLE', payload: {} })
 const nodes = structuredClone(useWorkspaceStore.getState().nodes), events = await database.telemetryEvents.toArray()
 await render()
 vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] })
 const speed = host.querySelector<HTMLSelectElement>('[aria-label="History playback speed"]')!
 expect([...speed.options].map(option => Number(option.value))).toEqual([0.5, 1, 2, 4, 8])
 await act(async () => { speed.value = '2'; speed.dispatchEvent(new Event('change', { bubbles: true })) })
 await click('Play replay')
 await act(async () => { await vi.advanceTimersByTimeAsync(400) })
 expect(host.querySelector<HTMLInputElement>('[aria-label="History timeline"]')!.value).toBe('0')
 await click('Pause replay')
 await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
 expect(host.querySelector<HTMLInputElement>('[aria-label="History timeline"]')!.value).toBe('0')
 await click('Play replay')
 await act(async () => { await vi.advanceTimersByTimeAsync(550) })
 expect(host.querySelector<HTMLInputElement>('[aria-label="History timeline"]')!.value).toBe('1')
 await click('Pause replay')
 expect(useWorkspaceStore.getState().nodes).toEqual(nodes)
 expect(await database.telemetryEvents.toArray()).toEqual(events)
})
