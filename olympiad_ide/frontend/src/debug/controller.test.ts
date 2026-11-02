import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { WorkspaceDatabase } from '../persistence/database'
import { WorkspaceAPI } from '../persistence/api'
import { initialData, seedFileIds, useWorkspaceStore } from '../store/workspaceStore'
import { DebugController, useDebugStore } from './controller'

vi.mock('../persistence/controller', () => ({ persistence: { checkpoint: vi.fn(async () => undefined), flush: vi.fn(async () => undefined) } }))
interface Message { seq?: number; type?: string; command?: string; arguments?: Record<string, unknown>; attachToken?: string }
class Socket {
  readyState = 1
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  messages: Message[] = []
  launch?: Message
  constructor() { setTimeout(() => this.onopen?.(), 0) }
  emit(message: unknown) { this.onmessage?.({ data: JSON.stringify(message) }) }
  respond(request: Message, body: unknown = {}) { this.emit({ type: 'response', command: request.command, request_seq: request.seq, success: true, body }) }
  send(raw: string) {
    const message = JSON.parse(raw) as Message; this.messages.push(message)
    queueMicrotask(() => {
      if (message.attachToken) { this.emit({ type: 'transport', status: 'attached' }); return }
      if (message.command === 'launch') { this.launch = message; this.emit({ type: 'event', event: 'initialized' }); return }
      if (message.command === 'configurationDone') { this.respond(message); this.respond(this.launch!); return }
      if (message.command === 'stackTrace') { this.respond(message, { stackFrames: [{ id: 42, name: 'solve', line: 7, source: { path: '/box/src/main.cpp' } }] }); return }
      if (message.command === 'scopes') { this.respond(message, { scopes: [{ name: 'Locals', variablesReference: 101 }] }); return }
      if (message.command === 'variables') { this.respond(message, { variables: [{ name: 'value', value: '7', type: 'int', variablesReference: 0 }] }); return }
      if (message.command === 'next') { this.emit({ type: 'event', event: 'stopped', body: { threadId: 1, reason: 'step' } }); this.respond(message); return }
      this.respond(message)
    })
  }
  close() { if (this.readyState === 3) return; this.readyState = 3; this.onclose?.() }
}
let db: WorkspaceDatabase, controller: DebugController, socket: Socket, url: URL
let createBody: Record<string, unknown>, attachCount: number
let delayedStop: (() => void) | undefined
let failAttach = false
const request = vi.fn(async (path: string, init?: RequestInit) => {
  if (path === '/debug/sessions') {
    createBody = JSON.parse(String(init?.body)); const submission = createBody.submission as { id: string; files: { id: string; path: string }[]; sourceHash: string }
    return { id: submission.id, files: submission.files, sourceHash: submission.sourceHash, status: 'QUEUED' }
  }
  if (path.endsWith('/attach')) { if (failAttach) throw new Error('CMS authorization expired'); return { token: `one-use-${++attachCount}`, expiresIn: 30 } }
  if (path.endsWith('/stop') && delayedStop) await new Promise<void>(resolve => { delayedStop = resolve })
  return {}
})
beforeEach(async () => {
  useWorkspaceStore.setState(initialData())
  useDebugStore.setState({ session: null, status: 'idle', location: null, breakpoints: {}, frames: [], variables: [], error: null, output: '', commandBusy: false })
  request.mockClear(); attachCount = 0; delayedStop = undefined; failAttach = false
  db = new WorkspaceDatabase(`debug-controller-${crypto.randomUUID()}`)
  const api = { session: async () => ({ identityId: 'owned' }), request } as unknown as WorkspaceAPI
  controller = new DebugController(db, api, target => { url = target; socket = new Socket(); return socket as unknown as WebSocket })
  await controller.loadBreakpoints()
})
afterEach(async () => { delayedStop = undefined; await controller.stop(); vi.useRealTimers(); await db.delete() })
async function paused() { socket.emit({ type: 'event', event: 'stopped', body: { threadId: 1, reason: 'breakpoint' } }); await vi.waitFor(() => expect(useDebugStore.getState().variables[0]?.value).toBe('7')) }

it('waits for initialized/configurationDone without deadlocking a deferred debugpy launch and sends immutable breakpoints', async () => {
  controller.toggleBreakpoint(seedFileIds.main, 7)
  await controller.start()
  expect(useDebugStore.getState().status).toBe('running')
  expect(socket.messages.map(message => message.command).filter(Boolean)).toEqual(['initialize', 'launch', 'setBreakpoints', 'configurationDone'])
  expect(socket.messages.find(message => message.command === 'setBreakpoints')?.arguments).toEqual({ source: { path: '/box/src/main.cpp' }, breakpoints: [{ line: 7 }] })
  const captured = JSON.stringify(createBody)
  useWorkspaceStore.getState().setFileContent(seedFileIds.main, '// edited after capture')
  controller.toggleBreakpoint(seedFileIds.main, 8)
  expect(JSON.stringify(createBody)).toBe(captured)
  expect(socket.messages.filter(message => message.command === 'setBreakpoints')).toHaveLength(1)
  expect(url.search).toBe(''); expect(url.pathname).toMatch(/^\/api\/v1\/debug\/sessions\/[^/]+\/dap$/)
})
it('renders only actual DAP frames/variables and keeps a newer stopped event after step response', async () => {
  await controller.start(); expect(useDebugStore.getState().frames).toEqual([]); expect(useDebugStore.getState().variables).toEqual([])
  await paused()
  expect(useDebugStore.getState().location).toEqual({ fileId: seedFileIds.main, line: 7 })
  expect(useDebugStore.getState().frames[0]?.name).toBe('solve')
  await controller.command('next')
  await vi.waitFor(() => expect(useDebugStore.getState().status).toBe('stopped'))
  expect(socket.messages.some(message => message.command === 'evaluate')).toBe(false)
})
it('refreshes one-use authorization and closes on expired CMS authorization without reusing the old token', async () => {
  await controller.start(); vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  // Restart captures the authorization interval under the fake clock.
  await controller.stop(); await controller.start()
  const before = attachCount
  await vi.advanceTimersByTimeAsync(20000)
  expect(attachCount).toBe(before + 1)
  expect(socket.messages.at(-1)?.attachToken).toBe(`one-use-${attachCount}`)
  failAttach = true; await vi.advanceTimersByTimeAsync(20000)
  expect(socket.readyState).toBe(3); expect(useDebugStore.getState().status).toBe('failed')
})
it('does not let a late old-workspace stop response reset new workspace breakpoints/status', async () => {
  await controller.start(); delayedStop = () => undefined
  const stopping = controller.stop()
  useWorkspaceStore.setState(state => ({ workspace: { ...state.workspace, id: crypto.randomUUID() } }))
  await controller.loadBreakpoints(); controller.toggleBreakpoint(seedFileIds.main, 11)
  delayedStop?.(); await stopping
  expect(useDebugStore.getState().status).toBe('idle')
  expect(useDebugStore.getState().breakpoints[seedFileIds.main]).toEqual([11])
})
it('retains only scoped bounded breakpoint lines across reload and does not expose arbitrary adapter commands', async () => {
  await db.metadata.put({ key: `debug-breakpoints:${useWorkspaceStore.getState().workspace.id}`, value: JSON.stringify({ [seedFileIds.main]: [4, 4, -2, 1000001, 6] }) })
  const next = new DebugController(db)
  await next.loadBreakpoints()
  expect(useDebugStore.getState().breakpoints[seedFileIds.main]).toEqual([4, 6])
  controller.relocateBreakpoints(seedFileIds.main, [10, 5, 5, 1000001])
  expect(useDebugStore.getState().breakpoints[seedFileIds.main]).toEqual([5, 10])
  expect('evaluate' in controller).toBe(false)
})
