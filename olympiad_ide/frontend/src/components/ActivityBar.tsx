import { BugPlay, Files, History, Search, Settings } from 'lucide-react'
import type { ActivityView } from '../types/workspace'
import { useWorkspaceStore } from '../store/workspaceStore'

const entries: { id: ActivityView; label: string; icon: typeof Files }[] = [
  { id: 'explorer', label: 'Explorer', icon: Files },
  { id: 'search', label: 'Search', icon: Search },
  { id: 'run', label: 'Run and Debug', icon: BugPlay },
  { id: 'history', label: 'History', icon: History },
]

export function ActivityBar() {
  const activeView = useWorkspaceStore((state) => state.activeView)
  const explorerVisible = useWorkspaceStore((state) => state.explorerVisible)
  const setActiveView = useWorkspaceStore((state) => state.setActiveView)

  const openView = (view: ActivityView) => {
    if (view === activeView && explorerVisible) {
      useWorkspaceStore.getState().setExplorerVisible(false)
      return
    }
    setActiveView(view)
  }

  return (
    <nav className="activity-bar" aria-label="Primary activity">
      <div>
        {entries.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            className={`activity-button ${activeView === id && explorerVisible ? 'active' : ''}`}
            onClick={() => openView(id)}
            title={label}
            aria-label={label}
            aria-pressed={activeView === id && explorerVisible}
          >
            <Icon className="h-[23px] w-[23px]" strokeWidth={1.7} />
          </button>
        ))}
      </div>
      <button
        className={`activity-button ${activeView === 'settings' && explorerVisible ? 'active' : ''}`}
        onClick={() => openView('settings')}
        title="Settings"
        aria-label="Settings"
      >
        <Settings className="h-[23px] w-[23px]" strokeWidth={1.7} />
      </button>
    </nav>
  )
}
