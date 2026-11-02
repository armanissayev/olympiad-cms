export type NodeId = string
export type EditorGroupId = 'primary' | 'secondary'
export type ThemeId = 'dark-modern' | 'light' | 'high-contrast'
export type ActivityView = 'explorer' | 'search' | 'run' | 'history' | 'settings'
export type BottomPanelView = 'terminal' | 'problems' | 'tests'

export type LanguageId = 'cpp' | 'python' | 'java' | 'plaintext'

interface BaseNode {
  id: NodeId
  parentId: NodeId | null
  name: string
  createdAt: string
  updatedAt: string
}

export interface WorkspaceFile extends BaseNode {
  type: 'file'
  content: string
  language: LanguageId
  documentRevision: number
}

export interface WorkspaceFolder extends BaseNode {
  type: 'folder'
}

export type WorkspaceNode = WorkspaceFile | WorkspaceFolder

export interface EditorGroup {
  id: EditorGroupId
  tabIds: NodeId[]
  activeFileId: NodeId | null
}

export interface EditorViewState {
  lineNumber: number
  column: number
  scrollTop: number
  scrollLeft: number
}

export interface EditorSettings {
  theme: ThemeId
  fontSize: number
  fontFamily: string
  tabSize: number
  insertSpaces: boolean
  wordWrap: 'on' | 'off'
  minimap: boolean
  autoClosingBrackets: 'always' | 'never'
  lineNumbers: 'on' | 'off' | 'relative'
  cursorStyle: 'line' | 'block' | 'underline'
  autoSave: 'off' | 'afterDelay'
  renderWhitespace: 'none' | 'selection' | 'all'
}

export interface WorkspaceMetadata {
  id: string
  ownerId: string
  name: string
  revision: number
  createdAt: string
  updatedAt: string
}

export const languageForFileName = (fileName: string): LanguageId => {
  const extension = fileName.split('.').pop()?.toLowerCase()
  if (['cpp', 'cc', 'cxx', 'h', 'hpp'].includes(extension ?? '')) return 'cpp'
  if (extension === 'py') return 'python'
  if (extension === 'java') return 'java'
  return 'plaintext'
}

export const displayLanguage = (language: LanguageId): string => {
  switch (language) {
    case 'cpp':
      return 'C++20'
    case 'python':
      return 'Python 3'
    case 'java':
      return 'Java 17'
    default:
      return 'Plain Text'
  }
}
