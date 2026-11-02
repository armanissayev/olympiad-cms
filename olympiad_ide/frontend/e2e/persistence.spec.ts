import { test, expect, type Page } from '@playwright/test'

async function editorText(page: Page, index = 0) {
  const value = await page.locator('.view-lines').nth(index).innerText()
  return value.replaceAll('\u00a0', ' ')
}

async function replaceEditor(page: Page, text: string, index = 0) {
  const editor = page.getByRole('textbox', { name: 'Editor content', exact: true }).nth(index)
  await editor.focus()
  await editor.press('ControlOrMeta+a')
  await editor.press('Backspace')
  await editor.pressSequentially(text)
}

async function synced(page: Page) {
  await expect(page.getByRole('button', { name: 'Synchronization: Synced', exact: true }).first()).toBeVisible({ timeout: 20_000 })
}

test('files, split state, exact text, offline queue and reconnect survive reload', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await synced(page)
  page.once('dialog', (dialog) => dialog.accept('extra.py'))
  await page.getByRole('button', { name: 'New File', exact: true }).click()
  await replaceEditor(page, 'print("Unicode Ω")')
  await synced(page)
  await page.getByRole('button', { name: 'Split Editor', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Editor content' })).toHaveCount(2)
  await replaceEditor(page, 'print("shared")', 1)
  await expect.poll(() => editorText(page, 0)).toContain('print("shared")')
  await synced(page)
  await page.reload()
  await expect(page.getByRole('textbox', { name: 'Editor content' })).toHaveCount(2)
  await expect.poll(() => editorText(page, 1)).toContain('print("shared")')
  await page.route('**/api/**', (route) => route.abort('failed'))
  await replaceEditor(page, 'offline_recovered = 42', 1)
  await expect(page.getByRole('button', { name: 'Synchronization: Offline', exact: true }).first()).toBeVisible({ timeout: 15_000 })
  await page.reload()
  await expect.poll(() => editorText(page, 1)).toContain('offline_recovered = 42')
  await page.unroute('**/api/**')
  await page.getByRole('button', { name: 'Synchronization: Offline', exact: true }).first().click()
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await synced(page)
  const workspaces = await (await page.request.get('/api/v1/workspaces')).json() as { document: { nodes: Record<string, { name: string; content: string }> } }[]
  expect(Object.values(workspaces[0]!.document.nodes).find((node) => node.name === 'extra.py')?.content).toBe('offline_recovered = 42')
  expect(errors).toEqual([])
})

test('two browser tabs preserve concurrent work and can save a recovered copy', async ({ context, page }) => {
  await page.goto('/')
  await synced(page)
  const second = await context.newPage()
  await second.goto('/')
  await synced(second)
  await page.route('**/api/**', (route) => route.abort('failed'))
  await second.route('**/api/**', (route) => route.abort('failed'))
  await replaceEditor(page, '// branch A')
  await expect(page.getByRole('button', { name: 'Synchronization: Offline', exact: true }).first()).toBeVisible({ timeout: 15_000 })
  await replaceEditor(second, '// branch B')
  await expect(second.getByRole('button', { name: 'Synchronization: Conflict', exact: true }).first()).toBeVisible()
  await second.reload()
  await expect.poll(() => editorText(second)).toContain('// branch B')
  await second.unroute('**/api/**')
  await second.getByRole('button', { name: 'Review', exact: true }).click()
  await expect(second.getByRole('dialog', { name: 'Resolve workspace conflict' })).toBeVisible()
  await expect(second.locator('.monaco-diff-editor')).toBeVisible()
  await second.getByRole('button', { name: 'Save local as recovered copy', exact: true }).click()
  await synced(second)
  const workspaces = await (await second.request.get('/api/v1/workspaces')).json() as { document: { nodes: Record<string, { type: string; content: string }> } }[]
  const contents = Object.values(workspaces[0]!.document.nodes).filter((node) => node.type === 'file').map((node) => node.content)
  expect(contents).toContain('// branch A')
  expect(contents).toContain('// branch B')
})

test('server conflict compares both branches and requires an explicit resolution', async ({ page }) => {
  await page.goto('/')
  await synced(page)
  const workspace = (await (await page.request.get('/api/v1/workspaces')).json() as {
    id: string; revision: number; document: { nodes: Record<string, { type: string; content?: string }> }
  }[])[0]!
  const fileId = Object.keys(workspace.document.nodes).find((id) => workspace.document.nodes[id]?.type === 'file')!
  await page.route('**/api/**', (route) => route.abort('failed'))
  await replaceEditor(page, '// local conflict')
  workspace.document.nodes[fileId]!.content = '// server conflict'
  const response = await page.request.post('/api/v1/sync/batches', { data: { operations: [{
    operationId: crypto.randomUUID(), workspaceId: workspace.id,
    baseRevision: workspace.revision, document: workspace.document,
  }] } })
  expect(response.status()).toBe(200)
  await page.unroute('**/api/**')
  await expect(page.getByRole('button', { name: 'Synchronization: Conflict', exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Review', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Resolve workspace conflict' })).toBeVisible()
  await page.getByRole('button', { name: 'Keep local version', exact: true }).click()
  await synced(page)
  await page.reload()
  await expect.poll(() => editorText(page)).toContain('// local conflict')
})

test('reload after server commit but before acknowledgement safely replays the operation', async ({ page }) => {
  await page.goto('/')
  await synced(page)
  let markCommitted: () => void = () => undefined
  const committed = new Promise<void>((resolve) => { markCommitted = resolve })
  let releaseResponse: () => void = () => undefined
  const release = new Promise<void>((resolve) => { releaseResponse = resolve })
  let first = true
  await page.route('**/api/v1/sync/batches', async (route) => {
    if (!first) { await route.continue(); return }
    first = false
    const response = await route.fetch()
    expect(response.status()).toBe(200)
    markCommitted()
    await release
    await route.fulfill({ response }).catch(() => undefined)
  })
  await replaceEditor(page, '// committed before acknowledgement')
  await committed
  await page.reload()
  releaseResponse()
  await synced(page)
  await expect.poll(() => editorText(page)).toContain('// committed before acknowledgement')
})

test('storage failure is visible and current work remains exportable', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(indexedDB, 'open', { value: () => { throw new DOMException('Storage blocked', 'QuotaExceededError') } })
  })
  await page.goto('/')
  await expect(page.getByRole('alert').filter({ hasText: 'Save Error' })).toBeVisible()
  await replaceEditor(page, '// preserve my unsaved work')
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export work', exact: true }).click()
  const exportFile = await downloaded
  expect(exportFile.suggestedFilename()).toContain('olympiad-recovery-')
})

test('tab changes and split reload preserve independent cursor positions', async ({ page }) => {
  await page.goto('/')
  await synced(page)
  const editor = page.getByRole('textbox', { name: 'Editor content', exact: true })
  await editor.press('ControlOrMeta+Home')
  await editor.press('ArrowRight')
  await editor.press('ArrowRight')
  await editor.press('ArrowRight')
  await expect(page.getByText('Ln 1, Col 4', { exact: true })).toBeVisible()
  await page.getByRole('tab', { name: /^solution.py / }).click()
  await page.getByRole('tab', { name: /^main.cpp / }).click()
  await expect(page.getByText('Ln 1, Col 4', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Split Editor', exact: true }).click()
  const editors = page.getByRole('textbox', { name: 'Editor content', exact: true })
  await editors.nth(1).press('ControlOrMeta+Home')
  await editors.nth(1).press('ArrowRight')
  await synced(page)
  await page.reload()
  await editors.first().focus()
  await expect(page.getByText('Ln 1, Col 4', { exact: true })).toBeVisible()
  await editors.nth(1).focus()
  await expect(page.getByText('Ln 1, Col 2', { exact: true })).toBeVisible()
})

test('production app shell can reload with the entire connection offline', async ({ context, page }) => {
  test.skip(!process.env.E2E_PRODUCTION, 'Offline shell is only installed by a production build')
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('requestfailed', (request) => errors.push(`${request.url()}: ${request.failure()?.errorText}`))
  await page.goto('/')
  await synced(page)
  await page.evaluate(async () => { await navigator.serviceWorker.ready })
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true)
  await replaceEditor(page, '// fully offline recovery')
  await synced(page)
  await context.setOffline(true)
  await page.reload()
  try {
    await expect.poll(async () => (await page.locator('.view-lines').allTextContents()).join(' ').replaceAll('\u00a0', ' '), { timeout: 10_000 }).toContain('// fully offline recovery')
  } catch (error) {
    console.log('Offline errors:', errors, 'Document:', await page.content())
    throw error
  }
  await context.setOffline(false)
})
