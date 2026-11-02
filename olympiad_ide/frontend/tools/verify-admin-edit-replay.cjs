// Read-only proof of an actual uploaded participant edit, using only private pinned CMS Admin.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process'),{createRequire}=require('node:module');
const {chromium,expect}=createRequire(path.join(__dirname,'../package.json'))('@playwright/test');
const [fixturePath,output,participantPath]=process.argv.slice(2);
if(!fixturePath||!output||!participantPath)throw Error('Protected fixture, output and participant evidence required');
if(fs.statSync(fixturePath).mode&0o077)throw Error('Fixture must be private');
const metadata=JSON.parse(fs.readFileSync(fixturePath,'utf8')),participant=JSON.parse(fs.readFileSync(participantPath,'utf8'));
if(metadata.kind!=='disposable-linux-staging'||metadata.adminUrl!=='https://localhost:28444'||metadata.baseUrl!=='https://54.206.171.67')throw Error('Exact authorized staging fixture required');
const expected=participant.sourceFixtures.find(row=>row.task==='cppsum'),task=metadata.tasks.find(row=>row.name==='cppsum');
const allowed=new Set(participant.telemetrySessions.filter(row=>String(row.taskId)===String(task.id)).map(row=>row.id));
const pub=execFileSync('openssl',['x509','-in','/private/tmp/cms-linux-staging/localhost.crt','-pubkey','-noout']);
const pin=crypto.createHash('sha256').update(execFileSync('openssl',['pkey','-pubin','-outform','der'],{input:pub})).digest('base64');
const hash=text=>crypto.createHash('sha256').update(text).digest('hex');fs.mkdirSync(output,{recursive:true,mode:0o700});
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_PATH?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH}:{}),args:[`--ignore-certificate-errors-spki-list=${pin}`]});
 const report={status:'running',participantUserId:String(metadata.acceptanceUserId),taskId:String(task.id),historyMutationRequests:0},errors=[];let page;
 try{
  page=await(await browser.newContext({viewport:{width:1440,height:1050}})).newPage();page.on('pageerror',error=>errors.push(error.message));page.on('request',r=>{if(r.url().includes('/ide-history/api/')&&r.method()!=='GET')report.historyMutationRequests++;});
  await page.goto(metadata.adminUrl+'/');const login=await page.evaluate(async credentials=>{const csrf=decodeURIComponent(document.cookie.split('; ').find(v=>v.startsWith('_xsrf='))?.slice(6)||'');const r=await fetch('/login',{method:'POST',body:new URLSearchParams({...credentials,_xsrf:csrf})});return {status:r.status,url:r.url};},{username:metadata.adminUsername,password:metadata.adminPassword});expect(login.status).toBe(200);expect(new URL(login.url).pathname).not.toBe('/login');
  const base='/contest/'+metadata.contestId+'/ide-history';await page.goto(metadata.adminUrl+base);await expect(page.getByRole('heading',{name:'Participant code history',exact:true})).toBeVisible();
  const params=()=>new URLSearchParams({userId:String(metadata.acceptanceUserId),taskId:String(task.id)});
  async function read(suffix,through){const query=params();if(through!==undefined)query.set('through',String(through));return page.evaluate(async route=>{const r=await fetch(route,{cache:'no-store'});if(r.status!==200)throw Error('Admin read failed: '+r.status);return r.json();},base+'/api/'+suffix+'?'+query);}
  const list=await read('sessions');let found=null;
  const node=frame=>Object.values(frame.nodes).find(value=>value.type==='file'&&value.name===expected.filename);
  let readCount=1;
  for(const session of list.sessions.filter(row=>allowed.has(row.id)&&row.lastSequence>1).sort((a,b)=>b.lastSequence-a.lastSequence)){
   const zero=await read('sessions/'+session.id+'/replay',0),last=await read('sessions/'+session.id+'/replay',session.lastSequence);readCount+=2;
   if(!zero.available||!last.available||node(zero)?.content===expected.sourceText||node(last)?.content!==expected.sourceText)continue;
   let low=1,high=session.lastSequence;
   while(low<high){const middle=Math.floor((low+high)/2),frame=await read('sessions/'+session.id+'/replay',middle);readCount++;expect(frame.available).toBe(true);if(node(frame)?.content===expected.sourceText)high=middle;else low=middle+1;}
   const before=await read('sessions/'+session.id+'/replay',low-1),after=await read('sessions/'+session.id+'/replay',low);readCount+=2;
   if(node(before)?.content===expected.sourceText||node(after)?.content!==expected.sourceText)continue;
   expect(['FILE_CREATED','TEXT_INSERT','TEXT_DELETE','TEXT_REPLACE','DOCUMENT_CHANGE','UNDO','REDO','WORKSPACE_RECONCILED']).toContain(after.event?.eventType);
   found={session,zero,before,after,sequence:low};break;
  }
  expect(found).not.toBeNull();
  await page.getByRole('combobox',{name:'History participant',exact:true}).selectOption(String(metadata.acceptanceUserId));await page.getByRole('combobox',{name:'History problem',exact:true}).selectOption(String(task.id));await page.getByRole('button',{name:'Load recordings',exact:true}).click();await expect(page.getByRole('combobox',{name:'History recording',exact:true}).locator('option[value="'+found.session.id+'"]')).toHaveCount(1);await page.getByRole('combobox',{name:'History recording',exact:true}).selectOption(found.session.id);await expect(page.locator('#history-event')).toContainText('Event 0 /');
  async function seekUI(sequence,frame,label){const timeline=page.getByRole('slider',{name:'History timeline',exact:true});const waited=page.waitForResponse(r=>r.url().includes('/sessions/'+found.session.id+'/replay?')&&new URL(r.url()).searchParams.get('through')===String(sequence));await timeline.evaluate((element,value)=>{element.value=String(value);element.dispatchEvent(new Event('input',{bubbles:true}));},sequence);expect((await waited).status()).toBe(200);await expect(page.locator('#history-event')).toContainText('Event '+sequence+' /');const selected=node(frame);if(selected){await page.getByRole('combobox',{name:'History source file',exact:true}).selectOption(selected.id);await expect(page.getByRole('textbox',{name:'Historical source',exact:true})).toHaveValue(selected.content);}else{expect(await page.getByRole('combobox',{name:'History source file',exact:true}).locator('option').evaluateAll((options,name)=>options.some(o=>o.textContent.endsWith(name)),expected.filename)).toBe(false);}await expect(page.locator('#history-source')).toHaveAttribute('readonly','');await page.screenshot({path:path.join(output,'admin-edit-'+label+'.png'),fullPage:true});}
  await seekUI(found.sequence-1,found.before,'before');await seekUI(found.sequence,found.after,'after');
  const first=node(found.before),final=node(found.after);expect(hash(final.content)).toBe(expected.sha256);expect(first?.content).not.toBe(final.content);
  report.recordingId=found.session.id;report.lastSequence=found.session.lastSequence;report.selectedEditSequence=found.sequence;report.actualEventType=found.after.event.eventType;report.eventId=found.after.event.eventId;report.sourceFile=expected.filename;report.before={sequence:found.sequence-1,fileExists:!!first,contentSha256:first?hash(first.content):null,characters:first?.content.length??0};report.after={sequence:found.sequence,fileExists:true,contentSha256:hash(final.content),characters:final.content.length};report.initialFileExists=!!node(found.zero);report.checkpointSequence=found.after.checkpointSequence;report.nativeReadRequestsForSearch=readCount;report.expectedParticipantSourceMatched=true;report.actualAdminUiBeforeAfterSeekVerified=true;expect(report.historyMutationRequests).toBe(0);expect(errors).toEqual([]);report.pageErrors=errors;report.status='passed';console.log('ADMIN_EDIT_REPLAY_PASSED',report.recordingId,report.actualEventType,report.selectedEditSequence);
 }catch(error){report.status='failed';report.error=String(error);if(page)await page.screenshot({path:path.join(output,'admin-edit-failure.png'),fullPage:true});throw error;}
 finally{fs.writeFileSync(path.join(output,'replay-edit.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
