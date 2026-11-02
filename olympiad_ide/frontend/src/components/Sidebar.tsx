import { Explorer } from './explorer/Explorer'
import { SearchPanel } from './sidebar/SearchPanel'
import { SettingsPanel } from './sidebar/SettingsPanel'
import { PhasePanel } from './sidebar/PhasePanel'
import { useWorkspaceStore } from '../store/workspaceStore'
import { RunPanel } from '../execution/RunPanel'

export function Sidebar() {
  const activeView = useWorkspaceStore((state) => state.activeView)
  if (activeView === 'explorer') return <Explorer />
  if (activeView === 'search') return <SearchPanel />
  if (activeView === 'settings') return <SettingsPanel />
  if (activeView === 'run') {
    return <RunPanel />
  }
  return (
    <PhasePanel
      title="History"
      eyebrow="PHASE 5"
      body="Editing-history replay will appear here after the durable event pipeline and checkpoints are implemented."
    />
  )
}
