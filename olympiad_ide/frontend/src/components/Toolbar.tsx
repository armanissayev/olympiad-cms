import { Bug, CircleStop, Columns2, PanelBottom, Play, Settings2 } from 'lucide-react'
import { SyncIndicator } from './PersistencePanel'
import { displayLanguage } from '../types/workspace'
import { useWorkspaceStore } from '../store/workspaceStore'
import { executions, useExecution } from '../execution/controller'
import { terminalStatuses } from '../execution/types'
import { usePersistenceStatus } from '../persistence/status'
import { cmsEnabled, useCMSSession } from '../cms/session'
import { debugging, useDebugStore } from '../debug/controller'

export function Toolbar() {
  const workspace = useWorkspaceStore((state) => state.workspace)
  const activeGroup = useWorkspaceStore((state) => state.groups[state.activeGroupId])
  const activeFile = useWorkspaceStore((state) =>
    activeGroup.activeFileId ? state.nodes[activeGroup.activeFileId] : undefined,
  )
  const splitEnabled = useWorkspaceStore((state) => state.splitEnabled)
  const bottomPanelVisible = useWorkspaceStore((state) => state.bottomPanelVisible)
  const execution = useExecution()
  const debugStatus = useDebugStore(s => s.status)
  const online = usePersistenceStatus(s => s.online)
  const cmsTask = useCMSSession(s => s.context?.tasks.find(task => task.id === s.taskId))
  const debugAvailable = online && (!cmsEnabled || !!cmsTask?.customRunSupported)
  const runAvailable = online && (!cmsEnabled || (!!cmsTask?.customRunSupported && execution.workers > 0))

  return (
    <header className="toolbar">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className="brand-mark" aria-hidden="true">O</div>
        <span className="font-semibold tracking-tight text-[var(--fg-strong)]">Olympiad IDE</span>
        <span className="toolbar-divider" />
        <span className="truncate text-xs text-[var(--muted)]">{workspace.name}</span>
      </div>

      <div className="toolbar-actions">
        <span className="hidden items-center gap-1.5 text-xs text-[var(--muted)] lg:flex">
          {activeFile?.type === 'file' ? displayLanguage(activeFile.language) : 'No file'}
        </span>
        <span className="toolbar-divider hidden lg:block" />
        <button className="tool-button primary" onClick={() => void executions.run()} disabled={execution.submitting || !runAvailable || activeFile?.type !== 'file' || activeFile.language === 'plaintext'} title={runAvailable ? 'Run active file (Ctrl/Cmd+Enter)' : 'Custom Run requires an authorized task and an available approved IDE worker'}>
          <Play className="h-3.5 w-3.5 fill-current" />
          Run active file
        </button>
        <button className="tool-button" aria-label="Debug active file" onClick={() => { useWorkspaceStore.getState().setActiveView('run'); void debugging.start() }} disabled={!debugAvailable || activeFile?.type !== 'file' || activeFile.language === 'plaintext' || ['starting', 'running', 'stopped', 'stopping'].includes(debugStatus)} title="Debug active file (F5)">
          <Bug className="h-4 w-4" />
        </button>
        <button className="tool-button muted-action" onClick={() => void executions.cancel()} disabled={!execution.job || terminalStatuses.has(execution.job.status)} title="Stop execution (Shift+F5)">
          <CircleStop className="h-4 w-4" />
        </button>
        <span className="toolbar-divider" />
        <button
          className={`icon-button ${splitEnabled ? 'selected' : ''}`}
          onClick={() => useWorkspaceStore.getState().toggleSplit()}
          title="Toggle Split Editor (Ctrl/Cmd+\\)"
          aria-label="Toggle Split Editor"
        >
          <Columns2 className="h-4 w-4" />
        </button>
        <button
          className={`icon-button ${bottomPanelVisible ? 'selected' : ''}`}
          onClick={() => useWorkspaceStore.getState().setBottomPanelVisible(!bottomPanelVisible)}
          title="Toggle Panel (Ctrl/Cmd+J)"
          aria-label="Toggle bottom panel"
        >
          <PanelBottom className="h-4 w-4" />
        </button>
        <SyncIndicator />
        <button
          className="icon-button"
          onClick={() => useWorkspaceStore.getState().setActiveView('settings')}
          title="Settings (Ctrl/Cmd+,)"
          aria-label="Open Settings"
        >
          <Settings2 className="h-4 w-4" />
        </button>
      </div>
    </header>
  )
}
