// Public-IP staging acceptance with ordinary browser/Node TLS validation; no certificate bypass.
const path=require('node:path');
const fs=require('node:fs');const {createRequire}=require('node:module');const {createHash}=require('node:crypto');
const localRequire=createRequire(path.join(__dirname,'../package.json'));const {chromium,expect}=localRequire('@playwright/test');
const fixture=process.argv[2];
if(!fixture)throw new Error('Usage: node tools/verify-public-staging.cjs <disposable-fixture.json> <output-directory>');
const metadata=JSON.parse(fs.readFileSync(fixture,'utf8'));
if(metadata.kind!=='disposable-linux-staging')throw new Error('Explicit disposable Linux staging fixture required');
const origin=new URL(metadata.baseUrl);
if(origin.protocol!=='https:'||origin.hostname!=='54.206.171.67')throw new Error('Only the explicitly authorized public staging IP is allowed');
const output=path.resolve(process.argv[3]||'test-results/native-cms');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({...(process.env.PLAYWRIGHT_CHROMIUM_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH}:{}),headless:true});
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
  await expect(page.locator('.cms-bar')).toBeVisible({timeout:120000});
  console.log('native bar',await page.locator('.cms-bar').innerText());
  await expect(page.getByRole('textbox',{name:'Editor content',exact:true})).toBeVisible({timeout:20000});
  await expect(page.getByRole('button',{name:'Run',exact:true})).toBeEnabled({timeout:20000});
  await expect(page.getByRole('button',{name:'Synchronization: Synced',exact:true}).first()).toBeVisible({timeout:30000});
  const editor=page.getByRole('textbox',{name:'Editor content',exact:true});
  const source='#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n';
  await editor.press('ControlOrMeta+a');await page.keyboard.insertText(source);

  const customResults=[];
  async function scopedJson(route){return page.evaluate(async route=>{
   const bootstrap=await (await fetch('/ide/api/context')).json();
   const task=document.querySelector('select[aria-label="Contest task"]').value;
   const response=await fetch(route,{headers:{'X-Olympiad-Principal':bootstrap.identity.principalId,'X-Olympiad-Task':task}});
   if(!response.ok)throw new Error('Scoped request failed '+response.status);return response.json();
  },route)}
  async function jobState(id){return scopedJson('/ide/api/runtime/v1/executions/'+id)}
  async function awaitJob(id,status){await expect.poll(async()=> (await jobState(id)).status,{timeout:60000,intervals:[150,300,500]}).toBe(status);return jobState(id)}
  await page.getByRole('textbox',{name:'Standard input',exact:true}).fill('2 3\n');
  let runningResponse=page.waitForResponse(r=>r.url().endsWith('/ide/api/runtime/v1/executions')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Run',exact:true}).click();
  let response=await runningResponse;expect(response.status()).toBe(201);let custom=await response.json();
  let completed=await awaitJob(custom.id,'FINISHED');
  expect(completed.result.cases[0].stdout).toBe('5\n');expect(completed.result.cases[0].wallTime).not.toBeNull();expect(completed.result.cases[0].peakMemoryKiB).not.toBeNull();expect(completed.result.toolchainVersion).toMatch(/g\+\+|GCC/);
  customResults.push({id:completed.id,status:completed.status,result:completed.result});console.log('Real isolated custom Run measured',completed.id);
  await page.reload();await expect(page.getByRole('textbox',{name:'Editor content',exact:true})).toBeVisible({timeout:20000});
  await expect(page.locator('.execution-summary').first()).toContainText('FINISHED',{timeout:20000});
  await page.getByRole('button',{name:'Test Cases',exact:true}).click();await page.getByRole('button',{name:'New Test',exact:true}).click();
  await page.getByRole('textbox',{name:'Test name',exact:true}).fill('Exact match');await page.getByRole('textbox',{name:'Test stdin',exact:true}).fill('2 3\n');
  await page.getByRole('checkbox',{name:'Compare expected stdout'}).check();await page.getByRole('textbox',{name:'Expected stdout',exact:true}).fill('5\n');
  await page.getByRole('button',{name:'Duplicate test',exact:true}).click();await page.getByRole('textbox',{name:'Test name',exact:true}).fill('Whitespace mismatch');await page.getByRole('textbox',{name:'Expected stdout',exact:true}).fill('5 \n');
  runningResponse=page.waitForResponse(r=>r.url().endsWith('/ide/api/runtime/v1/executions')&&r.request().method()==='POST');await page.getByRole('button',{name:'Run All',exact:true}).click();
  response=await runningResponse;expect(response.status()).toBe(201);custom=await response.json();completed=await awaitJob(custom.id,'FINISHED');
  await expect(page.locator('.test-result summary').filter({hasText:'Exact match'})).toContainText('Accepted',{timeout:20000});await expect(page.locator('.test-result summary').filter({hasText:'Whitespace mismatch'})).toContainText('Wrong Answer');
  customResults.push({id:completed.id,status:completed.status,result:completed.result});
  await editor.press('ControlOrMeta+a');await page.keyboard.insertText('#include <unistd.h>\nint main(){sleep(4);}\n');
  runningResponse=page.waitForResponse(r=>r.url().endsWith('/ide/api/runtime/v1/executions')&&r.request().method()==='POST');await page.getByRole('button',{name:'Run All',exact:true}).click();
  response=await runningResponse;expect(response.status()).toBe(201);custom=await response.json();await awaitJob(custom.id,'RUNNING');await page.getByRole('button',{name:'Stop execution',exact:true}).click();
  completed=await awaitJob(custom.id,'CANCELLED');customResults.push({id:completed.id,status:completed.status});console.log('Real isolated running cancellation verified',completed.id);
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
  await expect.poll(async()=> (await scopedJson('/ide/api/submissions/status/'+cppReceipt.submissionId+'?taskId='+metadata.tasks.find(t=>t.name==='cppsum').id)).status.status,{timeout:60000}).toBe(5);
  await page.locator('.cms-history button').filter({hasText:cppReceipt.submissionId}).click();
  await expect(page.getByText('Public score: 25 / 25',{exact:true})).toBeVisible({timeout:20000});
  await page.getByRole('button',{name:'Close CMS panel',exact:true}).click();
  await page.getByRole('combobox',{name:'Contest task',exact:true}).selectOption(String(metadata.tasks.find(t=>t.name==='pysum').id));
  await expect(page.getByRole('textbox',{name:'Editor content',exact:true})).toBeVisible({timeout:20000});
  await expect(page.getByRole('button',{name:'Synchronization: Synced',exact:true}).first()).toBeVisible({timeout:30000});
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
  await expect.poll(async()=> (await scopedJson('/ide/api/submissions/status/'+lostReceipt.submissionId+'?taskId='+metadata.tasks.find(t=>t.name==='pysum').id)).status.status,{timeout:60000}).toBe(5);
  await page.locator('.cms-history button').filter({hasText:lostReceipt.submissionId}).click();
  await expect(page.getByText('Public score: 25 / 25',{exact:true})).toBeVisible({timeout:20000});
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
  fs.writeFileSync(path.join(output,'linux-native-browser-results.json'),JSON.stringify({customResults,cppReceipt,pythonReceipt:lostReceipt,postCount,serviceWorkerScope:scope,cacheEntries:cached.length,retainedScopedDatabases:retained,errors,checks:['CMS login','native context and Monaco','real isolate custom Run with measured output','compile-once Run All exact/mismatch','running Stop cancellation','custom reload recovery','task-bound workspace switch','real CMS judging and visible public scores','C++ immutable exact-byte admission','Python response loss and reload reconciliation','official history','/ide/ offline shell and Monaco workers','authentication recovery','real CSRF logout and retained local data']},null,2));
  console.log('errors',errors);

 }catch(error){console.error('Page diagnostics',JSON.stringify({url:page.url(),errors,body:(await page.locator('body').innerText()).slice(0,1200)}));await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
