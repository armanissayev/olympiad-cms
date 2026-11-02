import { useWorkspaceStore, getNodePath } from '../store/workspaceStore'
import { executionResources, useExecutionResources } from './resources'
import { defaultConfiguration } from './snapshot'
import type { Language, RunConfiguration } from './types'

export function RunPanel() {
  const resources = useExecutionResources(), nodes = useWorkspaceStore(s => s.nodes)
  const configurations = resources.items.filter(r => !r.deleted && r.value.kind === 'configuration')
  const selected = configurations.find(r => r.id === resources.activeConfigurationId)
  const value = selected?.value.kind === 'configuration' ? selected.value : undefined
  const save = (patch: Partial<RunConfiguration>) => { if (value) void executionResources.save({ ...value, ...patch }).catch(() => undefined) }
  const create = () => { try { const value = defaultConfiguration(); void executionResources.save(value).catch(() => undefined); executionResources.select({ activeConfigurationId: value.id }) } catch (error) { executionResources.error(error) } }
  return <aside className="execution-config-panel">
    <h2>RUN CONFIGURATIONS</h2>
    <button className="tool-button" onClick={create}>New Configuration</button>
    <label>Active configuration<select aria-label="Active Run Configuration" value={resources.activeConfigurationId ?? ''} onChange={e => executionResources.select({ activeConfigurationId: e.target.value || null })}><option value="">Active file (create default on Run)</option>{configurations.map(r => <option key={r.id} value={r.id}>{r.value.name}</option>)}</select></label>
    {value && <>
      <label>Name<input aria-label="Configuration name" value={value.name} onChange={e => save({ name: e.target.value })} /></label>
      <label>Language<select aria-label="Execution language" value={value.language} onChange={e => save({ language: e.target.value as Language })}><option value="cpp17">C++17 · GCC release</option><option value="cpp20">C++20 · GCC release</option><option value="python3">Python 3 · CPython</option><option value="java17">Java 17 · OpenJDK</option></select></label>
      <label>Entry point<select aria-label="Entry point" value={value.entryPoint} onChange={e => save({ entryPoint: e.target.value, includedFiles: [...new Set([...value.includedFiles, e.target.value])] })}>{Object.values(nodes).filter(n => n.type === 'file').map(n => <option value={n.id} key={n.id}>{getNodePath(nodes, n.id)}</option>)}</select></label>
      {value.language === 'java17' && <label>Main class<input aria-label="Java main class" value={value.mainClass ?? ''} onChange={e => save({ mainClass: e.target.value })} placeholder="package.Main" /></label>}
      <label>Default test<select aria-label="Default test" value={value.defaultTestId ?? ''} onChange={e => save({ defaultTestId: e.target.value || null })}><option value="">Selected test / fixed stdin</option>{resources.items.filter(r => !r.deleted && r.value.kind === 'test').map(r => <option key={r.id} value={r.id}>{r.value.name}</option>)}</select></label>
      <fieldset><legend>Included files (explicit manifest)</legend>{Object.values(nodes).filter(n => n.type === 'file').map(n => <label className="source-check" key={n.id}><input type="checkbox" checked={value.includedFiles.includes(n.id)} disabled={n.id === value.entryPoint} onChange={e => save({ includedFiles: e.target.checked ? [...value.includedFiles, n.id] : value.includedFiles.filter(id => id !== n.id) })} />{getNodePath(nodes, n.id)}</label>)}</fieldset>
      <p>Release flags are allowlisted. Other solutions are not compiled unless explicitly included. Debugging remains Phase 6.</p>
      <button className="tool-button" onClick={() => { void executionResources.save(value, true).catch(() => undefined); executionResources.select({ activeConfigurationId: null }) }}>Delete configuration</button>
    </>}
    {resources.items.filter(r => r.conflict).map(r => <div className="execution-error" key={r.id}>Conflict: {r.value.name}. Both versions are retained.<button onClick={() => void executionResources.resolve(r.id, 'local')}>Keep local</button><button onClick={() => void executionResources.resolve(r.id, 'server')}>Use server</button></div>)}
    {resources.error && <p role="alert">Resource sync: {resources.error}</p>}
    <small>Pending resource changes: {resources.pending}</small>
    <button className="tool-button" onClick={() => {
      const url = URL.createObjectURL(new Blob([JSON.stringify(resources)], { type: 'application/json' })); const link = document.createElement('a'); link.href = url; link.download = 'olympiad-execution-resources.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    }}>Export configurations/tests</button>
  </aside>
}
