"""Build bounded valid fixture payloads; generated credentials/source stay outside repo."""
import hashlib,json,platform,secrets,subprocess,uuid
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
root=Path('/var/lib/cms-ide-stage/fixture');out=root/'load';out.mkdir(mode=0o700)
meta=json.loads((root/'browser.json').read_text());assert meta['kind']=='disposable-linux-staging' and meta['contestName']=='ide-load-linux-staging'
def uid():return str(uuid.uuid4())
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
def save(name,value):
 p=out/name;assert not p.exists();p.write_text(json.dumps(value,separators=(',',':'))+'\n');p.chmod(0o600);return str(p)
credentials=json.loads((root/'load-credentials.json').read_text());timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
source='#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n'+('// Representative staging editor source padding.\n'*12)
for actor in credentials:
 wid,fid,sid,sid2=uid(),uid(),uid(),uid();v={'workspaceId':wid,'fileId':fid,'sessionId':sid,'finalSessionId':sid2,'checkpointId':uid(),'finalCheckpointId':uid(),'timestamp':timestamp,'source':source,'cmsLanguage':'C++17 / g++'}
 for index in range(5):
  node={'id':fid,'parentId':None,'name':'main.cpp','type':'file','content':source+f'// saved revision {index}\n','language':'cpp','documentRevision':index+1,'createdAt':timestamp,'updatedAt':timestamp}
  v['document'+str(index)]={'name':'Staging load editor','nodes':{fid:node},'settings':{},'editorState':{}}
 for prefix,index,current_sid in [('',3,sid),('final',4,sid2)]:
  node=v['document'+str(index)]['nodes'][fid];nodes={fid:{'id':fid,'parentId':None,'name':node['name'],'type':'file','content':node['content'],'revision':node['documentRevision']}}
  v[prefix+'Nodes']=nodes;v[prefix+'Hash']=digest(nodes)
  events=[{'schemaVersion':1,'eventId':uid(),'sessionId':current_sid,'workspaceId':wid,'fileId':None,'sequence':seq,'clientTimestamp':timestamp,'monotonicOffsetMs':seq*10,'eventType':kind,'payload':{}} for seq,kind in [(1,'PAGE_VISIBLE'),(2,'PAGE_HIDDEN')]]
  batch={'id':uid(),'sessionId':current_sid,'events':events,'checkpoints':[]};batch['digest']=digest(batch);v[prefix+'Batch']=batch
  config={'kind':'configuration','id':uid(),'name':'Staging load C++20','language':'cpp20','entryPoint':fid,'includedFiles':[fid],'compilerProfile':'release','mainClass':None,'defaultTestId':None}
  files=[{'id':fid,'path':'main.cpp','content':node['content']}]
  v[prefix+'Job']={'id':uid(),'workspaceId':wid,'configuration':config,'files':files,'sourceHash':digest({'files':sorted(files,key=lambda f:f['id']),'configuration':config}),'tests':[{'kind':'test','id':uid(),'name':'Staging measured sum','stdin':'2 3\n','expectedStdout':'5\n'}]}
 actor['variables']=v
creds=save('credentials.json',credentials);assert Path(creds).stat().st_size<9_000_000
hardware={'logicalCpus':2,'memoryGiB':3.7,'kernel':platform.release(),'instance':'user-authorized dedicated AWS staging; no sizing certification'}
target_id=uid();save('target.json',{'schemaVersion':1,'disposable':True,'targetId':target_id,'origin':meta['baseUrl'],'installationId':meta['installationId'],'contestId':meta['contestId'],'contestName':meta['contestName'],'cwsBasePath':'/','caBundle':meta['certificate'],'serverHardware':hardware,'toolchains':{'gcc':subprocess.check_output(['g++','--version'],text=True).splitlines()[0],'python':subprocess.check_output(['/usr/bin/python3','--version'],text=True).strip(),'runtimePython':platform.python_version(),'java':subprocess.run(['java','-version'],capture_output=True,text=True,check=True).stderr.splitlines()[0]},'testSuiteCost':'custom:1small C++20 compile +1case; CMS:1small C++17 compile +4Batch cases; ~1KiB editor source'})
def step(method,path,body=None,status=200,capture=None,assertions=None,new=None):
 d={'method':method,'path':path,'expect':[status]}
 if body is not None:d['json']=body
 if capture:d['capture']=capture
 if assertions:d['assert']=assertions
 if new:d['newIds']=new
 return d
runtime='/ide/api/runtime/v1/'
create=step('POST',runtime+'workspaces',{'id':'{{workspaceId}}','document':'{{document0}}'},201,{'revision':'revision'})
read=step('GET',runtime+'workspaces/{{workspaceId}}',capture={'revision':'revision'})
def patch(index):return step('PATCH',runtime+'workspaces/{{workspaceId}}',{'operationId':'{{operationId}}','baseRevision':'{{revision}}','document':'{{document'+str(index)+'}}'},capture={'revision':'revision'},new=['operationId'])
def session(final=False):
 prefix='final' if final else '';sid='finalSessionId' if final else 'sessionId';cid='finalCheckpointId' if final else 'checkpointId'
 return step('POST',runtime+'telemetry/sessions',{'id':'{{'+sid+'}}','workspaceId':'{{workspaceId}}','startedAt':'{{timestamp}}','initial':{'id':'{{'+cid+'}}','sessionId':'{{'+sid+'}}','sequence':0,'workspaceRevision':'{{revision}}','nodes':'{{'+prefix+'Nodes}}','stateHash':'{{'+prefix+'Hash}}','createdAt':'{{timestamp}}','reason':'staging-load'}},201)
def batch(final=False):return step('POST',runtime+'telemetry/batches','{{finalBatch}}' if final else '{{Batch}}')
def job(final=False):return step('POST',runtime+'executions','{{finalJob}}' if final else '{{Job}}',201,{'jobId':'id'})
def job_get(check=False):return step('GET',runtime+'executions/{{jobId}}',assertions={'status':'FINISHED'} if check else None)
official=step('POST','/ide/api/submissions',{'schemaVersion':1,'intentId':'{{intentId}}','snapshotId':'{{snapshotId}}','workspaceId':'{{workspaceId}}','taskId':'{{taskId}}','language':'{{cmsLanguage}}','telemetry':None,'files':[{'filename':'main.%l','sourceFilename':'main.cpp','fileId':'{{fileId}}','content':'{{source}}'}]},201,{'submissionId':'submissionId'}, {'state':'admitted'}, ['intentId','snapshotId'])
def feedback(check=False):return step('GET','/ide/api/submissions/status/{{submissionId}}?taskId={{taskId}}',assertions={'status.status':5} if check else None)
paths={}
for name,setup,steps in [('autosave',[create],[patch(i) for i in (1,2,3)]),('telemetry',[],[session(),batch(),step('GET',runtime+'telemetry/sessions/{{sessionId}}/status',assertions={'lastSequence':2,'integrity':'Complete'})]),('custom_runs',[],[job(),job_get(),job_get(),job_get(),job_get(True)]),('official_submissions',[],[official,feedback(),feedback(),feedback(),feedback(True)]),('final_minutes',[read],[patch(4),session(True),batch(True),job(True),job_get(),official,feedback(),feedback(),job_get(True),feedback(True)])]:
 paths[name]=save(name+'.json',{'schemaVersion':1,'setup':setup,'steps':steps})
def scenario(name,count,rate,fixture=None):
 value={'name':name,'participants':count,'iterations':1,'concurrency':min(12,count),'ratePerSecond':rate,'rampSeconds':0,'durationSeconds':600,'timeoutSeconds':15}
 if fixture:value['requestsFile']=paths[fixture]
 return value
scenarios=[scenario('context_read',count, min(20,max(3,count/5))) for count in (1,10,50,100,200,300,350)]
scenarios += [scenario('autosave',350,20,'autosave'),scenario('telemetry',350,20,'telemetry')]
for name in ['custom_runs','official_submissions']:
 s=scenario(name,5,2,name);s['concurrency']=1;scenarios.append(s)
save('main-plan.json',{'schemaVersion':1,'scenarios':scenarios})
final=scenario('final_minutes',10,5,'final_minutes');final['concurrency']=2;save('final-plan.json',{'schemaVersion':1,'scenarios':[final]})
print(json.dumps({'targetId':target_id,'participants':len(credentials),'credentialBytes':Path(creds).stat().st_size,'scenarios':len(scenarios),'sourceBytes':len(source.encode()),'paths':'protected external fixture directory only'}))
