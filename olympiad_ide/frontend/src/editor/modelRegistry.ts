import type { editor } from 'monaco-editor'
import type { WorkspaceFile } from '../types/workspace'

export const modelUri = (workspaceId: string, fileId: string): string =>
  `olympiad://workspace/${encodeURIComponent(workspaceId)}/file/${encodeURIComponent(fileId)}`

export class MonacoModelRegistry {
  private readonly models = new Map<string, editor.ITextModel>()
  private readonly observers = new Set<(file: WorkspaceFile, model: editor.ITextModel) => void>()

  observe(observer: (file: WorkspaceFile, model: editor.ITextModel) => void): () => void {
    this.observers.add(observer)
    return () => this.observers.delete(observer)
  }

  adopt(file: WorkspaceFile, model: editor.ITextModel): editor.ITextModel {
    const existing = this.models.get(file.id)
    if (existing && existing !== model && !existing.isDisposed()) {
      model.dispose()
      return existing
    }
    this.models.set(file.id, model)
    this.observers.forEach(observer => observer(file, model))
    return model
  }

  get(fileId: string): editor.ITextModel | undefined {
    const model = this.models.get(fileId)
    return model?.isDisposed() ? undefined : model
  }

  disposeFile(fileId: string): void {
    const model = this.models.get(fileId)
    if (model && !model.isDisposed()) model.dispose()
    this.models.delete(fileId)
  }

  prune(validFileIds: Set<string>): void {
    for (const fileId of this.models.keys()) {
      if (!validFileIds.has(fileId)) this.disposeFile(fileId)
    }
  }

  disposeAll(): void {
    for (const model of this.models.values()) {
      if (!model.isDisposed()) model.dispose()
    }
    this.models.clear()
  }

  get size(): number {
    return this.models.size
  }
}

export const modelRegistry = new MonacoModelRegistry()
