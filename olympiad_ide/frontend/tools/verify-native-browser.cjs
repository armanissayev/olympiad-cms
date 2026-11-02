// Real disposable CMS browser acceptance. Never point this at a live contest.
const path=require('node:path');
const fs=require('node:fs');const {createRequire}=require('node:module');const {execFileSync}=require('node:child_process');const {createHash}=require('node:crypto');
const localRequire=createRequire(path.join(__dirname,'../package.json'));const {chromium,expect}=localRequire('@playwright/test');
const fixture=process.argv[2];
if(!fixture)throw new Error('Usage: node tools/verify-native-browser.cjs <disposable-fixture.json> <output-directory>');
const metadata=JSON.parse(fs.readFileSync(fixture,'utf8'));
const origin=new URL(metadata.baseUrl);
if(origin.protocol!=='https:'||!['localhost','127.0.0.1','[::1]'].includes(origin.hostname))throw new Error('This verification tool only accepts a local disposable HTTPS fixture');
if(process.env.NODE_EXTRA_CA_CERTS!==metadata.certificate){
 const {spawnSync}=require('node:child_process');
 const child=spawnSync(process.execPath,[__filename,...process.argv.slice(2)],{stdio:'inherit',env:{...process.env,NODE_EXTRA_CA_CERTS:metadata.certificate}});
 process.exit(child.status??1);
}
const output=path.resolve(process.argv[3]||'test-results/native-cms');fs.mkdirSync(output,{recursive:true});
const pub=execFileSync('openssl',['x509','-in',metadata.certificate,'-pubkey','-noout']);const der=execFileSync('openssl',['pkey','-pubin','-outform','der'],{input:pub});const pin=createHash('sha256').update(der).digest('base64');
(async()=>{
 const browser=await chromium.launch({...(process.env.PLAYWRIGHT_CHROMIUM_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH}:{}),headless:true,args:[`--ignore-certificate-errors-spki-list=${pin}`]});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(metadata.baseUrl+'/');
  const result=await page.evaluate(async credentials=>{
   const csrf=document.cookie.split('; ').find(v=>v.startsWith('_xsrf='))?.slice(6);
   const body=new URLSearchParams({...credentials,_xsrf:decodeURIComponent(csrf||'')});
   const response=await fetch('/login',{method:'POST',body,credentials:'same-origin'});return {status:response.status,url:response.url};
  },{username:metadata.username,password:metadata.password});
  console.log('real CWS login',result);
  await page.goto(metadata.baseUrl+'/ide/');
  await expect(page.locator('.cms-bar')).toBeVisible({timeout:20000});
  console.log('native bar',await page.locator('.cms-bar').innerText());
  await expect(page.getByRole('textbox',{name:'Editor content',exact:true})).toBeVisible({timeout:20000});
  await expect(page.getByRole('button',{name:'Run',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Synchronization: Synced',exact:true}).first()).toBeVisible({timeout:30000});
  const editor=page.getByRole('textbox',{name:'Editor content',exact:true});
  const source='#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n';
  await editor.press('ControlOrMeta+a');await page.keyboard.insertText(source);
  await page.getByRole('button',{name:'Submit & official feedback',exact:true}).click();
  await page.getByRole('combobox',{name:'CMS submission language'}).selectOption('C++17 / g++');
  const fileSelect=page.locator('select[aria-label^="Source file for "]');
  const cppValue=await fileSelect.locator('option').evaluateAll(nodes=>nodes.find(n=>n.textContent.endsWith('main.cpp')).value);
  await fileSelect.selectOption(cppValue);await page.getByRole('button',{name:'Capture source for review',exact:true}).click();
  await expect(page.getByRole('region',{name:'Confirm immutable submission'}).locator('pre')).toHaveText(source);
  await editor.press('ControlOrMeta+a');await page.keyboard.insertText('// changed after capture\n');
  const received=page.waitForResponse(r=>r.url().endsWith('/ide/api/submissions')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Confirm and submit captured source',exact:true}).click();
  const cppResponse=await received; const cppReceipt=await cppResponse.json();
  console.log('C++ native receipt',cppResponse.status(),cppReceipt.state,cppReceipt.submissionId);
  expect(cppResponse.ok()).toBeTruthy();expect(cppReceipt.files[0].sha256).toBe(createHash('sha256').update(source).digest('hex'));
  expect(cppResponse.request().postDataJSON().files[0].content).toBe(source);
  await expect(page.getByText(`CMS received ${cppReceipt.submissionId}`,{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Close CMS panel',exact:true}).click();
  await page.getByRole('tab',{name:/solution.py/}).click();await editor.press('ControlOrMeta+a');await page.keyboard.insertText('a,b=map(int,input().split())\nprint(a+b)\n');
  await page.getByRole('button',{name:'Submit & official feedback',exact:true}).click();
  await page.getByRole('combobox',{name:'CMS submission language'}).selectOption('Python 3 / CPython');
  const pyValue=await fileSelect.locator('option').evaluateAll(nodes=>nodes.find(n=>n.textContent.endsWith('solution.py')).value);
  await fileSelect.selectOption(pyValue);await page.getByRole('button',{name:'Capture source for review',exact:true}).click();
  let lostReceipt; let postCount=0;
  await page.route('**/ide/api/submissions',async route=>{
   if(route.request().method()!=='POST'){await route.continue();return}postCount++;const response=await route.fetch();lostReceipt=await response.json();await route.abort('failed');
  });
  await page.getByRole('button',{name:'Confirm and submit captured source',exact:true}).click();
  await expect(page.getByText('Outcome unknown — resolve receipt before retry',{exact:true})).toBeVisible();
  await page.unroute('**/ide/api/submissions');await page.reload();
  await page.getByRole('button',{name:'Submit & official feedback',exact:true}).click();
  await expect(page.getByText(`CMS received ${lostReceipt.submissionId}`,{exact:true})).toBeVisible({timeout:20000});
  expect(postCount).toBe(1);console.log('Python lost-ack reload reconciled',lostReceipt.submissionId,'single POST');
  await expect(page.locator('.cms-history').filter({hasText:lostReceipt.submissionId}).first()).toBeVisible();
  await page.screenshot({path:path.join(output,'native-submit.png'),fullPage:true});
  const scope=await page.evaluate(async()=> (await navigator.serviceWorker.ready).scope);expect(scope).toBe(metadata.baseUrl+'/ide/');
  const cached=await page.evaluate(async()=> (await Promise.all((await caches.keys()).filter(k=>k.startsWith('olympiad-shell-')).map(async key=>(await (await caches.open(key)).keys()).map(r=>r.url)))).flat());
  expect(cached.every(url=>url.startsWith(metadata.baseUrl+'/ide/')&&!url.includes('/api/'))).toBeTruthy();
  await page.getByRole('button',{name:'Close CMS panel',exact:true}).click();
  await context.setOffline(true);await page.reload();
  await expect(page.getByRole('textbox',{name:'Editor content',exact:true})).toBeVisible({timeout:20000});
  await expect(page.locator('.cms-auth-notice')).toContainText('Offline recovery');
  await expect(page.locator('.view-lines').first()).toContainText('print(a+b)');
  await context.setOffline(false);await page.getByRole('button',{name:'Check authentication',exact:true}).click();
  await expect(page.locator('.cms-auth-notice')).toHaveCount(0);console.log('native offline reload and authentication recovery passed');
  await page.getByRole('button',{name:'Submit & official feedback',exact:true}).click();
  await Promise.all([page.waitForURL(metadata.baseUrl+'/'),page.getByRole('button',{name:'CMS logout',exact:true}).click()]);
  await page.goto(metadata.baseUrl+'/ide/');await expect(page.locator('.cms-entry')).toContainText('Sign in');
  const retained=await page.evaluate(async()=> (await indexedDB.databases()).filter(db=>db.name.startsWith('olympiad-ide.cms.')).length);expect(retained).toBeGreaterThan(0);
  console.log('real CWS logout blocks IDE and retains scoped local database');
  expect(errors).toEqual([]);
  fs.writeFileSync(path.join(output,'native-browser-results.json'),JSON.stringify({cppReceipt,pythonReceipt:lostReceipt,postCount,serviceWorkerScope:scope,cacheEntries:cached.length,retainedScopedDatabases:retained,errors,checks:['CMS login','native context and Monaco','Run disabled without workers','C++ immutable exact-byte admission','Python response loss and reload reconciliation','official history','/ide/ offline shell and Monaco workers','authentication recovery','real CSRF logout and retained local data']},null,2));
  console.log('errors',errors);

 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
