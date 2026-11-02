// Read-only real CMS Admin history acceptance. Private localhost certificate is pinned exactly.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process'),{createRequire}=require('node:module');
const {chromium,expect}=createRequire(path.join(__dirname,'../package.json'))('@playwright/test');
const [fixturePath,output,participantResultsPath]=process.argv.slice(2);
if(!fixturePath||!output)throw Error('Protected staging fixture and output directory required');
if(fs.statSync(fixturePath).mode&0o077)throw Error('Protected fixture must have mode0600');
const metadata=JSON.parse(fs.readFileSync(fixturePath,'utf8'));
if(metadata.kind!=='disposable-linux-staging'||metadata.baseUrl!=='https://54.206.171.67'||metadata.adminUrl!=='https://localhost:28444')throw Error('Exact authorized staging and private Admin fixture required');
if(!metadata.acceptanceUserId)throw Error('A fresh authorized acceptance actor is required');
const certificate='/private/tmp/cms-linux-staging/localhost.crt';
const publicKey=execFileSync('openssl',['x509','-in',certificate,'-pubkey','-noout']);
const der=execFileSync('openssl',['pkey','-pubin','-outform','der'],{input:publicKey});
const pin=crypto.createHash('sha256').update(der).digest('base64');
const participant=participantResultsPath?JSON.parse(fs.readFileSync(participantResultsPath,'utf8')):null;
const expected=participant?.sourceFixtures?.find(row=>row.task==='cppsum');
const task=metadata.tasks.find(row=>row.name==='cppsum');if(!task)throw Error('Disposable C++ task missing');
fs.mkdirSync(output,{recursive:true,mode:0o700});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH}:{}),args:[`--ignore-certificate-errors-spki-list=${pin}`]});
 const report={status:'running',privateAdmin:metadata.adminUrl,certificatePublicKeySha256:pin,participantUserId:String(metadata.acceptanceUserId),taskId:String(task.id),checks:[]},errors=[];
 let page;
 async function login(target,username,password){const origin=new URL(target.url());if(origin.protocol!=='https:'||origin.hostname!=='localhost'||!['28443','28444'].includes(origin.port))throw Error('Private native login origin required');return target.evaluate(async credentials=>{const csrf=decodeURIComponent(document.cookie.split('; ').find(value=>value.startsWith('_xsrf='))?.slice(6)||'');const response=await fetch('/login',{method:'POST',credentials:'same-origin',body:new URLSearchParams({...credentials,_xsrf:csrf})});if(!response.ok)throw Error('Native login failed');return {status:response.status,url:response.url};},{username,password});}
 try{
  const route=metadata.adminUrl+'/contest/'+metadata.contestId+'/ide-history';
  const guest=await browser.newContext();const guestPage=await guest.newPage();await guestPage.goto(route);expect(new URL(guestPage.url()).pathname).toBe('/login');await guest.close();report.checks.push('Unauthenticated private Admin history redirects to CMS Admin login');
  const contestant=await browser.newContext();const contestantPage=await contestant.newPage();
  await contestantPage.goto('https://localhost:28443/');await login(contestantPage,metadata.username,metadata.password);
  const participantContext=await contestantPage.evaluate(async()=>{const response=await fetch('/ide/api/context',{cache:'no-store'});return {status:response.status,body:await response.json()};});expect(participantContext.status).toBe(200);expect(String(participantContext.body.identity.userId)).toBe(String(metadata.acceptanceUserId));expect(participantContext.body.user.username).toBe(metadata.username);report.actualParticipantContextVerified=true;
  await contestantPage.goto(route);expect(new URL(contestantPage.url()).pathname).toBe('/login');await contestant.close();report.checks.push('Actual participant cookie does not authorize private Admin history');
  const context=await browser.newContext({viewport:{width:1440,height:1050}});page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  let historyMutations=0;page.on('request',request=>{if(request.url().includes('/ide-history/api/')&&request.method()!=='GET')historyMutations++;});
  await page.goto(metadata.adminUrl+'/');const adminLogin=await login(page,metadata.adminUsername,metadata.adminPassword);expect(new URL(adminLogin.url).pathname).not.toBe('/login');await page.goto(route);
  await expect(page.getByRole('heading',{name:'Participant code history',exact:true})).toBeVisible();await expect(page.getByRole('link',{name:'Code history',exact:true})).toBeVisible();
  await page.getByRole('combobox',{name:'History participant',exact:true}).selectOption(String(metadata.acceptanceUserId));
  await page.getByRole('combobox',{name:'History problem',exact:true}).selectOption(String(task.id));
  const listing=page.waitForResponse(response=>response.url().includes('/ide-history/api/sessions?')&&response.request().method()==='GET');
  await page.getByRole('button',{name:'Load recordings',exact:true}).click();const listResponse=await listing;expect(listResponse.status()).toBe(200);const listed=await listResponse.json();
  const sessions=listed.sessions.filter(row=>row.lastSequence>1);expect(sessions.length).toBeGreaterThan(0);
  let selected=null;
  for(const session of sessions){
   await page.getByRole('combobox',{name:'History recording',exact:true}).selectOption(session.id);
   await expect(page.locator('#history-status')).toContainText('Uploaded recording:');
   const timeline=page.getByRole('slider',{name:'History timeline',exact:true});
   const replaying=page.waitForResponse(response=>response.url().includes('/sessions/'+session.id+'/replay?')&&new URL(response.url()).searchParams.get('through')===String(session.lastSequence));
   await timeline.focus();await timeline.press('End');const replayResponse=await replaying;expect(replayResponse.status()).toBe(200);const frame=await replayResponse.json();expect(frame.available).toBe(true);
   await expect(timeline).toHaveValue(String(session.lastSequence));
   const sources=Object.values(frame.nodes).filter(node=>node.type==='file');
   const node=expected?sources.find(node=>node.name===expected.filename):sources.find(node=>typeof node.content==='string'&&node.content.length>0);
   if(!node)continue;
   await page.getByRole('combobox',{name:'History source file',exact:true}).selectOption(node.id);
   const source=page.getByRole('textbox',{name:'Historical source',exact:true});await expect(source).toHaveValue(node.content);await expect(source).toHaveAttribute('readonly','');
   const hash=crypto.createHash('sha256').update(node.content).digest('hex');
   if(expected){expect(node.content).toBe(expected.sourceText);expect(hash).toBe(expected.sha256);}
   selected={id:session.id,lastSequence:session.lastSequence,sourceFile:node.name,sourceSha256:hash,checkpointSequence:frame.checkpointSequence,integrity:session.integrity};break;
  }
  expect(selected).not.toBeNull();report.recording=selected;report.expectedParticipantSourceMatched=!!expected;
  const source=page.getByRole('textbox',{name:'Historical source',exact:true}),timeline=page.getByRole('slider',{name:'History timeline',exact:true});
  const before=await source.inputValue();await source.focus();await page.keyboard.type('should-not-edit-recorded-source');expect(await source.inputValue()).toBe(before);
  await timeline.focus();await timeline.press('Home');await expect(timeline).toHaveValue('0');await expect(page.locator('#history-event')).toContainText('Event 0 /');
  await page.getByRole('button',{name:'Next event',exact:true}).click();await expect(timeline).toHaveValue('1');
  await page.getByRole('button',{name:'Previous event',exact:true}).click();await expect(timeline).toHaveValue('0');
  await page.getByRole('combobox',{name:'History speed',exact:true}).selectOption('2');
  await page.getByRole('button',{name:'Play',exact:true}).click();await expect(page.getByRole('button',{name:'Pause',exact:true})).toBeVisible();await expect.poll(()=>timeline.inputValue()).not.toBe('0');await page.getByRole('button',{name:'Pause',exact:true}).click();
  report.checks.push('Authenticated full CMS Admin selects actual participant/problem and reads uploaded source from a separate browser');
  report.checks.push('Server checkpoint timeline, Previous/Next and actual Play/Pause/speed work; source is read-only');
  report.historyMutationRequests=historyMutations;expect(historyMutations).toBe(0);expect(errors).toEqual([]);report.pageErrors=errors;report.status='passed';await page.screenshot({path:path.join(output,'admin-code-history.png'),fullPage:true});await page.getByRole('combobox',{name:'History participant',exact:true}).selectOption('');await expect(page.locator('#history-source')).toHaveValue('');await expect(page.locator('#history-file option')).toHaveCount(0);await expect(page.locator('#history-player')).toBeHidden();report.checks.push('Changing reviewed participant immediately clears prior source and metadata');console.log('ADMIN_HISTORY_PASSED');
 }catch(error){report.status='failed';report.error=String(error);report.pageErrors=errors;if(page)await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;}
 finally{fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
