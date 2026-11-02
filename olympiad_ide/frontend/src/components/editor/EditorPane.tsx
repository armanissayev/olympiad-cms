import Editor, { type OnMount } from '@monaco-editor/react'
import { FileQuestion } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { editor } from 'monaco-editor'
import { modelRegistry, modelUri, monacoThemeName } from '../../editor/monaco'
import { editorViewStateKey, useWorkspaceStore } from '../../store/workspaceStore'
import type { EditorGroupId, EditorViewState } from '../../types/workspace'
import { TabBar } from './TabBar'
import { attachPaneTelemetry } from '../../telemetry/navigationTracker'

interface EditorPaneProps {
  groupId: EditorGroupId
}

export function EditorPane({ groupId }: EditorPaneProps) {
  const workspaceId = useWorkspaceStore((state) => state.workspace.id)
  const activeFileId = useWorkspaceStore((state) => state.groups[groupId].activeFileId)
  const file = useWorkspaceStore((state) => activeFileId ? state.nodes[activeFileId] : undefined)
  const settings = useWorkspaceStore((state) => state.settings)
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null)
  const activeFileRef = useRef<string | null>(activeFileId)
  const switchingRef = useRef(false)
  const restoreRef = useRef<EditorViewState | undefined>()
  if (activeFileRef.current !== activeFileId) {
    activeFileRef.current = activeFileId
    switchingRef.current = true
    restoreRef.current = activeFileId ? useWorkspaceStore.getState().viewStates[editorViewStateKey(groupId, activeFileId)] : undefined
  }

  useEffect(() => {
    if (!activeFileId || !editorRef.current) return
    const saved = restoreRef.current ?? useWorkspaceStore.getState().viewStates[editorViewStateKey(groupId, activeFileId)]
    const frame = window.requestAnimationFrame(() => {
      const instance = editorRef.current
      if (!instance) return
      instance.setPosition({ lineNumber: saved?.lineNumber ?? 1, column: saved?.column ?? 1 })
      instance.setScrollPosition({ scrollTop: saved?.scrollTop ?? 0, scrollLeft: saved?.scrollLeft ?? 0 })
      switchingRef.current = false
      restoreRef.current = undefined
    })
    return () => window.cancelAnimationFrame(frame)
  }, [activeFileId, groupId])

  const captureViewState = (instance: editor.IStandaloneCodeEditor, fileId: string) => {
    if (switchingRef.current) return
    const position = instance.getPosition() ?? { lineNumber: 1, column: 1 }
    useWorkspaceStore.getState().setViewState(groupId, fileId, {
      lineNumber: position.lineNumber,
      column: position.column,
      scrollTop: instance.getScrollTop(),
      scrollLeft: instance.getScrollLeft(),
    })
  }

  const handleMount: OnMount = (instance, monaco) => {
    editorRef.current = instance
    const currentFile = activeFileRef.current ? useWorkspaceStore.getState().nodes[activeFileRef.current] : undefined
    const model = instance.getModel()
    if (currentFile?.type === 'file' && model) {
      const adopted = modelRegistry.adopt(currentFile, model)
      if (adopted !== model) instance.setModel(adopted)
      monaco.editor.setModelLanguage(adopted, currentFile.language)
    }

    const cursorDisposable = instance.onDidChangeCursorPosition(() => {
      const current = activeFileRef.current
      if (current) captureViewState(instance, current)
    })
    const scrollDisposable = instance.onDidScrollChange(() => {
      const current = activeFileRef.current
      if (current) captureViewState(instance, current)
    })
    const focusDisposable = instance.onDidFocusEditorText(() => useWorkspaceStore.getState().setActiveGroup(groupId))
    const disposeTelemetry = attachPaneTelemetry(instance, groupId, () => activeFileRef.current)
    const initialView = currentFile && useWorkspaceStore.getState().viewStates[editorViewStateKey(groupId, currentFile.id)]
    if (initialView) {
      instance.setPosition({ lineNumber: initialView.lineNumber, column: initialView.column })
      instance.setScrollPosition({ scrollTop: initialView.scrollTop, scrollLeft: initialView.scrollLeft })
    }
    instance.onDidDispose(() => {
      cursorDisposable.dispose()
      scrollDisposable.dispose()
      focusDisposable.dispose()
      disposeTelemetry()
      editorRef.current = null
    })
  }

  useEffect(() => {
    if (!file || file.type !== 'file' || !editorRef.current) return
    const model = editorRef.current.getModel()
    if (model?.uri.toString() === modelUri(workspaceId, file.id)) modelRegistry.adopt(file, model)
  }, [file, workspaceId])

  return (
    <section className="editor-pane" onMouseDown={() => useWorkspaceStore.getState().setActiveGroup(groupId)}>
      <TabBar groupId={groupId} />
      {file?.type === 'file' ? (
        <Editor
          path={modelUri(workspaceId, file.id)}
          defaultValue={file.content}
          defaultLanguage={file.language}
          language={file.language}
          theme={monacoThemeName(settings.theme)}
          onMount={handleMount}
          onChange={(value) => useWorkspaceStore.getState().setFileContent(file.id, value ?? '')}
          saveViewState={false}
          keepCurrentModel
          loading={<div className="editor-loading">Loading Monaco…</div>}
          options={{
            automaticLayout: true,
            fontSize: settings.fontSize,
            fontFamily: settings.fontFamily,
            tabSize: settings.tabSize,
            insertSpaces: settings.insertSpaces,
            wordWrap: settings.wordWrap,
            minimap: { enabled: settings.minimap, renderCharacters: false },
            autoClosingBrackets: settings.autoClosingBrackets,
            lineNumbers: settings.lineNumbers,
            cursorStyle: settings.cursorStyle,
            renderWhitespace: settings.renderWhitespace,
            bracketPairColorization: { enabled: true },
            guides: { bracketPairs: true, indentation: true },
            folding: true,
            matchBrackets: 'always',
            multiCursorModifier: 'alt',
            smoothScrolling: false,
            padding: { top: 8 },
            scrollBeyondLastLine: false,
            fixedOverflowWidgets: true,
          }}
        />
      ) : (
        <div className="empty-editor">
          <FileQuestion className="h-12 w-12 opacity-20" strokeWidth={1.2} />
          <p>No editor is open</p>
          <span>Choose a file from Explorer or press Ctrl/Cmd+P.</span>
        </div>
      )}
    </section>
  )
}
