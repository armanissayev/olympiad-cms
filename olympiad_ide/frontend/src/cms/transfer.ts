import type { WorkspaceNode } from '../types/workspace'
import { languageForFileName } from '../types/workspace'
import { useWorkspaceStore } from '../store/workspaceStore'
import { database } from '../persistence/database'
import { persistence } from '../persistence/controller'
import { toDocument } from '../persistence/types'
import { withDocumentOrigin } from '../telemetry/origin'
import { hashBytes, exactUTF8 } from './submissions'

function importFolderId(digest: string): string { return `${digest.slice(0,8)}-${digest.slice(8,12)}-5${digest.slice(13,16)}-a${digest.slice(17,20)}-${digest.slice(20,32)}` }
export interface ImportPlan { digest: string; nodes: Record<string, WorkspaceNode>; files: number; bytes: number; collisions: number; alreadyImported: boolean }
export function downloadJSON(name: string, value: unknown) {
  const link = document.createElement('a'), url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function exportWorkspace() {
  downloadJSON(`olympiad-workspace-${Date.now()}.json`, { schemaVersion: 1, kind: 'olympiad-workspace-export', exportedAt: new Date().toISOString(), document: toDocument(useWorkspaceStore.getState()) })
}
export async function planImport(raw: string): Promise<ImportPlan> {
  if (exactUTF8(raw).length > 12_000_000) throw new Error('Import exceeds the 12 MB archive limit')
  const parsed = JSON.parse(raw) as { document?: { nodes?: Record<string, WorkspaceNode> } }
  const input = parsed.document?.nodes
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Choose an Olympiad workspace or recovery JSON export containing document.nodes')
  if (Object.keys(input).length > 999) throw new Error('Import is limited to 999 nodes plus its recovery folder')
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
  const nodes: Record<string, WorkspaceNode> = {}; const siblings = new Set<string>(); let files = 0, bytes = 0
  for (const [id, value] of Object.entries(input)) {
    if (!uuid.test(id) || !value || value.id !== id || !['file', 'folder'].includes(value.type) || typeof value.name !== 'string' ||
        !value.name.trim() || value.name.length > 255 || ((value.name.includes('/') || value.name.includes('\\')) || [...value.name].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) || ['.', '..'].includes(value.name) ||
        (value.parentId !== null && (typeof value.parentId !== 'string' || !uuid.test(value.parentId)))) throw new Error('Import contains an invalid file identity or name')
    const sibling = `${value.parentId ?? ''}/${value.name}`
    if (siblings.has(sibling)) throw new Error('Import contains duplicate sibling names')
    siblings.add(sibling)
    const common = { id, name: value.name, parentId: value.parentId, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString() }
    if (value.type === 'file') {
      if (typeof value.content !== 'string') throw new Error('Import contains a file without text')
      const size = exactUTF8(value.content).length
      if (size > 2_000_000) throw new Error('An imported file exceeds 2 MB')
      bytes += size; files++
      nodes[id] = { ...common, type: 'file', content: value.content, language: languageForFileName(value.name), documentRevision: 1 }
    } else nodes[id] = { ...common, type: 'folder' }
  }
  if (bytes > 8_000_000) throw new Error('Imported source exceeds 8 MB')
  for (const [id, node] of Object.entries(nodes)) {
    const seen = new Set([id]); let parent = node.parentId
    while (parent) {
      if (seen.has(parent) || nodes[parent]?.type !== 'folder') throw new Error('Import contains a cyclic or missing folder')
      seen.add(parent); parent = nodes[parent]!.parentId
    }
  }
  const digest = await hashBytes(raw)
  return { digest, nodes, files, bytes, collisions: Object.keys(nodes).filter(id => id in useWorkspaceStore.getState().nodes).length,
    alreadyImported: !!await database.metadata.get(`cms-source-import:${digest}`) || importFolderId(digest) in useWorkspaceStore.getState().nodes }
}
export async function applyImport(plan: ImportPlan): Promise<void> {
  await persistence.flush()
  if (await database.metadata.get(`cms-source-import:${plan.digest}`)) throw new Error('This archive was already imported; existing source is retained')
  const state = useWorkspaceStore.getState(), incoming = Object.keys(plan.nodes)
  if (Object.keys(state.nodes).length + incoming.length + 1 > 1000) throw new Error('Combined workspace exceeds 1000 nodes')
  const currentBytes = Object.values(state.nodes).reduce((sum, node) => sum + (node.type === 'file' ? exactUTF8(node.content).length : 0), 0)
  if (currentBytes + plan.bytes > 8_000_000) throw new Error('Combined workspace exceeds 8 MB')
  const folderId = importFolderId(plan.digest)
  if (folderId in state.nodes) throw new Error('This archive recovery folder already exists; refusing duplicate import')
  const timestamp = new Date().toISOString()
  const ids = new Map(incoming.map(id => [id, id in state.nodes ? crypto.randomUUID() : id]))
  const nodes = { ...state.nodes, [folderId]: { id: folderId, parentId: null, type: 'folder' as const, name: `Imported-${Date.now()}`, createdAt: timestamp, updatedAt: timestamp } }
  for (const node of Object.values(plan.nodes)) {
    const id = ids.get(node.id)!
    nodes[id] = { ...node, id, parentId: node.parentId ? ids.get(node.parentId)! : folderId }
  }
  withDocumentOrigin('validated-source-import', () => useWorkspaceStore.setState({ nodes, expandedFolderIds: [...state.expandedFolderIds, folderId] }))
  await persistence.flush()
  await database.metadata.put({ key: `cms-source-import:${plan.digest}`, value: JSON.stringify({ importedAt: timestamp, folderId, remapped: [...ids].filter(([a, b]) => a !== b) }) })
}
