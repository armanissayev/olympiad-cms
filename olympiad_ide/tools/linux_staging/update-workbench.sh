#!/bin/bash
set -euo pipefail
umask 022
stage_root=/opt/cms-ide-stage
[ "$(id -u)" -eq 0 ]
[ -f "$stage_root/DEBUG_SANDBOX_REVIEW" ]
grep -qx DEBUG_SANDBOX_APPROVED=1 /etc/cms-ide-stage/debug.env
# This update retains an already reviewed debug approval; initial provisioning has a separate gate.
systemctl stop cms-ide-stage-runtime cms-ide-stage-worker cms-ide-stage-debug cms-ide-stage-resource cms-ide-stage-judge cms-ide-stage-ranking cms-ide-stage-log
trap 'systemctl start cms-ide-stage-runtime cms-ide-stage-worker cms-ide-stage-log cms-ide-stage-ranking cms-ide-stage-judge cms-ide-stage-resource cms-ide-stage-debug' EXIT
tar -xf "$stage_root/incoming/vnext-source.tar.gz" -C "$stage_root/source"
tar -xf "$stage_root/incoming/vnext-assets.tar.gz" -C "$stage_root/source"
chown -R root:root "$stage_root/source"
cd "$stage_root/source/olympiad_ide"
runuser -u ideworkerstage -- env -u WORKER_SANDBOX_APPROVED -u DEBUG_SANDBOX_APPROVED PYTHONPATH=backend:. PATH=/usr/local/bin:/usr/bin:/bin RUN_LINUX_DEBUG_TESTS=1 "$stage_root/runtime-venv/bin/python" -m pytest worker/tests/test_debugger.py -vv -p no:cacheprovider > /tmp/cms-debug-security-final.log 2>&1
"$stage_root/cms-venv/bin/pip" install --no-deps --no-build-isolation --force-reinstall "$stage_root/source" > "$stage_root/logs/vnext-cms-install-final.log" 2>&1
"$stage_root/runtime-venv/bin/pip" install --no-deps --force-reinstall "$stage_root/source/olympiad_ide/backend" > "$stage_root/logs/vnext-runtime-install-final.log" 2>&1
"$stage_root/runtime-venv/bin/pip" check
"$stage_root/cms-venv/bin/pip" check
python3 - <<'UNIT'
from pathlib import Path
p=Path('/etc/systemd/system/cms-ide-stage-runtime.service')
s=p.read_text()
if '--ws-max-size' not in s:
    assert s.count('--limit-concurrency 64')==1
    p.write_text(s.replace('--limit-concurrency 64','--limit-concurrency 64 --ws-max-size 32768 --ws-max-queue 4'))
else:
    assert '--ws-max-size 32768 --ws-max-queue 4' in s
UNIT
systemctl daemon-reload
install -m 0644 "$stage_root/incoming/vnext-commit.txt" "$stage_root/SOURCE_COMMIT"
systemctl start cms-ide-stage-runtime cms-ide-stage-worker cms-ide-stage-log cms-ide-stage-ranking cms-ide-stage-judge cms-ide-stage-resource cms-ide-stage-debug
trap - EXIT
systemctl is-active cms-ide-stage-resource cms-ide-stage-judge cms-ide-stage-runtime cms-ide-stage-worker cms-ide-stage-debug cms-ide-stage-ingress
