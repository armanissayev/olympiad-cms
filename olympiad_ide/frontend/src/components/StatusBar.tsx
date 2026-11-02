import { Braces, GitBranch, Radio } from 'lucide-react'
import { SyncIndicator } from './PersistencePanel'
import { TelemetryIndicator } from './TelemetryPanel'
import { usePersistenceStatus } from '../persistence/status'
import { displayLanguage } from '../types/workspace'
import { editorViewStateKey, useWorkspaceStore } from '../store/workspaceStore'

export function StatusBar() {
  const online = usePersistenceStatus((state) => state.online)
  const activeGroupId = useWorkspaceStore((state) => state.activeGroupId)
  const activeFileId = useWorkspaceStore((state) => state.groups[activeGroupId].activeFileId)
  const file = useWorkspaceStore((state) => activeFileId ? state.nodes[activeFileId] : undefined)
  const viewState = useWorkspaceStore((state) =>
    activeFileId ? state.viewStates[editorViewStateKey(activeGroupId, activeFileId)] : undefined,
  )
  const settings = useWorkspaceStore((state) => state.settings)

  return (
    <footer className="status-bar">
      <div className="flex items-center gap-4">
        <span className="status-item"><GitBranch className="h-3.5 w-3.5" /> local</span>
        <SyncIndicator />
        <TelemetryIndicator />
      </div>
      <div className="flex items-center gap-4">
        <span>Ln {viewState?.lineNumber ?? 1}, Col {viewState?.column ?? 1}</span>
        <span>{settings.insertSpaces ? 'Spaces' : 'Tabs'}: {settings.tabSize}</span>
        <span>UTF-8</span>
        <span className="status-item"><Braces className="h-3.5 w-3.5" /> {file?.type === 'file' ? displayLanguage(file.language) : 'Plain Text'}</span>
        <span className="status-item"><Radio className="h-3.5 w-3.5" /> {online ? 'Connected' : 'Offline'}</span>
      </div>
    </footer>
  )
}
