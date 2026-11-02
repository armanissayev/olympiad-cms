import os,json,subprocess
from pathlib import Path
assert os.geteuid()==0
root=Path('/etc/cms-ide-stage');backup=root/'before-public-https';backup.mkdir(mode=0o700,exist_ok=False)
for name in ['nginx.conf','runtime.env']:(backup/name).write_bytes((root/name).read_bytes());(backup/name).chmod(0o600)
unit=Path('/etc/systemd/system/cms-ide-stage-ingress.service');(backup/unit.name).write_bytes(unit.read_bytes())
web=Path('/var/lib/cms-ide-stage/acme');web.mkdir(mode=0o755);(web/'.well-known/acme-challenge').mkdir(parents=True);(web/'.well-known/acme-challenge/staging-connectivity').write_text('cms-staging-i-0ade1f8ddf0b0dad8\n')
s=(root/'nginx.conf').read_text();pos=s.index(' server {');s=s[:pos]+''' server {
  listen 0.0.0.0:80;
  server_name 54.206.171.67;
  location ^~ /.well-known/acme-challenge/ { root /var/lib/cms-ide-stage/acme; default_type text/plain; }
  location / { return 308 https://54.206.171.67$request_uri; }
 }
'''+s[pos:];(root/'nginx.conf').write_text(s)
s=unit.read_text();s=s.replace('[Service]','[Service]\nAmbientCapabilities=CAP_NET_BIND_SERVICE\nCapabilityBoundingSet=CAP_NET_BIND_SERVICE');unit.write_text(s)
subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemd-run','--quiet','--wait','--pipe','--collect','-p','User=cmsingressstage','-p','Group=cmsingressstage','-p','AmbientCapabilities=CAP_NET_BIND_SERVICE','-p','CapabilityBoundingSet=CAP_NET_BIND_SERVICE','-p','NoNewPrivileges=yes','/usr/sbin/nginx','-t','-c',str(root/'nginx.conf')],check=True);subprocess.run(['systemctl','restart','cms-ide-stage-ingress'],check=True)
# Boot persistence uses existing supervisors and keeps CMS children under ResourceService.
for name in ['postgres','log','resource','judge','runtime','worker','ranking','ingress']:
 directory=Path('/etc/systemd/system/multi-user.target.wants');directory.mkdir(exist_ok=True);link=directory/('cms-ide-stage-'+name+'.service')
 if not link.exists():link.symlink_to('/etc/systemd/system/'+link.name)
subprocess.run(['systemctl','enable','isolate.service','cms-ide-stage-sandbox.service'],check=True)
print('PUBLIC_HTTP_ACME_READY;APPLICATION_STILL_LOOPBACK;EXISTING_SUPERVISORS_PERSIST')
