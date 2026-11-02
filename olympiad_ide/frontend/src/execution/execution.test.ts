import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import Dexie from 'dexie'
import { WorkspaceDatabase } from '../persistence/database'
import { RequestError, WorkspaceAPI } from '../persistence/api'
import type { ServerWorkspace } from '../persistence/types'
import { initialData, seedFileIds, useWorkspaceStore } from '../store/workspaceStore'
import { ResourceController, useExecutionResources } from './resources'
import { ExecutionController, useExecution } from './controller'
import { captureSubmission, defaultConfiguration } from './snapshot'
import { digest } from '../telemetry/replayEngine'
import type { Job, RemoteResource, TestCase } from './types'
import { telemetry } from '../telemetry/collector'
import type { TelemetrySession } from '../telemetry/types'

let db: WorkspaceDatabase, resources: ResourceController
const testCase = (): TestCase => ({ kind: 'test', id: crypto.randomUUID(), name: 'Test', stdin: '2 3\n', expectedStdout: '5\n' })
beforeEach(() => {
  useWorkspaceStore.setState(initialData())
  useExecutionResources.setState({ items: [], activeConfigurationId: null, selectedTestId: null, stdin: '', error: null, pending: 0 })
  useExecution.setState({ job: null, events: [], partialResults: [], history: [], error: null })
  db = new WorkspaceDatabase(`execution-test-${crypto.randomUUID()}`)
  resources = new ResourceController(db)
})
afterEach(async () => { resources.stop(); vi.restoreAllMocks(); await db.delete() })

describe('immutable source and explicit configuration', () => {
  it('captures unsynchronized text before async hashing and never changes the snapshot afterward', async () => {
    const config = defaultConfiguration(), tests = [testCase()]
    useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'exact at click 😀\n')
    const pending = captureSubmission(config, tests)
    useWorkspaceStore.getState().setFileContent(seedFileIds.main, 'edited after click')
    config.name = 'changed'; tests[0]!.stdin = 'changed'
    const snapshot = await pending
    expect(snapshot.files[0]?.content).toBe('exact at click 😀\n')
    expect(snapshot.tests[0]?.stdin).toBe('2 3\n')
    expect(snapshot.configuration.name).not.toBe('changed')
    expect(snapshot.sourceHash).toBe(await digest({ files: snapshot.files, configuration: snapshot.configuration }))
  })
  it('does not compile unrelated C++ solutions and supports explicit multi-file manifests', async () => {
    const other = useWorkspaceStore.getState().createFile(null, 'other.cpp', 'int main(){}')
    useWorkspaceStore.getState().openFile(seedFileIds.main)
    const config = defaultConfiguration()
    expect(config.includedFiles).toEqual([seedFileIds.main])
    config.includedFiles.push(other)
    expect((await captureSubmission(config, [testCase()])).files).toHaveLength(2)
  })
  it('resolves the active file each time and never saves or reuses an old run configuration', async () => {
    const controller = new ExecutionController(db)
    const old = defaultConfiguration()
    useExecutionResources.setState({ items: [{ id: old.id, workspaceId: useWorkspaceStore.getState().workspace.id, revision: 1, localVersion: 1, value: old, deleted: false }], activeConfigurationId: old.id })
    const other = useWorkspaceStore.getState().createFile(null, 'new-solution.cpp', 'int main(){return 7;}')
    useWorkspaceStore.getState().openFile(other)
    const active = controller.configuration()
    expect(active.entryPoint).toBe(other)
    expect(active.includedFiles).toEqual([other])
    useWorkspaceStore.getState().openFile(seedFileIds.solution)
    expect(controller.configuration().entryPoint).toBe(seedFileIds.solution)
    expect(await db.runConfigurations.count()).toBe(0)
    expect(useExecutionResources.getState().items).toHaveLength(1) // Existing data retained, no automatic run-list additions.
    controller.stop()
  })
  it('Python captures only the active source file and deleted entry identities fail explicitly', async () => {
    useWorkspaceStore.getState().createFile(null, 'helper.py', 'x=1')
    useWorkspaceStore.getState().openFile(seedFileIds.solution)
    const config = defaultConfiguration()
    expect(config.language).toBe('python3'); expect(config.includedFiles).toEqual([seedFileIds.solution])
    useWorkspaceStore.getState().deleteNode(config.entryPoint)
    await expect(captureSubmission(config, [testCase()])).rejects.toThrow('deleted')
  })
})

describe('resource persistence and conflict journal', () => {
  it('creates, edits, duplicates, deletes, reloads and preserves exact expected whitespace', async () => {
    const value = testCase(); value.expectedStdout = '5 \n'
    await resources.save(value)
    const duplicate = { ...value, id: crypto.randomUUID(), name: 'Copy' }
    await resources.save(duplicate)
    await resources.save({ ...value, name: 'Renamed', stdin: '' })
    await resources.save(duplicate, true)
    db.close(); await db.open(); await new ResourceController(db).load()
    const items = useExecutionResources.getState().items
    expect(items.find(r => r.id === value.id)?.value).toMatchObject({ name: 'Renamed', stdin: '', expectedStdout: '5 \n' })
    expect(items.find(r => r.id === duplicate.id)?.deleted).toBe(true)
    expect(await db.executionResourceOperations.count()).toBe(2) // Only never-sent pending edits compact.
  })
  it('persists and switches configurations, active selection and fixed stdin independently of workspace sync', async () => {
    const config = defaultConfiguration(); await resources.save(config)
    executionSelection(config.id)
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(JSON.parse((await db.metadata.get(`execution-ui:${useWorkspaceStore.getState().workspace.id}`))!.value)).toMatchObject({ activeConfigurationId: config.id, stdin: 'a\nb\n' })
    expect(await db.syncOperations.count()).toBe(0)
    function executionSelection(id: string) { resources.select({ activeConfigurationId: id, selectedTestId: null, stdin: 'a\nb\n' }) }
  })
  it('keeps offline local and remote conflict versions and resolves only on explicit choice', async () => {
    const value = testCase(); await resources.save(value)
    const remote: RemoteResource = { id: value.id, workspaceId: useWorkspaceStore.getState().workspace.id, revision: 2, value: { ...value, stdin: 'remote' }, deleted: false }
    vi.spyOn(resources.api, 'session').mockResolvedValue({ identityId: 'owner' })
    const request = vi.spyOn(resources.api, 'request').mockRejectedValue(new RequestError(409, 'conflict', remote as unknown as ServerWorkspace))
    await resources.sync()
    expect(useExecutionResources.getState().items[0]?.value).toMatchObject({ stdin: '2 3\n' })
    expect(useExecutionResources.getState().items[0]?.conflict?.value).toMatchObject({ stdin: 'remote' })
    request.mockRejectedValue(new Error('Offline'))
    await resources.resolve(value.id, 'local')
    const queued = await db.executionResourceOperations.toArray()
    expect(queued[0]?.baseRevision).toBe(2)
    expect(await db.metadata.where('key').startsWith('execution-conflict:').count()).toBe(1)
  })
  it('quota failures leave the optimistic local resource available for export instead of replacing it on reload', async () => {
    vi.spyOn(db.testCases, 'put').mockRejectedValue(new DOMException('Quota', 'QuotaExceededError'))
    const value = testCase()
    await expect(resources.save(value)).rejects.toThrow('Quota')
    await resources.load()
    expect(useExecutionResources.getState().items[0]?.value).toEqual(value)
    expect(useExecutionResources.getState().error).toContain('Quota')
  })
  it('an already-sending operation is immutable and later edits append behind it', async () => {
    const value = testCase(); await resources.save(value)
    const first = (await db.executionResourceOperations.toArray())[0]!
    await db.executionResourceOperations.update(first.sequence!, { status: 'sending' })
    await resources.save({ ...value, stdin: 'later' })
    const operations = await db.executionResourceOperations.orderBy('sequence').toArray()
    expect(operations[0]?.value).toEqual(value)
    expect(operations[1]?.baseRevision).toBe(1)
    expect(operations[1]?.value).toMatchObject({ stdin: 'later' })
  })
  it('migrates the existing Phase 2/3 testCases store without dropping saved input', async () => {
    await db.delete()
    const old = new Dexie(db.name)
    old.version(3).stores({ testCases: 'id, workspaceId' })
    const value = testCase(), workspaceId = useWorkspaceStore.getState().workspace.id
    await old.table('testCases').put({ id: value.id, workspaceId, name: 'Legacy', stdin: 'old\n', expectedStdout: '' })
    old.close(); await db.open()
    expect((await db.testCases.get(value.id))?.value).toMatchObject({ name: 'Legacy', stdin: 'old\n', expectedStdout: '', kind: 'test' })
  })
})

describe('durable output resume', () => {
  it.each([false, true])('correlates real-shaped observed lifecycle once, without replaying historical telemetry on reload (recovering=%s)', async recovering => {
    // A frontend observer contract fixture, not a claimed executed program or sandbox certification.
    const previous = telemetry.session
    telemetry.session = { id: crypto.randomUUID() } as TelemetrySession
    const record = vi.spyOn(telemetry, 'record').mockReturnValue(null)
    vi.spyOn(WorkspaceAPI.prototype, 'request').mockResolvedValue({ events: [] })
    const controller = new ExecutionController(db)
    const job: Job = { id: crypto.randomUUID(), workspaceId: useWorkspaceStore.getState().workspace.id, snapshotId: crypto.randomUUID(), sourceHash: 'a'.repeat(64), sourceManifest: [], configuration: defaultConfiguration(), status: 'FINISHED', createdAt: '2026-10-20T00:00:00Z', startedAt: '2026-10-20T00:00:01Z', completedAt: '2026-10-20T00:00:03Z', cancelRequested: false, lastSequence: 0, result: null, tests: [] }
    try {
      await controller.attach(job, recovering)
      await vi.waitFor(async () => expect(await db.metadata.get(`execution-observed:${job.id}`)).toBeTruthy())
      await controller.attach(job, false)
      await new Promise(resolve => setTimeout(resolve, 10))
      expect(record).toHaveBeenCalledTimes(recovering ? 0 : 2)
      if (!recovering) expect(record).toHaveBeenCalledWith('RUN_STARTED', null, expect.objectContaining({ execution: expect.objectContaining({ snapshotId: job.snapshotId, sourceHash: job.sourceHash, jobId: job.id }) }))
    } finally { telemetry.session = previous; controller.stop() }
  })
  it('deduplicates repeated stream messages, detects gaps, and recovers without invented output', async () => {
    const controller = new ExecutionController(db)
    const job = { id: crypto.randomUUID() } as Job
    useExecution.setState({ job })
    const first = { sequence: 1, timestamp: new Date().toISOString(), eventType: 'STATUS' as const, status: 'QUEUED' as const }
    const output = { sequence: 2, timestamp: new Date().toISOString(), eventType: 'OUTPUT' as const, stream: 'stdout' as const, text: 'control-plane fixture' }
    await controller.acceptEvents(job.id, [first]); await controller.acceptEvents(job.id, [first, output])
    expect(useExecution.getState().events).toHaveLength(2)
    await controller.acceptEvents(job.id, [{ ...output, sequence: 4 }])
    expect(useExecution.getState().events).toHaveLength(2)
    expect(useExecution.getState().transport).toContain('Gap')
    await controller.acceptEvents(job.id, [{ ...output, sequence: 3 }, { ...output, sequence: 4 }])
    expect(await db.executionEvents.where('jobId').equals(job.id).count()).toBe(4)
  })
})
