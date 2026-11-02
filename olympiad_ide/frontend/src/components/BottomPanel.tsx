import { cmsEnabled } from '../cms/session'
import { ChevronDown, Copy, Eraser } from 'lucide-react'
import { executions, useExecution } from '../execution/controller'
import { TerminalOutput } from '../execution/TerminalOutput'
import { TestCasesPanel } from '../execution/TestCasesPanel'
import { executionResources, useExecutionResources } from '../execution/resources'
import { terminalStatuses } from '../execution/types'
import { useWorkspaceStore } from '../store/workspaceStore'
import type { BottomPanelView } from '../types/workspace'

const tabs: { id: BottomPanelView; label: string }[] = [
  { id: 'terminal', label: 'Terminal' },
  { id: 'problems', label: 'Problems' },
  { id: 'tests', label: 'Test Cases' },
]

export function BottomPanel() {
  const active = useWorkspaceStore((state) => state.bottomPanelView)
  const execution = useExecution()
  const stdin = useExecutionResources(s => s.stdin)

  return (
    <section className="bottom-panel" aria-label="Bottom panel">
      <div className="panel-tabs">
        <div className="flex h-full items-center gap-4 px-3">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`panel-tab ${active === tab.id ? 'active' : ''}`}
              onClick={() => useWorkspaceStore.getState().setBottomPanelView(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 px-2">
          <button className="tiny-icon-button" title="Copy panel text" aria-label="Copy panel text" onClick={() => void navigator.clipboard?.writeText(execution.events.filter(e => e.eventType === 'OUTPUT' && e.sequence > execution.clearAfter).map(e => e.text ?? '').join(''))}>
            <Copy className="h-3.5 w-3.5" />
          </button>
          <button className="tiny-icon-button" title="Clear" aria-label="Clear panel" onClick={() => useExecution.setState({ clearAfter: execution.events.at(-1)?.sequence ?? 0 })}>
            <Eraser className="h-3.5 w-3.5" />
          </button>
          <button className="tiny-icon-button" title="Hide Panel" aria-label="Hide Panel" onClick={() => useWorkspaceStore.getState().setBottomPanelVisible(false)}>
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="execution-panel-content">
        {execution.error && <div className="execution-error" role="alert">Execution: {execution.error}</div>}
        {!execution.workers && <div className="execution-worker-warning">{cmsEnabled ? 'No approved Linux worker is available. Custom Run is disabled; official CMS submission remains available.' : 'No verified Linux worker connected. Jobs can queue/cancel, but cannot compile or execute until one is deployed.'}</div>}
        <div className="execution-summary"><span>{execution.job?.status ?? 'No run'} · {execution.job?.configuration.name ?? 'Select an entry point'} · {execution.transport}</span><button className="tool-button" onClick={() => void executions.cancel()} disabled={!execution.job || terminalStatuses.has(execution.job.status)}>Stop execution</button><select aria-label="Execution history" value={execution.job?.id ?? ''} onChange={e => { const job = execution.history.find(j => j.id === e.target.value); if (job) void executions.attach(job, true) }}><option value="">Execution history</option>{execution.history.map(j => <option value={j.id} key={j.id}>{new Date(j.createdAt).toLocaleTimeString()} · {j.configuration.name} · {j.status}</option>)}</select></div>
        {execution.job && <div className="execution-summary" title={`Snapshot ${execution.job.snapshotId} · SHA-256 ${execution.job.sourceHash}`}>Entry: {execution.job.sourceManifest?.find(f => f.id === execution.job!.configuration.entryPoint)?.path} · {execution.job.configuration.language} · {execution.job.configuration.compilerProfile} · source {execution.job.sourceHash.slice(0, 12)}</div>}
        {active === 'terminal' && <div className="execution-terminal-layout"><TerminalOutput /><label className="execution-stdin">Fixed stdin (captured before launch)<textarea aria-label="Standard input" value={stdin} maxLength={262144} onChange={e => { executionResources.select({ stdin: e.target.value, selectedTestId: null }) }} /><button className="tool-button primary" onClick={() => void executions.run(undefined, false, true)}>Run with stdin</button></label></div>}
        {active === 'tests' && <TestCasesPanel />}
        {active === 'problems' && <pre className="compiler-diagnostics">{execution.job?.result?.compilationOutput || 'No compilation diagnostics received for this execution.'}</pre>}
        {execution.job?.result && <div className="execution-summary">{execution.job.configuration.language} · {execution.job.result.toolchainVersion} · compile {execution.job.result.compilationSeconds === null ? 'time unavailable' : `${execution.job.result.compilationSeconds}s`} · exit {execution.job.result.cases.at(-1)?.exitCode ?? 'unavailable'} · {execution.job.result.error}</div>}
      </div>
    </section>
  )
}
