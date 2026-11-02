// Actual public staging acceptance. No mocked workers, scores, source or authentication.
// Usage: node tools/verify-participant-polish.cjs /protected/fresh-actor.json /private/output
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const { chromium, expect } = createRequire(path.join(__dirname, '../package.json'))('@playwright/test');

const [fixturePath, output] = process.argv.slice(2);
if (!fixturePath || !output) throw Error('Protected fresh staging actor fixture and output directory are required');
if (fs.statSync(fixturePath).mode & 0o077) throw Error('Fixture must be private (mode0600)');
const metadata = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
if (metadata.kind !== 'disposable-linux-staging' || metadata.baseUrl !== 'https://54.206.171.67') {
  throw Error('Only the explicitly authorized disposable public staging host is allowed');
}
if (!metadata.username || !metadata.password || !Number.isInteger(metadata.contestId)) throw Error('Incomplete protected actor fixture');
fs.mkdirSync(output, { recursive: true, mode: 0o700 });
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {}) });
  const browserContext = await browser.newContext({ viewport: { width: 1440, height: 1050 },
    permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await browserContext.newPage();
  page.setDefaultTimeout(20000);
  const report = { status: 'running', baseUrl: metadata.baseUrl, checks: [], taskChanges: [],
    submissions: [], debug: null, telemetry: [], pageErrors: [], serverErrors: [], popups: [],
    budgets: { debugStarts: 0, officialPosts: 0, tokenPosts: 0 } };
  const save = () => fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  let participant = null, currentTaskId = null, activeDebugId = null, watchTaskChange = false;
  const forbiddenNavigations = [], registeredSessions = new Map(), wire = [];
  const editor = page.getByRole('textbox', { name: 'Editor content', exact: true });
  const taskSelector = page.getByRole('combobox', { name: 'Contest task', exact: true });
  const debugPanel = page.getByRole('region', { name: 'Interactive debugger', exact: true });
  const submitDialog = page.getByRole('dialog', { name: 'Submit solution', exact: true });
  page.on('pageerror', error => report.pageErrors.push(error.message));
  page.on('popup', popup => { report.popups.push(popup.url()); void popup.close(); });
  page.on('framenavigated', frame => {
    if (watchTaskChange && frame === page.mainFrame()) forbiddenNavigations.push(frame.url());
  });
  page.on('websocket', socket => {
    if (!/^wss:\/\/54\.206\.171\.67\/ide\/api\/debug\/sessions\/[0-9a-f-]+\/dap$/.test(socket.url())) return;
    for (const direction of ['framesent', 'framereceived']) socket.on(direction, frame => {
      try {
        const message = JSON.parse(String(frame.payload));
        // Deliberately never retain attachment frames/tickets or arbitrary variable/source payloads.
        if (message.type === 'request' && message.command === 'setBreakpoints') wire.push({ direction,
          kind: 'setBreakpoints', lines: message.arguments?.breakpoints?.map(point => point.line) ?? [] });
        if (message.type === 'event' && message.event === 'stopped') wire.push({ direction, kind: 'stopped',
          reason: message.body?.reason, threadId: message.body?.threadId, hitBreakpointIds: message.body?.hitBreakpointIds });
      } catch { /* Non-JSON/binary frames are not acceptance evidence. */ }
    });
  });
  page.on('response', response => {
    try {
      const request = response.request(), url = new URL(response.url());
      if (url.origin !== metadata.baseUrl) return;
      if (response.status() >= 500) report.serverErrors.push({ path: url.pathname, status: response.status() });
      if (request.method() !== 'POST') return;
      if (url.pathname.endsWith('/telemetry/sessions') && response.status() === 201) {
        const body = request.postDataJSON(), task = Number(request.headers()['x-olympiad-task']);
        if (body?.id && Number.isInteger(task) && task > 0) registeredSessions.set(body.id, task);
      }
      if (url.pathname.endsWith('/telemetry/batches')) {
        const body = request.postDataJSON(), observations = (body?.events ?? []).filter(event => event.eventType.startsWith('CMS_SUBMISSION_'));
        if (observations.length || response.status() >= 400) report.telemetry.push({ status: response.status(),
          sessionId: body?.sessionId, observations: observations.map(event => ({ type: event.eventType, taskId: event.payload?.taskId })) });
      }
    } catch { /* Only bounded recognized request metadata is retained. */ }
  });

  async function authenticatedContext() {
    const value = await page.evaluate(async () => {
      const response = await fetch('/ide/api/context', { cache: 'no-store', redirect: 'error' });
      return { status: response.status, body: response.ok ? await response.json() : null };
    });
    expect(value.status, 'Actual authenticated participant context, not a successful login-page response').toBe(200);
    expect(value.body?.user?.username).toBe(metadata.username);
    expect(String(value.body?.identity?.contestId)).toBe(String(metadata.contestId));
    expect(value.body?.identity?.principalId).toMatch(/^[0-9a-f-]{36}$/i);
    if (participant) expect(value.body.identity.principalId).toBe(participant.identity.principalId);
    if (metadata.principalId) expect(value.body.identity.principalId).toBe(metadata.principalId);
    participant = value.body;
    return participant;
  }
  async function scoped(route, taskId = currentTaskId, options = {}) {
    return page.evaluate(async ({ route, taskId, options }) => {
      const contextResponse = await fetch('/ide/api/context', { cache: 'no-store', redirect: 'error' });
      if (!contextResponse.ok) throw Error('Participant authentication failed: ' + contextResponse.status);
      const context = await contextResponse.json();
      const response = await fetch(route, { ...options, cache: 'no-store', redirect: 'error', headers: {
        'Content-Type': 'application/json', 'X-Olympiad-Principal': context.identity.principalId,
        'X-Olympiad-Task': String(taskId), 'X-XSRFToken': context.csrfToken,
      } });
      const body = await response.json().catch(() => null);
      return { status: response.status, body };
    }, { route, taskId, options });
  }
  async function assertParticipantUI() {
    await expect(page.getByRole('button', { name: 'History', exact: true })).toHaveCount(0);
    await expect(page.getByText('HISTORY REPLAY', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('dialog', { name: 'Recording diagnostics', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^Telemetry:/ })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /privacy.*diagnostics/i })).toHaveCount(0);
    for (const text of ['Pending events', 'Last acknowledged', 'Retry upload', 'Export recording']) {
      await expect(page.getByText(text, { exact: true })).toHaveCount(0);
    }
    await expect(page.getByText('Editor activity recorded', { exact: true })).toBeVisible();
  }
  async function readyForTask(id) {
    await expect(taskSelector).toHaveValue(String(id));
    await expect(taskSelector).toBeEnabled();
    await expect(page.getByText('Opening problem…', { exact: true })).toHaveCount(0);
    await expect(editor).toBeVisible({ timeout: 60000 });
    await expect(page.getByRole('button', { name: 'Run active file', exact: true })).toBeEnabled();
    currentTaskId = id;
  }
  async function changeTask(id, control = taskSelector) {
    const previous = Number(await taskSelector.inputValue());
    if (previous === id) { await readyForTask(id); return; }
    const before = forbiddenNavigations.length, pages = browserContext.pages().length;
    watchTaskChange = true;
    try {
      await control.selectOption(String(id));
      await readyForTask(id);
      expect(await page.evaluate(() => window.__participantPolishDocument)).toBe(report.documentMarker);
      expect(forbiddenNavigations.slice(before)).toEqual([]);
      expect(browserContext.pages().length).toBe(pages);
      expect(page.url()).toBe(metadata.baseUrl + '/ide/');
      report.taskChanges.push({ from: previous, to: id, documentPreserved: true, newWindows: 0 });
    } finally { watchTaskChange = false; }
  }
  async function write(source) {
    await page.evaluate(value => navigator.clipboard.writeText(value), source);
    await editor.press('ControlOrMeta+a'); await editor.press('ControlOrMeta+v');
  }
  async function newFile(name, source) {
    if (!await page.getByRole('button', { name: 'New File', exact: true }).isVisible()) {
      await page.getByRole('button', { name: 'Explorer', exact: true }).click();
    }
    page.once('dialog', dialog => dialog.accept(name));
    await page.getByRole('button', { name: 'New File', exact: true }).click();
    await page.getByRole('tab', { name: new RegExp(escape(name)) }).last().click();
    await expect(editor).toBeVisible(); await write(source);
  }
  async function showDebug() {
    if (!await debugPanel.isVisible()) await page.getByRole('button', { name: 'Run and Debug', exact: true }).click();
    await expect(debugPanel).toBeVisible();
  }
  async function continueToBreakpoint(line) {
    const after = wire.length;
    await debugPanel.getByRole('button', { name: 'Continue', exact: true }).click();
    await expect(debugPanel.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled({ timeout: 20000 });
    await expect(debugPanel.locator('.debug-list').nth(1).getByRole('button').first()).toContainText('main:' + line);
    await expect.poll(() => wire.slice(after).some(message => message.kind === 'stopped' && message.reason === 'breakpoint'), { timeout: 20000 }).toBe(true);
  }
  async function submitSource(task, filename, source, expectedLanguage) {
    if (report.budgets.officialPosts >= 3) throw Error('Three official submission budget exhausted; no retry attempted');
    await page.locator('.cms-submit-region').getByRole('button', { name: 'Submit', exact: true }).click();
    await expect(submitDialog).toBeVisible();
    await changeTask(task.id, submitDialog.getByRole('combobox', { name: 'Submission problem', exact: true }));
    await expect(submitDialog).toBeVisible();
    const file = submitDialog.getByRole('combobox', { name: 'Submission file', exact: true });
    await expect(file.locator('option', { hasText: filename })).toHaveCount(1);
    await file.selectOption({ label: filename });
    for (const phrase of ['Review captured source', 'Capture source for review', 'Recording comparison:',
      'Submission intents on this device', 'Custom and CMS toolchain mapping', 'Move source between browser origins']) {
      await expect(submitDialog.getByText(phrase, { exact: false })).toHaveCount(0);
    }
    const posting = page.waitForResponse(response => response.url().endsWith('/ide/api/submissions') && response.request().method() === 'POST');
    report.budgets.officialPosts++;
    await submitDialog.getByRole('button', { name: 'Submit solution', exact: true }).click();
    const response = await posting;
    if (response.status() !== 201) throw Error('Official submission not admitted; HTTP ' + response.status() + '; no automatic retry');
    const request = response.request().postDataJSON(), receipt = await response.json();
    expect(request.taskId).toBe(task.id); expect(request.files).toHaveLength(1);
    expect(request.files[0].sourceFilename).toBe(filename); expect(request.files[0].content).toBe(source);
    expect(request.language).toContain(expectedLanguage); expect(receipt.official).toBe(true);
    const evidence = { task: task.name, taskId: task.id, sourceFilename: filename, sourceTextSha256: sha256(source),
      intentId: request.intentId, submissionId: receipt.submissionId, admitted: true, realJudging: false };
    report.submissions.push(evidence); save();
    let feedback;
    await expect.poll(async () => {
      feedback = await scoped('/ide/api/submissions/status/' + encodeURIComponent(receipt.submissionId) + '?taskId=' + task.id, task.id);
      return feedback.status === 200 ? feedback.body?.status?.status : -feedback.status;
    }, { timeout: 180000, intervals: [500, 1000, 2000] }).toBe(5);
    expect(feedback.body.status.public_score).toBe(25);
    expect(feedback.body.status.score).toBeUndefined();
    Object.assign(evidence, { realJudging: true, status: 5, publicScore: feedback.body.status.public_score,
      fullScoreRestricted: true }); save();
    if (await submitDialog.isVisible()) await submitDialog.getByRole('button', { name: 'Close submit dialog', exact: true }).click();
    console.log('Actual native judging passed', task.name, receipt.submissionId);
    return evidence;
  }
  async function nativePage(task) {
    const target = new URL(task.submissionsUrl, metadata.baseUrl);
    expect(target.origin).toBe(metadata.baseUrl);
    const response = await page.goto(target.href, { waitUntil: 'domcontentloaded' });
    expect(response.status()).toBe(200);
    await authenticatedContext();
    await expect(page.locator('.submission_list').first()).toBeVisible();
    return response;
  }
  async function playNativeToken(task, number) {
    if (report.budgets.tokenPosts >= 2) throw Error('Two native token budget exhausted');
    await nativePage(task);
    const row = page.locator('.submission_list tbody tr[data-submission="' + number + '"]');
    await expect(row).toHaveCount(1);
    const button = row.locator('td.token').getByRole('button', { name: 'Play!', exact: true });
    await expect(button).toBeEnabled();
    report.budgets.tokenPosts++;
    await Promise.all([page.waitForNavigation({ waitUntil: 'domcontentloaded' }), button.click()]);
    await authenticatedContext();
    await expect(row.locator('td.token')).toContainText('Played');
  }

  try {
    await page.goto(metadata.baseUrl + '/');
    await page.evaluate(async credentials => {
      const xsrf = decodeURIComponent(document.cookie.split('; ').find(value => value.startsWith('_xsrf='))?.slice(6) || '');
      await fetch('/login', { method: 'POST', body: new URLSearchParams({ username: credentials.username,
        password: credentials.password, _xsrf: xsrf }) });
    }, { username: metadata.username, password: metadata.password });
    await authenticatedContext(); // Rejects stale credentials even when the login form returns HTTP200.
    expect(participant.actualPhase).toBe(0);
    const cpp = participant.tasks.find(task => task.name === 'cppsum'), python = participant.tasks.find(task => task.name === 'pysum');
    if (!cpp || !python) throw Error('Disposable C++ and Python fixture tasks are required');
    await page.goto(metadata.baseUrl + '/');
    await page.getByRole('link', { name: 'Open Olympiad IDE', exact: true }).click();
    await expect(page.locator('.cms-bar')).toBeVisible({ timeout: 120000 });
    await readyForTask(Number(await taskSelector.inputValue()));
    report.documentMarker = crypto.randomUUID();
    await page.evaluate(marker => { window.__participantPolishDocument = marker; }, report.documentMarker);
    report.participant = { username: participant.user.username, principalId: participant.identity.principalId,
      contestId: participant.identity.contestId };
    await assertParticipantUI();
    for (const task of [cpp, python]) {
      const existing = await scoped('/ide/api/submissions?taskId=' + task.id + '&offset=0', task.id);
      expect(existing.status).toBe(200);
      expect(existing.body.total, 'A fresh test actor is required before any mutating acceptance action').toBe(0);
    }
    const suffix = Date.now().toString(), cppName = 'participant' + suffix + '.cpp', pyName = 'participant' + suffix + '.py';
    const cppSource = '#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n';
    const pythonSource = 'a,b=map(int,input().split())\nprint(a+b)\n';
    report.sourceFixtures = [{ task: cpp.name, taskId: cpp.id, filename: cppName, sourceText: cppSource, sha256: sha256(cppSource) },
      { task: python.name, taskId: python.id, filename: pyName, sourceText: pythonSource, sha256: sha256(pythonSource) }];
    await changeTask(cpp.id); await newFile(cppName, cppSource);
    await page.getByRole('textbox', { name: 'STDIN File', exact: true }).fill('2 3\n');
    await changeTask(python.id); await expect(page.getByRole('tab', { name: new RegExp(escape(cppName)) })).toHaveCount(0);
    await newFile(pyName, pythonSource); await page.getByRole('textbox', { name: 'STDIN File', exact: true }).fill('11 4\n');
    await changeTask(cpp.id);
    await expect(page.getByRole('tab', { name: new RegExp(escape(cppName)) })).toBeVisible();
    await expect(page.getByRole('textbox', { name: 'STDIN File', exact: true })).toHaveValue('2 3\n');
    await expect(page.getByRole('tab', { name: new RegExp(escape(pyName)) })).toHaveCount(0);
    await changeTask(python.id); await expect(page.getByRole('textbox', { name: 'STDIN File', exact: true })).toHaveValue('11 4\n');
    await changeTask(cpp.id);
    report.checks.push('Task changes retain the same document/tab and restore separate source files and STDIN');
    await assertParticipantUI(); await page.screenshot({ path: path.join(output, 'participant-simple.png') });

    const debugName = 'breakpoints' + suffix + '.cpp';
    const debugSource = '#include <iostream>\nint main(){\n volatile int counter=0;\n while(true){\n  counter=(counter+1)%1000000007;\n  counter=(counter+2)%1000000007;\n }\n}\n';
    await newFile(debugName, debugSource); await showDebug();
    if (report.budgets.debugStarts >= 3) throw Error('Debug start budget exhausted');
    const creating = page.waitForResponse(response => response.url().endsWith('/debug/sessions') && response.request().method() === 'POST');
    report.budgets.debugStarts++;
    await debugPanel.getByRole('button', { name: 'Start debugging', exact: true }).click();
    const createdResponse = await creating;
    if (createdResponse.status() !== 201) throw Error('Real debugger unavailable: HTTP ' + createdResponse.status() + '; no retry');
    const created = await createdResponse.json(); activeDebugId = created.id;
    expect(createdResponse.request().postDataJSON().submission.files[0].content).toBe(debugSource);
    await expect(debugPanel.getByRole('button', { name: 'Pause', exact: true })).toBeEnabled({ timeout: 60000 });
    await debugPanel.getByRole('button', { name: 'Pause', exact: true }).click();
    await expect(debugPanel.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled({ timeout: 20000 });
    const counter = debugPanel.locator('.debug-variable').filter({ has: page.getByRole('button', { name: 'counter', exact: true }) }).first();
    await expect(counter).toBeVisible();
    const pausedCounter = await counter.locator('code').innerText();
    expect(pausedCounter).toMatch(/^\d+$/); expect(Number(pausedCounter)).toBeLessThan(1000000007);
    await page.locator('.editor-pane .view-lines .view-line').nth(4).click({ position: { x: 8, y: 8 } });
    await editor.press('F9');
    await expect(debugPanel.getByRole('button', { name: 'Remove ' + debugName + ':5', exact: true })).toBeVisible();
    await expect(debugPanel.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled();
    await continueToBreakpoint(5);
    await debugPanel.getByRole('button', { name: 'Remove ' + debugName + ':5', exact: true }).click();
    await debugPanel.getByRole('spinbutton', { name: 'Breakpoint line', exact: true }).fill('6');
    await debugPanel.getByRole('button', { name: 'Add breakpoint', exact: true }).click();
    await expect(debugPanel.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled();
    await continueToBreakpoint(6);
    await debugPanel.getByRole('button', { name: 'Remove ' + debugName + ':6', exact: true }).click();
    const number = page.locator('.editor-pane .margin-view-overlays .line-numbers').filter({ hasText: /^5$/ }).first();
    await number.click();
    await expect(debugPanel.getByRole('button', { name: 'Remove ' + debugName + ':5', exact: true })).toBeVisible();
    await expect(debugPanel.getByRole('button', { name: 'Continue', exact: true })).toBeEnabled();
    await continueToBreakpoint(5);
    await debugPanel.getByRole('button', { name: 'Remove ' + debugName + ':5', exact: true }).click();
    await page.screenshot({ path: path.join(output, 'breakpoints-live.png') });
    await debugPanel.getByRole('button', { name: 'Stop debugging', exact: true }).click();
    let terminal;
    await expect.poll(async () => {
      terminal = await scoped('/ide/api/runtime/v1/debug/sessions/' + created.id);
      return terminal.status === 200 ? terminal.body?.status : -terminal.status;
    }, { timeout: 20000 }).toBe('STOPPED');
    expect(terminal.body.sourceHash).toBe(created.sourceHash); activeDebugId = null;
    report.debug = { id: created.id, sourceHash: created.sourceHash, sourceTextSha256: sha256(debugSource),
      f9: true, explicitLine: true, lineNumberClick: true, liveAddRemove: true, actualStopLines: [5, 6, 5],
      terminal: 'STOPPED', actualPausedCounter: pausedCounter, immutableSourceHashPreserved: true, wire };
    report.checks.push('F9, explicit line and visible line-number breakpoints update a real paused isolate session'); save();

    const green = page.locator('.cms-submit-region'), topSubmit = green.getByRole('button', { name: 'Submit', exact: true });
    await expect(topSubmit).toBeVisible();
    const box = await green.boundingBox(); expect(box.x + box.width).toBeGreaterThan(1360); expect(box.y).toBeLessThan(80);
    const colors = await green.evaluate(element => [getComputedStyle(element).backgroundColor,
      getComputedStyle(element.querySelector('button')).backgroundColor]);
    expect(colors.some(color => { const rgb = color.match(/\d+(?:\.\d+)?/g)?.map(Number); return rgb && rgb[1] > rgb[0] + 10 && rgb[1] > rgb[2] + 10; })).toBe(true);
    await submitSource(cpp, cppName, cppSource, 'C++');
    await submitSource(python, pyName, pythonSource, 'Python');
    await submitSource(cpp, cppName, cppSource, 'C++');
    report.checks.push('Simple top-right green Submit chooses problem/file and receives real C++ and Python CMS scores');
    await expect.poll(() => report.telemetry.flatMap(batch => batch.status === 200 ? batch.observations : [])
      .filter(event => event.type === 'CMS_SUBMISSION_ADMITTED' && typeof event.taskId === 'number').length,
    { timeout: 30000 }).toBeGreaterThanOrEqual(3);
    expect(report.telemetry.filter(batch => batch.status >= 400)).toEqual([]);
    await expect.poll(() => registeredSessions.size, { timeout: 20000 }).toBeGreaterThan(0);
    report.telemetrySessions = [...registeredSessions].map(([id, taskId]) => ({ id, taskId }));
    const [recordingId, recordingTask] = registeredSessions.entries().next().value;
    for (const endpoint of ['events', 'checkpoints']) {
      const denied = await scoped('/ide/api/runtime/v1/telemetry/sessions/' + recordingId + '/' + endpoint, recordingTask);
      expect(denied.status).toBe(403);
    }
    report.checks.push('Numeric submission observations upload successfully; participant recording replay APIs are forbidden');
    await assertParticipantUI();
    // Exactly three real submissions permit the historic depleted-token branch without changing contest settings.
    await playNativeToken(cpp, 1); await playNativeToken(python, 1);
    await nativePage(cpp);
    await expect(page.locator('.submission_list tbody tr[data-submission="2"] td.token')).toContainText('No tokens');
    report.nativeCws = { cppSubmissionsHttp: 200, authenticated: true, tokenPosts: report.budgets.tokenPosts,
      exhaustedContestTokens: true, unplayedSecondCppSubmission: true };
    report.checks.push('Authenticated native CWS submission list stays HTTP200 with an unplayed row and exhausted contest tokens');
    await page.screenshot({ path: path.join(output, 'native-submissions-exhausted.png') });
    expect(report.pageErrors).toEqual([]); expect(report.serverErrors).toEqual([]); expect(report.popups).toEqual([]);
    expect(forbiddenNavigations).toEqual([]); expect(report.budgets.debugStarts).toBeLessThanOrEqual(3);
    expect(report.budgets.officialPosts).toBe(3); expect(report.budgets.tokenPosts).toBe(2);
    report.status = 'passed'; save(); console.log('PARTICIPANT_POLISH_PASSED');
  } catch (error) {
    report.status = 'failed'; report.error = String(error); report.url = page.url(); save();
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => undefined);
    throw error;
  } finally {
    if (activeDebugId && participant) {
      await scoped('/ide/api/runtime/v1/debug/sessions/' + activeDebugId + '/stop', currentTaskId, { method: 'POST' }).catch(() => undefined);
    }
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
