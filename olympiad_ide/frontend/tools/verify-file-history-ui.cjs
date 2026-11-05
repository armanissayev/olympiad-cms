// Local synthetic UI behavior evidence, not CMS or Linux execution acceptance.
const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module');
const {chromium,expect}=createRequire(path.join(__dirname,'../package.json'))('@playwright/test');
const checkout=path.resolve(__dirname,'../../..');
let html=fs.readFileSync(path.join(checkout,'cms/server/admin/templates/ide_history.html'),'utf8');
html=html.slice(html.indexOf('{% block core %}')+'{% block core %}'.length,html.lastIndexOf('{% endblock core %}'));
html=html.replace(/{% for user in history_users %}[\s\S]*?{% endfor %}/,'<option value="352">Local participant</option><option value="353">Other participant</option>');
html=html.replace(/{% for task in history_tasks %}[\s\S]*?{% endfor %}/,'<option value="1">C++ sum</option><option value="2">Python sum</option>');
html=html.replace(/{{ url\('contest', contest.id, 'ide-history', 'api'\) }}/g,'/admin/contest/1/ide-history/api').replace(/{{ url\('submission'\) }}/g,'/admin/submission').replace(/{{ url\('static', 'ide_history.js'\) }}/g,'/admin/static/ide_history.js');
html='<!doctype html><html><head><meta charset="utf-8"></head><body>'+html+'</body></html>';
const script=fs.readFileSync(path.join(checkout,'cms/server/admin/static/ide_history.js'),'utf8');
const output=process.argv[2];if(!output||!path.isAbsolute(output))throw Error('Absolute private output directory required');if(fs.existsSync(output)){const info=fs.lstatSync(output);if(!info.isDirectory()||info.isSymbolicLink()||info.mode&0o077)throw Error('Private regular output directory required');}fs.mkdirSync(output,{recursive:true,mode:0o700});
const point=(id,sequence,kind,offset,inserted=0,markers=[])=>({id,sessionId:'00000000-0000-4000-8000-000000000001',sequence,kind,offsetMs:offset,timestamp:new Date(Date.UTC(2026,10,5,0,0,0)+offset).toISOString(),label:kind,inserted,deleted:0,editCount:kind==='editing'?1:0,keyboardInputs:kind==='editing'?1:0,markers});
const points=[point('initial',0,'initial',0),point('edit1',3,'editing',1000,1),point('edit2',20,'editing',10000,500,[{kind:'paste',label:'Paste recorded',detail:'Paste source is unknown.'},{kind:'large_insert',label:'Large insertion',detail:'500 characters inserted.'}]),point('edit3',28,'editing',120000,1),point('submit',30,'submission',121000)];
const timeline={fileId:'00000000-0000-4000-8000-000000000004',points,periods:[{sessionId:points[0].sessionId,label:'Editing session 1',startedAt:points[0].timestamp}],summary:{inserted:502,deleted:0,editCount:3,keyboardInputs:3,markerCount:2,periodCount:1},correlation:{state:'matched',detail:'Verified submitted bytes.'},thresholds:{largeInsertCharacters:250},partial:true,notices:['Earlier retained activity may be unavailable.','All uploaded source shown here is synthetic test data.']};
const files=[{fileId:'91',submissionId:'41',submittedAt:points[4].timestamp,filename:'main.%l',sourceFilename:'<script>alert(1)</script>.cpp',language:'C++',hasHistory:true},{fileId:'92',submissionId:'42',submittedAt:points[4].timestamp,filename:'main.%l',sourceFilename:'second.cpp',language:'C++',hasHistory:true},{fileId:'93',submissionId:'43',submittedAt:points[4].timestamp,filename:'main.cpp',sourceFilename:'external.cpp',language:'C++',hasHistory:false,reason:'No linked IDE receipt.'}];
const frames={0:null,3:'a',20:'a'+'x'.repeat(500),28:'a'+'x'.repeat(500)+'!',30:'a'+'x'.repeat(500)+'!'};
const requests=[],errors=[];let slowReplay=false,releaseReplay;
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH});
 const context=await browser.newContext({viewport:{width:1440,height:1100}}),page=await context.newPage();page.on('pageerror',error=>errors.push(String(error)));
 await page.route('http://history-viewer.invalid/**',async route=>{
  const u=new URL(route.request().url());requests.push({path:u.pathname,query:u.search,method:route.request().method()});
  if(u.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
  if(u.pathname.endsWith('/ide_history.js'))return route.fulfill({contentType:'application/javascript',body:script});
  if(u.pathname.endsWith('/api/files'))return route.fulfill({json:{files:u.searchParams.get('taskId')==='1'?files:[],nextBeforeSubmission:null,notice:''}});
  if(u.pathname.endsWith('/timeline'))return route.fulfill({json:timeline});
  if(u.pathname.endsWith('/replay')){
   if(slowReplay&&u.pathname.includes('/91/')){slowReplay=false;await new Promise(resolve=>{releaseReplay=resolve;});}
   const content=u.pathname.includes('/92/')?'Second file only':frames[Number(u.searchParams.get('through'))];
   return route.fulfill({json:{available:typeof content==='string',content,name:'file.cpp',sequence:Number(u.searchParams.get('through')),notices:content===null?['File not created yet.']:[],session:{id:points[0].sessionId}}}).catch(()=>{});
  }
  return route.abort();
 });
 const report={status:'running',kind:'local-synthetic-browser-UI-only',checks:[]};
 try{
  await page.goto('http://history-viewer.invalid/');
  await page.getByRole('combobox',{name:'History participant',exact:true}).selectOption('352');await page.getByRole('combobox',{name:'History problem',exact:true}).selectOption('1');
  await expect(page.locator('.history-file-card')).toHaveCount(3);expect(await page.getByRole('combobox',{name:'History recording',exact:true}).count()).toBe(0);
  await page.locator('button.history-file-select[data-file-id="91"]').click();await expect(page.locator('#history-source')).toHaveValue(frames[30]);
  await expect(page.locator('#history-filename')).toHaveText(files[0].sourceFilename);expect(await page.locator('#history-filename script').count()).toBe(0);
  await expect(page.locator('#history-correlation')).toHaveText('Submitted bytes matched');await expect(page.locator('#history-timeline')).toHaveAttribute('max','4');
  await expect(page.locator('#history-event')).not.toContainText('Event 30');
  await expect(page.locator('#history-notes')).not.toHaveAttribute('open','');await expect(page.locator('#history-notes-summary')).toHaveText('Some earlier activity is unavailable — details');
  await page.locator('#history-notes-summary').click();await expect(page.locator('#history-notices')).toContainText('Earlier retained activity may be unavailable.');await expect(page.locator('#history-notices')).toContainText('All uploaded source shown here is synthetic test data.');
  report.checks.push('Auto submitted-file list, inert fixed-file source and compressed timeline.');
  await page.locator('#history-timeline').focus();await page.locator('#history-timeline').press('Home');await expect(page.locator('#history-event')).toContainText('Starting snapshot');
  await page.getByRole('button',{name:'Play',exact:true}).click();await expect.poll(()=>page.locator('#history-timeline').inputValue()).toBe('1');await page.getByRole('button',{name:'Pause',exact:true}).click();await expect(page.locator('#history-source')).toHaveValue('a');report.checks.push('Playback progresses from an empty pre-file snapshot and skips waiting by default.');
  await page.getByRole('button',{name:'Paste recorded',exact:true}).click();await expect(page.locator('#history-timeline')).toHaveValue('2');await expect(page.locator('#history-source')).toHaveValue(frames[20]);
  await page.getByRole('checkbox',{name:'Compare previous period',exact:true}).check();await expect(page.locator('#history-before')).toHaveValue('a');await expect(page.locator('#history-source')).toHaveValue(frames[20]);
  await page.getByRole('checkbox',{name:'Marked periods only',exact:true}).check();await expect(page.locator('#history-timeline')).toHaveAttribute('max','2');await expect(page.locator('#history-timeline')).toHaveValue('1');report.checks.push('Marker jump, previous-period comparison and marked-only initial/submission boundaries.');
  await page.getByRole('checkbox',{name:'Marked periods only',exact:true}).uncheck();
  await page.getByRole('checkbox',{name:'Compare previous period',exact:true}).uncheck();
  await page.locator('#history-timeline').focus();await page.locator('#history-timeline').press('Home');
  await expect(page.locator('#history-event')).not.toContainText('loading source');
  const playbackStart=requests.length;slowReplay=true;releaseReplay=null;
  await page.getByRole('button',{name:'Play',exact:true}).click();await expect.poll(()=>!!releaseReplay).toBe(true);
  await page.getByRole('combobox',{name:'History speed',exact:true}).selectOption('2');
  await page.getByRole('button',{name:'Pause',exact:true}).click();await page.getByRole('button',{name:'Play',exact:true}).click();
  releaseReplay();await expect(page.locator('#history-timeline')).toHaveValue('4');await expect(page.locator('#history-source')).toHaveValue(frames[30]);
  await expect(page.getByRole('button',{name:'Play',exact:true})).toBeVisible();
  const advances=requests.slice(playbackStart).filter(row=>row.path.endsWith('/replay')).map(row=>Number(new URLSearchParams(row.query).get('through')));
  expect(advances).toEqual([3,20,28,30]);
  report.checks.push('Changing speed and Pause/Play during a delayed replay produces exactly one advance per period.');
  await page.getByRole('button',{name:'Paste recorded',exact:true}).click();await page.getByRole('checkbox',{name:'Compare previous period',exact:true}).check();await expect(page.locator('#history-before')).toHaveValue('a');
  await expect(page.locator('#history-notes')).toHaveAttribute('open','');await page.locator('#history-notes-summary').click();
  await page.screenshot({path:path.join(output,'submitted-file-markers.png'),fullPage:true});
  await page.setViewportSize({width:390,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:path.join(output,'submitted-file-mobile.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:1100});
  await page.getByRole('checkbox',{name:'Marked periods only',exact:true}).check();
  slowReplay=true;releaseReplay=null;await page.getByRole('button',{name:'Previous period',exact:true}).click();await expect.poll(()=>!!releaseReplay).toBe(true);
  await page.locator('button.history-file-select[data-file-id="92"]').click();await expect(page.locator('#history-source')).toHaveValue('Second file only');await expect(page.locator('#history-notes')).not.toHaveAttribute('open','');releaseReplay();await page.waitForTimeout(60);await expect(page.locator('#history-source')).toHaveValue('Second file only');report.checks.push('Delayed old-file response cannot replace newly selected source.');
  await page.locator('button.history-file-select[data-file-id="93"]').click();await expect(page.locator('#history-source')).toHaveValue('');await expect(page.locator('#history-player')).toBeHidden();await expect(page.locator('#history-empty')).toContainText('No linked IDE receipt.');
  await page.getByRole('combobox',{name:'History problem',exact:true}).selectOption('2');await expect(page.locator('.history-file-card')).toHaveCount(0);await expect(page.locator('#history-source')).toHaveValue('');report.checks.push('Unavailable history and problem change clear prior source.');
  expect(errors).toEqual([]);expect(requests.filter(row=>row.method!=='GET')).toEqual([]);report.status='passed';report.pageErrors=errors;report.requests=requests;console.log('LOCAL_HISTORY_VIEWER_PASSED');
 }catch(error){report.status='failed';report.error=String(error.stack||error);await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;}
 finally{fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(report,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
