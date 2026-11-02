#!/bin/bash
set -euo pipefail
umask 077
stage_root=/opt/cms-ide-stage
ip=54.206.171.67
certbot="$stage_root/acme-venv/bin/certbot"
[ "$(id -u)" -eq 0 ]
[ -f /etc/cms-ide-stage/before-public-https/nginx.conf ]
"$certbot" certonly --non-interactive --agree-tos --register-unsafely-without-email \
 --preferred-profile shortlived --webroot --webroot-path /var/lib/cms-ide-stage/acme \
 --ip-address "$ip" --cert-name cms-staging-public-ip --keep-until-expiring
lineage=/etc/letsencrypt/live/cms-staging-public-ip
openssl x509 -in "$lineage/fullchain.pem" -noout -checkip "$ip"
openssl x509 -in "$lineage/fullchain.pem" -noout -checkend 86400
install -o cmsingressstage -g cmsingressstage -m 0644 "$lineage/fullchain.pem" /etc/cms-ide-stage/public.crt
install -o cmsingressstage -g cmsingressstage -m 0600 "$lineage/privkey.pem" /etc/cms-ide-stage/public.key
python=/opt/cms-ide-stage/cms-venv/bin/python
"$python" - <<'PY'
from pathlib import Path
import subprocess
root=Path('/etc/cms-ide-stage');p=root/'nginx.conf';previous=p.read_text()
assert 'listen 0.0.0.0:443 ssl' not in previous
block=''' server {
  listen 0.0.0.0:443 ssl;
  server_name 54.206.171.67;
  ssl_certificate /etc/cms-ide-stage/public.crt;
  ssl_certificate_key /etc/cms-ide-stage/public.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  add_header X-Content-Type-Options nosniff always;
  location /ide/ { proxy_pass http://127.0.0.1:18891; }
  location = /ide { return 308 /ide/; }
  location / { proxy_pass http://127.0.0.1:18888; }
 }
'''
pos=previous.index(' server {');p.write_text(previous[:pos]+block+previous[pos:])
try:subprocess.run(['systemd-run','--quiet','--wait','--pipe','--collect','-p','User=cmsingressstage','-p','Group=cmsingressstage','-p','AmbientCapabilities=CAP_NET_BIND_SERVICE','-p','CapabilityBoundingSet=CAP_NET_BIND_SERVICE','-p','NoNewPrivileges=yes','/usr/sbin/nginx','-t','-c',str(p)],check=True)
except Exception:p.write_text(previous);raise
p=root/'runtime.env';s=p.read_text();assert 'ALLOWED_ORIGINS=https://localhost:28443' in s;s=s.replace('ALLOWED_ORIGINS=https://localhost:28443','ALLOWED_ORIGINS=https://localhost:28443,https://54.206.171.67');p.write_text(s)
subprocess.run(['systemctl','restart','cms-ide-stage-runtime'],check=True)
subprocess.run(['systemctl','reload','cms-ide-stage-ingress'],check=True)
PY
install -d -m 0700 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/cms-staging <<'HOOK'
#!/bin/bash
set -euo pipefail
[ "$RENEWED_LINEAGE" = /etc/letsencrypt/live/cms-staging-public-ip ] || exit 0
openssl x509 -in "$RENEWED_LINEAGE/fullchain.pem" -noout -checkip 54.206.171.67
install -o cmsingressstage -g cmsingressstage -m 0644 "$RENEWED_LINEAGE/fullchain.pem" /etc/cms-ide-stage/public.crt
install -o cmsingressstage -g cmsingressstage -m 0600 "$RENEWED_LINEAGE/privkey.pem" /etc/cms-ide-stage/public.key
systemd-run --quiet --wait --pipe --collect -p User=cmsingressstage -p Group=cmsingressstage -p AmbientCapabilities=CAP_NET_BIND_SERVICE -p CapabilityBoundingSet=CAP_NET_BIND_SERVICE -p NoNewPrivileges=yes /usr/sbin/nginx -t -c /etc/cms-ide-stage/nginx.conf
systemctl reload cms-ide-stage-ingress
HOOK
chmod 0700 /etc/letsencrypt/renewal-hooks/deploy/cms-staging
cat > /etc/systemd/system/cms-ide-stage-acme-renew.service <<'UNIT'
[Unit]
Description=Renew staging CMS public IP certificate
After=network-online.target cms-ide-stage-ingress.service
[Service]
Type=oneshot
ExecStart=/opt/cms-ide-stage/acme-venv/bin/certbot renew --cert-name cms-staging-public-ip --quiet
UMask=0077
UNIT
cat > /etc/systemd/system/cms-ide-stage-acme-renew.timer <<'UNIT'
[Unit]
Description=Check staging CMS short-lived TLS certificate every six hours
[Timer]
OnBootSec=3min
OnUnitActiveSec=6h
RandomizedDelaySec=10min
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now cms-ide-stage-acme-renew.timer
printf '%s\n' PUBLIC_HTTPS_ACTIVATED
