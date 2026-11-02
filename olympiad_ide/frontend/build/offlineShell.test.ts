import { expect, it } from 'vitest'
import { runInNewContext } from 'node:vm'
import type { OutputBundle } from 'rollup'
import { offlineShell } from './offlineShell'

it('scopes production shell recovery to /ide/ and never intercepts CMS or runtime requests', () => {
  const plugin = offlineShell(); let source = ''
  const resolved = plugin.configResolved as (config: { base: string }) => void
  resolved({ base: '/ide/' })
  const generate = plugin.generateBundle as (this: unknown, options: unknown, bundle: OutputBundle) => void
  generate.call({ emitFile: (file: { source: string }) => { source = file.source } }, {}, { 'assets/editor.js': {} } as OutputBundle)
  const listeners: Record<string, (event: unknown) => void> = {}
  runInNewContext(source, { URL, self: { location: { origin: 'https://contest.example' }, addEventListener: (name: string, fn: (event: unknown) => void) => { listeners[name] = fn } } })
  for (const path of ['/login', '/admin', '/ranking', '/ide/api/context', '/ide/api/submissions', '/ide/api/runtime/v1/workspaces', '/ide/unknown', '/ide/assets/editor.js?secret=x']) {
    let intercepted = false
    listeners.fetch!({ request: { method: 'GET', url: `https://contest.example${path}`, mode: 'navigate' }, respondWith: () => { intercepted = true } })
    expect(intercepted, path).toBe(false)
  }
  expect(source).toContain('"/ide/index.html"'); expect(source).toContain('"/ide/assets/editor.js"')
})
