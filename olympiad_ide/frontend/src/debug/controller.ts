import { create } from 'zustand'
import { WorkspaceAPI } from '../persistence/api'
import { database, type WorkspaceDatabase } from '../persistence/database'
import { persistence } from '../persistence/controller'
import { cmsEnabled, appBase } from '../cms/session'
import { modelRegistry } from '../editor/modelRegistry'
import { useWorkspaceStore } from '../store/workspaceStore'
import { defaultConfiguration, captureSubmission } from '../execution/snapshot'
import { useExecutionResources } from '../execution/resources'
import { telemetry } from '../telemetry/collector'
import type { EditorGroupId } from '../types/workspace'

export interface DebugSession { id: string; status: string; files: { id: string; path: string }[]; sourceHash: string; error?: string | null }
export interface Frame { id: number; name: string; line: number; fileId?: string; path?: string }
export interface Variable { name: string; value: string; type?: string; variablesReference: number; scope?: string }
type Status = 'idle' | 'starting' | 'running' | 'stopped' | 'stopping' | 'finished' | 'failed'
interface BreakpointVerification { adapterId?: number; fileId: string; requestedLine: number; line: number; verified: boolean; message: string }
interface State { breakpointsBusy: boolean; breakpointNotice: string | null; navigation: { fileId: string; line: number; nonce: number; groupId: EditorGroupId } | null; verifiedBreakpoints: BreakpointVerification[]; session: DebugSession | null; status: Status; location: { fileId: string; line: number } | null; breakpoints: Record<string, number[]>; frames: Frame[]; variables: Variable[]; error: string | null; output: string; commandBusy: boolean; inspectionBusy: boolean }
const empty = (): State => ({ breakpointsBusy: false, breakpointNotice: null, navigation: null, verifiedBreakpoints: [], session: null, status: 'idle', location: null, breakpoints: {}, frames: [], variables: [], error: null, output: '', commandBusy: false, inspectionBusy: false })
export const useDebugStore = create<State>(() => empty())
const active = (status: string) => ['starting', 'running', 'stopped', 'stopping'].includes(status)
const cleanLines = (lines: number[]) => [...new Set(lines.filter(line => Number.isSafeInteger(line) && line > 0 && line <= 1000000))].sort((a, b) => a - b).slice(0, 100)
type DAP = Record<string, unknown>
interface Pending { command: string; resolve: (value: DAP) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }

export class DebugController {
  private socket: WebSocket | null = null
  private refresh?: ReturnType<typeof setInterval>
  private breakpointReady = false
  private capturedSources = new Map<string, string>()
  private appliedBreakpoints = new Map<string, string>()
  private breakpointUpdates: Promise<void> = Promise.resolve()
  private breakpointRevision = 0
  private seq = 0
  private threadId = 0
  private pending = new Map<number, Pending>()
  private scope = ''
  private generation = 0
  private stoppedGeneration = 0
  private inspection = 0
  private navigation = 0
  private finishedTelemetry = new Set<string>()
  private inspections = new Map<string, number>()
  private initialized = false
  private initializedWaiter?: { resolve: () => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }
  private load?: Promise<void>
  constructor(readonly db: WorkspaceDatabase = database, readonly api = new WorkspaceAPI(), readonly connect = (url: URL) => new WebSocket(url)) {}
  private key() { return `debug-breakpoints:${useWorkspaceStore.getState().workspace.id}` }
  private current(generation: number) { return generation === this.generation && this.scope === this.key() }
  private error(error: unknown) { useDebugStore.setState({ error: error instanceof Error ? error.message : String(error) }) }
  private inspecting(generation: number, stop: number): () => void {
    const key = `${generation}:${stop}`
    this.inspections.set(key, (this.inspections.get(key) ?? 0) + 1)
    useDebugStore.setState({ inspectionBusy: true })
    return () => {
      const count = Math.max(0, (this.inspections.get(key) ?? 1) - 1)
      if (count) this.inspections.set(key, count); else this.inspections.delete(key)
      if (this.current(generation) && this.stoppedGeneration === stop && useDebugStore.getState().status === 'stopped') useDebugStore.setState({ inspectionBusy: count > 0 })
    }
  }
  private closeTransport() {
    clearInterval(this.refresh)
    this.breakpointReady = false
    const socket = this.socket; this.socket = null
    if (socket) { socket.onopen = null; socket.onmessage = null; socket.onerror = null; socket.onclose = null; socket.close() }
    for (const value of this.pending.values()) { clearTimeout(value.timer); value.reject(new Error('Debug transport closed')) }
    this.pending.clear()
    if (this.initializedWaiter) { clearTimeout(this.initializedWaiter.timer); this.initializedWaiter.reject(new Error('Debug transport closed')); this.initializedWaiter = undefined }
  }
  retire() {
    ++this.generation; this.scope = ''; this.closeTransport(); this.load = undefined
    this.capturedSources.clear(); this.appliedBreakpoints.clear(); this.inspections.clear()
  }
  loadBreakpoints(): Promise<void> {
    const key = this.key()
    if (this.scope === key) return this.load ?? Promise.resolve()
    const priorState = useDebugStore.getState(), previous = priorState.session
    ++this.generation; this.closeTransport(); this.scope = key
    useDebugStore.setState(empty())
    // A delayed stop response from another workspace cannot reset the new workspace's UI.
    if (previous && (active(priorState.status) || priorState.status === 'failed')) void this.api.request(`/debug/sessions/${previous.id}/stop`, { method: 'POST' }).catch(() => undefined)
    this.load = this.db.metadata.get(key).then(row => {
      if (this.scope !== key) return
      const saved: unknown = JSON.parse(row?.value ?? '{}'), clean: Record<string, number[]> = {}
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) for (const [id, lines] of Object.entries(saved)) if (Array.isArray(lines)) clean[id] = cleanLines(lines)
      useDebugStore.setState({ breakpoints: clean })
    }).catch(error => { if (this.scope === key) this.error(error) })
    return this.load
  }
  private saveBreakpoints() {
    const key = this.key(), value = JSON.stringify(useDebugStore.getState().breakpoints)
    void this.db.metadata.put({ key, value }).catch(error => { if (this.scope === key) this.error(error) })
  }
  toggleBreakpoint(fileId: string, line: number) {
    if (useWorkspaceStore.getState().nodes[fileId]?.type !== 'file') return
    const points = useDebugStore.getState().breakpoints[fileId] ?? []
    this.relocateBreakpoints(fileId, points.includes(line) ? points.filter(value => value !== line) : [...points, line], points.includes(line) ? 'removed' : 'added')
  }
  relocateBreakpoints(fileId: string, lines: number[], operation: 'added' | 'removed' | 'relocated' = 'relocated') {
    if (useWorkspaceStore.getState().nodes[fileId]?.type !== 'file') return
    const clean = cleanLines(lines), state = useDebugStore.getState()
    if (JSON.stringify(clean) === JSON.stringify(state.breakpoints[fileId] ?? [])) return
    useDebugStore.setState({ breakpoints: { ...state.breakpoints, [fileId]: clean } }); this.saveBreakpoints()
    if (telemetry.session) telemetry.record('DEBUG_BREAKPOINT_CHANGED', fileId, { debugId: active(state.status) ? state.session?.id ?? null : null, operation, lines: clean })
    void this.updateBreakpoints(fileId)
  }
  private async applyBreakpoints(file: { id: string; path: string }, points: number[], generation: number) {
    const response = await this.send('setBreakpoints', { source: { path: '/box/' + file.path }, breakpoints: points.map(line => ({ line })) })
    if (!this.current(generation)) return
    const confirmations = (response.breakpoints ?? []) as { id?: number; line?: number; verified?: boolean; message?: string }[]
    this.appliedBreakpoints.set(file.id, JSON.stringify(points))
    useDebugStore.setState(state => ({ verifiedBreakpoints: [...state.verifiedBreakpoints.filter(point => point.fileId !== file.id), ...points.map((line, index) => ({ adapterId: confirmations[index]?.id, fileId: file.id, requestedLine: line, line: confirmations[index]?.line ?? line, verified: confirmations[index]?.verified === true, message: confirmations[index]?.message ?? (confirmations[index]?.verified ? '' : 'Adapter has not verified this breakpoint') }))] }))
  }
  private updateBreakpoints(fileId: string): Promise<void> {
    const state = useDebugStore.getState(), generation = this.generation
    if (!this.breakpointReady || !['running', 'stopped'].includes(state.status)) return Promise.resolve()
    const revision = ++this.breakpointRevision
    useDebugStore.setState({ breakpointsBusy: true })
    this.breakpointUpdates = this.breakpointUpdates.then(async () => {
      if (!this.current(generation) || !this.breakpointReady) return
      const current = useDebugStore.getState(), file = current.session?.files.find(file => file.id === fileId), node = useWorkspaceStore.getState().nodes[fileId]
      if (!file) { useDebugStore.setState({ breakpointNotice: 'Debug this file to use its breakpoints.' }); return }
      const source = node?.type === 'file' ? modelRegistry.get(fileId)?.getValue() ?? node.content : undefined
      if (source !== this.capturedSources.get(fileId)) { useDebugStore.setState({ breakpointNotice: 'This file changed after debugging started. Restart debugging to use its updated breakpoints.' }); return }
      const points = current.breakpoints[fileId] ?? []
      if (JSON.stringify(points) !== this.appliedBreakpoints.get(fileId)) await this.applyBreakpoints(file, points, generation)
      if (this.current(generation)) useDebugStore.setState({ breakpointNotice: null })
    }).catch(error => { if (this.current(generation)) this.error(error) }).finally(() => {
      if (this.current(generation) && this.breakpointRevision === revision) useDebugStore.setState({ breakpointsBusy: false })
    })
    return this.breakpointUpdates
  }
  goToBreakpoint(fileId: string, line: number) {
    const state = useWorkspaceStore.getState(), file = state.nodes[fileId]
    if (file?.type !== 'file' || !Number.isSafeInteger(line) || line < 1) { this.error(new Error('Breakpoint source is no longer available')); return }
    const count = (modelRegistry.get(fileId)?.getValue() ?? file.content).split(/\r\n|\r|\n/).length
    const target = Math.min(line, count)
    state.openFile(fileId)
    useDebugStore.setState({ navigation: { fileId, line: target, nonce: ++this.navigation, groupId: state.activeGroupId } })
  }
  acknowledgeNavigation(nonce: number) {
    if (useDebugStore.getState().navigation?.nonce === nonce) useDebugStore.setState({ navigation: null })
  }
  private finished(sessionId: string, reason: string) {
    if (this.finishedTelemetry.has(sessionId)) return
    this.finishedTelemetry.add(sessionId)
    if (telemetry.session) telemetry.record('DEBUG_FINISHED', null, { debugId: sessionId, reason: reason.slice(0, 200) })
  }
  private waitInitialized(): Promise<void> {
    if (this.initialized) return Promise.resolve()
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.initializedWaiter = undefined; reject(new Error('Adapter did not initialize')) }, 45000)
      this.initializedWaiter = { resolve, reject, timer }
    })
  }
  async start() {
    const intendedScope = this.key()
    await this.loadBreakpoints()
    if (this.key() !== intendedScope || this.scope !== intendedScope) return
    if (active(useDebugStore.getState().status)) return
    if (useDebugStore.getState().status === 'failed' && useDebugStore.getState().session) await this.stop()
    const generation = ++this.generation, workspace = useWorkspaceStore.getState().workspace.id
    this.closeTransport(); this.capturedSources.clear(); this.appliedBreakpoints.clear(); this.breakpointUpdates = Promise.resolve(); this.breakpointRevision = 0; this.seq = 0; this.threadId = 0; this.initialized = false
    useDebugStore.setState({ breakpointsBusy: false, breakpointNotice: null, navigation: null, verifiedBreakpoints: [], session: null, status: 'starting', error: null, location: null, frames: [], variables: [], output: '', commandBusy: false, inspectionBusy: false })
    let created: DebugSession | null = null
    try {
      const configuration = defaultConfiguration(), capturedBreakpoints = structuredClone(useDebugStore.getState().breakpoints)
      const submission = await captureSubmission(configuration, [{ kind: 'test', id: crypto.randomUUID(), name: 'Debug stdin', stdin: useExecutionResources.getState().stdin, expectedStdout: null }])
      this.capturedSources = new Map(submission.files.map(file => [file.id, file.content]))
      await persistence.checkpoint(); await persistence.flush(); await this.api.session()
      if (!this.current(generation) || workspace !== submission.workspaceId) return
      created = await this.api.request<DebugSession>('/debug/sessions', { method: 'POST', body: JSON.stringify({ submission }) })
      if (!this.current(generation)) { void this.api.request(`/debug/sessions/${created.id}/stop`, { method: 'POST' }).catch(() => undefined); return }
      const session = created; useDebugStore.setState({ session })
      const ticket = await this.api.request<{ token: string }>(`/debug/sessions/${session.id}/attach`, { method: 'POST' })
      if (!this.current(generation)) return
      const path = cmsEnabled ? `${appBase}api/debug/sessions/${session.id}/dap` : `/api/v1/debug/sessions/${session.id}/dap`
      const url = new URL(path, location.href); url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      const socket = this.connect(url); this.socket = socket
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Debug transport did not connect')), 10000)
        socket.onopen = () => socket.send(JSON.stringify({ attachToken: ticket.token }))
        socket.onmessage = event => {
          if (!this.current(generation)) return
          try {
            const message = JSON.parse(String(event.data)) as DAP
            if (message.type === 'transport' && message.status === 'attached') { clearTimeout(timer); resolve() }
            void this.receive(message, generation)
          } catch { clearTimeout(timer); reject(new Error('Invalid debugger protocol message')); this.error(new Error('Invalid debugger protocol message')); socket.close() }
        }
        socket.onerror = () => { clearTimeout(timer); reject(new Error('Debug WebSocket unavailable')) }
        socket.onclose = () => {
          clearTimeout(timer); reject(new Error('Debug transport disconnected'))
          if (!this.current(generation)) return
          this.closeTransport()
          if (active(useDebugStore.getState().status)) useDebugStore.setState({ status: 'failed', commandBusy: false, error: 'Debug transport closed. Stop the old session or start again after checking CMS authentication.', location: null, frames: [], variables: [] })
        }
      })
      if (!this.current(generation)) return
      this.refresh = setInterval(() => {
        void this.api.request<{ token: string }>(`/debug/sessions/${session.id}/attach`, { method: 'POST' }).then(value => { if (this.current(generation) && socket.readyState === 1) socket.send(JSON.stringify({ attachToken: value.token })) }).catch(error => { if (this.current(generation)) { this.error(error); socket.close() } })
      }, 20000)
      await this.send('initialize')
      const initialized = this.waitInitialized()
      // debugpy's launch response arrives only after configurationDone. Do not deadlock waiting for it.
      const launched = this.send('launch'); void launched.catch(() => undefined)
      await Promise.race([initialized, launched.then(() => initialized)])
      for (const file of session.files) {
        const points = capturedBreakpoints[file.id] ?? []
        await this.applyBreakpoints(file, points, generation)
        if (!this.current(generation)) return
      }
      if (this.current(generation) && telemetry.session) telemetry.record('DEBUG_STARTED', null, { debugId: session.id })
      await this.send('configurationDone'); await launched
      if (this.current(generation) && useDebugStore.getState().status === 'starting') useDebugStore.setState({ status: 'running' })
      if (this.current(generation)) { this.breakpointReady = true; for (const file of session.files) await this.updateBreakpoints(file.id) }
    } catch (error) {
      if (!this.current(generation)) return
      this.error(error); this.closeTransport(); useDebugStore.setState({ status: 'failed', commandBusy: false, inspectionBusy: false, breakpointsBusy: false, location: null })
      if (created) void this.api.request(`/debug/sessions/${created.id}/stop`, { method: 'POST' }).catch(() => undefined)
    }
  }
  private send(command: string, args: DAP = {}): Promise<DAP> {
    if (this.socket?.readyState !== 1) return Promise.reject(new Error('Debug session is not connected'))
    const seq = ++this.seq
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(seq); reject(new Error(`Debugger timed out: ${command}`)) }, 45000)
      this.pending.set(seq, { command, resolve, reject, timer }); this.socket!.send(JSON.stringify({ seq, type: 'request', command, arguments: args }))
    })
  }
  private async receive(message: DAP, generation: number) {
    if (!this.current(generation)) return
    if (message.type === 'response') {
      const seq = Number(message.request_seq), pending = this.pending.get(seq)
      if (pending) {
        clearTimeout(pending.timer); this.pending.delete(seq)
        if (message.command !== pending.command) pending.reject(new Error('Debugger response command mismatch'))
        else if (message.success === true) pending.resolve((message.body ?? {}) as DAP)
        else pending.reject(new Error(String(message.message ?? 'Debugger request failed')))
      }
      return
    }
    if (message.type === 'transport') {
      const session = message.session as DebugSession | undefined
      if (session && session.id === useDebugStore.getState().session?.id) {
        useDebugStore.setState({ session })
        if (['FAILED', 'EXPIRED', 'STOPPED', 'FINISHED'].includes(session.status)) {
          this.finished(session.id, session.status.toLowerCase())
          useDebugStore.setState({ status: ['FAILED', 'EXPIRED'].includes(session.status) ? 'failed' : 'finished', commandBusy: false, inspectionBusy: false, breakpointsBusy: false, location: null, frames: [], variables: [], ...(session.error ? { error: session.error } : {}) }); this.closeTransport()
        }
      }
      return
    }
    if (message.type !== 'event') return
    const body = (message.body ?? {}) as DAP
    if (message.event === 'initialized') { this.initialized = true; if (this.initializedWaiter) { clearTimeout(this.initializedWaiter.timer); this.initializedWaiter.resolve(); this.initializedWaiter = undefined } }
    if (message.event === 'breakpoint') {
      const point = body.breakpoint as { id?: number; verified?: boolean; line?: number; message?: string; source?: { path?: string } } | undefined
      if (point) useDebugStore.setState(state => ({ verifiedBreakpoints: state.verifiedBreakpoints.map(previous => {
        const sameId = Number.isSafeInteger(point.id) && previous.adapterId === point.id
        const capturedPath = state.session?.files.find(file => file.id === previous.fileId)?.path
        const sameSourceLine = !!capturedPath && point.source?.path === '/box/' + capturedPath && (point.line === previous.line || point.line === previous.requestedLine)
        if (!sameId && !sameSourceLine) return previous
        const verified = body.reason === 'removed' ? false : typeof point.verified === 'boolean' ? point.verified : previous.verified
        return { ...previous, adapterId: point.id ?? previous.adapterId, verified, line: Number.isSafeInteger(point.line) && point.line! > 0 ? point.line! : previous.line, message: point.message ?? (verified ? '' : previous.message) }
      }) }))
    }
    if (message.event === 'output') useDebugStore.setState(state => ({ output: (state.output + String(body.output ?? '')).slice(-262144) }))
    if (message.event === 'continued') useDebugStore.setState({ status: 'running', inspectionBusy: false, breakpointsBusy: false, location: null, frames: [], variables: [] })
    if (message.event === 'terminated' || message.event === 'exited') { const id = useDebugStore.getState().session?.id; if (id) this.finished(id, String(message.event)); useDebugStore.setState({ status: 'finished', commandBusy: false, inspectionBusy: false, breakpointsBusy: false, location: null, frames: [], variables: [] }); return }
    if (message.event === 'stopped') {
      const stop = ++this.stoppedGeneration; this.threadId = Number(body.threadId)
      useDebugStore.setState({ status: 'stopped', commandBusy: false, inspectionBusy: true, error: null, location: null, frames: [], variables: [] })
      const release = this.inspecting(generation, stop)
      try {
        if (!Number.isSafeInteger(this.threadId) || this.threadId <= 0) {
          const threads = await this.send('threads'), list = (threads.threads ?? []) as { id: number }[]
          if (!this.current(generation) || stop !== this.stoppedGeneration || useDebugStore.getState().status !== 'stopped') return
          this.threadId = list[0]?.id ?? 0
          if (!Number.isSafeInteger(this.threadId) || this.threadId <= 0) throw new Error('The paused adapter did not report an inspectable thread')
        }
        const response = await this.send('stackTrace', { threadId: this.threadId })
        if (!this.current(generation) || stop !== this.stoppedGeneration || useDebugStore.getState().status !== 'stopped') return
        const frames = (response.stackFrames ?? []) as { id: number; name: string; line: number; source?: { path?: string } }[]
        const files = useDebugStore.getState().session?.files ?? []
        useDebugStore.setState({ frames: frames.map(frame => ({ id: frame.id, name: frame.name, line: frame.line, path: frame.source?.path, fileId: files.find(file => '/box/' + file.path === frame.source?.path || file.path === frame.source?.path)?.id })) })
        if (frames[0]) await this.selectFrame(frames[0].id, true)
      } catch (error) { if (this.current(generation) && stop === this.stoppedGeneration) this.error(error) }
      finally { release() }
    }
  }
  async command(command: 'continue' | 'pause' | 'next' | 'stepIn' | 'stepOut') {
    const state = useDebugStore.getState(), generation = this.generation, stop = this.stoppedGeneration
    if (state.commandBusy || state.inspectionBusy || (command === 'pause' ? state.status !== 'running' : state.status !== 'stopped')) return
    useDebugStore.setState({ commandBusy: true, error: null })
    try {
      if (command === 'pause' && (!Number.isSafeInteger(this.threadId) || this.threadId <= 0)) {
        const response = await this.send('threads')
        if (!this.current(generation) || stop !== this.stoppedGeneration || useDebugStore.getState().status !== 'running') return
        const threads = (response.threads ?? []) as { id: number }[]
        const thread = threads.find(value => Number.isSafeInteger(value.id) && value.id > 0)
        if (!thread) throw new Error('The running adapter did not report a thread that can be paused')
        this.threadId = thread.id
      }
      await this.send(command, { threadId: this.threadId })
      if (this.current(generation) && command !== 'pause' && stop === this.stoppedGeneration) useDebugStore.setState({ status: 'running', location: null, frames: [], variables: [] })
      if (this.current(generation) && telemetry.session && state.session) telemetry.record('DEBUG_ACTION', null, { debugId: state.session.id, action: command === 'continue' ? 'continue' : command === 'pause' ? 'pause' : 'step' })
    } catch (error) { if (this.current(generation)) this.error(error) }
    finally { if (this.current(generation)) useDebugStore.setState({ commandBusy: false }) }
  }
  async selectFrame(id: number, automatic = false) {
    const generation = this.generation, stop = this.stoppedGeneration
    if (useDebugStore.getState().status !== 'stopped' || (!automatic && (useDebugStore.getState().inspectionBusy || useDebugStore.getState().commandBusy))) return
    const inspection = ++this.inspection
    const release = this.inspecting(generation, stop)
    useDebugStore.setState({ variables: [] })
    try {
      const frame = useDebugStore.getState().frames.find(value => value.id === id)
      if (frame?.fileId) { useDebugStore.setState({ location: { fileId: frame.fileId, line: frame.line } }); if (useWorkspaceStore.getState().nodes[frame.fileId]?.type === 'file') useWorkspaceStore.getState().openFile(frame.fileId) }
      const response = await this.send('scopes', { frameId: id })
      if (!this.current(generation) || stop !== this.stoppedGeneration || inspection !== this.inspection || useDebugStore.getState().status !== 'stopped') return
      const scopes = (response.scopes ?? []) as { name?: string; variablesReference: number; presentationHint?: string }[]
      const variables: Variable[] = []
      // GDB separates function Arguments from Locals; reading only the first scope hides real local results.
      // Register banks are not participant variables and can contain very large platform-specific dumps.
      for (const scope of scopes.filter(value => !/register/i.test(value.name ?? '') && value.presentationHint !== 'registers')) {
        if (!Number.isSafeInteger(scope.variablesReference) || scope.variablesReference <= 0) continue
        const result = await this.send('variables', { variablesReference: scope.variablesReference })
        if (!this.current(generation) || stop !== this.stoppedGeneration || inspection !== this.inspection || useDebugStore.getState().status !== 'stopped') return
        variables.push(...((result.variables ?? []) as Variable[]).map(variable => ({ ...variable, scope: scope.name })))
      }
      useDebugStore.setState({ variables })
    } catch (error) { if (this.current(generation) && stop === this.stoppedGeneration) this.error(error) }
    finally { release() }
  }
  async expandVariable(reference: number, automatic = false) {
    const generation = this.generation, stop = this.stoppedGeneration
    if (useDebugStore.getState().status !== 'stopped' || (!automatic && (useDebugStore.getState().inspectionBusy || useDebugStore.getState().commandBusy))) return
    const inspection = ++this.inspection
    const release = this.inspecting(generation, stop)
    useDebugStore.setState({ variables: [] })
    try {
      const response = await this.send('variables', { variablesReference: reference })
      if (this.current(generation) && stop === this.stoppedGeneration && inspection === this.inspection && useDebugStore.getState().status === 'stopped') useDebugStore.setState({ variables: (response.variables ?? []) as Variable[] })
    } catch (error) { if (this.current(generation) && stop === this.stoppedGeneration) this.error(error) }
    finally { release() }
  }
  async stop() {
    const current = useDebugStore.getState()
    if (current.status === 'stopping') return
    const session = current.session, generation = ++this.generation
    this.closeTransport()
    useDebugStore.setState({ status: session ? 'stopping' : 'idle', error: null, commandBusy: false, inspectionBusy: false, breakpointsBusy: false, location: null, frames: [], variables: [] })
    if (!session) return
    try {
      let result = await this.api.request<DebugSession>(`/debug/sessions/${session.id}/stop`, { method: 'POST', keepalive: true })
      const deadline = Date.now() + 15000
      while (this.current(generation) && !['FINISHED', 'STOPPED', 'FAILED', 'EXPIRED'].includes(result.status)) {
        if (Date.now() >= deadline) throw new Error('The worker has not confirmed a terminal session state')
        await new Promise(resolve => setTimeout(resolve, 200))
        if (!this.current(generation)) return
        result = await this.api.request<DebugSession>(`/debug/sessions/${session.id}`)
      }
      if (!this.current(generation)) return
      useDebugStore.setState({ session: result, status: ['FAILED', 'EXPIRED'].includes(result.status) ? 'failed' : 'finished', error: result.error ?? null })
      this.finished(session.id, result.status.toLowerCase())
    } catch (error) {
      if (this.current(generation)) useDebugStore.setState({ status: 'failed', error: `Stop is unconfirmed: ${error instanceof Error ? error.message : String(error)}. Check CMS authentication and retry Stop; no worker termination is assumed.` })
    }
  }
}
export let debugging = new DebugController()
/** Rebind only after old task execution has reached an owned terminal state. */
export function assertDebugStopped() {
  const current = useDebugStore.getState()
  if (active(current.status) || (current.status === 'failed' && current.session && !['FINISHED', 'STOPPED', 'FAILED', 'EXPIRED'].includes(current.session.status))) throw new Error('Stop the current debugger before switching problems.')
}
export async function resetDebugController(db: WorkspaceDatabase = database) {
  assertDebugStopped()
  debugging.retire()
  debugging = new DebugController(db)
  await debugging.loadBreakpoints()
}
