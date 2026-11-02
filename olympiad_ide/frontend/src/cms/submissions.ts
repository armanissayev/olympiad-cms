import { database } from '../persistence/database'
import { modelRegistry } from '../editor/modelRegistry'
import { useWorkspaceStore } from '../store/workspaceStore'
import { telemetry } from '../telemetry/collector'
import { replay, verifyCheckpoint } from '../telemetry/replayEngine'
import { cmsURL, pauseSession, trustedHeaders, useCMSSession } from './session'
import type { CMSTask, OfficialHistory, OfficialIntent, OfficialReceipt, ParticipantStatus, StoredIntent } from './types'

export class CMSError extends Error { constructor(readonly status: number, message: string, readonly code?: string) { super(message) } }
export async function cmsRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(cmsURL(path), { ...init, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15000), headers: { 'Content-Type': 'application/json', ...init?.headers, ...trustedHeaders() } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { error?: { message?: string; code?: string } | string; message?: string; code?: string }
    const message = (typeof body.error === 'string' ? body.error : body.error?.message) ?? body.message ?? `CMS request failed (${response.status})`
    const code = (typeof body.error === 'object' ? body.error?.code : undefined) ?? body.code
    if (response.status === 401 || response.status === 403 || (response.status === 409 && /identity|principal|scope/.test(code ?? ''))) pauseSession(message)
    throw new CMSError(response.status, message, code)
  }
  return response.json() as Promise<T>
}
export function exactUTF8(text: string): Uint8Array<ArrayBuffer> {
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i)
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = text.charCodeAt(++i)
      if (!(next >= 0xdc00 && next <= 0xdfff)) throw new Error('Source contains an unpaired UTF-16 surrogate and cannot be submitted as exact UTF-8.')
    } else if (code >= 0xdc00 && code <= 0xdfff) throw new Error('Source contains an unpaired UTF-16 surrogate and cannot be submitted as exact UTF-8.')
  }
  return new TextEncoder().encode(text)
}
export async function hashBytes(text: string): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', exactUTF8(text))
  return [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}
export async function captureOfficial(task: CMSTask, language: string, mapping: Record<string, string>): Promise<StoredIntent> {
  const { context } = useCMSSession.getState()
  if (!context) throw new Error('CMS identity is unavailable')
  if (!task.supported) throw new Error(task.reason ?? 'Use the CMS participant page for this task')
  const allowed = task.languages.find(item => item.id === language)
  if (!allowed) throw new Error('Choose a language permitted by CMS')
  const state = useWorkspaceStore.getState()
  const files = task.submissionFormat.map(filename => {
    const node = state.nodes[mapping[filename] ?? '']
    if (node?.type !== 'file') throw new Error(`Select the exact source file for ${filename}`)
    const extension = allowed.extension.startsWith('.') ? allowed.extension : `.${allowed.extension}`
    const extensions = allowed.extensions?.length ? allowed.extensions : [extension]
    if (filename.includes('%l') && !extensions.some(suffix => node.name.endsWith(suffix))) throw new Error(`${node.name} does not match the CMS language extension ${extension}`)
    const content = modelRegistry.get(node.id)?.getValue() ?? node.content
    if (exactUTF8(content).length > 2_000_000) throw new Error('Selected source exceeds the IDE 2 MB per-file bound; use CMS if its configured limit permits it.')
    return { filename, sourceFilename: node.name, fileId: node.id, content }
  })
  if (new Set(files.map(file => file.fileId)).size !== files.length) throw new Error('Select a distinct source file for each CMS filename')
  if (files.reduce((sum, file) => sum + exactUTF8(file.content).length, 0) > 8_000_000) throw new Error('Selected source exceeds the IDE 8 MB snapshot bound')
  // All text and correlation boundaries are captured before hashing or network awaits.
  const body: OfficialIntent = { schemaVersion: 1, intentId: crypto.randomUUID(), taskId: task.id, language, files,
    snapshotId: crypto.randomUUID(), workspaceId: state.workspace.id,
    telemetry: telemetry.session ? { sessionId: telemetry.session.id, sequence: telemetry.session.lastSequence } : null }
  const hashes = Object.fromEntries(await Promise.all(files.map(async file => [file.filename, await hashBytes(file.content)])))
  return { intentId: body.intentId, principalId: context.identity.principalId, taskId: task.id, body, hashes, correlation: await verifyRecordedSource(body, hashes), state: 'confirmed', createdAt: new Date().toISOString() }
}
export async function verifyRecordedSource(body: OfficialIntent, hashes: Record<string, string>): Promise<NonNullable<StoredIntent['correlation']>> {
  if (!body.telemetry) return { state: 'unknown', reason: 'No telemetry boundary was available at capture.' }
  try {
    const boundary = body.telemetry
    const session = await database.telemetrySessions.get(boundary.sessionId)
    if (!session || session.workspaceId !== body.workspaceId || session.integrity !== 'Complete') return { state: 'unknown', reason: 'The durable recording is missing, interrupted or belongs to another workspace.' }
    await verifyCheckpoint(session.initial.nodes, session.initial)
    const events = boundary.sequence === 0 ? [] : await database.telemetryEvents.where('[sessionId+sequence]').between([boundary.sessionId, 1], [boundary.sessionId, boundary.sequence], true, true).sortBy('sequence')
    const nodes = replay(session.initial.nodes, events, boundary.sequence)
    for (const file of body.files) {
      const recorded = nodes[file.fileId]
      if (recorded?.type !== 'file' || recorded.content === null || await hashBytes(recorded.content) !== hashes[file.filename]) return { state: 'mismatch', reason: 'The complete durable recording at this boundary differs from the captured source. This is an integrity diagnostic, not a cheating verdict.' }
    }
    return { state: 'verified', reason: 'Exact submitted-file bytes match reconstruction from the durable local recording at the captured boundary. Browser observations are not tamper-proof.' }
  } catch {
    return { state: 'unknown', reason: 'The durable recording prefix could not be reconstructed; events may still be buffered or missing. Submission remains independent of telemetry.' }
  }
}
export async function persistIntent(intent: StoredIntent): Promise<void> {
  if (intent.principalId !== useCMSSession.getState().context?.identity.principalId) throw new Error('The captured intent belongs to another CMS identity')
  const existing = await database.officialSubmissionIntents.get(intent.intentId)
  if (existing && JSON.stringify(existing.body) !== JSON.stringify(intent.body)) throw new Error('An immutable intent cannot be changed. Capture a new submission.')
  if (!existing) {
    await database.officialSubmissionIntents.add(structuredClone(intent))
    observe('CMS_SUBMISSION_INTENT', intent)
  }
}
function observe(event: 'CMS_SUBMISSION_INTENT' | 'CMS_SUBMISSION_ADMITTED' | 'CMS_SUBMISSION_REJECTED', intent: StoredIntent) {
  if (!telemetry.session) return
  try { telemetry.record(event, null, { intentId: intent.intentId, snapshotId: intent.body.snapshotId, taskId: intent.taskId, language: intent.body.language, ...(intent.receipt ? { submissionId: intent.receipt.submissionId, receivedAt: intent.receipt.receivedAt } : {}) }) }
  catch (error) { telemetry.fail(error) }
}
const inFlight = new Map<string, Promise<StoredIntent>>()
async function saveReceipt(intent: StoredIntent, receipt: OfficialReceipt): Promise<StoredIntent> {
  if (receipt.schemaVersion !== 1 || receipt.state !== 'admitted' || receipt.intentId !== intent.intentId || receipt.taskId !== intent.taskId ||
      receipt.language !== intent.body.language || receipt.workspaceId !== intent.body.workspaceId || receipt.snapshotId !== intent.body.snapshotId ||
      !receipt.submissionId || !Number.isFinite(Date.parse(receipt.receivedAt)) || receipt.files.length !== intent.body.files.length ||
      receipt.files.some(file => { const captured = intent.body.files.find(source => source.filename === file.filename); return !captured || captured.fileId !== file.fileId || captured.sourceFilename !== file.sourceFilename || exactUTF8(captured.content).length !== file.size || intent.hashes[file.filename] !== file.sha256 })) throw new Error('CMS returned a receipt that does not match the captured source; outcome remains unknown.')
  const saved: StoredIntent = { ...intent, state: 'admitted', receipt, error: undefined }
  await database.officialSubmissionIntents.put(saved)
  return saved
}
export async function reconcileIntent(intent: StoredIntent): Promise<StoredIntent> {
  if (intent.principalId !== useCMSSession.getState().context?.identity.principalId) throw new Error('Intent belongs to another CMS participant; retained locally without upload')
  try { return await saveReceipt(intent, await cmsRequest<OfficialReceipt>(`submissions/${encodeURIComponent(intent.intentId)}`)) }
  catch (error) {
    if (error instanceof CMSError && error.status === 404) return intent
    throw error
  }
}
export function sendIntent(intentId: string): Promise<StoredIntent> {
  const active = inFlight.get(intentId)
  if (active) return active
  const promise = (async () => {
    let intent = await database.officialSubmissionIntents.get(intentId)
    if (!intent) throw new Error('Durable submission intent is missing')
    if (intent.state === 'admitted' || intent.state === 'rejected') return intent
    if (intent.principalId !== useCMSSession.getState().context?.identity.principalId) throw new Error('Intent belongs to another CMS identity')
    trustedHeaders()
    try {
      // Resolve a lost acknowledgement before retransmission, including after the deadline.
      if (intent.state === 'pending' || intent.state === 'unknown') {
        intent = await reconcileIntent(intent)
        if (intent.state === 'admitted') return intent
      }
      intent = { ...intent, state: 'pending', error: undefined }
      await database.officialSubmissionIntents.put(intent)
      const admitted = await saveReceipt(intent, await cmsRequest<OfficialReceipt>('submissions', { method: 'POST', body: JSON.stringify(intent.body) }))
      observe('CMS_SUBMISSION_ADMITTED', admitted)
      return admitted
    } catch (error) {
      const rejected = error instanceof CMSError && [400, 409, 413, 415, 422, 429].includes(error.status) && !/identity|principal|scope/.test(error.code ?? '')
      const saved: StoredIntent = { ...intent, state: rejected ? 'rejected' : 'unknown', error: error instanceof Error ? error.message : String(error) }
      await database.officialSubmissionIntents.put(saved)
      if (rejected) observe('CMS_SUBMISSION_REJECTED', saved)
      return saved
    }
  })().finally(() => inFlight.delete(intentId))
  inFlight.set(intentId, promise)
  return promise
}
export const listHistory = (taskId: number, offset = 0) => cmsRequest<{ submissions: OfficialHistory[]; total: number; nextOffset: number | null }>(`submissions?taskId=${taskId}&offset=${offset}`)
export const getFeedback = async (taskId: number, id: string) => (await cmsRequest<{ status: ParticipantStatus }>(`submissions/status/${encodeURIComponent(id)}?taskId=${taskId}`)).status
