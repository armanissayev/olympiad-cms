import { cmsEnabled } from '../cms/session'
import { Explorer } from './explorer/Explorer'
import { SearchPanel } from './sidebar/SearchPanel'
import { SettingsPanel } from './sidebar/SettingsPanel'
import { HistoryPanel } from '../history/HistoryPanel'
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
  return cmsEnabled ? <Explorer /> : <HistoryPanel />
}
