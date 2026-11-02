import json,os,pwd,secrets,subprocess,uuid
from pathlib import Path
root=Path('/opt/cms-ide-stage'); conf=Path('/etc/cms-ide-stage'); conf.mkdir(mode=0o755,exist_ok=True)
assert not (conf/'cms.conf').exists(), 'Refusing to overwrite existing staging configuration'
def owned(path,text,user,mode=0o600):
 path=Path(path);path.write_text(text);info=pwd.getpwnam(user);os.chown(path,info.pw_uid,info.pw_gid);path.chmod(mode)
def directory(path,user,mode=0o700):
 path=Path(path);path.mkdir(parents=True,exist_ok=True);info=pwd.getpwnam(user);os.chown(path,info.pw_uid,info.pw_gid);path.chmod(mode)
for p in ('cms-log','cms-cache','cms-data','cms-run','cms-tmp','ranking-data','ranking-log','fixture'):
 directory('/var/lib/cms-ide-stage/'+p,'cmsstage')
directory('/var/lib/cms-ide-stage/ingress','cmsingressstage')
directory('/var/lib/cms-ide-stage/worker','ideworkerstage')
installation=str(uuid.uuid4()); key=secrets.token_bytes(64)
for filename,user in [('native.key','cmsstage'),('runtime.key','ideapistage')]:
 path=conf/filename;path.write_bytes(key);info=pwd.getpwnam(user);os.chown(path,info.pw_uid,info.pw_gid);path.chmod(0o600)
ranking_password=secrets.token_urlsafe(32)
services={name:[['127.0.0.1',31000+index]] for index,name in enumerate(['LogService','ResourceService','ContestWebServer','OlympiadIDEService','EvaluationService','ScoringService','Worker','AdminWebServer','ProxyService'])}
cms={'cmsuser':'cmsstage','core_services':services,'other_services':{},'database':'postgresql+psycopg2://cmsstage@/cmside_linux_fortesting?host=/run/cms-ide-stage-pg&port=15432','secret_key':secrets.token_hex(16),'temp_dir':'/var/lib/cms-ide-stage/cms-tmp','log_dir':'/var/lib/cms-ide-stage/cms-log','cache_dir':'/var/lib/cms-ide-stage/cms-cache','data_dir':'/var/lib/cms-ide-stage/cms-data','run_dir':'/var/lib/cms-ide-stage/cms-run','contest_listen_address':['127.0.0.1'],'contest_listen_port':[18888],'admin_listen_address':'127.0.0.1','admin_listen_port':18889,'admin_num_proxies_used':1,'num_proxies_used':1,'submit_local_copy':False,'use_cgroups':True,'keep_sandbox':False,'rankings':['http://stageproxy:'+ranking_password+'@127.0.0.1:18890/'],'olympiad_ide_enabled':True,'olympiad_ide_installation_id':installation,'olympiad_ide_listen_address':['127.0.0.1'],'olympiad_ide_listen_port':[18891],'olympiad_ide_runtime_url':'http://127.0.0.1:18801','olympiad_ide_signing_key_file':str(conf/'native.key'),'olympiad_ide_trusted_proxy_addresses':['127.0.0.1'],'olympiad_ide_num_proxies':1,'olympiad_ide_cws_base_path':'/'}
owned(conf/'cms.conf',json.dumps(cms,indent=2)+'\n','cmsstage')
ranking={'bind_address':'127.0.0.1','http_port':18890,'username':'stageproxy','password':ranking_password,'log_dir':'/var/lib/cms-ide-stage/ranking-log','lib_dir':'/var/lib/cms-ide-stage/ranking-data'}
owned(conf/'ranking.conf',json.dumps(ranking,indent=2)+'\n','cmsstage')
url='postgresql+psycopg://{}@/ide_linux_staging?host=/run/cms-ide-stage-pg&port=15432'
owned(conf/'runtime.env','IDE_AUTH_MODE=cms\nCMS_INSTALLATION_ID='+installation+'\nCMS_ASSERTION_KEY_FILE='+str(conf/'runtime.key')+'\nDATABASE_URL='+url.format('ideapistage')+'\nALLOWED_ORIGINS=https://localhost:28443\nCOOKIE_SECURE=true\nTELEMETRY_RETENTION_DAYS=30\n','root')
owned(conf/'migration.env','DATABASE_URL='+url.format('idemigratestage')+'\n','root')
# Approval is deliberately absent until the mandatory real suite passes review.
owned(conf/'worker.env','DATABASE_URL='+url.format('ideworkerstage')+'\nWORKER_CONCURRENCY=1\nWORKER_BOX_ID_BASE=200\nWORKER_ID=cms-ide-linux-staging\nPYTHONPATH=/opt/cms-ide-stage/source/olympiad_ide/backend:/opt/cms-ide-stage/source/olympiad_ide\n','root')
cert=conf/'localhost.crt';certkey=conf/'localhost.key'
subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(certkey),'-out',str(cert),'-subj','/CN=localhost','-days','7','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
info=pwd.getpwnam('cmsingressstage');os.chown(certkey,info.pw_uid,info.pw_gid);certkey.chmod(0o600);cert.chmod(0o644)
nginx='''pid /var/lib/cms-ide-stage/ingress/nginx.pid;
error_log /var/lib/cms-ide-stage/ingress/error.log warn;
events { worker_connections 1024; }
http {
 include /etc/nginx/mime.types;
 gzip on;
 gzip_types text/css text/javascript application/javascript application/json;
 gzip_min_length 1024;
 access_log /var/lib/cms-ide-stage/ingress/access.log;
 client_body_temp_path /var/lib/cms-ide-stage/ingress/body;
 proxy_temp_path /var/lib/cms-ide-stage/ingress/proxy;
 fastcgi_temp_path /var/lib/cms-ide-stage/ingress/fastcgi;
 uwsgi_temp_path /var/lib/cms-ide-stage/ingress/uwsgi;
 scgi_temp_path /var/lib/cms-ide-stage/ingress/scgi;
 client_max_body_size 9m;
 proxy_connect_timeout 2s;
 proxy_read_timeout 30s;
 proxy_set_header Host $http_host;
 proxy_set_header X-Forwarded-For $remote_addr;
 proxy_set_header X-Forwarded-Proto https;
 proxy_set_header Forwarded "";
 proxy_set_header Authorization "";
 proxy_cookie_flags ~.*_login secure httponly samesite=strict;
 proxy_cookie_flags _xsrf secure samesite=strict;
 server {
  listen 127.0.0.1:28443 ssl;
  ssl_certificate /etc/cms-ide-stage/localhost.crt;
  ssl_certificate_key /etc/cms-ide-stage/localhost.key;
  add_header X-Content-Type-Options nosniff always;
  location /ide/ { proxy_pass http://127.0.0.1:18891; }
  location = /ide { return 308 /ide/; }
  location / { proxy_pass http://127.0.0.1:18888; }
 }
 server {
  listen 127.0.0.1:28444 ssl;
  ssl_certificate /etc/cms-ide-stage/localhost.crt;
  ssl_certificate_key /etc/cms-ide-stage/localhost.key;
  location / { proxy_pass http://127.0.0.1:18889; }
 }
 server {
  listen 127.0.0.1:28445 ssl;
  ssl_certificate /etc/cms-ide-stage/localhost.crt;
  ssl_certificate_key /etc/cms-ide-stage/localhost.key;
  location / { proxy_pass http://127.0.0.1:18890; }
 }
}
'''
owned(conf/'nginx.conf',nginx,'cmsingressstage')
units={
'cms-ide-stage-runtime.service':'''[Unit]
Description=Disposable private CMS IDE staging runtime
After=cms-ide-stage-postgres.service
Requires=cms-ide-stage-postgres.service
[Service]
User=ideapistage
Group=ideapistage
WorkingDirectory=/opt/cms-ide-stage/source/olympiad_ide/backend
EnvironmentFile=/etc/cms-ide-stage/runtime.env
ExecStart=/opt/cms-ide-stage/runtime-venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18801 --workers 1 --limit-concurrency 64
Restart=on-failure
RestartSec=5
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
UMask=0077
''',
'cms-ide-stage-log.service':'''[Unit]
Description=Disposable CMS staging LogService
After=cms-ide-stage-postgres.service
[Service]
User=cmsstage
Group=cmsstage
WorkingDirectory=/opt/cms-ide-stage/source
Environment=CMS_CONFIG=/etc/cms-ide-stage/cms.conf
Environment=PATH=/opt/cms-ide-stage/cms-venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/cms-ide-stage/cms-venv/bin/cmsLogService 0
KillMode=control-group
Restart=on-failure
UMask=0077
''',
'cms-ide-stage-resource.service':'''[Unit]
Description=Disposable CMS staging ResourceService and owned CMS children
After=cms-ide-stage-postgres.service cms-ide-stage-log.service isolate.service
Requires=cms-ide-stage-postgres.service cms-ide-stage-log.service isolate.service
Wants=cms-ide-stage-runtime.service cms-ide-stage-ranking.service
[Service]
User=cmsstage
Group=cmsstage
WorkingDirectory=/opt/cms-ide-stage/source
Environment=CMS_CONFIG=/etc/cms-ide-stage/cms.conf
Environment=PATH=/opt/cms-ide-stage/cms-venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/cms-ide-stage/cms-venv/bin/cmsResourceService 0 -a 1
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=30
UMask=0077
''',
'cms-ide-stage-ranking.service':'''[Unit]
Description=Disposable CMS staging RankingWebServer
[Service]
User=cmsstage
Group=cmsstage
WorkingDirectory=/opt/cms-ide-stage/source
Environment=CMS_RANKING_CONFIG=/etc/cms-ide-stage/ranking.conf
ExecStart=/opt/cms-ide-stage/cms-venv/bin/cmsRankingWebServer
Restart=on-failure
KillMode=control-group
UMask=0077
''',
'cms-ide-stage-worker.service':'''[Unit]
Description=Approved disposable IDE isolate worker (separate from CMS judging)
After=isolate.service cms-ide-stage-postgres.service
Requires=isolate.service cms-ide-stage-postgres.service
[Service]
User=ideworkerstage
Group=ideworkerstage
WorkingDirectory=/opt/cms-ide-stage/source/olympiad_ide
EnvironmentFile=/etc/cms-ide-stage/worker.env
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/cms-ide-stage/runtime-venv/bin/python -m worker.app.main
PrivateNetwork=true
ProtectHome=true
Restart=on-failure
RestartSec=5
KillMode=control-group
UMask=0077
''',
'cms-ide-stage-ingress.service':'''[Unit]
Description=Loopback-only TLS ingress for disposable CMS staging
After=cms-ide-stage-resource.service
[Service]
User=cmsingressstage
Group=cmsingressstage
ExecStart=/usr/sbin/nginx -c /etc/cms-ide-stage/nginx.conf -g "daemon off;"
ExecReload=/usr/sbin/nginx -c /etc/cms-ide-stage/nginx.conf -s reload
KillMode=control-group
Restart=on-failure
UMask=0077
'''}
for name,text in units.items():
 Path('/etc/systemd/system',name).write_text(text)
subprocess.run(['systemctl','daemon-reload'],check=True)
Path(root/'STAGING_INSTALLATION_ID').write_text(installation+'\n')
print('STAGING_CONFIGURED_NO_APPLICATION_OR_WORKER_STARTED')
