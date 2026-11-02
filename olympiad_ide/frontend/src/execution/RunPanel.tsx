import { getNodePath, useWorkspaceStore } from '../store/workspaceStore'
import { DebugPanel } from '../debug/DebugPanel'
import { displayLanguage } from '../types/workspace'

export function RunPanel() {
  const state = useWorkspaceStore()
  const file = state.nodes[state.groups[state.activeGroupId].activeFileId ?? '']
  return <aside className="execution-config-panel">
    <h2>RUN ACTIVE FILE</h2>
    <p>{file?.type === 'file' ? getNodePath(state.nodes, file.id) : 'Open a source file in the editor.'}</p>
    {file?.type === 'file' && <p>{displayLanguage(file.language)}</p>}
    <p>Run always uses the file in the focused editor. Switch files to run a different solution.</p>
    <p>Enter input in STDIN File. Your program’s output appears in STDOUT File.</p>
    <DebugPanel />
  </aside>
}
