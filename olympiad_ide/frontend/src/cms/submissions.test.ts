import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { bindDatabase, database, WorkspaceDatabase } from '../persistence/database'
import { initialData, seedFileIds, useWorkspaceStore } from '../store/workspaceStore'
import { useCMSSession } from './session'
import { captureOfficial, exactUTF8, hashBytes, persistIntent, reconcileIntent, sendIntent, verifyRecordedSource } from './submissions'
import { snapshotOf } from '../telemetry/types'
import { digest } from '../telemetry/replayEngine'
import { planImport } from './transfer'
import type { CMSContext, CMSTask, OfficialReceipt, StoredIntent } from './types'

const principal = '45b6ea68-30bf-5d34-971d-898a335ad99a'
const task: CMSTask = { id: 7, name: 'sum', title: 'Sum', languages: [{ id: 'CPP17', name: 'C++17', extension: '.cpp' }], submissionFormat: ['main.%l'], supported: true, statements: [], attachments: [], statementUrl: '/tasks/sum', submissionsUrl: '/tasks/sum/submissions' }
const capture = () => captureOfficial(task, 'CPP17', { 'main.%l': seedFileIds.main })
const receipt = (intent: StoredIntent): OfficialReceipt => ({ schemaVersion: 1, state: 'admitted', intentId: intent.intentId, submissionId: 'opaque-cms-17', receivedAt: '2026-11-02T09:00:00Z', official: true, taskId: intent.taskId, language: intent.body.language, snapshotId: intent.body.snapshotId, workspaceId: intent.body.workspaceId, files: intent.body.files.map(file => ({ ...file, sha256: intent.hashes[file.filename]!, size: exactUTF8(file.content).length })) })
beforeEach(async () => { useWorkspaceStore.setState(initialData()); useCMSSession.setState({ context: { identity: { principalId: principal } } as CMSContext, paused: false, taskId: 7 }); await database.officialSubmissionIntents.clear(); await database.metadata.clear() })
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('captures exact live source before hashing, independently of custom runs, autosave and telemetry', async () => {
  useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'before 😀\r\n')
  const pending = capture(); useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'after')
  const intent = await pending
  expect(intent.body.files[0]?.content).toBe('before 😀\r\n')
  expect(intent.body.language).toBe('CPP17'); expect(intent.hashes['main.%l']).toBe(await hashBytes('before 😀\r\n'))
  expect(intent.body.files).toHaveLength(1)
})
it('rejects invalid Unicode, undeclared languages and file-language mismatch without replacement', async () => {
  expect(() => exactUTF8('\ud800')).toThrow('unpaired')
  expect(() => exactUTF8('\udc00')).toThrow('unpaired')
  await expect(captureOfficial(task, 'java17', { 'main.%l': seedFileIds.main })).rejects.toThrow('permitted')
  await expect(captureOfficial(task, 'CPP17', { 'main.%l': seedFileIds.solution })).rejects.toThrow('extension')
})
it('makes duplicate confirmation idempotent and rejects changed-body UUID reuse', async () => {
  const intent = await capture(); await persistIntent(intent); await persistIntent(intent)
  expect(await database.officialSubmissionIntents.count()).toBe(1)
  const changed = structuredClone(intent); changed.body.files[0]!.content = 'changed'
  await expect(persistIntent(changed)).rejects.toThrow('immutable')
})
it('concurrent sends share one request and require a real matching CMS receipt', async () => {
  const intent = await capture(); await persistIntent(intent)
  const request = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt(intent)))); vi.stubGlobal('fetch', request)
  const [a, b] = await Promise.all([sendIntent(intent.intentId), sendIntent(intent.intentId)])
  expect(a.state).toBe('admitted'); expect(b.receipt?.submissionId).toBe('opaque-cms-17'); expect(request).toHaveBeenCalledTimes(1)
})
it('recovers a lost acknowledgement by receipt lookup without creating another submission', async () => {
  const intent = await capture(); await persistIntent(intent)
  const request = vi.fn().mockRejectedValueOnce(new Error('response lost after commit')).mockResolvedValueOnce(new Response(JSON.stringify(receipt(intent))))
  vi.stubGlobal('fetch', request)
  expect((await sendIntent(intent.intentId)).state).toBe('unknown')
  useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'later edit')
  expect((await sendIntent(intent.intentId)).state).toBe('admitted')
  expect(request.mock.calls.filter(([, init]) => (init as RequestInit).method === 'POST')).toHaveLength(1)
  expect(JSON.parse((request.mock.calls[0]![1] as RequestInit).body as string)).toEqual(intent.body)
})
it('preserves uncertain receipt mismatches and never claims success for changed bytes', async () => {
  const intent = await capture(); await persistIntent(intent); const bad = receipt(intent); bad.files[0]!.sha256 = '0'.repeat(64)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(bad))))
  expect((await sendIntent(intent.intentId)).state).toBe('unknown')
})
it('receipt-only recovery never sends a late POST when the intent was never admitted', async () => {
  const intent = await capture(); await persistIntent(intent)
  const request = vi.fn().mockResolvedValue(new Response('{}', { status: 404 })); vi.stubGlobal('fetch', request)
  expect((await reconcileIntent(intent)).state).toBe('confirmed')
  expect((request.mock.calls[0]![1] as RequestInit).method).toBeUndefined()
})
it('refuses replay under a different CMS principal', async () => {
  const intent = await capture(); await persistIntent(intent)
  useCMSSession.setState({ context: { identity: { principalId: 'another-principal' } } as CMSContext })
  const request = vi.fn(); vi.stubGlobal('fetch', request)
  await expect(sendIntent(intent.intentId)).rejects.toThrow('another CMS identity'); expect(request).not.toHaveBeenCalled()
})
it('bounded import reports collisions and rejects malformed trees and traversal names', async () => {
  const nodes = structuredClone(useWorkspaceStore.getState().nodes)
  const plan = await planImport(JSON.stringify({ document: { nodes } }))
  expect(plan.files).toBe(3); expect(plan.collisions).toBe(4)
  nodes[seedFileIds.main]!.name = '../secret'
  await expect(planImport(JSON.stringify({ document: { nodes } }))).rejects.toThrow('invalid')
})

it('compares exact source with reconstructed durable telemetry and distinguishes missing history from mismatch', async () => {
  const intent = await capture(), sessionId = crypto.randomUUID(), now = new Date().toISOString()
  const nodes = snapshotOf(useWorkspaceStore.getState().nodes)
  const initial = { id: crypto.randomUUID(), sessionId, sequence: 0, workspaceRevision: 1, nodes, stateHash: await digest(nodes), createdAt: now, reason: 'initial' }
  await database.telemetrySessions.add({ id: sessionId, workspaceId: intent.body.workspaceId, tabId: crypto.randomUUID(), startedAt: now, completedAt: null, lastSequence: 0, lastAck: 0, integrity: 'Complete', initial, registered: false, retentionDays: 30, error: null })
  intent.body.telemetry = { sessionId, sequence: 0 }
  expect((await verifyRecordedSource(intent.body, intent.hashes)).state).toBe('verified')
  expect((await verifyRecordedSource(intent.body, { 'main.%l': '0'.repeat(64) })).state).toBe('mismatch')
  intent.body.telemetry.sequence = 1
  expect((await verifyRecordedSource(intent.body, intent.hashes)).state).toBe('unknown')
})

it('keeps identity-changed conflicts uncertain so the original participant can recover the committed receipt', async () => {
  const intent = await capture(); await persistIntent(intent)
  const request = vi.fn().mockRejectedValueOnce(new Error('lost response'))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'identity_changed', message: 'CMS identity changed' } }), { status: 409 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(receipt(intent))))
  vi.stubGlobal('fetch', request)
  expect((await sendIntent(intent.intentId)).state).toBe('unknown')
  expect((await sendIntent(intent.intentId)).state).toBe('unknown')
  expect((await sendIntent(intent.intentId)).state).toBe('admitted')
  expect(request.mock.calls.filter(([, init]) => (init as RequestInit).method === 'POST')).toHaveLength(1)
})


it('commits a delayed receipt to its captured database after another task database is bound', async () => {
  const original = database, next = new WorkspaceDatabase('receipt-scope-' + crypto.randomUUID())
  const intent = await capture(); await persistIntent(intent)
  let resolve!: (response: Response) => void
  const request = vi.fn(() => new Promise<Response>(done => { resolve = done })); vi.stubGlobal('fetch', request)
  const recovering = reconcileIntent(intent)
  await vi.waitFor(() => expect(request).toHaveBeenCalledOnce())
  try {
    bindDatabase(next)
    resolve(new Response(JSON.stringify(receipt(intent))))
    await recovering
    expect((await original.officialSubmissionIntents.get(intent.intentId))?.state).toBe('admitted')
    expect(await next.officialSubmissionIntents.count()).toBe(0)
  } finally { bindDatabase(original); await next.delete() }
})
