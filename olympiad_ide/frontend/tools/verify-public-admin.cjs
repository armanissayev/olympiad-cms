// Real public HTTPS acceptance for the explicitly authorized disposable CMS staging instance.
// Performs only native login/logout and read-only history review. No TLS bypass or SSH tunnel.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {createRequire} = require('node:module');
const {chromium, expect} = createRequire(path.join(__dirname, '../package.json'))('@playwright/test');
const [fixturePath, output, participantResultsPath] = process.argv.slice(2);
if (!fixturePath || !output || !participantResultsPath) throw Error('Protected fixture, output directory and previous participant results are required');
const stat = fs.lstatSync(fixturePath);
if (!stat.isFile() || stat.isSymbolicLink() || stat.mode & 0o077) throw Error('Protected fixture must be a regular non-symlink mode0600 file');
const metadata = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
const origin = 'https://54.206.171.67';
const admin = origin + '/admin';
if (metadata.kind !== 'disposable-linux-staging' || metadata.baseUrl !== origin || metadata.adminUrl !== 'https://localhost:28444' || !metadata.acceptanceUserId || String(metadata.contestId) !== '1') throw Error('Exact authorized disposable staging fixture required');
const task = metadata.tasks.find(row => row.name === 'cppsum');
const participant = JSON.parse(fs.readFileSync(participantResultsPath, 'utf8'));
const expected = participant.sourceFixtures?.find(row => row.task === 'cppsum');
if (!task || !expected || participant.status !== 'passed') throw Error('Successful previous disposable participant source fixture required');
const secrets = [metadata.password, metadata.adminPassword].filter(Boolean);
const safe = value => secrets.reduce((result, secret) => result.split(secret).join('[REDACTED]'), String(value));
fs.mkdirSync(output, {recursive:true, mode:0o700});
const report = {status:'running', publicAdmin:admin + '/', codeHistory:admin + '/contest/1/ide-history', normalPublicTls:true, participantUserId:String(metadata.acceptanceUserId), taskId:String(task.id), checks:[]};
const route = report.codeHistory;
const listingUrl = route + '/api/sessions?' + new URLSearchParams({userId:String(metadata.acceptanceUserId), taskId:String(task.id)});
let browser, page;
const errors = [];

function assertAdminUrl(value) {
  const parsed = new URL(value);
  expect(parsed.origin).toBe(origin);
  expect(parsed.pathname.startsWith('/admin/')).toBe(true);
}

async function deniedApi(context, url, label) {
  const response = await context.request.get(url, {maxRedirects:0});
  expect([302, 303, 401, 403]).toContain(response.status());
  if ([302,303].includes(response.status())) {
    const location = response.headers().location;
    expect(location).toBeTruthy();
    const target = new URL(location, response.url());
    expect(target.origin).toBe(origin);
    expect(target.pathname).toBe('/admin/login');
  }
  const text = await response.text();
  expect(text).not.toContain(expected.sourceText);
  expect(text).not.toContain('"sessions"');
  report.checks.push(label);
}

async function participantContext(target) {
  const value = await target.evaluate(async () => {
    const response = await fetch('/ide/api/context', {cache:'no-store'});
    return {status:response.status, body:await response.json()};
  });
  expect(value.status).toBe(200);
  expect(String(value.body.identity.userId)).toBe(String(metadata.acceptanceUserId));
  expect(value.body.user.username).toBe(metadata.username);
}

async function formLogin(target, adminLogin, username, password) {
  const prefix = adminLogin ? '/admin' : '';
  await target.goto(adminLogin ? origin + prefix + '/login' : origin + '/');
  const form = target.locator('form').filter({has:target.locator('input[name="password"]')});
  await expect(form).toHaveCount(1);
  const action = await form.evaluate(node => new URL(node.getAttribute('action') || '', document.URL).href);
  expect(action).toBe(origin + prefix + '/login');
  await form.locator('input[name="username"]').fill(username);
  await form.locator('input[name="password"]').fill(password);
  await Promise.all([target.waitForNavigation({waitUntil:'domcontentloaded'}), form.locator('button[type="submit"],input[type="submit"]').click()]);
  expect(new URL(target.url()).origin).toBe(origin);
}

async function prefixLinks(target) {
  const violations = await target.evaluate(() => {
    const rows = [...document.querySelectorAll('a[href],form[action],script[src],link[href]')];
    return rows.flatMap(node => {
      const attribute = node.tagName === 'FORM' ? 'action' : node.tagName === 'SCRIPT' ? 'src' : 'href';
      const raw = node.getAttribute(attribute);
      if (!raw || raw.startsWith('#')) return [];
      const url = new URL(raw, document.URL);
      return url.origin === location.origin && !url.pathname.startsWith('/admin/') ? [{tag:node.tagName,path:url.pathname}] : [];
    });
  });
  expect(violations).toEqual([]);
}

(async () => {
  browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH} : {})});
  try {
    const guest = await browser.newContext();
    const guestPage = await guest.newPage();
    const canonical = await guest.request.get(admin, {maxRedirects:0});
    expect([301,302,307,308]).toContain(canonical.status());
    expect(new URL(canonical.headers().location, canonical.url()).href).toBe(admin + '/');
    await guestPage.goto(route);
    assertAdminUrl(guestPage.url());
    expect(new URL(guestPage.url()).pathname).toBe('/admin/login');
    await prefixLinks(guestPage);
    await deniedApi(guest, listingUrl, 'Guest page and history API require CMS Admin authentication');
    await guest.close();

    const contestant = await browser.newContext();
    const contestantPage = await contestant.newPage();
    await formLogin(contestantPage, false, metadata.username, metadata.password);
    await participantContext(contestantPage);
    await contestantPage.goto(route);
    expect(new URL(contestantPage.url()).pathname).toBe('/admin/login');
    await deniedApi(contestant, listingUrl, 'Actual authenticated participant cookie does not authorize public Admin history');
    await formLogin(contestantPage, true, metadata.username, metadata.password);
    expect(new URL(contestantPage.url()).pathname).toBe('/admin/login');
    expect(new URL(contestantPage.url()).searchParams.get('login_error')).toBe('true');
    await deniedApi(contestant, listingUrl, 'Participant credentials cannot log in to CMS Admin');
    await contestant.close();

    const context = await browser.newContext({viewport:{width:1440,height:1050}});
    page = await context.newPage();
    page.on('pageerror', error => errors.push(safe(error.message)));
    const serverErrors = [], escapedAdminRequests = [];
    let historyMutations = 0;
    page.on('request', request => {
      const url = new URL(request.url());
      if (url.pathname.includes('/ide-history/api/') && request.method() !== 'GET') historyMutations++;
      if (page.url().startsWith(admin + '/') && ['script','stylesheet','xhr','fetch'].includes(request.resourceType()) && url.origin === origin && !url.pathname.startsWith('/admin/')) escapedAdminRequests.push(url.pathname);
    });
    page.on('response', response => { if (response.status() >= 500) serverErrors.push({path:new URL(response.url()).pathname,status:response.status()}); });
    // Exercise the shared-root XSRF cookie with a participant and Admin session in the same browser.
    await formLogin(page, false, metadata.username, metadata.password);
    await participantContext(page);
    await formLogin(page, true, metadata.adminUsername, metadata.adminPassword);
    assertAdminUrl(page.url());
    expect(new URL(page.url()).pathname).not.toBe('/admin/login');
    await page.goto(route);
    await expect(page.getByRole('heading', {name:'Participant code history',exact:true})).toBeVisible();
    await expect(page.getByRole('link', {name:'Code history',exact:true})).toBeVisible();
    await prefixLinks(page);
    const adminCookie = (await context.cookies(admin + '/')).find(cookie => cookie.name === 'awslogin');
    expect(adminCookie).toBeTruthy();
    expect(adminCookie.secure).toBe(true);
    expect(adminCookie.httpOnly).toBe(true);
    expect(adminCookie.sameSite).toBe('Strict');
    report.adminCookie = {name:adminCookie.name,path:adminCookie.path,secure:adminCookie.secure,httpOnly:adminCookie.httpOnly,sameSite:adminCookie.sameSite};
    // A missing XSRF token must not log out or mutate the authenticated administrator.
    const noXsrf = await page.evaluate(async () => { const response = await fetch('/admin/logout', {method:'POST',credentials:'same-origin',redirect:'manual',body:new URLSearchParams()}); return response.status; });
    expect(noXsrf).toBe(403);
    await page.reload();
    await expect(page.getByRole('heading', {name:'Participant code history',exact:true})).toBeVisible();
    report.checks.push('Public Admin uses Secure/HttpOnly/SameSiteStrict cookie; missing-XSRF logout is rejected without losing authentication');

    await page.getByRole('combobox', {name:'History participant',exact:true}).selectOption(String(metadata.acceptanceUserId));
    await page.getByRole('combobox', {name:'History problem',exact:true}).selectOption(String(task.id));
    const listing = page.waitForResponse(response => response.url().startsWith(route + '/api/sessions?') && response.request().method() === 'GET');
    await page.getByRole('button', {name:'Load recordings',exact:true}).click();
    const listResponse = await listing;
    expect(listResponse.status()).toBe(200);
    const listed = await listResponse.json();
    const sessions = listed.sessions.filter(row => row.lastSequence > 1);
    expect(sessions.length).toBeGreaterThan(0);
    let selected = null;
    for (const session of sessions) {
      await page.getByRole('combobox', {name:'History recording',exact:true}).selectOption(session.id);
      await expect(page.locator('#history-status')).toContainText('Uploaded recording:');
      const timeline = page.getByRole('slider', {name:'History timeline',exact:true});
      const replaying = page.waitForResponse(response => response.url().includes('/sessions/' + session.id + '/replay?') && new URL(response.url()).searchParams.get('through') === String(session.lastSequence));
      await timeline.focus();
      await timeline.press('End');
      const replayResponse = await replaying;
      expect(replayResponse.status()).toBe(200);
      const frame = await replayResponse.json();
      expect(frame.available).toBe(true);
      await expect(timeline).toHaveValue(String(session.lastSequence));
      const node = Object.values(frame.nodes).find(node => node.type === 'file' && node.name === expected.filename);
      if (!node) continue;
      await page.getByRole('combobox', {name:'History source file',exact:true}).selectOption(node.id);
      const source = page.getByRole('textbox', {name:'Historical source',exact:true});
      await expect(source).toHaveValue(expected.sourceText);
      await expect(source).toHaveAttribute('readonly', '');
      const hash = crypto.createHash('sha256').update(node.content).digest('hex');
      expect(hash).toBe(expected.sha256);
      selected = {id:session.id,lastSequence:session.lastSequence,sourceFile:node.name,sourceSha256:hash,checkpointSequence:frame.checkpointSequence};
      break;
    }
    expect(selected).not.toBeNull();
    report.recording = selected;
    report.expectedParticipantSourceMatched = true;
    report.checks.push('Full CMS Admin reads the actual uploaded participant source and verified hash through public HTTPS in a separate browser');
    await page.screenshot({path:path.join(output, 'public-admin-code-history.png'),fullPage:true});
    const timeline = page.getByRole('slider', {name:'History timeline',exact:true});
    await timeline.focus(); await timeline.press('Home'); await expect(timeline).toHaveValue('0');
    await page.getByRole('button', {name:'Next event',exact:true}).click(); await expect(timeline).toHaveValue('1');
    await page.getByRole('button', {name:'Previous event',exact:true}).click(); await expect(timeline).toHaveValue('0');
    await page.getByRole('combobox', {name:'History speed',exact:true}).selectOption('2');
    await page.getByRole('button', {name:'Play',exact:true}).click();
    await expect(page.getByRole('button', {name:'Pause',exact:true})).toBeVisible();
    await expect.poll(() => timeline.inputValue()).not.toBe('0');
    await page.getByRole('button', {name:'Pause',exact:true}).click();
    report.checks.push('Public Admin timeline, Previous/Next and Play/Pause use prefixed read-only history endpoints');
    const participantTab = await context.newPage();
    await participantTab.goto(origin + '/');
    await participantContext(participantTab);
    await participantTab.close();
    report.checks.push('Participant CMS context remains valid while Admin is authenticated on the same HTTPS origin');

    const logoutForm = page.locator('form').filter({has:page.locator('input[value="Logout"]')});
    await expect(logoutForm).toHaveCount(1);
    expect(await logoutForm.evaluate(node => new URL(node.action, document.URL).href)).toBe(admin + '/logout');
    await Promise.all([page.waitForURL(url => url.origin === origin && url.pathname === '/admin/login'), logoutForm.locator('input[type="submit"]').click()]);
    await deniedApi(context, listingUrl, 'Native XSRF-protected logout removes public Admin history access');
    await page.goBack();
    await deniedApi(context, listingUrl, 'Browser-back after logout cannot reacquire code history');
    await page.goto(route);
    expect(new URL(page.url()).pathname).toBe('/admin/login');
    await page.goto(origin + '/');
    await participantContext(page);
    expect(historyMutations).toBe(0);
    expect(escapedAdminRequests).toEqual([]);
    expect(serverErrors).toEqual([]);
    expect(errors).toEqual([]);
    report.historyMutationRequests = historyMutations;
    report.escapedAdminRequests = escapedAdminRequests;
    report.serverErrors = serverErrors;
    report.pageErrors = errors;
    report.status = 'passed';
    report.checks.push('Static assets, navigation, native forms and history requests stay under /admin/; no history mutations, server or page errors');
    console.log('PUBLIC_ADMIN_HTTPS_PASSED');
  } catch (error) {
    report.status = 'failed';
    report.error = safe(error.stack || error);
    report.pageErrors = errors;
    if (page) await page.screenshot({path:path.join(output, 'failure.png'),fullPage:true}).catch(() => {});
    throw error;
  } finally {
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2), {mode:0o600});
    await browser.close();
  }
})().catch(error => { console.error(safe(error.stack || error)); process.exitCode = 1; });
