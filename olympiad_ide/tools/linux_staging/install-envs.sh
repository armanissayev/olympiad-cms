#!/usr/bin/env bash
# Fresh authorized staging host only; intentionally separate Python dependency graphs.
set -euo pipefail
stage_root=/opt/cms-ide-stage
[ "$(id -u)" -eq 0 ]
[ -f "$stage_root/AUTHORIZED_DISPOSABLE" ]
[ ! -e "$stage_root/cms-venv" ]
[ ! -e "$stage_root/runtime-venv" ]
"$stage_root/python312/bin/python3.12" -m venv "$stage_root/cms-venv"
"$stage_root/cms-venv/bin/pip" install --no-input -r "$stage_root/source/requirements-olympiad-ide.lock" > "$stage_root/logs/cms-pip-install.log" 2>&1
"$stage_root/cms-venv/bin/pip" install --no-input wheel >> "$stage_root/logs/cms-pip-install.log" 2>&1
"$stage_root/cms-venv/bin/pip" install --no-deps --no-build-isolation "$stage_root/source" >> "$stage_root/logs/cms-pip-install.log" 2>&1
"$stage_root/cms-venv/bin/pip" check
"$stage_root/python312/bin/python3.12" -m venv "$stage_root/runtime-venv"
"$stage_root/runtime-venv/bin/pip" install --no-input -r "$stage_root/source/olympiad_ide/backend/requirements.lock" > "$stage_root/logs/runtime-pip-install.log" 2>&1
"$stage_root/runtime-venv/bin/pip" install --no-deps "$stage_root/source/olympiad_ide/backend" >> "$stage_root/logs/runtime-pip-install.log" 2>&1
"$stage_root/runtime-venv/bin/pip" check
[ ! -e "$stage_root/isolate-source" ]
git clone https://github.com/ioi/isolate.git "$stage_root/isolate-source"
git -C "$stage_root/isolate-source" checkout --detach 8f185bb37f3f23e29b33b0c7727c91c13429abe3
test "$(git -C "$stage_root/isolate-source" rev-parse HEAD)" = 8f185bb37f3f23e29b33b0c7727c91c13429abe3
