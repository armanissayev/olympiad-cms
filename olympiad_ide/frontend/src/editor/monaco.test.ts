import { describe, expect, it, vi } from 'vitest'
import type { editor } from 'monaco-editor'
import { MonacoModelRegistry, modelUri } from './modelRegistry'
import type { WorkspaceFile } from '../types/workspace'

const file: WorkspaceFile = {
  id: 'fixed-file-id',
  parentId: null,
  type: 'file',
  name: 'renamed.cpp',
  language: 'cpp',
  content: '',
  documentRevision: 1,
  createdAt: '2026-01-01T00:00:00.000Z',
  updatedAt: '2026-01-01T00:00:00.000Z',
}

const fakeModel = () => ({
  isDisposed: vi.fn(() => false),
  dispose: vi.fn(),
}) as unknown as editor.ITextModel

describe('Monaco model lifecycle', () => {
  it('uses a URI based on stable workspace and file identities, not a mutable path', () => {
    expect(modelUri('workspace-id', file.id)).toBe('olympiad://workspace/workspace-id/file/fixed-file-id')
  })

  it('reuses one adopted model when the same file is opened in two panes', () => {
    const registry = new MonacoModelRegistry()
    const primaryModel = fakeModel()
    const duplicateModel = fakeModel()

    expect(registry.adopt(file, primaryModel)).toBe(primaryModel)
    expect(registry.adopt(file, duplicateModel)).toBe(primaryModel)
    expect(duplicateModel.dispose).toHaveBeenCalledOnce()
    expect(registry.size).toBe(1)
  })

  it('keeps models alive when tabs close and disposes only when the file is pruned', () => {
    const registry = new MonacoModelRegistry()
    const model = fakeModel()
    registry.adopt(file, model)

    expect(registry.get(file.id)).toBe(model)
    registry.prune(new Set())
    expect(model.dispose).toHaveBeenCalledOnce()
    expect(registry.get(file.id)).toBeUndefined()
  })
})
