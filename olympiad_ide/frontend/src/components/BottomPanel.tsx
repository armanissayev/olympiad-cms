import { cmsEnabled } from '../cms/session'
import { ChevronDown, Copy, Download, Eraser } from 'lucide-react'
import { executions, useExecution } from '../execution/controller'
import { executionResources, useExecutionResources } from '../execution/resources'
import { terminalStatuses } from '../execution/types'
import { useWorkspaceStore } from '../store/workspaceStore'
import { runOutput } from '../execution/output'

export function BottomPanel() {
  const execution = useExecution()
  const stdin = useExecutionResources(s => s.stdin)
  const { stdout, diagnostics } = runOutput(execution.job, execution.events, execution.clearAfter)
  const running = !!execution.job && !terminalStatuses.has(execution.job.status)
  const entry = execution.job?.sourceManifest?.find(f => f.id === execution.job!.configuration.entryPoint)?.path
  const saveOutput = () => {
    const url = URL.createObjectURL(new Blob([stdout], { type: 'text/plain;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = 'stdout.txt'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="bottom-panel io-panel" aria-label="Program input and output">
    <div className="io-run-status" role="status">
      <span>{entry ? `${entry} · ${execution.job?.status}` : 'Open a file, enter input below, then choose Run active file.'}</span>
      {running && <button className="tool-button" onClick={() => void executions.cancel()}>Stop execution</button>}
      <button className="tiny-icon-button" title="Hide input and output" aria-label="Hide input and output" onClick={() => useWorkspaceStore.getState().setBottomPanelVisible(false)}><ChevronDown size={16} /></button>
    </div>
    {execution.error && <div className="execution-error" role="alert">{execution.error}</div>}
    {!execution.workers && <div className="execution-worker-warning">{cmsEnabled ? 'Run is unavailable while the execution worker is offline. Official submission is still available.' : 'Waiting for an approved execution worker.'}</div>}
    <div className="io-file-panes">
      <label className="io-file-pane"><span className="io-file-heading">STDIN File <small>Input for the next run</small></span>
        <textarea aria-label="STDIN File" placeholder="Enter the input your program should read…" value={stdin} maxLength={262144} spellCheck={false} onChange={e => executionResources.select({ stdin: e.target.value, selectedTestId: null })} />
      </label>
      <section className="io-file-pane" aria-label="Program output">
        <div className="io-file-heading"><label htmlFor="stdout-file">STDOUT File</label><div className="io-output-actions">
          <button title="Copy output" aria-label="Copy output" onClick={() => void navigator.clipboard?.writeText(stdout)}><Copy size={15} /></button>
          <button title="Save stdout.txt" aria-label="Save stdout.txt" onClick={saveOutput}><Download size={15} /></button>
          <button title="Clear output" aria-label="Clear output" onClick={() => useExecution.setState({ clearAfter: Math.max(1, execution.events.at(-1)?.sequence ?? 0, execution.job?.lastSequence ?? 0) })}><Eraser size={15} /></button>
        </div></div>
        <textarea id="stdout-file" aria-label="STDOUT File" placeholder={running ? 'Program is running…' : 'Program output will appear here.'} readOnly value={stdout} spellCheck={false} />
        {diagnostics && <details className="io-diagnostics" open={execution.job?.status !== 'FINISHED'}><summary>Compiler messages and errors</summary><pre>{diagnostics}</pre></details>}
      </section>
    </div>
  </section>
}
