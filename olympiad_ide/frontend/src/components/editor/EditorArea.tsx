import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { EditorPane } from './EditorPane'

export function EditorArea() {
  const splitEnabled = useWorkspaceStore((state) => state.splitEnabled)
  const splitRatio = useWorkspaceStore((state) => state.splitRatio)

  if (!splitEnabled) return <EditorPane groupId="primary" />

  return (
    <PanelGroup
      direction="horizontal"
      className="h-full"
      onLayout={([primarySize]) => primarySize !== undefined && useWorkspaceStore.getState().setSplitRatio(primarySize)}
    >
      <Panel defaultSize={splitRatio} minSize={25}>
        <EditorPane groupId="primary" />
      </Panel>
      <PanelResizeHandle className="editor-resize-handle" />
      <Panel minSize={25}>
        <EditorPane groupId="secondary" />
      </Panel>
    </PanelGroup>
  )
}
