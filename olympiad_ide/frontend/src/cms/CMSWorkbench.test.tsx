import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { database } from '../persistence/database'
import { initialData, seedFileIds, useWorkspaceStore } from '../store/workspaceStore'
import { useCMSSession } from './session'
import type { CMSContext, OfficialIntent, OfficialReceipt } from './types'
import { exactUTF8, hashBytes } from './submissions'

vi.mock('./session', async load => ({ ...await load<typeof import('./session')>(), cmsEnabled: true }))
vi.mock('./taskWorkspace', () => ({ switchTaskWorkspace: vi.fn().mockResolvedValue(undefined) }))
import { CMSWorkbench } from './CMSWorkbench'
import { participantMessage, sourceLanguage } from './submissionPresentation'
import { CMSError } from './submissions'
let host: HTMLDivElement, root: Root, posts: OfficialIntent[], receipt: OfficialReceipt | null
const context: CMSContext = { schemaVersion: 1, identity: { installationId: 'unit', userId: 1, contestId: 1, participationId: 1, principalId: '45b6ea68-30bf-5d34-971d-898a335ad99a' }, user: { username: 'participant', firstName: '', lastName: '' }, contest: { id: 1, name: 'Contest', description: 'Test contest' }, actualPhase: 0, serverTime: new Date().toISOString(), phaseEnd: null, csrfToken: 'test-csrf', tasks: [{ id: 1, name: 'sum', title: 'Sum', supported: true, languages: [{ id: 'CPP', name: 'C++17', extension: '.cpp' }, { id: 'PY', name: 'Python 3', extension: '.py' }], submissionFormat: ['main.%l'], statements: [], attachments: [], statementUrl: '/tasks/sum', submissionsUrl: '/tasks/sum/submissions' }], links: { login: '/login', logout: '/logout', fallback: '/', announcements: '/', clarifications: '/' } }
beforeEach(async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  useWorkspaceStore.setState(initialData()); useCMSSession.setState({ context, taskId: 1, paused: false, switching: false })
  await database.officialSubmissionIntents.clear(); posts = []; receipt = null
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      const body = JSON.parse(init.body as string) as OfficialIntent
      expect((await database.officialSubmissionIntents.get(body.intentId))?.body).toEqual(body)
      posts.push(body)
      receipt = { schemaVersion: 1, state: 'admitted', intentId: body.intentId, submissionId: 'unit-receipt', receivedAt: new Date().toISOString(), official: true, taskId: body.taskId, language: body.language, workspaceId: body.workspaceId, snapshotId: body.snapshotId, files: await Promise.all(body.files.map(async file => ({ filename: file.filename, sourceFilename: file.sourceFilename, fileId: file.fileId, sha256: await hashBytes(file.content), size: exactUTF8(file.content).length }))) }
      return new Response(JSON.stringify(receipt))
    }
    if (String(_url).includes('/status/')) return new Response(JSON.stringify({ status: { status: 5, status_text: 'Scored', public_score: 25, max_public_score: 25 } }))
    return new Response(JSON.stringify({ submissions: [], total: 0, nextOffset: null }))
  }))
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  await act(async () => root.render(<CMSWorkbench />))
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks(); await database.officialSubmissionIntents.clear() })
const button = (name: string) => [...host.querySelectorAll('button')].find(item => item.textContent === name)!
async function open() { await act(async () => { button('Submit').click(); await new Promise(resolve => setTimeout(resolve, 30)) }) }
it('offers a small problem/file form with a top-right green submit region and inferred language', async () => {
  expect(host.querySelector('.cms-submit-region')?.textContent).toBe('Submit')
  await open()
  const panel = host.querySelector('[role="dialog"][aria-label="Submit solution"]')!
  expect(panel.querySelector('[aria-label="Submission problem"]')).toBeTruthy()
  expect(panel.querySelector<HTMLSelectElement>('[aria-label="Submission file"]')?.value).toBe(seedFileIds.main)
  expect(panel.querySelector('[aria-label="Submission language"]')).toBeNull()
  for (const text of ['Capture source', 'SHA-256', 'Recording comparison', 'Submission intents', 'Move source between', 'toolchain mapping']) expect(panel.textContent).not.toContain(text)
  expect(host.querySelectorAll('a[target="_blank"]')).toHaveLength(0)
})
it('one click captures source before later edits, persists the immutable intent and sends it once', async () => {
  useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'captured source')
  await open()
  await act(async () => { button('Submit solution').click(); button('Submit solution').click(); useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'later source'); await new Promise(resolve => setTimeout(resolve, 80)) })
  expect(posts).toHaveLength(1); expect(posts[0]?.files[0]?.content).toBe('captured source'); expect(posts[0]?.language).toBe('CPP')
  expect((await database.officialSubmissionIntents.toArray())[0]?.state).toBe('admitted')
  expect(host.textContent).toContain('Submission received')
})
it('automatically selects the allowed Python language when a Python file is selected', async () => {
  await open()
  const select = host.querySelector<HTMLSelectElement>('[aria-label="Submission file"]')!
  await act(async () => { select.value = seedFileIds.solution; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(host.textContent).toContain('Python 3')
  await act(async () => { button('Submit solution').click(); await new Promise(resolve => setTimeout(resolve, 80)) })
  expect(posts[0]?.language).toBe('PY'); expect(posts[0]?.files[0]?.fileId).toBe(seedFileIds.solution)
})
it('does not show raw server diagnostics to participants', () => {
  expect(participantMessage(new CMSError(500, 'File /opt/private.py token=secret SQL failed'))).not.toMatch(/private|secret|SQL/)
  expect(participantMessage(new CMSError(429, 'debug details'))).toContain('wait')
  expect(sourceLanguage(context.tasks[0]!, 'solution.py', undefined)).toBe('PY')
})
