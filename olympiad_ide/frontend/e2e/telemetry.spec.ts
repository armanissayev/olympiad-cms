import { test, expect, type Page } from '@playwright/test'
import { replay, verifyCheckpoint } from '../src/telemetry/replayEngine'
import type { Checkpoint, TelemetryEvent, TelemetrySession } from '../src/telemetry/types'

test.setTimeout(90_000)
async function localJournal(page: Page) {
  return page.evaluate(async () => {
    const opened = indexedDB.open('olympiad-ide')
    const db = await new Promise<IDBDatabase>((resolve, reject) => { opened.onsuccess = () => resolve(opened.result); opened.onerror = () => reject(opened.error) })
    const read = <T>(name: string) => new Promise<T[]>((resolve, reject) => {
      const request = db.transaction(name).objectStore(name).getAll()
      request.onsuccess = () => resolve(request.result as T[]); request.onerror = () => reject(request.error)
    })
    const id = sessionStorage.getItem('olympiad-telemetry-session')
    const sessions = await read<TelemetrySession>('telemetrySessions')
    const events = (await read<TelemetryEvent>('telemetryEvents')).filter(e => e.sessionId === id).sort((a, b) => a.sequence - b.sequence)
    const checkpoints = (await read<Checkpoint>('telemetryCheckpoints')).filter(c => c.sessionId === id)
    db.close()
    return { session: sessions.find(s => s.id === id)!, events, checkpoints }
  })
}
const editor = (page: Page, pane = 0) => page.getByRole('textbox', { name: 'Editor content', exact: true }).nth(pane)
async function telemetrySynced(page: Page) {
  await expect(page.getByRole('button', { name: 'Telemetry: Synced', exact: true })).toBeVisible({ timeout: 45_000 })
}

test('real Monaco keys, Unicode, repeat, paste, multi-cursor, replacement, undo, tabs and shared split replay exactly', async ({ page, context }) => {
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto('/')
  await expect(page.getByText(/Editor recording enabled/)).toBeVisible()
  await editor(page).focus()
  await editor(page).press('ControlOrMeta+a')
  await editor(page).press('Backspace')
  await editor(page).pressSequentially('hello hello')
  await page.keyboard.insertText('😀你好')
  await page.keyboard.down('x'); await page.keyboard.down('x'); await page.keyboard.up('x')
  await editor(page).press('ArrowLeft')
  await editor(page).press('Delete')
  await editor(page).press('Shift+ArrowLeft')
  await editor(page).press('Backspace')
  // Monaco's explicit composition observations are recorded; synthetic events do not emulate a real OS IME.
  await editor(page).evaluate(element => { element.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true })); element.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '' })) })
  await page.getByRole('button', { name: 'Split Editor', exact: true }).click()
  await editor(page, 1).focus()
  await editor(page, 1).press('End')
  await editor(page, 1).pressSequentially(' split')
  await page.getByRole('tab', { name: /^solution.py / }).first().click()
  await page.getByRole('tab', { name: /^main.cpp / }).first().click()
  await editor(page).focus()
  await editor(page).press('ControlOrMeta+z')
  await editor(page).press('ControlOrMeta+Shift+z')
  // Two matches selected by Monaco's built-in action form one multi-cursor model transaction.
  await editor(page).press('ControlOrMeta+a')
  await page.keyboard.insertText('hello hello')
  await editor(page).press('ControlOrMeta+Home')
  await editor(page).press('ArrowRight')
  await editor(page).press('ControlOrMeta+d')
  await editor(page).press('ControlOrMeta+d')
  await page.keyboard.insertText('world')
  await editor(page).press('Escape')
  // Find widget input itself is excluded from key telemetry; Replace All still changes the authoritative model.
  const isMac = await page.evaluate(() => navigator.platform.includes('Mac'))
  await editor(page).press(isMac ? 'Alt+Meta+f' : 'Control+h')
  await page.getByRole('textbox', { name: 'Find', exact: true }).fill('world')
  await page.getByRole('textbox', { name: 'Replace', exact: true }).fill('replaced')
  await page.getByRole('button', { name: /^Replace All/ }).click()
  await page.getByRole('button', { name: /^Close \(Escape\)/ }).click()
  await editor(page).focus()
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])
  const pasted = '\n' + 'large_paste😀Ω\n'.repeat(25_000)
  await page.evaluate(text => navigator.clipboard.writeText(text), pasted)
  await editor(page).press('ControlOrMeta+v')
  await expect.poll(async () => (await localJournal(page)).events.some(e => e.eventType === 'PASTE')).toBe(true)
  await telemetrySynced(page)
  const journal = await localJournal(page)
  const types = journal.events.map(e => e.eventType)
  for (const type of ['KEY_DOWN', 'KEY_UP', 'TEXT_INSERT', 'TEXT_DELETE', 'UNDO', 'REDO', 'PASTE', 'CURSOR_MOVED', 'SELECTION_CHANGED', 'SPLIT_CHANGED', 'TAB_SWITCHED', 'COMPOSITION_START', 'COMPOSITION_END']) expect(types).toContain(type)
  expect(journal.events.some(e => e.eventType === 'KEY_DOWN' && e.payload.repeat)).toBe(true)
  expect(journal.events.some(e => 'changes' in e.payload && e.payload.changes.length > 1)).toBe(true)
  const paste = journal.events.find(e => e.eventType === 'PASTE')!
  expect(paste.eventType === 'PASTE' && paste.payload.transactionId).toBeTruthy()
  const reconstructed = replay(journal.session.initial.nodes, journal.events)
  for (const checkpoint of journal.checkpoints) await verifyCheckpoint(replay(journal.session.initial.nodes, journal.events, checkpoint.sequence), checkpoint)
  const documents = journal.events.filter(e => 'changes' in e.payload)
  expect(new Set(documents.map(e => 'transactionId' in e.payload ? e.payload.transactionId : '')).size).toBe(documents.length)
  const state = await (await page.request.get(`/api/v1/telemetry/sessions/${journal.session.id}/status`)).json() as { integrity: string; lastSequence: number }
  expect(state.integrity).toBe('Complete')
  expect(state.lastSequence).toBe(journal.session.lastSequence)
  const files = Object.values(reconstructed).filter(n => n.type === 'file')
  expect(files.some(n => n.content?.includes(pasted.trim()))).toBe(true)
  expect(errors).toEqual([])
})

test('offline reload and a lost server acknowledgement retry immutable telemetry without duplicates', async ({ page }) => {
  await page.goto('/')
  await telemetrySynced(page)
  await page.route('**/api/v1/telemetry/**', route => route.abort('failed'))
  await editor(page).focus()
  await editor(page).pressSequentially('// offline recording')
  await expect.poll(async () => (await localJournal(page)).events.filter(e => e.eventType === 'KEY_DOWN').length).toBeGreaterThan(5)
  const previous = await localJournal(page)
  await page.reload()
  await expect(editor(page)).toBeVisible()
  const next = await localJournal(page)
  expect(next.session.id).not.toBe(previous.session.id)
  await page.unroute('**/api/v1/telemetry/**')
  await telemetrySynced(page)
  const prior = await (await page.request.get(`/api/v1/telemetry/sessions/${previous.session.id}/status`)).json() as { lastSequence: number; integrity: string }
  expect(prior.lastSequence).toBeGreaterThanOrEqual(previous.session.lastSequence)
  expect(prior.integrity).toBe('Recording Interrupted')
  let lost = false
  await page.route('**/api/v1/telemetry/batches', async route => {
    if (!lost) { lost = true; const response = await route.fetch(); expect(response.status()).toBe(200); await route.abort('failed') }
    else await route.continue()
  })
  await editor(page).focus(); await editor(page).pressSequentially('after reload')
  await expect.poll(() => lost, { timeout: 20_000 }).toBe(true)
  await telemetrySynced(page)
  const current = await localJournal(page)
  const result = await (await page.request.get(`/api/v1/telemetry/sessions/${current.session.id}/events?pageSize=500`)).json() as { events: TelemetryEvent[] }
  expect(new Set(result.events.map(e => e.eventId)).size).toBe(result.events.length)
  expect(result.events.length).toBe(current.session.lastSequence)
})

test('telemetry storage failure is visible and unrelated form typing is excluded', async ({ page }) => {
  await page.addInitScript(() => {
    const original = IDBObjectStore.prototype.add
    IDBObjectStore.prototype.add = function (...args) {
      if (this.name === 'telemetryEvents') throw new DOMException('Telemetry quota reached', 'QuotaExceededError')
      return original.apply(this, args)
    }
  })
  await page.goto('/')
  await expect(editor(page)).toBeVisible()
  await page.evaluate(() => { const input = document.createElement('input'); input.id = 'unrelated-form'; document.body.append(input) })
  await page.locator('#unrelated-form').fill('UNRELATED_PASSWORD')
  await editor(page).focus(); await editor(page).pressSequentially('// retained in memory')
  await expect(page.getByRole('alert').filter({ hasText: 'Recording Error' })).toBeVisible()
  await page.getByRole('button', { name: 'Telemetry: Recording Error', exact: true }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export recording', exact: true }).click()
  const result = await download
  const fs = await import('node:fs/promises')
  const archive = await fs.readFile((await result.path())!, 'utf8')
  expect(archive).not.toContain('UNRELATED_PASSWORD')
  expect(archive).toContain('KEY_DOWN')
  expect(JSON.parse(archive).interrupted).toBe(true)
})
