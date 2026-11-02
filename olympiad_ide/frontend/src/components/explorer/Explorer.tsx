import { useMemo, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Copy,
  FilePlus2,
  Folder,
  FolderOpen,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Trash2,
} from 'lucide-react'
import { FileIcon } from '../FileIcon'
import { getNodePath, getSortedChildren, useWorkspaceStore } from '../../store/workspaceStore'
import type { NodeId, WorkspaceNode } from '../../types/workspace'

interface MenuState {
  id: NodeId
  x: number
  y: number
}

export function Explorer() {
  const workspace = useWorkspaceStore((state) => state.workspace)
  const nodes = useWorkspaceStore((state) => state.nodes)
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [error, setError] = useState<string | null>(null)

  const perform = (operation: () => void) => {
    try {
      operation()
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The operation could not be completed.')
    }
    setMenu(null)
  }

  const askForName = (kind: 'file' | 'folder', parentId: NodeId | null) => {
    const name = window.prompt(`New ${kind} name`)
    if (!name) return
    perform(() => {
      if (kind === 'file') useWorkspaceStore.getState().createFile(parentId, name)
      else useWorkspaceStore.getState().createFolder(parentId, name)
    })
  }

  const selectedParent = menu ? (nodes[menu.id]?.type === 'folder' ? menu.id : nodes[menu.id]?.parentId ?? null) : null

  return (
    <aside className="sidebar-panel" onClick={() => setMenu(null)}>
      <div className="sidebar-title">Explorer</div>
      <div className="explorer-heading">
        <div className="flex min-w-0 items-center gap-1">
          <ChevronDown className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{workspace.name.toUpperCase()}</span>
        </div>
        <div className="flex items-center">
          <button className="tiny-icon-button" onClick={() => askForName('file', null)} title="New File" aria-label="New File">
            <FilePlus2 className="h-3.5 w-3.5" />
          </button>
          <button className="tiny-icon-button" onClick={() => askForName('folder', null)} title="New Folder" aria-label="New Folder">
            <FolderPlus className="h-3.5 w-3.5" />
          </button>
          <button className="tiny-icon-button" title="More actions" aria-label="Explorer actions">
            <MoreHorizontal className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {error && (
        <button className="mx-2 mb-1 w-[calc(100%-1rem)] border border-[#be1100] bg-[#5a1d1d] px-2 py-1.5 text-left text-[11px] text-white" onClick={() => setError(null)}>
          {error}
        </button>
      )}

      <div className="tree" role="tree" aria-label="Workspace files">
        {getSortedChildren(nodes, null).map((node) => (
          <TreeNode key={node.id} node={node} depth={0} onContextMenu={setMenu} />
        ))}
        {Object.keys(nodes).length === 0 && <p className="p-4 text-xs text-[var(--muted)]">No files yet.</p>}
      </div>

      {menu && nodes[menu.id] && (
        <div
          className="context-menu"
          style={{ left: Math.min(menu.x, window.innerWidth - 210), top: Math.min(menu.y, window.innerHeight - 260) }}
          onClick={(event) => event.stopPropagation()}
          role="menu"
        >
          <MenuButton icon={FilePlus2} label="New File" onClick={() => askForName('file', selectedParent)} />
          <MenuButton icon={FolderPlus} label="New Folder" onClick={() => askForName('folder', selectedParent)} />
          <div className="context-separator" />
          <MenuButton
            icon={Pencil}
            label="Rename"
            onClick={() => {
              const node = nodes[menu.id]
              const name = node ? window.prompt('Rename', node.name) : null
              if (name) perform(() => useWorkspaceStore.getState().renameNode(menu.id, name))
            }}
          />
          <MenuButton icon={Copy} label="Duplicate" onClick={() => perform(() => void useWorkspaceStore.getState().duplicateNode(menu.id))} />
          <MenuButton
            icon={FolderOpen}
            label="Move to…"
            onClick={() => {
              const destinations = [
                { id: null, path: '/' },
                ...Object.values(nodes)
                  .filter((node) => node.type === 'folder' && node.id !== menu.id)
                  .map((node) => ({ id: node.id, path: `/${getNodePath(nodes, node.id)}` })),
              ]
              const choice = window.prompt(
                `Destination number:\n${destinations.map((destination, index) => `${index + 1}. ${destination.path}`).join('\n')}`,
                '1',
              )
              const destination = choice ? destinations[Number(choice) - 1] : undefined
              if (destination) perform(() => useWorkspaceStore.getState().moveNode(menu.id, destination.id))
            }}
          />
          <div className="context-separator" />
          <MenuButton
            icon={Trash2}
            danger
            label="Delete"
            onClick={() => {
              if (window.confirm(`Delete “${nodes[menu.id]?.name}”?`)) perform(() => useWorkspaceStore.getState().deleteNode(menu.id))
            }}
          />
        </div>
      )}
    </aside>
  )
}

interface TreeNodeProps {
  node: WorkspaceNode
  depth: number
  onContextMenu: (state: MenuState) => void
}

function TreeNode({ node, depth, onContextMenu }: TreeNodeProps) {
  const nodes = useWorkspaceStore((state) => state.nodes)
  const expanded = useWorkspaceStore((state) => state.expandedFolderIds.includes(node.id))
  const active = useWorkspaceStore((state) =>
    Object.values(state.groups).some((group) => group.activeFileId === node.id && state.activeGroupId === group.id),
  )
  const children = useMemo(() => getSortedChildren(nodes, node.id), [node.id, nodes])

  const activate = () => {
    if (node.type === 'folder') useWorkspaceStore.getState().toggleFolder(node.id)
    else useWorkspaceStore.getState().openFile(node.id)
  }

  return (
    <div role="none">
      <div
        className={`tree-row ${active ? 'active' : ''}`}
        style={{ paddingLeft: 5 + depth * 14 }}
        role="treeitem"
        aria-expanded={node.type === 'folder' ? expanded : undefined}
        aria-selected={active}
        tabIndex={0}
        onClick={activate}
        onDoubleClick={() => node.type === 'file' && useWorkspaceStore.getState().openFile(node.id)}
        onContextMenu={(event) => {
          event.preventDefault()
          onContextMenu({ id: node.id, x: event.clientX, y: event.clientY })
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') activate()
          if (node.type === 'folder' && event.key === 'ArrowRight' && !expanded) useWorkspaceStore.getState().toggleFolder(node.id)
          if (node.type === 'folder' && event.key === 'ArrowLeft' && expanded) useWorkspaceStore.getState().toggleFolder(node.id)
        }}
      >
        {node.type === 'folder' ? (
          <>
            {expanded ? <ChevronDown className="tree-chevron" /> : <ChevronRight className="tree-chevron" />}
            {expanded ? <FolderOpen className="tree-folder" /> : <Folder className="tree-folder" />}
          </>
        ) : (
          <>
            <span className="w-3.5 shrink-0" />
            <FileIcon name={node.name} />
          </>
        )}
        <span className="truncate">{node.name}</span>
      </div>
      {node.type === 'folder' && expanded && children.map((child) => (
        <TreeNode key={child.id} node={child} depth={depth + 1} onContextMenu={onContextMenu} />
      ))}
    </div>
  )
}

interface MenuButtonProps {
  icon: typeof FilePlus2
  label: string
  onClick: () => void
  danger?: boolean
}

function MenuButton({ icon: Icon, label, onClick, danger }: MenuButtonProps) {
  return (
    <button className={`context-item ${danger ? 'danger' : ''}`} onClick={onClick} role="menuitem">
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}
