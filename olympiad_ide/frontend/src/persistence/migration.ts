import { initialData, type WorkspaceData } from '../store/workspaceStore'
import type { WorkspaceNode } from '../types/workspace'

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** Parsing never removes the legacy key; malformed input is exportable from the error UI. */
export function migratePhase1(raw: string): WorkspaceData {
  const parsed = JSON.parse(raw) as { state?: Partial<WorkspaceData>; version?: number }
  const old = parsed.state
  if (!old?.workspace || !uuid.test(old.workspace.id) || !old.nodes || !old.groups || !old.settings) {
    throw new Error('Legacy workspace is incomplete. Export the original data before recovery.')
  }
  const nodes = old.nodes as Record<string, WorkspaceNode>
  for (const [id, node] of Object.entries(nodes)) {
    if (!uuid.test(id) || node.id !== id || !node.name || !['file', 'folder'].includes(node.type)) {
      throw new Error('Legacy workspace has invalid file identities.')
    }
    const seen = new Set([id])
    let parent = node.parentId
    while (parent) {
      if (seen.has(parent) || nodes[parent]?.type !== 'folder') throw new Error('Legacy workspace has an invalid folder tree.')
      seen.add(parent)
      parent = nodes[parent]!.parentId
    }
    if (node.type === 'file' && typeof node.content !== 'string') throw new Error('Legacy file content is missing.')
  }
  const defaults = initialData()
  return {
    ...defaults, ...old, nodes,
    settings: { ...defaults.settings, ...old.settings },
    groups: old.groups,
    workspace: old.workspace,
    savedContents: Object.fromEntries(Object.values(nodes).flatMap((node) => node.type === 'file' ? [[node.id, node.content]] : [])),
  }
}
