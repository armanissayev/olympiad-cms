from pathlib import Path
import subprocess
p=Path('/etc/cms-ide-stage/nginx.conf');text=p.read_text()
assert 'location ~ "^/ide/api/debug/sessions/' not in text
backup=Path('/etc/cms-ide-stage/before-debug-ws.conf');assert not backup.exists();backup.write_text(text);backup.chmod(0o600)
ws='''  location ~ "^/ide/api/debug/sessions/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/dap$" {
   if ($args != "") { return 400; }
   proxy_pass http://127.0.0.1:18801/api/v1/debug/sessions/$1/dap;
   proxy_http_version 1.1;
   proxy_set_header Upgrade $http_upgrade;
   proxy_set_header Connection "upgrade";
   proxy_set_header Host $host;
   proxy_set_header X-Forwarded-For $remote_addr;
   proxy_set_header X-Forwarded-Proto https;
   proxy_set_header Forwarded "";
   proxy_set_header Authorization "";
   proxy_read_timeout 330s;
   proxy_buffering off;
  }
'''
needle='  location /ide/ { proxy_pass http://127.0.0.1:18891; }';assert text.count(needle)==2
p.write_text(text.replace(needle,ws+needle))
try:
 subprocess.run(['systemd-run','--quiet','--wait','--pipe','--collect','-p','User=cmsingressstage','-p','Group=cmsingressstage','-p','AmbientCapabilities=CAP_NET_BIND_SERVICE','-p','CapabilityBoundingSet=CAP_NET_BIND_SERVICE','-p','NoNewPrivileges=yes','/usr/sbin/nginx','-t','-c',str(p)],check=True)
 subprocess.run(['systemctl','reload','cms-ide-stage-ingress'],check=True)
except Exception:p.write_text(text);raise
print('EXACT_AUTHENTICATED_DEBUG_WS_ROUTES_READY')
