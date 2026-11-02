import { useState } from 'react'
import { modelRegistry } from '../editor/modelRegistry'
import { debugging, useDebugStore } from './controller'
import { getNodePath, useWorkspaceStore } from '../store/workspaceStore'
import './debug.css'

export function DebugPanel() {
  const state = useDebugStore(), nodes = useWorkspaceStore(s => s.nodes)
  const [line, setLine] = useState('1')
  const activeFile = useWorkspaceStore(s => s.nodes[s.groups[s.activeGroupId].activeFileId ?? ''])
  const maxLine = activeFile?.type === 'file' ? (modelRegistry.get(activeFile.id)?.getValue() ?? activeFile.content).split(/\r\n|\r|\n/).length : 1
  const active = ['starting', 'running', 'stopped', 'stopping'].includes(state.status), stopped = state.status === 'stopped'
  return <section aria-label="Interactive debugger" className="debug-panel">
    <h2>DEBUG ACTIVE FILE</h2>
    <p role="status">Isolated debugger · {state.status}. Sessions expire after five minutes.</p>
    <div className="debug-controls"><button className="tool-button primary" disabled={active} onClick={() => void debugging.start()}>Start debugging</button><button className="tool-button" disabled={!state.session || (!active && state.status !== 'failed')} onClick={() => void debugging.stop()}>Stop debugging</button></div>
    <div className="debug-controls">{(['continue', 'pause', 'next', 'stepIn', 'stepOut'] as const).map((command, index) => <button className="tool-button" key={command} disabled={state.commandBusy || state.inspectionBusy || state.breakpointsBusy || (command === 'pause' ? state.status !== 'running' : !stopped)} onClick={() => void debugging.command(command)}>{['Continue', 'Pause', 'Step Over', 'Step Into', 'Step Out'][index]}</button>)}</div>
    {state.error && <p role="alert" className="debug-error">{state.error}</p>}
    {state.session && <details className="debug-snapshot"><summary>Captured source · {state.session.sourceHash.slice(0, 12)}</summary><code>{state.session.sourceHash}</code>{state.session.files.map(file => <div key={file.id}>{file.path}</div>)}</details>}
    <h3>Breakpoints</h3><p>Click a line number or press F9 to toggle a breakpoint. You can also enter a line below.</p>
    <form className="breakpoint-form" onSubmit={event => { event.preventDefault(); const value = Number(line); if (activeFile?.type === 'file' && Number.isSafeInteger(value) && value > 0 && value <= maxLine && !(state.breakpoints[activeFile.id] ?? []).includes(value)) debugging.toggleBreakpoint(activeFile.id, value) }}>
      <label>Line<input aria-label="Breakpoint line" type="number" min="1" max={maxLine} step="1" value={line} onChange={event => setLine(event.target.value)} /></label>
      <button className="tool-button" type="submit" disabled={activeFile?.type !== 'file' || activeFile.language === 'plaintext' || !Number.isSafeInteger(Number(line)) || Number(line) < 1 || Number(line) > maxLine}>Add breakpoint</button>
    </form>
    {state.breakpointNotice && <p role="status">{state.breakpointNotice}</p>}
    {state.breakpointsBusy && <p role="status">Updating breakpoints…</p>}
    <div className="debug-list">{Object.entries(state.breakpoints).flatMap(([id, lines]) => lines.map(line => <div className="debug-breakpoint-row" key={id + ':' + line}><button className="tool-button" aria-label={`Go to breakpoint ${nodes[id] ? getNodePath(nodes, id) : 'Removed file'}:${line}`} onClick={() => debugging.goToBreakpoint(id, line)}>Go to {nodes[id] ? getNodePath(nodes, id) : 'Removed file'}:{line}</button><button className="tool-button" onClick={() => debugging.toggleBreakpoint(id, line)}>Remove {nodes[id] ? getNodePath(nodes, id) : 'Removed file'}:{line}</button></div>))}</div>
    {!Object.values(state.breakpoints).some(lines => lines.length) && <p>No breakpoints. The adapter may stop at entry.</p>}
    {!!state.verifiedBreakpoints.length && <details className="debug-snapshot"><summary>Captured breakpoint verification</summary>{state.verifiedBreakpoints.map((point, index) => <p key={index}>{state.session?.files.find(file => file.id === point.fileId)?.path}:{point.requestedLine}{point.line !== point.requestedLine ? ` → ${point.line}` : ''} · {point.verified ? 'Verified by adapter' : 'Not verified'}{point.message ? ` · ${point.message}` : ''}</p>)}</details>}
    {state.inspectionBusy && <p role="status">Loading paused stack and variables…</p>}
    <h3>Call Stack</h3><div className="debug-list">{state.frames.map(frame => <button className="tool-button" key={frame.id} disabled={!stopped || state.commandBusy || state.inspectionBusy} onClick={() => void debugging.selectFrame(frame.id)}>{frame.name}:{frame.line}</button>)}</div>
    {!state.frames.length && <p>Stack frames appear when the real debugger pauses.</p>}
    <h3>Variables</h3>{state.variables.map((variable, index) => <div className="debug-variable" key={index}><button className="tool-button" disabled={!stopped || !variable.variablesReference || state.commandBusy || state.inspectionBusy} onClick={() => void debugging.expandVariable(variable.variablesReference)}>{variable.name}</button>{(variable.type || variable.scope) && <small>{[variable.scope, variable.type].filter(Boolean).join(' · ')}</small>}<code>{variable.value}</code></div>)}
    {!state.variables.length && <p>Choose a paused stack frame to inspect its variables.</p>}
    {state.output && <><h3>Debug output</h3><pre className="debug-output">{state.output}</pre></>}
  </section>
}
