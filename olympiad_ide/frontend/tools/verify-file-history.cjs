// Real public staging Admin file-history acceptance. No account, source or submission mutations.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {createRequire} = require('node:module');
const {chromium, expect} = createRequire(path.join(__dirname, '../package.json'))('@playwright/test');
const [fixturePath, output, participantResultsPath] = process.argv.slice(2);
if (!fixturePath || !output || !participantResultsPath) throw Error('Protected staging fixture, output and prior participant results required');
const mode = fs.lstatSync(fixturePath);
if (!mode.isFile() || mode.isSymbolicLink() || mode.mode & 0o077) throw Error('Protected regular non-symlink fixture required');
const metadata = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const origin = 'https://54.206.171.67', admin = origin + '/admin', route = admin + '/contest/1/ide-history', api = route + '/api';
if (metadata.kind !== 'disposable-linux-staging' || metadata.baseUrl !== origin || String(metadata.contestId) !== '1' || !metadata.acceptanceUserId) throw Error('Exact authorized disposable staging fixture required');
const prior = JSON.parse(fs.readFileSync(participantResultsPath, 'utf8'));
const expected = prior.sourceFixtures?.find(file => file.task === 'cppsum'), task = metadata.tasks.find(row => row.name === 'cppsum');
if (prior.status !== 'passed' || !expected || !task) throw Error('Previous successful participant source fixture required');
const secrets = [metadata.password, metadata.adminPassword].filter(Boolean), safe = text => secrets.reduce((value, secret) => value.split(secret).join('[REDACTED]'), String(text));
fs.mkdirSync(output, {recursive:true, mode:0o700});
const report = {status:'running', kind:'real-public-admin-read-only', normalPublicTls:true, route, participantUserId:String(metadata.acceptanceUserId), taskId:String(task.id), checks:[]};
const params = new URLSearchParams({userId:String(metadata.acceptanceUserId),taskId:String(task.id)}), errors = [], serverErrors = [], mutations = [];
let browser, page;
async function login(target, isAdmin, username, password) {
  await target.goto(isAdmin ? admin + '/login' : origin + '/');
  const form = target.locator('form').filter({has:target.locator('input[name="password"]')});
  expect(await form.evaluate(node => new URL(node.action, document.URL).href)).toBe((isAdmin ? admin : origin) + '/login');
  await form.locator('input[name="username"]').fill(username); await form.locator('input[name="password"]').fill(password);
  await Promise.all([target.waitForNavigation({waitUntil:'domcontentloaded'}), form.locator('button[type="submit"],input[type="submit"]').click()]);
  expect(new URL(target.url()).origin).toBe(origin);
}
async function deny(context, suffix) {
  const response = await context.request.get(api + suffix + (suffix.includes('?') ? '&' : '?') + params, {maxRedirects:0});
  expect([302,303,401,403]).toContain(response.status());
  expect(await response.text()).not.toContain(expected.sourceText);
}
(async () => {
  browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH} : {})});
  try {
    const guest = await browser.newContext(); await deny(guest, '/files'); const gp = await guest.newPage(); await gp.goto(route); expect(new URL(gp.url()).pathname).toBe('/admin/login'); await guest.close();
    const participant = await browser.newContext(), participantPage = await participant.newPage();
    await login(participantPage, false, metadata.username, metadata.password);
    const verified = await participantPage.evaluate(async () => { const response = await fetch('/ide/api/context', {cache:'no-store'}); return {status:response.status,body:await response.json()}; });
    expect(verified.status).toBe(200); expect(String(verified.body.identity.userId)).toBe(String(metadata.acceptanceUserId));
    await deny(participant, '/files'); await participantPage.goto(route); expect(new URL(participantPage.url()).pathname).toBe('/admin/login'); await participant.close();
    report.checks.push('Guest and actual authenticated participant cannot read submitted files or open Admin history.');
    const context = await browser.newContext({viewport:{width:1560,height:1100}}); page = await context.newPage();
    page.on('pageerror', error => errors.push(safe(error.message)));
    page.on('response', response => { if (response.status() >= 500) serverErrors.push({path:new URL(response.url()).pathname,status:response.status()}); });
    page.on('request', request => { if (new URL(request.url()).pathname.includes('/ide-history/api/') && request.method() !== 'GET') mutations.push({method:request.method(),path:new URL(request.url()).pathname}); });
    await login(page, true, metadata.adminUsername, metadata.adminPassword); expect(new URL(page.url()).pathname).not.toBe('/admin/login'); await page.goto(route);
    await expect(page.getByRole('heading', {name:'Participant code history',exact:true})).toBeVisible();
    expect(await page.getByRole('combobox', {name:'History recording',exact:true}).count()).toBe(0);
    await page.getByRole('combobox', {name:'History participant',exact:true}).selectOption(String(metadata.acceptanceUserId));
    const listing = page.waitForResponse(response => response.url().startsWith(api + '/files?') && response.request().method() === 'GET');
    await page.getByRole('combobox', {name:'History problem',exact:true}).selectOption(String(task.id));
    const listResponse = await listing; expect(listResponse.status()).toBe(200); const list = await listResponse.json();
    expect(list.files.length).toBeGreaterThan(0); await expect(page.locator('.history-file-card')).toHaveCount(list.files.length);
    const selected = list.files.find(file => file.hasHistory && file.sourceFilename === expected.filename); expect(selected).toBeTruthy();
    const timelineResponse = page.waitForResponse(response => response.url().includes('/files/' + selected.fileId + '/timeline?'));
    await page.locator('button.history-file-select[data-file-id="' + selected.fileId + '"]').click();
    const timeResponse = await timelineResponse; expect(timeResponse.status()).toBe(200); const timeline = await timeResponse.json();
    expect(timeline.intervalSeconds).toBe(5); expect(timeline.correlation.state).toBe('matched');
    expect(timeline.points.length).toBeGreaterThan(0); expect(timeline.points.some(point => point.kind === 'initial')).toBe(true); expect(timeline.points.some(point => point.kind === 'submission')).toBe(true);
    await expect(page.locator('#history-timeline')).toHaveAttribute('max', String(timeline.points.length - 1));
    await expect(page.locator('#history-source')).toHaveValue(expected.sourceText); await expect(page.locator('#history-source')).toHaveAttribute('readonly','');
    expect(crypto.createHash('sha256').update(await page.locator('#history-source').inputValue()).digest('hex')).toBe(expected.sha256);
    await expect(page.locator('#history-correlation')).toHaveText('Submitted bytes matched');
    report.file = {fileId:String(selected.fileId),submissionId:String(selected.submissionId),sourceFilename:selected.sourceFilename,sourceSha256:expected.sha256,points:timeline.points.length,editingPoints:timeline.points.filter(point => point.kind === 'editing').length,correlation:timeline.correlation.state};
    report.observedMarkerKinds = [...new Set(timeline.points.flatMap(point => (point.markers || []).map(marker => marker.kind)))];
    report.checks.push('Actual CMS submissions supply the file selector; selected retained file reconstructs the exact submitted source/hash at the capture boundary.');
    const slider = page.getByRole('slider', {name:'History timeline',exact:true});
    await slider.focus(); await slider.press('Home'); await expect(slider).toHaveValue('0');
    if (timeline.points.length > 1) {
      await page.getByRole('button', {name:'Next period',exact:true}).click(); await expect(slider).toHaveValue('1');
      await page.getByRole('button', {name:'Previous period',exact:true}).click(); await expect(slider).toHaveValue('0');
      await page.getByRole('combobox', {name:'History speed',exact:true}).selectOption('2');
      await page.getByRole('button', {name:'Play',exact:true}).click(); await expect.poll(() => slider.inputValue()).not.toBe('0');
      if (await page.getByRole('button', {name:'Pause',exact:true}).count()) await page.getByRole('button', {name:'Pause',exact:true}).click();
    }
    const regroup = page.waitForResponse(response => response.url().includes('/files/' + selected.fileId + '/timeline?') && new URL(response.url()).searchParams.get('intervalSeconds') === '30');
    await page.getByRole('combobox', {name:'Editing period',exact:true}).selectOption('30');
    const regroupResponse = await regroup; expect(regroupResponse.status()).toBe(200); const grouped = await regroupResponse.json(); expect(grouped.intervalSeconds).toBe(30);
    await expect(page.locator('#history-source')).toHaveValue(expected.sourceText); await expect(slider).toHaveAttribute('max',String(grouped.points.length - 1));
    await page.getByRole('checkbox', {name:'Marked periods only',exact:true}).check();
    await expect(slider).toHaveAttribute('max', String(grouped.points.filter(point => point.kind !== 'editing' || point.markers?.length).length - 1));
    await page.getByRole('checkbox', {name:'Marked periods only',exact:true}).uncheck(); await slider.focus(); await slider.press('End'); await expect(page.locator('#history-source')).toHaveValue(expected.sourceText);
    await page.getByRole('checkbox', {name:'Compare previous period',exact:true}).check(); await expect(page.locator('#history-before-panel')).toBeVisible();
    await expect(page.locator('#history-source')).toHaveValue(expected.sourceText);
    await expect(page.getByRole('region', {name:'Review markers',exact:true})).toContainText('Paste sources are not recorded');
    report.checks.push('Editing-period navigation, playback, interval grouping, boundary-preserving marker filter and previous-period comparison work on retained real data.');
    await page.screenshot({path:path.join(output,'submitted-file-history.png'),fullPage:true});
    const other = list.files.find(file => String(file.fileId) !== String(selected.fileId));
    if (other) {
      await page.locator('button.history-file-select[data-file-id="' + other.fileId + '"]').click();
      await expect(page.locator('.history-file-card.is-selected')).toHaveAttribute('data-file-id',String(other.fileId));
    }
    await page.getByRole('combobox', {name:'History participant',exact:true}).selectOption(''); await expect(page.locator('#history-source')).toHaveValue(''); await expect(page.locator('#history-before')).toHaveValue(''); await expect(page.locator('.history-file-card')).toHaveCount(0); await expect(page.locator('#history-player')).toBeHidden();
    report.checks.push('Changing the reviewed identity clears the prior submitted file and source immediately.');
    expect(mutations).toEqual([]); expect(errors).toEqual([]); expect(serverErrors).toEqual([]);
    report.historyMutations=mutations; report.pageErrors=errors; report.serverErrors=serverErrors; report.status='passed'; console.log('FILE_HISTORY_PUBLIC_ACCEPTANCE_PASSED');
  } catch (error) { report.status='failed'; report.error=safe(error.stack || error); report.pageErrors=errors; report.serverErrors=serverErrors; if(page)await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{}); throw error; }
  finally { fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(report,null,2),{mode:0o600}); await browser.close(); }
})().catch(error => { console.error(safe(error.stack || error)); process.exitCode=1; });
