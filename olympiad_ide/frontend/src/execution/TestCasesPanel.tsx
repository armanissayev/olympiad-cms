import { executions, useExecution } from './controller'
import { executionResources, useExecutionResources } from './resources'
import type { TestCase } from './types'

export function TestCasesPanel() {
  const resources = useExecutionResources(), execution = useExecution()
  const tests = resources.items.filter(r => !r.deleted && r.value.kind === 'test')
  const chosen = tests.find(r => r.id === resources.selectedTestId) ?? tests[0]
  const value = chosen?.value.kind === 'test' ? chosen.value : undefined
  const save = (patch: Partial<TestCase>) => { if (value) void executionResources.save({ ...value, ...patch }).catch(() => undefined) }
  const create = (copy = false) => {
    const test: TestCase = { kind: 'test', id: crypto.randomUUID(), name: copy && value ? `${value.name} copy` : `Test ${tests.length + 1}`, stdin: copy && value ? value.stdin : '', expectedStdout: copy && value ? value.expectedStdout : null }
    void executionResources.save(test).catch(() => undefined); executionResources.select({ selectedTestId: test.id })
  }
  const results = execution.job?.result?.cases.length ? execution.job.result.cases : execution.partialResults
  return <div className="test-cases-panel">
    <div className="test-list"><div className="flex gap-1"><button className="tool-button" onClick={() => create()}>New Test</button><button className="tool-button" onClick={() => void executions.run(undefined, true)} disabled={!tests.length || execution.submitting}>Run All</button></div>{tests.map(r => <button className={`test-select ${r.id === chosen?.id ? 'selected' : ''}`} key={r.id} onClick={() => executionResources.select({ selectedTestId: r.id })}>{r.value.name}</button>)}</div>
    <div className="test-details">
      {value ? <>
        <div className="flex gap-2"><input aria-label="Test name" value={value.name} onChange={e => save({ name: e.target.value })} /><button className="tool-button" onClick={() => void executions.run(value.id)}>Run test</button><button className="tool-button" onClick={() => create(true)}>Duplicate test</button><button className="tool-button" onClick={() => void executionResources.save(value, true).catch(() => undefined)}>Delete test</button></div>
        <div className="test-buffers"><label>stdin<textarea aria-label="Test stdin" value={value.stdin} onChange={e => save({ stdin: e.target.value })} /></label><label><span><input type="checkbox" checked={value.expectedStdout !== null} onChange={e => save({ expectedStdout: e.target.checked ? '' : null })} /> Compare expected stdout</span><textarea aria-label="Expected stdout" disabled={value.expectedStdout === null} value={value.expectedStdout ?? ''} onChange={e => save({ expectedStdout: e.target.value })} /></label></div>
      </> : <p>Create a saved test. Empty expected output is different from no expected output.</p>}
      <p>{execution.job?.status ?? 'No execution'} · {results.length}/{execution.job?.tests.length ?? 0} results · CRLF→LF normalization only; whitespace is significant. “Accepted” means a custom expectation matched, not official judging.</p>
      {resources.error && <p role="alert">{resources.error} · Resolve resource conflicts in Run and Debug; local changes remain exportable.</p>}
      {results.map(result => <details key={result.testId} className="test-result"><summary>{result.name} · {result.status} · {result.verdict} · {result.wallTime === null ? 'time unavailable' : `${result.wallTime}s`} · {result.peakMemoryKiB === null ? 'memory unavailable' : `${result.peakMemoryKiB} KiB`}</summary><div className="test-buffers"><label>Actual output<pre>{result.stdout || '(empty)'}</pre></label><label>Expected<pre>{result.expectedStdout ?? '(not compared)'}</pre></label><label>stderr<pre>{result.stderr || '(empty)'}</pre></label></div></details>)}
      {execution.job?.tests.filter(t => !results.some(r => r.testId === t.id)).map(t => <div className="test-result" key={t.id}>{t.name} · {execution.job?.status} · no result received; output/time/memory unavailable</div>)}
    </div>
  </div>
}
