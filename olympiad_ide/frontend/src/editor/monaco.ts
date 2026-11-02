import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import 'monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution'
import 'monaco-editor/esm/vs/basic-languages/java/java.contribution'
import 'monaco-editor/esm/vs/basic-languages/python/python.contribution'
// The lightweight API entry does not register these actions. Keep real multi-edit/find transactions available.
import 'monaco-editor/esm/vs/editor/contrib/find/browser/findController'
import 'monaco-editor/esm/vs/editor/contrib/multicursor/browser/multicursor'
import { modelRegistry, modelUri, MonacoModelRegistry } from './modelRegistry'

self.MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
}

loader.config({ monaco })

export { modelRegistry, modelUri, MonacoModelRegistry }

export const defineOlympiadThemes = (): void => {
  monaco.editor.defineTheme('olympiad-dark-modern', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '6A9955' },
      { token: 'keyword', foreground: 'C586C0' },
      { token: 'string', foreground: 'CE9178' },
      { token: 'number', foreground: 'B5CEA8' },
      { token: 'type.identifier', foreground: '4EC9B0' },
    ],
    colors: {
      'editor.background': '#1F1F1F',
      'editor.foreground': '#CCCCCC',
      'editorLineNumber.foreground': '#6E7681',
      'editorLineNumber.activeForeground': '#C6C6C6',
      'editorCursor.foreground': '#AEAFAD',
      'editor.selectionBackground': '#264F78',
      'editor.inactiveSelectionBackground': '#3A3D41',
      'editor.lineHighlightBackground': '#2A2D2E66',
      'editorIndentGuide.background1': '#404040',
      'editorIndentGuide.activeBackground1': '#707070',
      'editorWidget.background': '#252526',
      'editorWidget.border': '#454545',
    },
  })
  monaco.editor.defineTheme('olympiad-light', {
    base: 'vs',
    inherit: true,
    rules: [],
    colors: { 'editor.background': '#FFFFFF', 'editor.lineHighlightBackground': '#F4F4F4' },
  })
  monaco.editor.defineTheme('olympiad-high-contrast', {
    base: 'hc-black',
    inherit: true,
    rules: [],
    colors: { 'editor.background': '#000000', 'editorCursor.foreground': '#FFFFFF' },
  })
}

export const monacoThemeName = (theme: 'dark-modern' | 'light' | 'high-contrast'): string => {
  if (theme === 'light') return 'olympiad-light'
  if (theme === 'high-contrast') return 'olympiad-high-contrast'
  return 'olympiad-dark-modern'
}
