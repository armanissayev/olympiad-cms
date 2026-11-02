import { beforeEach, describe, expect, it } from 'vitest'
import { editorViewStateKey, seedFileIds, useWorkspaceStore } from './workspaceStore'

describe('workspace file management', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().reset()
  })

  it('keeps a stable identity and content when a file is renamed and moved', () => {
    const store = useWorkspaceStore.getState()
    const folderId = store.createFolder(null, 'algorithms')
    const fileId = store.createFile(null, 'graph.cpp', 'int main() {}')

    useWorkspaceStore.getState().renameNode(fileId, 'shortest_path.cpp')
    useWorkspaceStore.getState().moveNode(fileId, folderId)

    const file = useWorkspaceStore.getState().nodes[fileId]
    expect(file).toMatchObject({
      id: fileId,
      parentId: folderId,
      name: 'shortest_path.cpp',
      type: 'file',
      content: 'int main() {}',
      language: 'cpp',
    })
  })

  it('duplicates nested folders with new IDs and deletes a subtree without deleting tab-independent files', () => {
    const originalFolder = useWorkspaceStore.getState().createFolder(null, 'round-1')
    const nestedFolder = useWorkspaceStore.getState().createFolder(originalFolder, 'include')
    const originalFile = useWorkspaceStore.getState().createFile(nestedFolder, 'math.hpp', '#pragma once')

    const copyFolder = useWorkspaceStore.getState().duplicateNode(originalFolder)
    const stateAfterCopy = useWorkspaceStore.getState()
    const descendants = Object.values(stateAfterCopy.nodes).filter((node) => node.parentId === copyFolder)
    expect(copyFolder).not.toBe(originalFolder)
    expect(descendants).toHaveLength(1)
    expect(descendants[0]?.id).not.toBe(nestedFolder)

    useWorkspaceStore.getState().deleteNode(originalFolder)
    const stateAfterDelete = useWorkspaceStore.getState()
    expect(stateAfterDelete.nodes[originalFolder]).toBeUndefined()
    expect(stateAfterDelete.nodes[nestedFolder]).toBeUndefined()
    expect(stateAfterDelete.nodes[originalFile]).toBeUndefined()
    expect(stateAfterDelete.nodes[seedFileIds.main]).toBeDefined()
  })

  it('rejects sibling name collisions and recursive folder moves', () => {
    const parent = useWorkspaceStore.getState().createFolder(null, 'parent')
    const child = useWorkspaceStore.getState().createFolder(parent, 'child')
    useWorkspaceStore.getState().createFile(parent, 'a.cpp')

    expect(() => useWorkspaceStore.getState().createFile(parent, 'A.CPP')).toThrow(/already exists/)
    expect(() => useWorkspaceStore.getState().moveNode(parent, child)).toThrow(/cannot be moved inside itself/)
  })
})

describe('tabs and editor state', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().reset()
  })

  it('closes a tab without deleting its file and can reopen it', () => {
    const fileId = seedFileIds.main
    useWorkspaceStore.getState().closeTab(fileId, 'primary')

    expect(useWorkspaceStore.getState().groups.primary.tabIds).not.toContain(fileId)
    expect(useWorkspaceStore.getState().nodes[fileId]).toBeDefined()

    useWorkspaceStore.getState().openFile(fileId, 'primary')
    expect(useWorkspaceStore.getState().groups.primary.activeFileId).toBe(fileId)
  })

  it('preserves independent cursor and scroll state for each file and group', () => {
    const fileId = seedFileIds.main
    useWorkspaceStore.getState().setViewState('primary', fileId, {
      lineNumber: 8,
      column: 5,
      scrollTop: 120,
      scrollLeft: 0,
    })
    useWorkspaceStore.getState().setViewState('secondary', fileId, {
      lineNumber: 2,
      column: 11,
      scrollTop: 20,
      scrollLeft: 12,
    })

    expect(useWorkspaceStore.getState().viewStates[editorViewStateKey('primary', fileId)]).toMatchObject({ lineNumber: 8, scrollTop: 120 })
    expect(useWorkspaceStore.getState().viewStates[editorViewStateKey('secondary', fileId)]).toMatchObject({ lineNumber: 2, scrollTop: 20 })
  })
})

describe('split editor behavior', () => {
  beforeEach(() => {
    useWorkspaceStore.getState().reset()
  })

  it('opens the active file in both groups and shares store content updates', () => {
    const fileId = seedFileIds.main
    useWorkspaceStore.getState().toggleSplit()

    expect(useWorkspaceStore.getState().groups.primary.activeFileId).toBe(fileId)
    expect(useWorkspaceStore.getState().groups.secondary.activeFileId).toBe(fileId)

    useWorkspaceStore.getState().setFileContent(fileId, '// shared edit')
    const state = useWorkspaceStore.getState()
    expect(state.nodes[state.groups.primary.activeFileId!]).toMatchObject({ content: '// shared edit' })
    expect(state.nodes[state.groups.secondary.activeFileId!]).toMatchObject({ content: '// shared edit' })
  })

  it('moves tabs between groups and merges them without deleting files when split closes', () => {
    const secondFileId = seedFileIds.solution
    useWorkspaceStore.getState().moveTab(secondFileId, 'primary', 'secondary')
    expect(useWorkspaceStore.getState().groups.secondary.tabIds).toContain(secondFileId)
    expect(useWorkspaceStore.getState().groups.primary.tabIds).not.toContain(secondFileId)

    useWorkspaceStore.getState().toggleSplit()
    const state = useWorkspaceStore.getState()
    expect(state.splitEnabled).toBe(false)
    expect(state.groups.primary.tabIds).toContain(secondFileId)
    expect(state.nodes[secondFileId]).toBeDefined()
  })
})

describe('settings and checkpoint state (durability is tested through Dexie)', () => {
  it('updates editor preferences without writing the legacy storage key', () => {
    useWorkspaceStore.getState().reset()
    useWorkspaceStore.getState().updateSettings({ fontSize: 18, theme: 'high-contrast', minimap: false })

    expect(useWorkspaceStore.getState().settings).toMatchObject({ fontSize: 18, theme: 'high-contrast', minimap: false })
    expect(window.localStorage.getItem('olympiad-ide-phase1')).toBeNull()
  })

  it('persists clamped workbench panel sizes', () => {
    useWorkspaceStore.getState().reset()
    useWorkspaceStore.getState().setExplorerSize(31)
    useWorkspaceStore.getState().setBottomPanelSize(44)

    expect(useWorkspaceStore.getState()).toMatchObject({ explorerSize: 31, bottomPanelSize: 44 })
  })

  it('does not overwrite the saved file checkpoint when auto-save is off', () => {
    useWorkspaceStore.getState().reset()
    useWorkspaceStore.getState().updateSettings({ autoSave: 'off' })
    useWorkspaceStore.getState().setFileContent(seedFileIds.main, '// unsaved')

    expect(useWorkspaceStore.getState().nodes[seedFileIds.main]).toMatchObject({ content: '// unsaved' })
    expect(useWorkspaceStore.getState().savedContents[seedFileIds.main]).not.toBe('// unsaved')

    useWorkspaceStore.getState().saveCheckpoint()
    expect(useWorkspaceStore.getState().savedContents[seedFileIds.main]).toBe('// unsaved')
  })
})
