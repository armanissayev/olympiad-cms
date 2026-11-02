import { test, expect } from '@playwright/test'
import type { Job, Submission } from '../src/execution/types'

test.setTimeout(60_000)
test('configuration, exact live source, stdin, durable queued job, reload and real cancellation', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Synchronization: Synced', exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Run and Debug', exact: true }).click()
  await page.getByRole('button', { name: 'New Configuration', exact: true }).click()
  await page.getByRole('textbox', { name: 'Configuration name', exact: true }).fill('Live C++20')
  const editor = page.getByRole('textbox', { name: 'Editor content', exact: true })
  await editor.press('ControlOrMeta+a')
  await page.keyboard.insertText('#include <iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n')
  await page.getByRole('textbox', { name: 'Standard input', exact: true }).fill('2 3\n')
  const submitted = page.waitForResponse(r => r.url().endsWith('/api/v1/executions') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const response = await submitted
  expect(response.status()).toBe(201)
  const request = response.request().postDataJSON() as Submission
  expect(request.files).toHaveLength(1)
  expect(request.files[0]?.content).toContain('std::cout<<a+b')
  expect(request.tests[0]?.stdin).toBe('2 3\n')
  const job = await response.json() as Job
  await expect(page.locator('.xterm')).toBeVisible()
  if (!process.env.REAL_LINUX_WORKER) {
    expect(job.status).toBe('QUEUED')
    await expect(page.getByText(/No verified Linux worker connected/)).toBeVisible()
    expect(job.result).toBeNull()
  }
  await page.reload()
  await expect(page.getByRole('combobox', { name: 'Run configuration selector', exact: true })).toHaveValue(request.configuration.id)
  await expect(page.locator('.execution-summary').first()).toContainText(job.configuration.name)
  await page.getByRole('button', { name: 'Stop execution', exact: true }).click()
  await expect.poll(async () => (await (await page.request.get(`/api/v1/executions/${job.id}`)).json() as Job).status).toBe('CANCELLED')
})

test('saved test CRUD, duplication, exact expectations and Run All share one source snapshot', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Synchronization: Synced', exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Test Cases', exact: true }).click()
  await page.getByRole('button', { name: 'New Test', exact: true }).click()
  await page.getByRole('textbox', { name: 'Test name', exact: true }).fill('Whitespace matters')
  await page.getByRole('textbox', { name: 'Test stdin', exact: true }).fill('2 3\n')
  await page.getByRole('checkbox', { name: 'Compare expected stdout' }).check()
  await page.getByRole('textbox', { name: 'Expected stdout', exact: true }).fill('5 \n')
  await page.getByRole('button', { name: 'Duplicate test', exact: true }).click()
  await page.getByRole('textbox', { name: 'Test name', exact: true }).fill('Second test')
  await page.getByRole('textbox', { name: 'Expected stdout', exact: true }).fill('5\n')
  await page.reload()
  await expect(page.getByRole('button', { name: 'Whitespace matters', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Second test', exact: true })).toBeVisible()
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/executions') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Run All', exact: true }).click()
  const submitted = await response
  expect(submitted.status()).toBe(201)
  const job = await submitted.json() as Job
  expect(job.tests).toHaveLength(2)
  expect(job.tests.map(t => t.expectedStdout)).toContain('5 \n')
  expect(job.snapshotId).toBeTruthy()
  await page.getByRole('button', { name: 'Stop execution', exact: true }).click()
  await page.getByRole('button', { name: 'Delete test', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Second test', exact: true })).toHaveCount(0)
})

test('lost submission acknowledgement retries the identical durable job without duplicate execution', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Synchronization: Synced', exact: true }).first()).toBeVisible({ timeout: 20_000 })
  const ids: string[] = []
  let committed = false
  await page.route('**/api/v1/executions', async route => {
    const body = route.request().postDataJSON() as Submission
    ids.push(body.id)
    if (!committed) {
      const response = await route.fetch(); expect(response.status()).toBe(201); committed = true
      await route.abort('failed')
    } else await route.continue()
  })
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  await expect.poll(() => ids.length, { timeout: 15_000 }).toBeGreaterThan(1)
  expect(new Set(ids).size).toBe(1)
  const job = await (await page.request.get(`/api/v1/executions/${ids[0]}`)).json() as Job
  const history = await (await page.request.get(`/api/v1/workspaces/${job.workspaceId}/executions`)).json() as Job[]
  expect(history.filter(j => j.id === job.id)).toHaveLength(1)
  await page.request.post(`/api/v1/executions/${job.id}/cancel`)
})

test('real Linux worker produces measured output and custom-test verdicts', async ({ page }, testInfo) => {
  test.skip(process.env.REAL_LINUX_WORKER !== '1', 'Requires an approved running Linux isolate worker; no mocked execution accepted')
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Synchronization: Synced', exact: true }).first()).toBeVisible({ timeout: 20_000 })
  const editor = page.getByRole('textbox', { name: 'Editor content', exact: true })
  await editor.press('ControlOrMeta+a'); await page.keyboard.insertText('#include<iostream>\nint main(){int a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}')
  await page.getByRole('textbox', { name: 'Standard input', exact: true }).fill('2 3\n')
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/executions') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Run', exact: true }).click()
  const job = await (await response).json() as Job
  await expect.poll(async () => (await (await page.request.get(`/api/v1/executions/${job.id}`)).json() as Job).status, { timeout: 45_000 }).toBe('FINISHED')
  const finished = await (await page.request.get(`/api/v1/executions/${job.id}`)).json() as Job
  expect(finished.result?.cases[0]?.stdout).toBe('5\n')
  expect(finished.result?.toolchainVersion).toMatch(/g\+\+|GCC/)
  expect(finished.result?.cases[0]?.wallTime).not.toBeNull()
  expect(finished.result?.cases[0]?.peakMemoryKiB).not.toBeNull()
  await expect(page.getByText(/No verified Linux worker connected/)).toHaveCount(0)

  await page.getByRole('button', { name: 'Test Cases', exact: true }).click()
  await page.getByRole('button', { name: 'New Test', exact: true }).click()
  await page.getByRole('textbox', { name: 'Test name', exact: true }).fill('Exact match')
  await page.getByRole('textbox', { name: 'Test stdin', exact: true }).fill('2 3\n')
  await page.getByRole('checkbox', { name: 'Compare expected stdout' }).check()
  await page.getByRole('textbox', { name: 'Expected stdout', exact: true }).fill('5\n')
  await page.getByRole('button', { name: 'Duplicate test', exact: true }).click()
  await page.getByRole('textbox', { name: 'Test name', exact: true }).fill('Whitespace mismatch')
  await page.getByRole('textbox', { name: 'Expected stdout', exact: true }).fill('5 \n')
  const batchResponse = page.waitForResponse(r => r.url().endsWith('/api/v1/executions') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Run All', exact: true }).click()
  const batch = await (await batchResponse).json() as Job
  await expect.poll(async () => (await (await page.request.get(`/api/v1/executions/${batch.id}`)).json() as Job).status, { timeout: 45_000 }).toBe('FINISHED')
  await expect(page.locator('.test-result summary').filter({ hasText: 'Exact match' })).toContainText('Accepted')
  await expect(page.locator('.test-result summary').filter({ hasText: 'Whitespace mismatch' })).toContainText('Wrong Answer')
  await page.setViewportSize({ width: 1440, height: 1400 })
  await expect(page.locator('.execution-summary').first()).toContainText('FINISHED', { timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Stop execution', exact: true })).toBeDisabled()
  await page.locator('.test-result').last().scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('real-worker-verified.png'), fullPage: true })
})
