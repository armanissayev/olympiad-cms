#!/usr/bin/env bash
set -euo pipefail
umask 022
stage_root=/opt/cms-ide-stage
[ "$(id -u)" -eq 0 ]
[ -f "$stage_root/incoming/cms-source.tar" ]
[ -f "$stage_root/incoming/source-commit.txt" ]
[ -f "$stage_root/AUTHORIZED_DISPOSABLE" ]
[ ! -e "$stage_root/source" ] || { echo 'Source already exists; inspect before rerunning'; exit 1; }
# The procedure is only for a fresh, explicitly authorized host.
for unit in nginx postgresql; do
 if systemctl is-active --quiet "$unit"; then echo 'Existing service requires operator review'; exit 1; fi
done
[ ! -d /etc/cms-ide-stage ]
[ ! -d /var/lib/cms-ide-stage/postgres ]
install -d -m 0755 "$stage_root/source" "$stage_root/logs" "$stage_root/downloads"
tar -xf "$stage_root/incoming/cms-source.tar" -C "$stage_root/source"
tar -xf "$stage_root/incoming/ide-assets.tar" -C "$stage_root/source"
chown -R root:root "$stage_root/source"
grep -Ex '[0-9a-f]{40}' "$stage_root/incoming/source-commit.txt" > "$stage_root/SOURCE_COMMIT"
# Prevent package installation from starting public/default services.
[ ! -e /usr/sbin/policy-rc.d ] || { echo 'Existing package service policy requires review'; exit 1; }
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 0755 /usr/sbin/policy-rc.d
trap 'rm -f /usr/sbin/policy-rc.d' EXIT
export DEBIAN_FRONTEND=noninteractive
apt-get update > "$stage_root/logs/apt-update.log" 2>&1
apt-get install -y --no-install-recommends build-essential pkg-config git curl ca-certificates xz-utils zip unzip libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev libffi-dev liblzma-dev libncurses-dev uuid-dev libgdbm-dev libexpat1-dev libpq-dev libcups2-dev libyaml-dev libcap-dev libseccomp-dev libsystemd-dev quota e2fsprogs postgresql-18 postgresql-client-18 nginx openjdk-17-jdk-headless nodejs npm shared-mime-info > "$stage_root/logs/apt-install.log" 2>&1
rm -f /usr/sbin/policy-rc.d
trap - EXIT
systemctl disable nginx.service postgresql.service > "$stage_root/logs/default-services-disable.log" 2>&1
cd "$stage_root/downloads"
curl --fail --location --proto '=https' --tlsv1.2 --output Python-3.12.16.tar.xz https://www.python.org/ftp/python/3.12.16/Python-3.12.16.tar.xz
printf '%s\n' 'b5796915dc45ff745cfb4e990a7e7c93d6f546328a102ce31448d69ebc37575c  Python-3.12.16.tar.xz' | sha256sum --check
tar -xf Python-3.12.16.tar.xz
cd Python-3.12.16
./configure --prefix="$stage_root/python312" --with-ensurepip=install > "$stage_root/logs/python-configure.log" 2>&1
make -j2 > "$stage_root/logs/python-build.log" 2>&1
make install > "$stage_root/logs/python-install.log" 2>&1
"$stage_root/python312/bin/python3.12" --version
printf '%s\n' 'BOOTSTRAP_BASE_COMPLETE'
