import type { Job, JobEvent } from './types'

/** Keep exact program output separate from compiler/stderr text; never interpret terminal controls. */
export function runOutput(job: Job | null, events: JobEvent[], clearAfter = 0) {
  const visible = events.filter(event => event.sequence > clearAfter && event.eventType === 'OUTPUT')
  const streamed = visible.filter(event => event.stream === 'stdout').map(event => event.text ?? '').join('')
  const stdout = clearAfter > 0 ? streamed : job?.result?.cases.map(result => result.stdout).join('') ?? streamed
  const errors = visible.filter(event => event.stream !== 'stdout').map(event => event.text ?? '').join('')
  const resultDiagnostics = job?.result ? [job.result.compilationOutput, ...job.result.cases.map(result => result.stderr), job.result.error].filter(Boolean).join('\n') : ''
  return { stdout, diagnostics: clearAfter > 0 ? errors : resultDiagnostics || errors }
}
