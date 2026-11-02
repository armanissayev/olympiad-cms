import { describe, expect, it } from 'vitest'
import { runOutput } from './output'
import type { Job, JobEvent } from './types'

describe('plain stdout file rendering', () => {
  const events: JobEvent[] = [
    { sequence: 1, timestamp: '', eventType: 'OUTPUT', stream: 'compiler', text: 'warning\n' },
    { sequence: 2, timestamp: '', eventType: 'OUTPUT', stream: 'stdout', text: '5 \n' },
    { sequence: 3, timestamp: '', eventType: 'OUTPUT', stream: 'stderr', text: 'own error\n' },
  ]
  it('keeps exact stdout whitespace and separates compiler/stderr messages', () => {
    expect(runOutput(null, events)).toEqual({ stdout: '5 \n', diagnostics: 'warning\nown error\n' })
  })
  it('uses durable final output once rather than duplicating streamed output', () => {
    const job = { result: { cases: [{ stdout: '5 \n', stderr: 'own error' }], compilationOutput: 'warning', error: null } } as Job
    expect(runOutput(job, events)).toEqual({ stdout: '5 \n', diagnostics: 'warning\nown error' })
  })
  it('clears historical final output and shows only subsequent stream data', () => {
    const job = { result: { cases: [{ stdout: 'old' }], compilationOutput: '', error: null } } as Job
    expect(runOutput(job, events, 2)).toEqual({ stdout: '', diagnostics: 'own error\n' })
  })
})
