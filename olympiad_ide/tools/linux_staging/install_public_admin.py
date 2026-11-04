#!/usr/bin/env python3
"""Expose native Admin on the explicitly authorized disposable staging HTTPS ingress."""
import datetime
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile
import time

CONF = Path('/etc/cms-ide-stage/nginx.conf')
PUBLIC = '54.206.171.67'
ZONE = ' limit_req_zone $binary_remote_addr zone=cms_stage_admin_login:1m rate=10r/m;\n'
START = '  # BEGIN CMS STAGING PUBLIC ADMIN\n'
END = '  # END CMS STAGING PUBLIC ADMIN\n'


def proxy_settings():
    # Defining flags here replaces inherited flags: keep both Admin and XSRF protections.
    # Keep root _xsrf shared with CWS; rewriting all cookies to /admin/ causes duplicates.
    return '''   proxy_cookie_flags awslogin secure httponly samesite=strict;
   proxy_cookie_flags _xsrf secure samesite=strict;
   proxy_hide_header Cache-Control;
   add_header Cache-Control "no-store" always;
   add_header X-Frame-Options DENY always;
   add_header X-Content-Type-Options nosniff always;
   add_header Referrer-Policy same-origin always;
'''


BLOCK = START + '''  location = /admin { return 308 /admin/; }
  location = /admin/login {
   limit_req zone=cms_stage_admin_login burst=10 nodelay;
   limit_req_status 429;
   proxy_pass http://127.0.0.1:18889/login;
''' + proxy_settings() + '''  }
  location ^~ /admin/ {
   proxy_pass http://127.0.0.1:18889/;
''' + proxy_settings() + '  }\n' + END


def render(previous):
    for directive in ('proxy_set_header Host $http_host;',
                      'proxy_set_header X-Forwarded-For $remote_addr;',
                      'proxy_set_header X-Forwarded-Proto https;',
                      'proxy_set_header Forwarded "";',
                      'proxy_set_header Authorization "";'):
        if directive not in previous:
            raise RuntimeError('Reviewed global proxy protection missing: ' + directive)
    marker = ' server {\n  listen 0.0.0.0:443 ssl;'
    if previous.count(marker) != 1:
        raise RuntimeError('Expected exactly one existing public HTTPS server')
    position = previous.index(marker)
    following = previous.find('\n server {', position + len(marker))
    following = len(previous) if following < 0 else following
    server = previous[position:following]
    for required in ('server_name ' + PUBLIC + ';',
                     'ssl_certificate /etc/cms-ide-stage/public.crt;',
                     'location / { proxy_pass http://127.0.0.1:18888; }'):
        if required not in server:
            raise RuntimeError('Unexpected public HTTPS server layout')
    if START in previous or 'cms_stage_admin_login' in previous:
        if previous.count(BLOCK) != 1 or previous.count(ZONE) != 1 or BLOCK not in server:
            raise RuntimeError('Existing Admin configuration differs; refusing overwrite')
        return previous
    if re.search(r'location\s+(?:=\s+|\^~\s+)?/admin(?:[\s/;{]|$)', previous):
        raise RuntimeError('An unreviewed Admin location already exists')
    needle = '  location = /ide { return 308 /ide/; }'
    if server.count(needle) != 1:
        raise RuntimeError('Expected public IDE location not found')
    server = server.replace(needle, BLOCK + needle, 1)
    updated = previous[:position] + server + previous[following:]
    if updated.count('http {\n') != 1:
        raise RuntimeError('Unexpected nginx HTTP context')
    return updated.replace('http {\n', 'http {\n' + ZONE, 1)


def nginx_test(path):
    subprocess.run(['systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                    '-p', 'User=cmsingressstage', '-p', 'Group=cmsingressstage',
                    '-p', 'AmbientCapabilities=CAP_NET_BIND_SERVICE',
                    '-p', 'CapabilityBoundingSet=CAP_NET_BIND_SERVICE',
                    '-p', 'NoNewPrivileges=yes', '/usr/sbin/nginx', '-t', '-c', str(path)], check=True)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Run as root on the authorized staging host')
    if CONF.is_symlink() or not CONF.is_file():
        raise RuntimeError('Regular staging configuration required')
    if not Path('/opt/cms-ide-stage/SOURCE_COMMIT').is_file():
        raise RuntimeError('Staging installation marker missing')
    cms_path = CONF.parent / 'cms.conf'
    if cms_path.is_symlink():
        raise RuntimeError('Regular native configuration required')
    cms = json.loads(cms_path.read_text())
    if (cms.get('admin_listen_address'), cms.get('admin_listen_port'), cms.get('admin_num_proxies_used')) != ('127.0.0.1', 18889, 1):
        raise RuntimeError('Native Admin must remain private with one trusted proxy')
    info = CONF.stat()
    if info.st_uid != pwd.getpwnam('cmsingressstage').pw_uid or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeError('Unexpected ingress configuration owner/mode')
    previous = CONF.read_text()
    updated = render(previous)
    backup = None
    candidate = None
    if updated != previous:
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        backup = CONF.parent / ('before-public-admin-' + stamp)
        backup.mkdir(mode=0o700)
        (backup / 'nginx.conf').write_text(previous)
        (backup / 'nginx.conf').chmod(0o600)
        descriptor, temporary = tempfile.mkstemp(prefix='.nginx-public-admin-', dir=CONF.parent)
        os.close(descriptor)
        candidate = Path(temporary)
        candidate.write_text(updated)
        os.chown(candidate, info.st_uid, info.st_gid)
        candidate.chmod(0o600)
    try:
        nginx_test(candidate or CONF)
        if candidate:
            os.replace(candidate, CONF)
        subprocess.run(['systemctl', 'reload', 'cms-ide-stage-ingress'], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'cms-ide-stage-ingress'], check=True)
        # Verify the public IP certificate with the normal system CA store, using local ingress.
        for attempt in range(5):
            check = subprocess.run(['curl', '--noproxy', '*', '--silent', '--show-error', '--fail',
                                    '--connect-timeout', '5', '--max-time', '15',
                                    '--resolve', PUBLIC + ':443:127.0.0.1',
                                    'https://' + PUBLIC + '/admin/login'], capture_output=True, text=True)
            if check.returncode == 0 and '<title>Admin</title>' in check.stdout and 'name="password"' in check.stdout:
                break
            if attempt == 4:
                raise RuntimeError('Expected native Admin login was not served with trusted TLS')
            time.sleep(1)
    except Exception:
        if updated != previous and CONF.read_text() != previous:
            CONF.write_text(previous)
            os.chown(CONF, info.st_uid, info.st_gid)
            CONF.chmod(0o600)
            nginx_test(CONF)
            subprocess.run(['systemctl', 'reload', 'cms-ide-stage-ingress'], check=True)
        raise
    finally:
        if candidate and candidate.exists():
            candidate.unlink()
    print(json.dumps({'status': 'configured', 'adminUrl': 'https://' + PUBLIC + '/admin/',
                      'historyUrl': 'https://' + PUBLIC + '/admin/contest/1/ide-history',
                      'nativeAdmin': '127.0.0.1:18889', 'servicesReloaded': ['cms-ide-stage-ingress'],
                      'changed': updated != previous, 'backup': str(backup) if backup else None}))


if __name__ == '__main__':
    main()
