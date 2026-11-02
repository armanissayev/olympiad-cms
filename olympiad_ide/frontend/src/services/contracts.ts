import type { LanguageId, NodeId, WorkspaceMetadata, WorkspaceNode } from '../types/workspace'

/** Durable workspace adapters use optimistic revisions; see persistence/api.ts and repository.ts. */
export interface WorkspacePersistenceGateway {
  loadWorkspace(workspaceId: string): Promise<{
    workspace: WorkspaceMetadata
    nodes: Record<NodeId, WorkspaceNode>
  }>
  saveWorkspace(input: {
    workspaceId: string
    expectedRevision: number
    nodes: Record<NodeId, WorkspaceNode>
  }): Promise<{ revision: number }>
}

export interface SourceSnapshot {
  workspaceId: string
  workspaceRevision: number
  entryPointFileId: NodeId
  language: LanguageId
  files: ReadonlyArray<{ id: NodeId; path: string; content: string }>
}

/** Phase 4 adapter boundary. Implementations must call an isolated worker-backed API. */
export interface ExecutionGateway {
  run(snapshot: SourceSnapshot, stdin: string, signal: AbortSignal): Promise<{ jobId: string }>
  cancel(jobId: string): Promise<void>
}

/** Phase 6 adapter boundary. Implementations must connect through the authenticated DAP gateway. */
export interface DebugGateway {
  start(snapshot: SourceSnapshot): Promise<{ sessionId: string }>
  stop(sessionId: string): Promise<void>
}
