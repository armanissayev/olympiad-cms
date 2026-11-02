import { create } from 'zustand'
import type { CMSContext, CMSTask } from './types'

export const cmsEnabled = import.meta.env.VITE_CMS_MODE === 'true'
export const appBase = import.meta.env.BASE_URL
export const cmsURL = (path: string) => `${appBase}api/${path}`
export const runtimeURL = (path: string) => cmsEnabled ? cmsURL(`runtime/v1${path}`) : `/api/v1${path}`
interface SessionState { context: CMSContext | null; taskId: number | null; paused: boolean; message: string | null; receivedAt: number }
export const useCMSSession = create<SessionState>(() => ({ context: null, taskId: null, paused: true, message: null, receivedAt: Date.now() }))
const cacheKey = `olympiad-cms-recovery:${appBase}`
export const currentTask = (): CMSTask | undefined => {
  const { context, taskId } = useCMSSession.getState()
  return context?.tasks.find(task => task.id === taskId)
}
export function safeCMSLink(value: string | undefined): string | undefined {
  if (!value) return undefined
  try { const url = new URL(value, location.href); return url.origin === location.origin && /^https?:$/.test(url.protocol) ? url.href : undefined } catch { return undefined }
}
export function validateContext(value: unknown): CMSContext {
  const c = value as CMSContext
  if (!c || c.schemaVersion !== 1 || !c.identity || !/^[0-9a-f-]{36}$/i.test(c.identity.principalId) ||
      typeof c.identity.installationId !== 'string' || !c.contest || !Array.isArray(c.tasks) || !c.links ||
      typeof c.csrfToken !== 'string' || !Number.isFinite(Date.parse(c.serverTime)) || !Number.isInteger(c.actualPhase)) throw new Error('CMS returned an unsupported participant context')
  for (const task of c.tasks) if (!Number.isInteger(task.id) || !Array.isArray(task.languages) || !Array.isArray(task.submissionFormat) || !Array.isArray(task.statements) || !Array.isArray(task.attachments)) throw new Error('CMS returned an invalid task contract')
  return c
}
export function scopedDatabaseName(context: CMSContext, taskId: number | null): string {
  return `olympiad-ide.cms.${encodeURIComponent(context.identity.installationId)}.${context.identity.principalId}.task.${taskId ?? 'scratch'}`
}
export function databaseName(): string {
  const { context, taskId } = useCMSSession.getState()
  return cmsEnabled && context ? scopedDatabaseName(context, taskId) : 'olympiad-ide'
}
export function pauseSession(message: string) { if (cmsEnabled) useCMSSession.setState({ paused: true, message }) }
export function trustedHeaders(requireTask = false): Record<string, string> {
  if (!cmsEnabled) return {}
  const { context, paused } = useCMSSession.getState()
  if (!context || paused) throw new Error('CMS authentication is paused. Local work remains recoverable; sign in again to resume server operations.')
  const taskId = useCMSSession.getState().taskId
  if (requireTask && !context.tasks.some(task => task.id === taskId)) throw new Error('Private IDE operations are paused because this task is not currently authorized. Local work is retained.')
  return { 'X-Olympiad-Principal': context.identity.principalId, 'X-XSRFToken': context.csrfToken, ...(requireTask ? { 'X-Olympiad-Task': String(taskId) } : {}) }
}
export async function initializeCMS(): Promise<void> {
  if (!cmsEnabled) return
  let response: Response
  try { response = await fetch(cmsURL('context'), { credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(8000) }) }
  catch (error) {
    // Only the same tab's previously authenticated scope may recover offline. This never authorizes uploads.
    const cached = sessionStorage.getItem(cacheKey)
    if (!cached) throw error
    const recovery = JSON.parse(cached) as { context: CMSContext; taskId: number | null }
    const context = validateContext({ ...recovery.context, csrfToken: '' })
    useCMSSession.setState({ context, taskId: recovery.taskId, paused: true, message: 'Offline recovery. CMS server operations are paused until authentication is checked.' })
    return
  }
  if (!response.ok) {
    sessionStorage.removeItem(cacheKey)
    pauseSession('CMS authentication failed. Existing local work is retained.')
    throw new Error(response.status === 401 || response.status === 403 ? 'Sign in through CMS to open this IDE. Existing local work is retained.' : `CMS participant context is unavailable (${response.status}). Existing local work is retained.`)
  }
  const context = validateContext(await response.json())
  const saved = localStorage.getItem(`olympiad-cms-task:${context.identity.principalId}`)
  const taskId = context.tasks.find(task => String(task.id) === saved)?.id ?? (saved && /^\d+$/.test(saved) ? Number(saved) : context.tasks[0]?.id ?? null)
  useCMSSession.setState({ context, taskId, paused: false, message: null, receivedAt: Date.now() })
  // CSRF material is never persisted; offline context is only a recovery locator.
  sessionStorage.setItem(cacheKey, JSON.stringify({ context: { ...context, csrfToken: '' }, taskId }))
}
export async function checkCMSContext(): Promise<void> {
  if (!cmsEnabled) return
  const previous = useCMSSession.getState()
  try {
    const response = await fetch(cmsURL('context'), { credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(8000) })
    if (!response.ok) { pauseSession('CMS session expired or participation changed. Local work is retained. Sign in again.'); return }
    const context = validateContext(await response.json())
    if (context.identity.principalId !== previous.context?.identity.principalId) { pauseSession('CMS account changed. Uploads for this workspace are paused. Reopen the IDE to use the current account.'); return }
    useCMSSession.setState({ context, paused: false, message: null, receivedAt: Date.now() })
  } catch { pauseSession('CMS is unreachable. Editing remains local; server operations are paused.') }
}
export function selectTask(id: number) {
  const { context } = useCMSSession.getState()
  if (!context?.tasks.some(task => task.id === id)) throw new Error('Task is not currently authorized')
  localStorage.setItem(`olympiad-cms-task:${context.identity.principalId}`, String(id))
  sessionStorage.setItem(cacheKey, JSON.stringify({ context: { ...context, csrfToken: '' }, taskId: id }))
}
