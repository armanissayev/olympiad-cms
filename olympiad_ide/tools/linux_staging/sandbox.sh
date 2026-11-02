#!/usr/bin/env bash
set -euo pipefail
stage_root=/opt/cms-ide-stage
[ "$(id -u)" -eq 0 ]
for account in cmsstage ideapistage ideworkerstage idemigratestage stagepguser cmsingressstage; do
 if ! id "$account" >/dev/null 2>&1; then useradd --system --no-create-home --shell /usr/sbin/nologin "$account"; fi
done
python3 - <<'RANGE'
import pwd
assert not [(u.pw_name,u.pw_uid) for u in pwd.getpwall() if 60000<=u.pw_uid<61000], 'Sandbox UID range already allocated'
RANGE
cd "$stage_root/isolate-source"
[ "$(git rev-parse HEAD)" = 8f185bb37f3f23e29b33b0c7727c91c13429abe3 ]
[ ! -e /usr/local/bin/isolate ] || { echo 'Existing helper requires review'; exit 1; }
make -j2 install > "$stage_root/logs/isolate-build-install.log" 2>&1
install -d -m 0755 /var/lib/cms-ide-stage /var/lib/cms-ide-stage/boxes
[ ! -e /var/lib/cms-ide-stage/boxes.ext4 ]
truncate -s 2G /var/lib/cms-ide-stage/boxes.ext4
chmod 0600 /var/lib/cms-ide-stage/boxes.ext4
mkfs.ext4 -q -F -O quota /var/lib/cms-ide-stage/boxes.ext4
cat > /etc/systemd/system/cms-ide-stage-sandbox.service <<'UNIT'
[Unit]
Description=Disposable CMS IDE staging quota filesystem
Before=isolate.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/mount -o loop,usrquota /var/lib/cms-ide-stage/boxes.ext4 /var/lib/cms-ide-stage/boxes
ExecStop=/usr/bin/umount /var/lib/cms-ide-stage/boxes
[Install]
WantedBy=multi-user.target
UNIT
sed -i 's|^box_root *=.*|box_root = /var/lib/cms-ide-stage/boxes|' /usr/local/etc/isolate
# isolate2.7 defaults to an unprovisioned subordinate user on this image.
sed -i -e 's/^subid_user *=.*/# subid_user disabled: explicit staging UID range/' -e '/^first_uid *=/d' -e '/^first_gid *=/d' -e '/^num_boxes *=/d' /usr/local/etc/isolate
printf '\nfirst_uid = 60000\nfirst_gid = 60000\nnum_boxes = 1000\n' >> /usr/local/etc/isolate
install -d /etc/systemd/system/isolate.service.d
cat > /etc/systemd/system/isolate.service.d/staging.conf <<'UNIT'
[Unit]
Requires=cms-ide-stage-sandbox.service
After=cms-ide-stage-sandbox.service
UNIT
systemctl daemon-reload
systemctl start cms-ide-stage-sandbox.service isolate.service
/usr/local/bin/isolate --version
systemctl show isolate.service -p ActiveState -p Delegate -p ControlGroup
findmnt /var/lib/cms-ide-stage/boxes
stat -c '%U %a %n' /usr/local/bin/isolate
cat /usr/local/etc/isolate
printf '%s\n' 'SANDBOX_INFRASTRUCTURE_READY_APPROVAL_STILL_DISABLED'
