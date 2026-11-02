import { create } from 'zustand'
import type {
  ActivityView,
  BottomPanelView,
  EditorGroup,
  EditorGroupId,
  EditorSettings,
  EditorViewState,
  NodeId,
  WorkspaceFile,
  WorkspaceMetadata,
  WorkspaceNode,
} from '../types/workspace'
import { languageForFileName } from '../types/workspace'

const ROOT_SRC_ID = '70fa4b02-62ad-4ec6-8dc5-a360133e9c18'
const MAIN_FILE_ID = 'edac1b57-613f-4ca8-90e8-d459d7ac92d2'
const SOLUTION_FILE_ID = '1ee27fe8-49f4-40ac-b54a-354da9eb4b34'
const INPUT_FILE_ID = '996c8c29-0216-45b1-89fd-3c465211b81d'

const makeId = (): string =>
  typeof globalThis.crypto?.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`

const now = (): string => new Date().toISOString()

export const defaultSettings: EditorSettings = {
  theme: 'dark-modern',
  fontSize: 14,
  fontFamily: 'SFMono-Regular, Consolas, Liberation Mono, monospace',
  tabSize: 4,
  insertSpaces: true,
  wordWrap: 'off',
  minimap: true,
  autoClosingBrackets: 'always',
  lineNumbers: 'on',
  cursorStyle: 'line',
  autoSave: 'afterDelay',
  renderWhitespace: 'selection',
}

const seedNodes = (): Record<NodeId, WorkspaceNode> => {
  const timestamp = now()
  return {
    [ROOT_SRC_ID]: {
      id: ROOT_SRC_ID,
      type: 'folder',
      parentId: null,
      name: 'src',
      createdAt: timestamp,
      updatedAt: timestamp,
    },
    [MAIN_FILE_ID]: {
      id: MAIN_FILE_ID,
      type: 'file',
      parentId: ROOT_SRC_ID,
      name: 'main.cpp',
      language: 'cpp',
      documentRevision: 1,
      content:
        '#include <bits/stdc++.h>\n\nusing namespace std;\n\nint main() {\n    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n\n    cout << "Ready for the next problem!" << \'\\n\';\n    return 0;\n}\n',
      createdAt: timestamp,
      updatedAt: timestamp,
    },
    [SOLUTION_FILE_ID]: {
      id: SOLUTION_FILE_ID,
      type: 'file',
      parentId: ROOT_SRC_ID,
      name: 'solution.py',
      language: 'python',
      documentRevision: 1,
      content:
        'def solve() -> None:\n    n = int(input())\n    values = list(map(int, input().split()))\n    print(sum(values[:n]))\n\n\nif __name__ == "__main__":\n    solve()\n',
      createdAt: timestamp,
      updatedAt: timestamp,
    },
    [INPUT_FILE_ID]: {
      id: INPUT_FILE_ID,
      type: 'file',
      parentId: null,
      name: 'input.txt',
      language: 'plaintext',
      documentRevision: 1,
      content: '5\n1 2 3 4 5\n',
      createdAt: timestamp,
      updatedAt: timestamp,
    },
  }
}

export interface WorkspaceData {
  workspace: WorkspaceMetadata
  nodes: Record<NodeId, WorkspaceNode>
  expandedFolderIds: NodeId[]
  groups: Record<EditorGroupId, EditorGroup>
  activeGroupId: EditorGroupId
  splitEnabled: boolean
  splitRatio: number
  viewStates: Record<string, EditorViewState>
  savedContents: Record<NodeId, string>
  settings: EditorSettings
  activeView: ActivityView
  explorerVisible: boolean
  explorerSize: number
  bottomPanelVisible: boolean
  bottomPanelSize: number
  bottomPanelView: BottomPanelView
  zenMode: boolean
}

export const initialData = (): WorkspaceData => {
  const timestamp = now()
  const nodes = seedNodes()
  return {
    workspace: {
      id: crypto.randomUUID(),
      ownerId: 'development-session',
      name: 'Algorithm Practice',
      revision: 1,
      createdAt: timestamp,
      updatedAt: timestamp,
    },
    nodes,
    expandedFolderIds: [ROOT_SRC_ID],
    groups: {
      primary: { id: 'primary', tabIds: [MAIN_FILE_ID, SOLUTION_FILE_ID], activeFileId: MAIN_FILE_ID },
      secondary: { id: 'secondary', tabIds: [], activeFileId: null },
    },
    activeGroupId: 'primary',
    splitEnabled: false,
    splitRatio: 50,
    viewStates: {},
    savedContents: Object.fromEntries(
      Object.values(nodes).filter((node): node is WorkspaceFile => node.type === 'file').map((file) => [file.id, file.content]),
    ),
    settings: defaultSettings,
    activeView: 'explorer',
    explorerVisible: true,
    explorerSize: 19,
    bottomPanelVisible: true,
    bottomPanelSize: 25,
    bottomPanelView: 'terminal',
    zenMode: false,
  }
}

const siblingsOf = (nodes: Record<NodeId, WorkspaceNode>, parentId: NodeId | null): WorkspaceNode[] =>
  Object.values(nodes).filter((node) => node.parentId === parentId)

const uniqueName = (
  nodes: Record<NodeId, WorkspaceNode>,
  parentId: NodeId | null,
  requestedName: string,
  excludedId?: NodeId,
): string => {
  const name = requestedName.trim()
  if (!name || name === '.' || name === '..' || name.includes('/') || name.includes('\\')) {
    throw new Error('Use a non-empty name without path separators.')
  }
  const collides = siblingsOf(nodes, parentId).some(
    (node) => node.id !== excludedId && node.name.toLocaleLowerCase() === name.toLocaleLowerCase(),
  )
  if (collides) throw new Error(`“${name}” already exists in this folder.`)
  return name
}

const descendantIds = (nodes: Record<NodeId, WorkspaceNode>, rootId: NodeId): NodeId[] => {
  const result = [rootId]
  const visit = (parentId: NodeId) => {
    for (const child of siblingsOf(nodes, parentId)) {
      result.push(child.id)
      if (child.type === 'folder') visit(child.id)
    }
  }
  visit(rootId)
  return result
}

const viewStateKey = (groupId: EditorGroupId, fileId: NodeId): string => `${groupId}:${fileId}`

export interface WorkspaceActions {
  createFile: (parentId: NodeId | null, name: string, content?: string) => NodeId
  createFolder: (parentId: NodeId | null, name: string) => NodeId
  renameNode: (id: NodeId, name: string) => void
  deleteNode: (id: NodeId) => void
  duplicateNode: (id: NodeId) => NodeId
  moveNode: (id: NodeId, parentId: NodeId | null) => void
  toggleFolder: (id: NodeId) => void
  openFile: (fileId: NodeId, groupId?: EditorGroupId) => void
  closeTab: (fileId: NodeId, groupId: EditorGroupId) => void
  moveTab: (fileId: NodeId, from: EditorGroupId, to: EditorGroupId) => void
  setActiveGroup: (groupId: EditorGroupId) => void
  setFileContent: (fileId: NodeId, content: string) => void
  setViewState: (groupId: EditorGroupId, fileId: NodeId, viewState: EditorViewState) => void
  toggleSplit: () => void
  setSplitRatio: (ratio: number) => void
  updateSettings: (settings: Partial<EditorSettings>) => void
  saveCheckpoint: () => void
  setActiveView: (view: ActivityView) => void
  setExplorerVisible: (visible: boolean) => void
  setExplorerSize: (size: number) => void
  setBottomPanelVisible: (visible: boolean) => void
  setBottomPanelSize: (size: number) => void
  setBottomPanelView: (view: BottomPanelView) => void
  toggleZenMode: () => void
  reset: () => void
}

export type WorkspaceState = WorkspaceData & WorkspaceActions

const bumpWorkspace = (workspace: WorkspaceMetadata): WorkspaceMetadata => ({
  ...workspace,
  revision: workspace.revision + 1,
  updatedAt: now(),
})

export const useWorkspaceStore = create<WorkspaceState>()(
    (set, get) => ({
      ...initialData(),

      createFile: (parentId, requestedName, content = '') => {
        const state = get()
        if (parentId && state.nodes[parentId]?.type !== 'folder') throw new Error('Parent must be a folder.')
        const name = uniqueName(state.nodes, parentId, requestedName)
        const id = makeId()
        const timestamp = now()
        const file: WorkspaceFile = {
          id,
          parentId,
          name,
          type: 'file',
          content,
          language: languageForFileName(name),
          documentRevision: 1,
          createdAt: timestamp,
          updatedAt: timestamp,
        }
        set((current) => ({
          nodes: { ...current.nodes, [id]: file },
          savedContents: { ...current.savedContents, [id]: content },
          workspace: bumpWorkspace(current.workspace),
          expandedFolderIds: parentId
            ? Array.from(new Set([...current.expandedFolderIds, parentId]))
            : current.expandedFolderIds,
        }))
        get().openFile(id)
        return id
      },

      createFolder: (parentId, requestedName) => {
        const state = get()
        if (parentId && state.nodes[parentId]?.type !== 'folder') throw new Error('Parent must be a folder.')
        const name = uniqueName(state.nodes, parentId, requestedName)
        const id = makeId()
        const timestamp = now()
        set((current) => ({
          nodes: {
            ...current.nodes,
            [id]: { id, parentId, name, type: 'folder', createdAt: timestamp, updatedAt: timestamp },
          },
          workspace: bumpWorkspace(current.workspace),
          expandedFolderIds: parentId
            ? Array.from(new Set([...current.expandedFolderIds, parentId]))
            : current.expandedFolderIds,
        }))
        return id
      },

      renameNode: (id, requestedName) =>
        set((state) => {
          const node = state.nodes[id]
          if (!node) throw new Error('File or folder no longer exists.')
          const name = uniqueName(state.nodes, node.parentId, requestedName, id)
          return {
            nodes: {
              ...state.nodes,
              [id]: {
                ...node,
                name,
                updatedAt: now(),
                ...(node.type === 'file' ? { language: languageForFileName(name) } : {}),
              } as WorkspaceNode,
            },
            workspace: bumpWorkspace(state.workspace),
          }
        }),

      deleteNode: (id) =>
        set((state) => {
          if (!state.nodes[id]) return state
          const removed = new Set(descendantIds(state.nodes, id))
          const nodes = Object.fromEntries(Object.entries(state.nodes).filter(([nodeId]) => !removed.has(nodeId)))
          const groups = Object.fromEntries(
            (Object.entries(state.groups) as [EditorGroupId, EditorGroup][]).map(([groupId, group]) => {
              const tabIds = group.tabIds.filter((fileId) => !removed.has(fileId))
              const activeFileId = removed.has(group.activeFileId ?? '')
                ? (tabIds[Math.max(0, group.tabIds.indexOf(group.activeFileId ?? '') - 1)] ?? tabIds[0] ?? null)
                : group.activeFileId
              return [groupId, { ...group, tabIds, activeFileId }]
            }),
          ) as Record<EditorGroupId, EditorGroup>
          return {
            nodes,
            groups,
            savedContents: Object.fromEntries(
              Object.entries(state.savedContents).filter(([fileId]) => !removed.has(fileId)),
            ),
            expandedFolderIds: state.expandedFolderIds.filter((folderId) => !removed.has(folderId)),
            viewStates: Object.fromEntries(
              Object.entries(state.viewStates).filter(([key]) => !Array.from(removed).some((nodeId) => key.endsWith(`:${nodeId}`))),
            ),
            workspace: bumpWorkspace(state.workspace),
          }
        }),

      duplicateNode: (id) => {
        const state = get()
        const source = state.nodes[id]
        if (!source) throw new Error('File or folder no longer exists.')
        const copyName = (() => {
          const dot = source.type === 'file' ? source.name.lastIndexOf('.') : -1
          const stem = dot > 0 ? source.name.slice(0, dot) : source.name
          const extension = dot > 0 ? source.name.slice(dot) : ''
          let index = 1
          let candidate = `${stem} copy${extension}`
          const names = new Set(siblingsOf(state.nodes, source.parentId).map((node) => node.name.toLocaleLowerCase()))
          while (names.has(candidate.toLocaleLowerCase())) candidate = `${stem} copy ${++index}${extension}`
          return candidate
        })()

        const cloneRecursively = (sourceId: NodeId, parentId: NodeId | null, name?: string): NodeId => {
          const current = get().nodes[sourceId]
          if (!current) throw new Error('Source disappeared while duplicating.')
          if (current.type === 'file') return get().createFile(parentId, name ?? current.name, current.content)
          const folderId = get().createFolder(parentId, name ?? current.name)
          for (const child of siblingsOf(get().nodes, sourceId)) cloneRecursively(child.id, folderId)
          return folderId
        }
        return cloneRecursively(id, source.parentId, copyName)
      },

      moveNode: (id, parentId) =>
        set((state) => {
          const node = state.nodes[id]
          if (!node) throw new Error('File or folder no longer exists.')
          if (parentId && state.nodes[parentId]?.type !== 'folder') throw new Error('Destination must be a folder.')
          if (id === parentId || (node.type === 'folder' && descendantIds(state.nodes, id).includes(parentId ?? ''))) {
            throw new Error('A folder cannot be moved inside itself.')
          }
          uniqueName(state.nodes, parentId, node.name, id)
          return {
            nodes: { ...state.nodes, [id]: { ...node, parentId, updatedAt: now() } },
            expandedFolderIds: parentId
              ? Array.from(new Set([...state.expandedFolderIds, parentId]))
              : state.expandedFolderIds,
            workspace: bumpWorkspace(state.workspace),
          }
        }),

      toggleFolder: (id) =>
        set((state) => ({
          expandedFolderIds: state.expandedFolderIds.includes(id)
            ? state.expandedFolderIds.filter((folderId) => folderId !== id)
            : [...state.expandedFolderIds, id],
        })),

      openFile: (fileId, targetGroupId) =>
        set((state) => {
          if (state.nodes[fileId]?.type !== 'file') return state
          const groupId = targetGroupId ?? state.activeGroupId
          const group = state.groups[groupId]
          return {
            groups: {
              ...state.groups,
              [groupId]: {
                ...group,
                tabIds: group.tabIds.includes(fileId) ? group.tabIds : [...group.tabIds, fileId],
                activeFileId: fileId,
              },
            },
            activeGroupId: groupId,
          }
        }),

      closeTab: (fileId, groupId) =>
        set((state) => {
          const group = state.groups[groupId]
          const index = group.tabIds.indexOf(fileId)
          if (index < 0) return state
          const tabIds = group.tabIds.filter((id) => id !== fileId)
          const activeFileId =
            group.activeFileId === fileId ? (tabIds[Math.min(index, tabIds.length - 1)] ?? null) : group.activeFileId
          return { groups: { ...state.groups, [groupId]: { ...group, tabIds, activeFileId } } }
        }),

      moveTab: (fileId, from, to) =>
        set((state) => {
          if (from === to || !state.groups[from].tabIds.includes(fileId)) return state
          const source = state.groups[from]
          const destination = state.groups[to]
          const sourceTabs = source.tabIds.filter((id) => id !== fileId)
          return {
            splitEnabled: true,
            activeGroupId: to,
            groups: {
              ...state.groups,
              [from]: {
                ...source,
                tabIds: sourceTabs,
                activeFileId:
                  source.activeFileId === fileId ? (sourceTabs[0] ?? null) : source.activeFileId,
              },
              [to]: {
                ...destination,
                tabIds: destination.tabIds.includes(fileId) ? destination.tabIds : [...destination.tabIds, fileId],
                activeFileId: fileId,
              },
            },
          }
        }),

      setActiveGroup: (activeGroupId) => set({ activeGroupId }),

      setFileContent: (fileId, content) =>
        set((state) => {
          const file = state.nodes[fileId]
          if (!file || file.type !== 'file' || file.content === content) return state
          return {
            nodes: {
              ...state.nodes,
              [fileId]: {
                ...file,
                content,
                documentRevision: file.documentRevision + 1,
                updatedAt: now(),
              },
            },
            savedContents:
              state.settings.autoSave === 'afterDelay'
                ? { ...state.savedContents, [fileId]: content }
                : state.savedContents,
          }
        }),

      setViewState: (groupId, fileId, viewState) =>
        set((state) => ({ viewStates: { ...state.viewStates, [viewStateKey(groupId, fileId)]: viewState } })),

      toggleSplit: () =>
        set((state) => {
          if (state.splitEnabled) {
            const secondary = state.groups.secondary
            const mergedTabs = Array.from(new Set([...state.groups.primary.tabIds, ...secondary.tabIds]))
            return {
              splitEnabled: false,
              activeGroupId: 'primary' as const,
              groups: {
                primary: {
                  ...state.groups.primary,
                  tabIds: mergedTabs,
                  activeFileId:
                    state.activeGroupId === 'secondary' && secondary.activeFileId
                      ? secondary.activeFileId
                      : state.groups.primary.activeFileId,
                },
                secondary: { ...secondary, tabIds: [], activeFileId: null },
              },
            }
          }
          const currentFileId = state.groups[state.activeGroupId].activeFileId
          return {
            splitEnabled: true,
            activeGroupId: 'secondary' as const,
            groups: {
              ...state.groups,
              secondary: {
                ...state.groups.secondary,
                tabIds: currentFileId ? [currentFileId] : [],
                activeFileId: currentFileId,
              },
            },
          }
        }),

      setSplitRatio: (splitRatio) => set({ splitRatio: Math.min(75, Math.max(25, splitRatio)) }),
      updateSettings: (partial) =>
        set((state) => ({
          settings: { ...state.settings, ...partial },
          savedContents:
            partial.autoSave === 'afterDelay'
              ? Object.fromEntries(
                  Object.values(state.nodes)
                    .filter((node): node is WorkspaceFile => node.type === 'file')
                    .map((file) => [file.id, file.content]),
                )
              : state.savedContents,
        })),
      saveCheckpoint: () =>
        set((state) => ({
          savedContents: Object.fromEntries(
            Object.values(state.nodes)
              .filter((node): node is WorkspaceFile => node.type === 'file')
              .map((file) => [file.id, file.content]),
          ),
        })),
      setActiveView: (activeView) => set({ activeView, explorerVisible: true, zenMode: false }),
      setExplorerVisible: (explorerVisible) => set({ explorerVisible }),
      setExplorerSize: (explorerSize) => set({ explorerSize: Math.min(36, Math.max(14, explorerSize)) }),
      setBottomPanelVisible: (bottomPanelVisible) => set({ bottomPanelVisible }),
      setBottomPanelSize: (bottomPanelSize) => set({ bottomPanelSize: Math.min(55, Math.max(12, bottomPanelSize)) }),
      setBottomPanelView: (bottomPanelView) => set({ bottomPanelView, bottomPanelVisible: true }),
      toggleZenMode: () =>
        set((state) => ({
          zenMode: !state.zenMode,
          explorerVisible: state.zenMode ? true : false,
          bottomPanelVisible: state.zenMode ? true : false,
        })),
      reset: () => set(initialData()),
    }),
)

export const getSortedChildren = (
  nodes: Record<NodeId, WorkspaceNode>,
  parentId: NodeId | null,
): WorkspaceNode[] =>
  siblingsOf(nodes, parentId).sort((a, b) => {
    if (a.type !== b.type) return a.type === 'folder' ? -1 : 1
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' })
  })

export const getNodePath = (nodes: Record<NodeId, WorkspaceNode>, id: NodeId): string => {
  const names: string[] = []
  let current = nodes[id]
  while (current) {
    names.unshift(current.name)
    current = current.parentId ? nodes[current.parentId] : undefined
  }
  return names.join('/')
}

export const editorViewStateKey = viewStateKey
export const seedFileIds = { main: MAIN_FILE_ID, solution: SOLUTION_FILE_ID, input: INPUT_FILE_ID }
