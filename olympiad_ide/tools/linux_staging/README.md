# Disposable Linux staging procedure

These scripts retain the commands used on the explicitly authorized EC2 instance on 2 November 2026. They provision **a fresh disposable Ubuntu 26.04 host only**. They are intentionally one-shot, reject existing fixture state and are not upgrades for an existing CMS installation. Never point them at a live contest, production database or another AWS instance without explicit authorization. No AWS API, DNS, security-group or firewall command is included.

See [Linux acceptance](../../../docs/olympiad-ide/LINUX_ACCEPTANCE.md) for actual outcomes, failures and limits. The tested application commit is `349d1e9559023b57b28d3e0dac95ca2b97c4a0dc`, after original implementation `7c2bd34d16a6ae9bc263feb660bb60505c31bfab` and packaging checkpoint `7f6517fa12d6e6555382f5f2c4fbeb1f6e03dd01`. The scripts consolidate executed commands and include the observed configuration corrections. Their complete fresh-host sequence has not been rerun on a second host; individual acceptance drivers ran on the authorized host. Do not rerun the destructive unit fixture against the acceptance database.

## 1. Export and transfer reviewed sources

Use the feature branch at an explicitly reviewed commit; record its exact SHA and archive checksums. Build public assets with Node 22 or 24 and the frontend lockfile. Ordinary Python CMS installation still does not run Node. On the operator machine:

```sh
cd /Users/isaevarman/Developer/cms
python3.12 tools/build_olympiad_ide.py
mkdir -m 700 /private/tmp/cms-stage-transfer
git rev-parse HEAD > /private/tmp/cms-stage-transfer/source-commit.txt
git archive --format=tar HEAD > /private/tmp/cms-stage-transfer/cms-source.tar
tar -cf /private/tmp/cms-stage-transfer/ide-assets.tar cms/server/olympiadide/static
shasum -a 256 /private/tmp/cms-stage-transfer/*.tar
```

Do not archive the original IDE folder, `.env`, keys, databases, node_modules or virtualenvs. Set `STAGE_SSH` to the explicitly authorized `ubuntu@HOST` and `STAGE_KEY` to its existing private key path. Both variable names are task-specific. Verify the host fingerprint; use a task-owned known-hosts file. The historical first connection used `accept-new`, then strict checking.

```sh
ssh -i "$STAGE_KEY" "$STAGE_SSH" 'hostname; uname -a; lsb_release -ds; ss -lnt; systemctl --failed --no-pager; df -h /'
# Continue only after auditing a fresh target with no existing application/contest data.
ssh -i "$STAGE_KEY" "$STAGE_SSH" 'sudo install -d -m 0755 /opt/cms-ide-stage; sudo install -d -m 0755 -o ubuntu -g ubuntu /opt/cms-ide-stage/incoming; printf "%s\n" "Explicitly authorized disposable staging" | sudo tee /opt/cms-ide-stage/AUTHORIZED_DISPOSABLE >/dev/null'
scp -i "$STAGE_KEY" /private/tmp/cms-stage-transfer/* olympiad_ide/tools/linux_staging/*.py olympiad_ide/tools/linux_staging/*.sh "$STAGE_SSH":/opt/cms-ide-stage/incoming/
```

The following commands run **on that host**, with root used only for provisioning, supervisor control, peer-authenticated database administration and sandbox setup. Programs always run in isolate through a non-root controller.

```sh
sudo bash /opt/cms-ide-stage/incoming/bootstrap.sh
sudo bash /opt/cms-ide-stage/incoming/install-envs.sh
sudo bash /opt/cms-ide-stage/incoming/sandbox.sh
sudo bash /opt/cms-ide-stage/incoming/postgres.sh
sudo /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/configure.py
```

Bootstrap prevents apt from starting default nginx/PostgreSQL and disables only those fresh default units. It compiles checksum-verified Python 3.12.16 into `/opt/cms-ide-stage/python312`; the image's system Python 3.14 remains available for contestant programs. CMS and IDE use different venvs/SQLAlchemy versions. Isolate 2.7 is pinned to `8f185bb37f3f23e29b33b0c7727c91c13429abe3`. A 2 GiB ext4 loop filesystem supplies real user quotas. Verify UID 60000–60999 are unused before provisioning the explicit isolate UID range. This is a disposable staging filesystem, not a production storage-sizing recommendation.

## 2. Mandatory sandbox gate and separate process ownership

Do not set `WORKER_SANDBOX_APPROVED` to collect tests. As the non-root custom controller, run every real test:

```sh
cd /opt/cms-ide-stage/source/olympiad_ide
sudo runuser -u ideworkerstage -- env -u WORKER_SANDBOX_APPROVED \
  PATH=/usr/local/bin:/usr/bin:/bin PYTHONPATH=backend:. \
  WORKER_BOX_ID_BASE=400 RUN_LINUX_SANDBOX_TESTS=1 \
  /opt/cms-ide-stage/runtime-venv/bin/python -m pytest worker/tests/test_worker.py -k real_ -vv -p no:cacheprovider \
  > /tmp/cms-mandatory26.log 2>&1
sudo install -m 0644 /tmp/cms-mandatory26.log /opt/cms-ide-stage/logs/linux-worker-mandatory.log
```

Review exit status and **26 passed, 7 deselected**, all isolation/credential/quota/network/memory results, helper ownership, cgroup delegation, swap, compiler paths, distinct box-ID ranges and filesystem cleanup. The 7 deselected policy checks are separate; none of the 26 mandatory cases may be skipped. Only after that review, record it and unlock this worker:

```sh
printf '%s\n' 'Operator reviewed mandatory26 pass and actual isolate/cgroup/quota/credential/network controls; record UTC reviewer/date' | sudo tee /opt/cms-ide-stage/SANDBOX_REVIEW >/dev/null
sudo bash /opt/cms-ide-stage/incoming/migrate-start.sh
sudo /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/separate_judge.py
```

`migrate-start.sh` requires the reviewed marker and successful output before setting approval in the root-only worker environment. It migrates only the IDE database as its schema owner and seeds the empty CMS contest. `separate_judge.py` restricts isolate to `root:isolatestage` 4750, gives helper access only to `cmsjudgestage` and `ideworkerstage`, and moves the official Worker to existing CMS ResourceService shard 1 at 127.0.0.2. Main ResourceService shard 0 retains native/CWS/ES/SS/Admin/Proxy. Both use upstream autorestart/process ownership; no second native launcher is introduced. Web/API/ingress units use NoNewPrivileges; the custom controller has PrivateNetwork and execution-only DB grants. Re-run the 26 test command into a different log after changing helper access, then run `verify_boundaries.py` and, as ideworkerstage with `PYTHONPATH=backend:.`, `verify_syscalls.py`.

## 3. Acceptance and regressions

The fixture creates protected random participant/admin credentials in `/var/lib/cms-ide-stage/fixture/browser.json`, six hidden plus two public cases, and separate C++/Python standalone Batch tasks. No credentials or dump should enter Git or CI logs. All HTTP clients validate the dedicated localhost certificate. The scripts below print only sanitized results:

```sh
sudo runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/cms.conf /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/verify_core.py
sudo runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/cms.conf /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/verify_feedback.py
sudo env CMS_CONFIG=/etc/cms-ide-stage/cms.conf /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/verify_outages.py
sudo /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/verify_database_faults.py
sudo bash /opt/cms-ide-stage/incoming/regressions.sh
```

Run core once: feedback expects its persisted original receipts and creates an alternate dataset once. Outage tests intentionally stop/restart only fixture services. DB fault tests temporarily deny connections only to the two exact original staging DB names and restore flags in `finally`. They belong **before** the restore switch. The unit script creates its own `cmside_linux_unitfortesting`; test coordinates/state directories are independent of live staging. Its database-mixin reset must never target `cmside_linux_fortesting` or a restored application DB.

On the operator machine, forward loopback TLS ports 28443/28444/28445 with SSH (`-L PORT:127.0.0.1:PORT`), securely copy only the disposable browser fixture and public certificate into a mode 0700 directory, and update the local fixture's certificate path. Use frontend dependencies from `npm ci` and an installed Playwright Chromium:

```sh
cd /Users/isaevarman/Developer/cms/olympiad_ide/frontend
PLAYWRIGHT_CHROMIUM_PATH=/absolute/path/to/Chromium node tools/verify-linux-staging.cjs /private/browser.json /private/browser-results
```

The verifier requires a loopback HTTPS disposable fixture and pins its certificate SPKI; Node trusts only its CA for response-loss interception. It runs real Run/Run All/Stop, immutable C++ Submit, Python acknowledgement loss/receipt reload, actual judging/public score, task switch, offline Monaco and logout. It does not change OS trust. Leave source and generated evidence in separate directories.

## 4. Bounded load, deadline and restore

```sh
sudo runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/cms.conf /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/fixture.py --add-load-participants 350
sudo runuser -u cmsstage -- /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/build_load.py
```

This creates a private 4.55 MB credential/variable file and target/plan manifests. Inspect their target UUID, actual installation/contest, hardware, toolchains and request costs. Use the generated UUID as `--confirm-disposable`; first run `cms_load.py --validate-only`, then remove only that flag and add `--allow-custom-runs --allow-official-submissions`. Supply **new report paths**. See [CMS_LOAD](../CMS_LOAD.md) for exact flags, fixture protocol and error semantics. The main plan ramps 1/10/50/100/200/300/350 accounts, caps 12 concurrent HTTP actors and 20 HTTP/s, performs 3 new autosaves/account, 2 new visibility events/account, then 5 serial custom runs and 5 real official submissions. It is a short functional workload; it is not a 350-editor soak or 350-compilation capacity claim.

For the fresh generated fixture, set `STAGE_TARGET_ID` to the UUID printed by `build_load.py`. These commands run on the explicitly authorized staging host and refuse existing report paths:

```sh
sudo install -d -m 0700 -o stagepguser -g stagepguser /var/lib/cms-ide-stage/metrics
sudo systemd-run --unit=cms-ide-stage-load-metrics --uid=stagepguser \
 /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/metrics.py \
 --seconds 900 --output /var/lib/cms-ide-stage/metrics/load.json
sudo runuser -u cmsstage -- /opt/cms-ide-stage/cms-venv/bin/python \
 /opt/cms-ide-stage/source/olympiad_ide/tools/cms_load.py \
 --target /var/lib/cms-ide-stage/fixture/load/target.json \
 --credentials /var/lib/cms-ide-stage/fixture/load/credentials.json \
 --plan /var/lib/cms-ide-stage/fixture/load/main-plan.json \
 --confirm-disposable "$STAGE_TARGET_ID" --allow-custom-runs --allow-official-submissions --validate-only \
 --report /var/lib/cms-ide-stage/fixture/load/validation.json
sudo runuser -u cmsstage -- /opt/cms-ide-stage/cms-venv/bin/python \
 /opt/cms-ide-stage/source/olympiad_ide/tools/cms_load.py \
 --target /var/lib/cms-ide-stage/fixture/load/target.json \
 --credentials /var/lib/cms-ide-stage/fixture/load/credentials.json \
 --plan /var/lib/cms-ide-stage/fixture/load/main-plan.json \
 --confirm-disposable "$STAGE_TARGET_ID" --allow-custom-runs --allow-official-submissions \
 --report /var/lib/cms-ide-stage/fixture/load/main-report.json
sudo runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/cms.conf \
 /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/final_minutes.py
```

This is the short measured procedure, including its original short-poll failure. Do not run an unrelated submission workload during the deadline driver. Preserve report exit codes; stop and reconcile unknown official outcomes. After the metrics unit exits, its protected output remains; stop it before any DB fault test.


The historical main official fixture has only four feedback GETs at 2 HTTP/s. It deliberately remains unchanged as evidence: all 5 final assertions failed while judging was still pending; later real scores were 100. `reconcile_load.py` is a **historical read-only** checker for that fixture's IDs 5–9; it must not be generalized to a different run by guessing IDs. Preserve original failures; for a new acceptance plan use a documented sufficiently long bounded feedback window and reconcile by original intent. Never retry official POST automatically.

As a separate run, `final_minutes.py` configures an actual 120 second deadline in this disposable contest, runs 10 mixed actors at 5 HTTP/s/concurrency 2 with longer bounded feedback polling, verifies committed receipt access after expiry and rejects a new late intent, then restores the old stop time in `finally`. It is not a 350-participant deadline burst. Do not run any unrelated workload while it counts its 10 receipts.

Start `metrics.py --seconds 900 --output /var/lib/cms-ide-stage/metrics/NEW.json` as stagepguser after creating its owned 0700 metrics directory. A task-owned transient systemd unit keeps sampling independent of the test client. Match UTC sample windows to actual report start/end before computing CPU/RAM, custom-queue age, connection maxima and allocated-file growth. The sampler counts its own DB connections and host CPU includes the loopback load generator. Keep raw protected samples; use sanitized aggregates for Git. Stop the sampler before independent DB fault injection. Its exact source DB names intentionally require review after restoration.

For a representative capacity release gate, use separately authorized resources and record the actual contest source sizes/test costs/arrival rates. Progress from 10→50→100→200→300→350, with a sustained mixed-editor soak, realistic per-participant fresh edit/telemetry events, measured custom-run concurrency/queue age, independent official submission bursts, and a 350-participant last-minute burst plus recovery. Agree latency/error/queue budgets before the test; stop escalation on infrastructure failures, unknown official outcomes or exhausted disk/memory. The current 2 CPU host and short fixtures do not establish those budgets. More polling or idempotent replay alone does not simulate typing or new compilation. No such additional soak/burst was executed here.

After all original-DB faults/load tests, quiesce writers and restore into **new empty databases**:

```sh
sudo /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/backup_restore.py
sudo runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/cms.conf /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/verify_verdicts.py
sudo /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/verify_boundaries.py
sudo /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/incoming/inspect_final.py
```

`backup_restore.py` stops both ResourceService owners plus runtime/custom worker/ranking, archives protected configuration/ranking state, calls `restore.py` as the local PostgreSQL owner, compares all rows/schema/sequences/large objects/source bytes/principal mappings, restores role CONNECT grants and starts the application against new DBs. It checks the same participant's workspace fingerprints, original receipts and actual judged feedback. Originals remain untouched. Failures restore original configuration in `finally`. Re-run the real browser and a 350-account context-only plan after success. Localhost source/destination restoration is not off-host disaster recovery, and the retained configuration archive was not restored onto a second host.

## Operations and retained state

Public access is SSH only. Participant/native TLS is `https://localhost:28443/ide/`, admin 28444, ranking 28445 through the task tunnel. PostgreSQL uses only `/run/cms-ide-stage-pg` port 15432. `/etc/cms-ide-stage` holds protected config/key/env files; application state is `/var/lib/cms-ide-stage`. Do not copy those trees into Git. The generated certificate expires after 7 days; the disposable contest closes 2 days after creation. Reboot/autostart, off-host recovery, dedicated production worker hosts, production certificates/ingress and production sizing were not certified. Units are started explicitly; no reboot was performed.

Inspect `systemctl status cms-ide-stage-{postgres, log, resource, judge, runtime, worker, ranking, ingress}` and the two ResourceService child groups. To stop this beta, stop only those eight task-owned units and the task SSH tunnel; do not delete databases, private keys or original IDE source. Isolate/mount/loop-file cleanup requires all sandbox users stopped first. No unattended cleanup, instance termination or recurring load run was scheduled.

## 7. Workbench, history and debugger update

The 3 November update adds the CWS entry card, simple STDIN/STDOUT, active-file execution, deterministic read-only replay and isolated DAP. Follow [Phase6 architecture](../../docs/PHASE6_ARCHITECTURE.md) for the additive IDE migration, role grants, dedicated worker and separate approval gate. The original26 Run prerequisites remain in `test_worker.py`; new debug tests must not be confused with those26.

`install_debug_ws.py` adds only the exact UUID DAP WebSocket routes to the existing staging public/private HTTPS server blocks, rejects query tokens, validates nginx as its restricted account and reloads only ingress. Ordinary HTTP debug APIs still pass CMS authentication; the WS requires an owned, short-lived, single-use attachment ticket. The script is one-time and refuses duplicate installation; it preserves a0600configuration backup.

After building assets, create Git source and generated-asset archives named `vnext-source.tar.gz` and `vnext-assets.tar.gz` with an exact `vnext-commit.txt`, then copy them plus `update-workbench.sh` into the task-owned incoming directory. Execute the update from `tmux` as documented in PUBLIC_HTTPS. It preserves CMS ResourceService ownership, keeps separate Python environments, runs all debug prerequisites with both approval flags unset, and only retains an existing reviewed debug approval. It does not perform initial approval or database migration. Root-owned public application installs use umask022; secrets stay in separate0600configuration files.

`repair_package_permissions.py` retains the narrow repair used after the initial umask077application-install failure. It byte-compares installed application Python to owned source and touches only those packages, CMS metadata and CMS launchers. It never changes dependency/configuration/key permissions. Correctly installed releases do not require this repair.

## 8. Participant workflow and private Admin history

The participant follow-up removes History/recording diagnostics, adds line-number/F9/explicit-line breakpoints, preserves problem workspaces in place and presents a green minimal Submit form. Private CMS Admin has Code history with uploaded-recording replay. See [PARTICIPANT_ACCEPTANCE](../../../docs/olympiad-ide/PARTICIPANT_ACCEPTANCE.md) for exact deployed commit, browser/role/source proof and final 130/97/759 test outcomes.

For repeat Linux checks use `reverify_linux.py`: it refuses the missing-config fallback and validates the retained `/etc/cms-ide-stage/cms-unit.conf`, exact test database, account, Unix socket, fixture paths and service coordinates before running fixtures. Runtime tests use isolated `test_*` schemas in the non-active retained IDE database. `create_ui_acceptance.py` retains the executed fresh-actor procedure and refuses existing output/account replacement. All credentials remain in protected 0600 files outside Git. No new migration, public Admin port, dependency upgrade or worker-security relaxation is involved.

## Public Admin HTTPS follow-up

The bounded existing-host `install_public_admin.py` procedure is documented in [PUBLIC_ADMIN_HTTPS](../../../docs/olympiad-ide/PUBLIC_ADMIN_HTTPS.md). It changes only the explicitly authorized staging ingress, keeps native Admin authentication/permissions, and reloads only nginx. Its current deployment and verification status is recorded there; do not treat preparation as a successful deployment.
