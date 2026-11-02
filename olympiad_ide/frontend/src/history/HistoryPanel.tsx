import Editor from '@monaco-editor/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { database } from '../persistence/database'
import { telemetry } from '../telemetry/collector'
import type { TelemetrySession } from '../telemetry/types'
import { useWorkspaceStore } from '../store/workspaceStore'
import { monacoThemeName } from '../editor/monaco'
import { describeEvent, historicalPath, HistoryTimeline } from './timeline'
import './history.css'

export function HistoryPanel() {
  const workspaceId = useWorkspaceStore(s => s.workspace.id), theme = useWorkspaceStore(s => s.settings.theme)
  const [sessions, setSessions] = useState<TelemetrySession[]>([]), [selected, setSelected] = useState('')
  const [timeline, setTimeline] = useState<HistoryTimeline | null>(null), [position, setPosition] = useState(0)
  const [fileId, setFileId] = useState(''), [playing, setPlaying] = useState(false), [speed, setSpeed] = useState(1)
  const [expanded, setExpanded] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null)
  const generation = useRef(0), positionRef = useRef(0), dialogRef = useRef<HTMLElement | null>(null)
  positionRef.current = position
  const refresh = useCallback(async () => {
    try {
      if (telemetry.session?.workspaceId === workspaceId) await telemetry.flush()
      const rows = await database.telemetrySessions.where('workspaceId').equals(workspaceId).sortBy('startedAt')
      setSessions(rows.reverse()); setSelected(previous => rows.some(row => row.id === previous) ? previous : rows[0]?.id ?? ''); setError(null)
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Cannot read local recordings') }
  }, [workspaceId])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    const ticket = ++generation.current
    setPlaying(false); setTimeline(null); setPosition(0)
    if (!selected) return
    setBusy(true)
    void (async () => {
      const session = await database.telemetrySessions.get(selected)
      if (!session || session.workspaceId !== workspaceId) throw new Error('Recording does not belong to this workspace')
      const [events, checkpoints] = await Promise.all([database.telemetryEvents.where('sessionId').equals(selected).sortBy('sequence'), database.telemetryCheckpoints.where('sessionId').equals(selected).sortBy('sequence')])
      const loaded = await HistoryTimeline.create(session, events, checkpoints)
      if (ticket === generation.current) { setTimeline(loaded); setPosition(0); setFileId(''); setError(null) }
    })().catch(failure => { if (ticket === generation.current) setError(failure instanceof Error ? failure.message : 'Cannot replay recording') })
      .finally(() => { if (ticket === generation.current) setBusy(false) })
    return () => { generation.current = ticket + 1 }
  }, [selected, workspaceId, sessions])
  const frame = timeline?.seek(position) ?? null
  const files = Object.values(frame?.nodes ?? {}).filter(node => node.type === 'file')
  const previewId = files.some(node => node.id === fileId) ? fileId : frame?.activeFileId ?? files[0]?.id ?? ''
  const preview = frame?.nodes[previewId]
  useEffect(() => {
    if (!playing || !timeline) return
    const started = performance.now(), offset = timeline.elapsed(positionRef.current)
    const timer = window.setInterval(() => {
      const next = timeline.advance(positionRef.current, offset + (performance.now() - started) * speed)
      if (next !== positionRef.current) { positionRef.current = next; setFileId(''); setPosition(next) }
      if (!timeline.seek(next).available || next >= timeline.lastSequence) setPlaying(false)
    }, 33)
    return () => window.clearInterval(timer)
  }, [playing, timeline, speed])
  useEffect(() => {
    if (!expanded) return
    const previous = document.activeElement as HTMLElement | null
    dialogRef.current?.querySelector<HTMLButtonElement>('button')?.focus()
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setExpanded(false); setPlaying(false) } }
    window.addEventListener('keydown', close); return () => { window.removeEventListener('keydown', close); previous?.focus() }
  }, [expanded])
  const seek = (value: number) => { setPlaying(false); setPosition(value); positionRef.current = value; setFileId('') }
  const controls = timeline && frame && <>
    <div className="history-controls">
      <button className="tool-button" aria-label="Previous history event" disabled={!position} onClick={() => seek(position - 1)}>Previous</button>
      <button className="tool-button primary" disabled={!timeline.lastSequence || !frame.available} onClick={() => { if (position === timeline.lastSequence) { setPosition(0); positionRef.current = 0; setFileId('') }; setPlaying(value => !value) }}>{playing ? 'Pause replay' : 'Play replay'}</button>
      <button className="tool-button" aria-label="Next history event" disabled={position >= timeline.lastSequence} onClick={() => seek(position + 1)}>Next</button>
      <label>Speed<select aria-label="History playback speed" value={speed} onChange={event => setSpeed(Number(event.target.value))}>{[0.5, 1, 2, 4, 8].map(value => <option key={value} value={value}>{value}×</option>)}</select></label>
    </div>
    <label className="history-timeline">Timeline · event {position} / {timeline.lastSequence}<input aria-label="History timeline" type="range" min={0} max={timeline.lastSequence} step={1} value={position} onChange={event => seek(Number(event.target.value))} /></label>
    <div className="history-event" aria-live="polite"><strong>{describeEvent(frame.event)}</strong><span>{frame.event?.clientTimestamp ?? timeline.session.startedAt} · {(timeline.elapsed(frame.verifiedThrough) / 1000).toFixed(3)}s</span><span>Recorded active file: {frame.activeFileId ? historicalPath(frame.nodes, frame.activeFileId) : 'not recorded / no active file'}</span><span>Read-only · checkpoint {frame.checkpointSequence} · {frame.appliedEvents} events applied</span></div>
    {!!timeline.issues.length && <details className="history-warning" open><summary>Recording integrity: {timeline.issues.length} notice{timeline.issues.length === 1 ? '' : 's'}</summary>{timeline.issues.slice(0, 8).map((issue, index) => <p key={index}>{issue.integrity} at event {issue.sequence}: {issue.message}</p>)}{timeline.issues.length > 8 && <p>Additional integrity notices remain in the recording.</p>}</details>}
    {!frame.available && <p className="history-warning" role="alert">{frame.error}. Showing only the last verified state at event {frame.verifiedThrough}. Seek to a later recorded checkpoint to resume; unavailable edits are not invented.</p>}
    <label className="history-file">Preview file<select aria-label="History preview file" value={previewId} onChange={event => setFileId(event.target.value)}>{!files.length && <option value="">No file exists at this point</option>}{files.map(node => <option key={node.id} value={node.id}>{historicalPath(frame.nodes, node.id)}</option>)}</select></label>
  </>
  const language = preview?.name.endsWith('.py') ? 'python' : preview?.name.endsWith('.java') ? 'java' : /\.(cpp|cc|c|h|hpp)$/.test(preview?.name ?? '') ? 'cpp' : 'plaintext'
  return <aside className="history-panel sidebar-panel">
    <div className="sidebar-title">HISTORY REPLAY</div>
    <p>Replay saved editing sessions from this browser. Historical code is read-only and never replaces your live files.</p>
    <div className="history-controls"><button className="tool-button" disabled={busy} onClick={() => void refresh()}>Refresh recordings</button><button className="tool-button primary" disabled={!timeline} onClick={() => setExpanded(true)}>Open replay</button></div>
    <label>Recording session<select aria-label="History recording session" value={selected} onChange={event => setSelected(event.target.value)}>{!sessions.length && <option value="">No local recording available</option>}{sessions.map(session => <option key={session.id} value={session.id}>{new Date(session.startedAt).toLocaleString()} · {session.lastSequence} events{session.completedAt ? '' : ' · current'}</option>)}</select></label>
    {busy && <p role="status">Verifying recording and checkpoints…</p>}{error && <p role="alert" className="history-warning">{error}. Original data is retained.</p>}
    {!expanded && controls}{!expanded && preview && <pre className="history-mini-source" aria-label="History source preview">{preview.content}</pre>}
    {expanded && <div className="history-backdrop"><section ref={dialogRef} className="history-dialog" onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setExpanded(false); setPlaying(false) }
      if (event.key === 'F5' || ((event.ctrlKey || event.metaKey) && event.key === 'Enter')) { event.preventDefault(); event.stopPropagation() }
      if (event.key === 'Tab') {
        const controls = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), select, input, textarea, [tabindex="0"]') ?? [])].filter(element => element.tabIndex >= 0)
        const first = controls[0], last = controls.at(-1)
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }} role="dialog" aria-modal="true" aria-label="Editing history replay"><header><strong>Editing history · read-only</strong><button className="tool-button" onClick={() => { setExpanded(false); setPlaying(false) }}>Close replay</button></header><div className="history-dialog-controls">{controls}</div><div className="history-editor">{preview ? <Editor path={`inmemory://olympiad-history/${selected}/${previewId}`} value={preview.content ?? ''} language={language} theme={monacoThemeName(theme)} options={{ readOnly: true, domReadOnly: true, ariaLabel: 'History replay source', automaticLayout: true, minimap: { enabled: false }, wordWrap: 'on', scrollBeyondLastLine: false }} /> : <p>No file exists at this event.</p>}</div></section></div>}
  </aside>
}
