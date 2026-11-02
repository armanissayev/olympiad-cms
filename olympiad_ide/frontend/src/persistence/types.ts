import type { WorkspaceData } from '../store/workspaceStore'
import type { EditorSettings, WorkspaceNode } from '../types/workspace'

export type EditorSession = Omit<WorkspaceData, 'workspace' | 'nodes' | 'settings' | 'savedContents'>

export interface WorkspaceDocument {
  name: string
  nodes: Record<string, WorkspaceNode>
  settings: EditorSettings
  editorState: Partial<EditorSession>
}

export interface ServerWorkspace {
  id: string
  ownerId: string
  revision: number
  createdAt: string
  updatedAt: string
  document: WorkspaceDocument
}

export interface SyncOperation {
  sequence?: number
  operationId: string
  workspaceId: string
  baseRevision: number
  document: WorkspaceDocument
  status: 'pending' | 'sending'
  createdAt: string
  retryCount: number
}

export interface RecoverySnapshot {
  snapshotId: string
  workspaceId: string
  fileId: string
  name: string
  content: string
  contentHash: string
  revision: number
  reason: string
  createdAt: string
}

export interface Conflict {
  workspaceId: string
  kind: 'server' | 'local'
  local: WorkspaceDocument
  server: ServerWorkspace
  createdAt: string
}

export type SaveStatus = 'Loading' | 'Saving' | 'Saved locally' | 'Syncing' | 'Synced' | 'Offline' | 'Conflict' | 'Save Error'

export const toDocument = (state: WorkspaceData): WorkspaceDocument => ({
  name: state.workspace.name,
  nodes: state.nodes,
  settings: state.settings,
  editorState: {
    expandedFolderIds: state.expandedFolderIds,
    groups: state.groups,
    activeGroupId: state.activeGroupId,
    splitEnabled: state.splitEnabled,
    splitRatio: state.splitRatio,
    viewStates: state.viewStates,
    activeView: state.activeView,
    explorerVisible: state.explorerVisible,
    explorerSize: state.explorerSize,
    bottomPanelVisible: state.bottomPanelVisible,
    bottomPanelSize: state.bottomPanelSize,
    bottomPanelView: state.bottomPanelView,
    zenMode: state.zenMode,
  },
})

export function stableJSON(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) => {
    if (item && typeof item === 'object' && !Array.isArray(item)) {
      return Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b)))
    }
    return item
  })
}

export const semanticKey = (document: WorkspaceDocument): string =>
  stableJSON({ name: document.name, nodes: document.nodes, settings: document.settings })

export function savedContents(nodes: Record<string, WorkspaceNode>): Record<string, string> {
  return Object.fromEntries(Object.values(nodes).flatMap((node) => node.type === 'file' ? [[node.id, node.content]] : []))
}
