import type { ServerWorkspace, SyncOperation } from './types'
import { cmsEnabled, pauseSession, runtimeURL, trustedHeaders, useCMSSession } from '../cms/session'

// Workspace and telemetry uploaders share one cookie identity, including their very first request.
let identityRequest: Promise<{ identityId: string }> | null = null

export class RequestError extends Error {
  constructor(readonly status: number, message: string, readonly server?: ServerWorkspace) {
    super(message)
  }
}

export class WorkspaceAPI {
  async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(runtimeURL(path), {
      ...init, credentials: 'same-origin', signal: AbortSignal.timeout(8000),
      headers: { 'Content-Type': 'application/json', ...init?.headers, ...trustedHeaders(true) },
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { error?: { message: string; code?: string; server?: ServerWorkspace } }
      if (cmsEnabled && (response.status === 401 || response.status === 403 || (response.status === 409 && /scope|principal|identity/i.test((body.error?.code ?? '') + (body.error?.message ?? ''))))) pauseSession(body.error?.message ?? 'CMS authentication changed. Server operations are paused.')
      throw new RequestError(response.status, body.error?.message ?? `Request failed (${response.status})`, body.error?.server)
    }
    return response.status === 204 ? undefined as T : response.json() as Promise<T>
  }

  session() {
    if (cmsEnabled) {
      trustedHeaders(true)
      return Promise.resolve({ identityId: useCMSSession.getState().context!.identity.principalId })
    }
    if (!identityRequest) {
      const establish = () => this.request<{ identityId: string }>('/session', { method: 'POST' })
      identityRequest = (navigator.locks ? navigator.locks.request('olympiad-development-identity', establish) : establish())
        .finally(() => { identityRequest = null })
    }
    return identityRequest
  }
  get(id: string) { return this.request<ServerWorkspace>(`/workspaces/${id}`) }
  status(id: string) { return this.request<{ revision: number }>(`/sync/status/${id}`) }
  list() { return this.request<ServerWorkspace[]>('/workspaces') }
  send(operation: SyncOperation) {
    const { operationId, workspaceId, baseRevision, document } = operation
    return this.request<{ acknowledgements: { operationId: string; revision: number }[] }>('/sync/batches', {
      method: 'POST', body: JSON.stringify({ operations: [{ operationId, workspaceId, baseRevision, document }] }),
    })
  }
}

export const retryDelay = (attempt: number, random = Math.random): number =>
  Math.round(Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5)) * (0.8 + random() * 0.4))
