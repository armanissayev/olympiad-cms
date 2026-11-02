import { create } from 'zustand'
import { cmsEnabled, currentTask } from '../cms/session'
import { database, type WorkspaceDatabase } from '../persistence/database'
import { WorkspaceAPI } from '../persistence/api'
import { useWorkspaceStore } from '../store/workspaceStore'
import { telemetry } from '../telemetry/collector'
import { captureSubmission, defaultConfiguration } from './snapshot'
import { executionResources, useExecutionResources } from './resources'
import { terminalStatuses, type CaseResult, type Job, type JobEvent, type RunConfiguration, type TestCase } from './types'

interface ExecutionState { job: Job | null; history: Job[]; events: JobEvent[]; partialResults: CaseResult[]; error: string | null; submitting: boolean; workers: number; transport: string; clearAfter: number }
export const useExecution = create<ExecutionState>(() => ({ job: null, history: [], events: [], partialResults: [], error: null, submitting: false, workers: 0, transport: 'Polling', clearAfter: 0 }))
export class ExecutionController {
  constructor(readonly db: WorkspaceDatabase = database) {}
  private api = new WorkspaceAPI()
  private timer?: ReturnType<typeof setInterval>
  private stream: EventSource | null = null
  private observing = false
  private eventsTail: Promise<void> = Promise.resolve()
  private requestTail: Promise<void> = Promise.resolve()
  private correlationTail: Promise<void> = Promise.resolve()
  async start() {
    await executionResources.start()
    await this.refresh(true)
    this.timer = setInterval(() => { void this.refresh(); void this.retryPending() }, 2000)
  }
  stop() { clearInterval(this.timer); this.stream?.close(); executionResources.stop() }
  error(error: unknown) { useExecution.setState({ error: error instanceof Error ? error.message : String(error) }) }
  configuration(): RunConfiguration {
    const state = useExecutionResources.getState()
    const selected = state.items.find(r => r.id === state.activeConfigurationId && !r.deleted)?.value
    if (selected?.kind === 'configuration') return structuredClone(selected)
    const created = defaultConfiguration()
    void executionResources.save(created).catch(error => executionResources.error(error))
    executionResources.select({ activeConfigurationId: created.id })
    return created
  }
  async run(testId?: string, all = false, fixedStdin = false) {
    if (useExecution.getState().submitting) return
    useExecution.setState({ submitting: true, error: null })
    try {
      if (cmsEnabled && !currentTask()?.customRunSupported) throw new Error(currentTask()?.customRunReason ?? 'Custom Run is unavailable for this CMS task')
      if (cmsEnabled && useExecution.getState().workers === 0) throw new Error('No approved IDE worker is available. Official CMS submission remains available.')
      if (!navigator.onLine) throw new Error('Run requires an online backend and a verified Linux worker')
      const configuration = this.configuration(), state = useExecutionResources.getState()
      const saved = state.items.filter(r => !r.deleted && r.value.kind === 'test').map(r => r.value as TestCase)
      const selected = saved.find(t => t.id === (testId ?? configuration.defaultTestId ?? state.selectedTestId))
      const tests = all ? saved : !fixedStdin && selected ? [selected] : [{ kind: 'test' as const, id: crypto.randomUUID(), name: 'Standard Run', stdin: state.stdin, expectedStdout: null }]
      if (!tests.length) throw new Error('Create a test case before Run All')
      const submission = await captureSubmission(configuration, tests)
      // Capture is finished before any network operation. A later edit cannot alter this payload.
      await this.db.executionSubmissions.add({ ...submission, acknowledged: false })
      void telemetry.checkpoint('execution-snapshot').catch(() => undefined)
      await this.retryPending()
      useWorkspaceStore.getState().setBottomPanelVisible(true)
      useWorkspaceStore.getState().setBottomPanelView(all || testId ? 'tests' : 'terminal')
    } catch (error) { this.error(error) }
    finally { useExecution.setState({ submitting: false }) }
  }
  retryPending(): Promise<void> {
    this.requestTail = this.requestTail.catch(() => undefined).then(async () => {
      try {
        await this.api.session()
        const pending = await this.db.executionSubmissions.where('workspaceId').equals(useWorkspaceStore.getState().workspace.id).filter(s => !s.acknowledged).toArray()
        for (const stored of pending) {
          const submission = { id: stored.id, workspaceId: stored.workspaceId, configuration: stored.configuration, files: stored.files, sourceHash: stored.sourceHash, tests: stored.tests }
          const job = await this.api.request<Job>('/executions', { method: 'POST', body: JSON.stringify(submission) })
          await this.db.executionSubmissions.update(job.id, { acknowledged: true })
          await this.attach(job, false)
        }
      } catch (error) { this.error(error) }
    })
    return this.requestTail
  }
  async refresh(recovering = false) {
    if (this.observing) return
    this.observing = true
    try {
      await this.api.session()
      const capacity = await this.api.request<{ workers: number }>('/execution-capacity')
      useExecution.setState({ workers: capacity.workers })
      const id = useWorkspaceStore.getState().workspace.id
      const history = await this.api.request<Job[]>(`/workspaces/${id}/executions`)
      useExecution.setState({ history, error: null })
      const selected = useExecution.getState().job
      const current = history.find(j => j.id === selected?.id) ?? history.find(j => !terminalStatuses.has(j.status)) ?? history[0]
      if (current) await this.attach(current, recovering)
    } catch (error) { this.error(error) }
    finally { this.observing = false }
  }
  private async correlation(job: Job, recovering: boolean) {
    const key = `execution-observed:${job.id}`
    const previous = await this.db.metadata.get(key)
    const flags = previous ? JSON.parse(previous.value) as { started: boolean; finished: boolean } : { started: false, finished: false }
    const started = !!job.startedAt, finished = terminalStatuses.has(job.status)
    const execution = { jobId: job.id, snapshotId: job.snapshotId, sourceHash: job.sourceHash, configurationId: job.configuration.id, language: job.configuration.language, status: job.status, serverTimestamp: job.completedAt ?? job.startedAt ?? job.createdAt }
    if (!recovering && telemetry.session) {
      if (started && !flags.started) telemetry.record('RUN_STARTED', null, { runId: job.id, language: job.configuration.language, execution: { ...execution, serverTimestamp: job.startedAt! } })
      if (started && finished && !flags.finished) telemetry.record('RUN_FINISHED', null, { runId: job.id, exitCode: job.result?.cases.at(-1)?.exitCode ?? null, durationMs: Math.max(0, Date.parse(job.completedAt!) - Date.parse(job.startedAt!)), execution })
    }
    await this.db.metadata.put({ key, value: JSON.stringify({ started: flags.started || started, finished: flags.finished || finished }) })
  }
  async attach(job: Job, recovering: boolean) {
    const previous = useExecution.getState().job
    if (previous?.id !== job.id) {
      this.stream?.close(); this.stream = null
      const events = await this.db.executionEvents.where('jobId').equals(job.id).sortBy('sequence')
      useExecution.setState({ job, events, partialResults: events.flatMap(e => e.case ? [e.case] : []), clearAfter: 0 })
    } else useExecution.setState({ job })
    // Telemetry storage failure must not block execution/results.
    this.correlationTail = this.correlationTail.catch(() => undefined).then(() => this.correlation(job, recovering)).catch(error => telemetry.fail(error))
    await this.pollEvents(job.id)
    if (!cmsEnabled && !terminalStatuses.has(job.status) && !this.stream && typeof EventSource !== 'undefined') {
      const after = useExecution.getState().events.at(-1)?.sequence ?? 0
      const source = new EventSource(`/api/v1/executions/${job.id}/events?stream=true&after=${after}`)
      this.stream = source
      source.onopen = () => useExecution.setState({ transport: 'SSE + polling recovery' })
      source.onmessage = message => {
        try { void this.acceptEvents(job.id, [JSON.parse(message.data) as JobEvent]) }
        catch { source.close(); if (this.stream === source) this.stream = null; useExecution.setState({ transport: 'Malformed stream; polling recovery' }) }
      }
      source.onerror = () => { source.close(); if (this.stream === source) this.stream = null; useExecution.setState({ transport: 'Polling fallback' }) }
    }
    if (terminalStatuses.has(job.status)) { this.stream?.close(); this.stream = null }
  }
  private async pollEvents(id: string) {
    for (let page = 0; page < 8; page++) {
      const after = useExecution.getState().events.at(-1)?.sequence ?? 0
      const result = await this.api.request<{ events: JobEvent[] }>(`/executions/${id}/events?after=${after}`)
      await this.acceptEvents(id, result.events)
      if (result.events.length < 200) break
    }
  }
  acceptEvents(jobId: string, incoming: JobEvent[]): Promise<void> {
    this.eventsTail = this.eventsTail.catch(() => undefined).then(async () => {
      if (useExecution.getState().job?.id !== jobId) return
      const state = useExecution.getState(), seen = state.events.at(-1)?.sequence ?? 0
      const added = incoming.filter(e => e.sequence > seen).sort((a, b) => a.sequence - b.sequence)
      if (!added.length) return
      if (added.some((e, i) => e.sequence !== seen + i + 1)) { useExecution.setState({ transport: 'Gap detected; polling recovery' }); return }
      await this.db.executionEvents.bulkPut(added.map(e => ({ ...e, jobId })))
      useExecution.setState({ events: [...state.events, ...added], partialResults: [...state.partialResults, ...added.flatMap(e => e.case ? [e.case] : [])] })
    }).catch(error => this.error(error))
    return this.eventsTail
  }
  async cancel() {
    const job = useExecution.getState().job
    if (!job || terminalStatuses.has(job.status)) return
    try { await this.attach(await this.api.request<Job>(`/executions/${job.id}/cancel`, { method: 'POST' }), false) } catch (error) { this.error(error) }
  }
}
export const executions = new ExecutionController()
