// Real public staging only. Three starts maximum; no judging submissions or mocked DAP.
// Usage: node tools/verify-debug-lifecycle.cjs /protected/browser-public.json /private/output-dir
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const { chromium, expect } = createRequire(path.join(__dirname, '../package.json'))('@playwright/test');

const [fixturePath, output] = process.argv.slice(2);
if (!fixturePath || !output) throw Error('Protected fixture and output directory are required');
const fixtureStat = fs.statSync(fixturePath);
if (process.platform !== 'win32' && (fixtureStat.mode & 0o077)) {
  throw Error('Fixture must have no group or other permissions');
}
const metadata = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
if (metadata.kind !== 'disposable-linux-staging' || metadata.baseUrl !== 'https://54.206.171.67') {
  throw Error('Explicit authorized public staging fixture required');
}
if (typeof metadata.username !== 'string' || typeof metadata.password !== 'string') {
  throw Error('Protected fixture is missing participant credentials');
}
fs.mkdirSync(output, { recursive: true, mode: 0o700 });

(async () => {
  // TLS validation remains enabled. Browser creation does not grant extra network targets.
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 },
    permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const report = { status: 'running', baseUrl: metadata.baseUrl, checks: [], sessions: [], startsAttempted: 0 };
  let currentSession = null;
  let taskId = null;
  const save = () => fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  const editor = page.getByRole('textbox', { name: 'Editor content', exact: true });
  const panel = page.getByRole('region', { name: 'Interactive debugger' });

  async function scoped(route, method = 'GET') {
    return page.evaluate(async ({ route, method, taskId }) => {
      const contextResponse = await fetch('/ide/api/context', { cache: 'no-store' });
      if (!contextResponse.ok) throw Error('Participant context unavailable: ' + contextResponse.status);
      const current = await contextResponse.json();
      const response = await fetch(route, { method, cache: 'no-store', headers: {
        'Content-Type': 'application/json',
        'X-Olympiad-Principal': current.identity.principalId,
        'X-Olympiad-Task': String(taskId),
        'X-XSRFToken': current.csrfToken,
      } });
      if (!response.ok) throw Error('Owned debug request failed: ' + response.status);
      return response.json();
    }, { route, method, taskId });
  }
  async function ownedSession(id) {
    return scoped('/ide/api/runtime/v1/debug/sessions/' + encodeURIComponent(id));
  }
  async function confirmedStopped(id) {
    let terminal;
    await expect.poll(async () => {
      terminal = await ownedSession(id);
      return terminal.status;
    }, { timeout: 20000, intervals: [200, 500, 1000] }).toBe('STOPPED');
    return { id: terminal.id, status: terminal.status, sourceHash: terminal.sourceHash, error: terminal.error };
  }
  async function showDebugger() {
    if (!await panel.isVisible()) await page.getByRole('button', { name: 'Run and Debug', exact: true }).click();
    await expect(panel).toBeVisible();
  }
  async function newFile(name, source) {
    if (!await page.getByRole('button', { name: 'New File', exact: true }).isVisible()) {
      await page.getByRole('button', { name: 'Explorer', exact: true }).click();
    }
    page.once('dialog', dialog => dialog.accept(name));
    await page.getByRole('button', { name: 'New File', exact: true }).click();
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    await page.getByRole('tab', { name: new RegExp(escaped) }).last().click();
    await expect(editor).toBeVisible();
    await page.evaluate(text => navigator.clipboard.writeText(text), source);
    await editor.press('ControlOrMeta+a');
    await editor.press('ControlOrMeta+v');
    await page.getByRole('textbox', { name: 'STDIN File', exact: true }).fill('');
  }

  try {
    await page.goto(metadata.baseUrl + '/');
    await page.evaluate(async credentials => {
      const csrf = decodeURIComponent(document.cookie.split('; ').find(value => value.startsWith('_xsrf='))?.slice(6) || '');
      const response = await fetch('/login', { method: 'POST', body: new URLSearchParams({
        username: credentials.username, password: credentials.password, _xsrf: csrf,
      }) });
      if (!response.ok) throw Error('CWS login failed');
    }, { username: metadata.username, password: metadata.password });
    await page.goto(metadata.baseUrl + '/');
    const card = page.getByRole('region', { name: 'Olympiad IDE', exact: true });
    const entry = page.getByRole('link', { name: 'Open Olympiad IDE', exact: true });
    await expect(card).toBeVisible();
    await expect(entry).toBeVisible();
    const mobileCard = await card.boundingBox(), mobileLink = await entry.boundingBox();
    expect(mobileCard.x).toBeGreaterThanOrEqual(0);
    expect(mobileCard.x + mobileCard.width).toBeLessThanOrEqual(391);
    expect(mobileLink.y).toBeGreaterThanOrEqual(0);
    expect(mobileLink.y + mobileLink.height).toBeLessThanOrEqual(844);
    await page.screenshot({ path: path.join(output, 'cms-entry-mobile.png') });
    report.mobile = { viewport: { width: 390, height: 844 }, card: mobileCard, link: mobileLink };
    report.checks.push('Mobile CWS IDE card and actionable link fit the initial viewport');
    await page.setViewportSize({ width: 1440, height: 1050 });
    await entry.click();
    await expect(page.locator('.cms-bar')).toBeVisible({ timeout: 120000 });
    await expect(editor).toBeVisible({ timeout: 30000 });
    taskId = await page.getByRole('combobox', { name: 'Contest task', exact: true }).inputValue();
    if (!/^\d+$/.test(taskId)) throw Error('Authorized contest task is required');
    const suffix = Date.now().toString();
    const javaClass = 'Lifecycle' + suffix;
    const programs = [
      { name: 'lifecycle' + suffix + '.cpp', language: 'C++', cleanup: 'Stop button',
        source: '#include <cstdint>\nint main() {\n volatile std::int64_t counter = 0;\n while (true) {\n  counter = (counter + 1) % 1000000007;\n }\n}\n' },
      { name: 'lifecycle' + suffix + '.py', language: 'Python', cleanup: 'Stop button',
        source: 'counter = 0\nwhile True:\n counter = (counter + 1) % 1000000007\n' },
      { name: javaClass + '.java', language: 'Java', cleanup: 'Active page refresh/disconnect',
        source: `public class ${javaClass} {\n static volatile long observed;\n public static void main(String[] args) {\n  long counter = 0;\n  while (true) {\n   counter = (counter + 1) % 1000000007;\n   observed = counter;\n  }\n }\n}\n` },
    ];
    for (const program of programs) {
      // Each previous worker must be terminal before a new file can start another session.
      if (currentSession) throw Error('Previous session has not been confirmed terminal');
      await newFile(program.name, program.source);
      await showDebugger();
      await expect(panel.getByRole('button', { name: 'Start debugging', exact: true })).toBeEnabled();
      if (report.startsAttempted >= 3) throw Error('Three-start acceptance budget exhausted');
      report.startsAttempted++;
      const creating = page.waitForResponse(response => response.url().endsWith('/debug/sessions') && response.request().method() === 'POST');
      await panel.getByRole('button', { name: 'Start debugging', exact: true }).click();
      const response = await creating;
      if (response.status() === 429) {
        report.status = 'blocked';
        report.blocker = 'Participant debug quota/capacity returned HTTP 429; no retry attempted';
        throw Error(report.blocker);
      }
      expect(response.status()).toBe(201);
      const submission = response.request().postDataJSON().submission;
      const created = await response.json();
      currentSession = created.id;
      expect(submission.files).toHaveLength(1);
      expect(submission.files[0].path).toBe(program.name);
      expect(submission.files[0].content).toBe(program.source);
      expect(created.sourceHash).toBe(submission.sourceHash);
      expect(created.sourceHash).toMatch(/^[a-f0-9]{64}$/);
      const evidence = { language: program.language, file: program.name, id: created.id,
        sourceHash: created.sourceHash, sourceTextSha256: crypto.createHash('sha256').update(program.source).digest('hex'),
        cleanup: program.cleanup };
      report.sessions.push(evidence); save();
      console.log('Started real lifecycle session', program.language, created.id);
      await expect(panel.getByRole('button', { name: 'Pause', exact: true })).toBeEnabled({ timeout: 60000 });
      await expect.poll(async () => (await ownedSession(created.id)).status, { timeout: 10000 }).toBe('RUNNING');
      await panel.getByRole('button', { name: 'Pause', exact: true }).click();
      await expect(panel.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled({ timeout: 20000 });
      await expect(panel.locator('.debug-list').nth(1).getByRole('button').first()).toBeVisible();
      const counter = panel.locator('.debug-variable').filter({ has: page.getByRole('button', { name: 'counter', exact: true }) }).first();
      await expect(counter).toBeVisible({ timeout: 10000 });
      const events = await scoped('/ide/api/runtime/v1/debug/sessions/' + created.id + '/events?after=0');
      const pauseEvent = events.events.find(event => event.message.type === 'event' && event.message.event === 'stopped' && event.message.body?.reason === 'pause');
      expect(pauseEvent).toBeTruthy();
      evidence.pause = { reason: pauseEvent.message.body.reason, threadId: pauseEvent.message.body.threadId,
        frame: await panel.locator('.debug-list').nth(1).getByRole('button').first().innerText(),
        counter: await counter.innerText(), sequence: pauseEvent.sequence };
      await page.screenshot({ path: path.join(output, 'paused-' + program.language + '.png') });
      await panel.getByRole('button', { name: 'Continue', exact: true }).click();
      await expect(panel.getByRole('button', { name: 'Pause', exact: true })).toBeEnabled({ timeout: 10000 });
      if (program.cleanup === 'Stop button') {
        await panel.getByRole('button', { name: 'Stop debugging', exact: true }).click();
        evidence.terminal = await confirmedStopped(created.id);
        await expect(panel.getByRole('status').first()).toContainText('finished', { timeout: 10000 });
        await expect(panel.getByRole('button', { name: 'Start debugging', exact: true })).toBeEnabled();
        await expect(panel.locator('.debug-error')).toHaveCount(0);
      } else {
        // Reload the running session itself; this exercises pagehide plus actual WebSocket disconnection.
        await page.reload();
        await expect(page.locator('.cms-bar')).toBeVisible({ timeout: 30000 });
        await expect(editor).toBeVisible({ timeout: 30000 });
        evidence.terminal = await confirmedStopped(created.id);
        await page.getByRole('tab', { name: new RegExp(program.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).last().click();
        await expect(page.locator('.editor-pane .view-lines')).toContainText('observed = counter');
        await showDebugger();
        await expect(panel.getByRole('button', { name: 'Start debugging', exact: true })).toBeEnabled();
        await expect(panel.getByRole('status').first()).toContainText('idle');
        evidence.recovery = { sourceRestored: true, debuggerIdle: true, oldWorkerConfirmedStopped: true };
      }
      expect(evidence.terminal.sourceHash).toBe(evidence.sourceHash);
      currentSession = null;
      save();
      console.log('Actual pause and confirmed worker termination passed', program.language);
    }
    expect(errors).toEqual([]);
    report.errors = errors;
    report.checks.push('Real C++/Python/Java Pause events, stack frames and counter locals');
    report.checks.push('C++/Python Stop UI waits for confirmed STOPPED worker state');
    report.checks.push('Active Java refresh disconnects and stops old worker; saved source recovers idle');
    report.status = 'passed'; save();
    console.log('DEBUG_LIFECYCLE_PASSED');
  } catch (error) {
    if (report.status !== 'blocked') report.status = 'failed';
    report.error = String(error); report.errors = errors;
    // Only the session created by this script is eligible for best-effort cleanup.
    if (currentSession && taskId) {
      try {
        await scoped('/ide/api/runtime/v1/debug/sessions/' + currentSession + '/stop', 'POST');
        report.failureCleanup = await confirmedStopped(currentSession);
        currentSession = null;
      } catch (cleanupError) { report.failureCleanupError = String(cleanupError); }
    }
    save();
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => undefined);
    console.error('Lifecycle diagnostics', JSON.stringify({ url: page.url(), errors, currentSession }));
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
