import { ArrowLeftToLine, ArrowRightToLine, Columns2, X } from 'lucide-react'
import { FileIcon } from '../FileIcon'
import { useWorkspaceStore } from '../../store/workspaceStore'
import type { EditorGroupId } from '../../types/workspace'

interface TabBarProps {
  groupId: EditorGroupId
}

export function TabBar({ groupId }: TabBarProps) {
  const group = useWorkspaceStore((state) => state.groups[groupId])
  const nodes = useWorkspaceStore((state) => state.nodes)
  const savedContents = useWorkspaceStore((state) => state.savedContents)
  const splitEnabled = useWorkspaceStore((state) => state.splitEnabled)
  const targetGroup: EditorGroupId = groupId === 'primary' ? 'secondary' : 'primary'

  return (
    <div className="tab-bar" onDragOver={(event) => event.preventDefault()} onDrop={(event) => {
      const fileId = event.dataTransfer.getData('application/x-olympiad-file')
      const source = event.dataTransfer.getData('application/x-olympiad-group') as EditorGroupId
      if (fileId && source) useWorkspaceStore.getState().moveTab(fileId, source, groupId)
    }}>
      <div className="flex min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
        {group.tabIds.map((fileId) => {
          const file = nodes[fileId]
          if (!file || file.type !== 'file') return null
          const active = group.activeFileId === fileId
          return (
            <div
              className={`editor-tab group ${active ? 'active' : ''}`}
              key={fileId}
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData('application/x-olympiad-file', fileId)
                event.dataTransfer.setData('application/x-olympiad-group', groupId)
              }}
              onClick={() => useWorkspaceStore.getState().openFile(fileId, groupId)}
              onAuxClick={(event) => event.button === 1 && useWorkspaceStore.getState().closeTab(fileId, groupId)}
              role="tab"
              aria-selected={active}
            >
              <FileIcon name={file.name} className="h-3.5 w-3.5" />
              <span className="max-w-36 truncate">{file.name}</span>
              {file.content !== savedContents[file.id] && <span className="modified-dot" title="Modified locally" aria-label="Modified locally" />}
              <button
                className="tab-action"
                onClick={(event) => {
                  event.stopPropagation()
                  useWorkspaceStore.getState().closeTab(fileId, groupId)
                }}
                title="Close"
                aria-label={`Close ${file.name}`}
              >
                <X className="h-3.5 w-3.5" />
              </button>
              <button
                className="tab-action hidden group-hover:flex"
                onClick={(event) => {
                  event.stopPropagation()
                  useWorkspaceStore.getState().moveTab(fileId, groupId, targetGroup)
                }}
                title={`Move to ${targetGroup} group`}
                aria-label={`Move ${file.name} to ${targetGroup} group`}
              >
                {groupId === 'primary' ? <ArrowRightToLine className="h-3 w-3" /> : <ArrowLeftToLine className="h-3 w-3" />}
              </button>
            </div>
          )
        })}
      </div>
      {groupId === 'primary' && (
        <button
          className={`editor-action ${splitEnabled ? 'active' : ''}`}
          onClick={() => useWorkspaceStore.getState().toggleSplit()}
          title="Split Editor"
          aria-label="Split Editor"
        >
          <Columns2 className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
