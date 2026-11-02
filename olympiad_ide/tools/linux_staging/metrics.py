"""Bounded staging-only host/queue/database sampler; never captures source or credentials."""
import argparse,json,os,platform,signal,time
from datetime import datetime,timezone
from pathlib import Path
import psutil,psycopg2
p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=900);p.add_argument('--output',required=True);a=p.parse_args();assert 1<=a.seconds<=3600
out=Path(a.output);assert str(out).startswith('/var/lib/cms-ide-stage/metrics/') and not out.exists()
connections={name:psycopg2.connect(dbname=name,user='stagepguser',host='/run/cms-ide-stage-pg',port=15432) for name in ['cmside_linux_fortesting','ide_linux_staging']}
for c in connections.values():c.autocommit=True
stop=False
def end(*_):
 global stop;stop=True
signal.signal(signal.SIGTERM,end);signal.signal(signal.SIGINT,end)
report={'kind':'staging-host-sample','startedAt':datetime.now(timezone.utc).isoformat(),'hardware':{'cpus':os.cpu_count(),'memoryBytes':psutil.virtual_memory().total,'kernel':platform.release()},'samples':[]}
psutil.cpu_percent(None);deadline=time.monotonic()+a.seconds
try:
 while not stop and time.monotonic()<deadline:
  row={'time':datetime.now(timezone.utc).isoformat(),'cpuPercent':psutil.cpu_percent(None),'memoryUsedBytes':psutil.virtual_memory().used,'memoryAvailableBytes':psutil.virtual_memory().available,'databases':{}}
  for name,c in connections.items():
   with c.cursor() as cursor:
    cursor.execute('SELECT pg_database_size(current_database()), (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database())');size,count=cursor.fetchone();row['databases'][name]={'bytes':size,'connections':count}
    if name=='ide_linux_staging':
     cursor.execute("SELECT count(*) FILTER (WHERE status='QUEUED'),count(*) FILTER (WHERE status IN ('COMPILING','RUNNING')),COALESCE(EXTRACT(EPOCH FROM(now()-min(created_at) FILTER(WHERE status='QUEUED'))),0) FROM execution_jobs");queued,running,age=cursor.fetchone();row['customQueue']={'queued':queued,'running':running,'oldestAgeSeconds':float(age)}
  report['samples'].append(row);time.sleep(1)
finally:
 for c in connections.values():c.close()
 report['finishedAt']=datetime.now(timezone.utc).isoformat();out.write_text(json.dumps(report,indent=2)+'\n');out.chmod(0o600)
print(json.dumps({'samples':len(report['samples']),'report':str(out)}))
