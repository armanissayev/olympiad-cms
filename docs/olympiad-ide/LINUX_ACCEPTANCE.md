# Linux staging end-to-end acceptance — 2 November 2026

**The beta end-to-end milestone passed on the explicitly authorized Linux staging instance.** The same participant logged in through CMS, edited Monaco, executed a custom test through real isolate, submitted official C++ and Python solutions, and received real CMS judging results. Run/Stop, refresh, lost-response receipt recovery, component/DB outages, CWS fallback and application recovery from restored databases were exercised. This accepts the disposable beta workflow; production contest readiness remains gated by the limits below.

## Scope and provenance

Only `ec2-54-206-171-67.ap-southeast-2.compute.amazonaws.com` was accessed, using the user-specified existing SSH key. The target was a fresh host without an existing application or contest database. No other AWS host, production data, DNS, security group, firewall or AWS account setting was accessed/modified. Application listeners remain loopback; only SSH 22 binds publicly. Host-key checking used a task-owned known-hosts file. Original authoritative IDE source and private key were preserved.

Repository `/Users/isaevarman/Developer/cms`, branch `feature/olympiad-ide-integration`; CMS base `CMSv1.5.1`, SHA `7c9fec8aa1a25ec93d624aebf815804dd93df9db`; integration `7c2bd34d16a6ae9bc263feb660bb60505c31bfab`. Initial Linux archive was checkpoint `7f6517fa12d6e6555382f5f2c4fbeb1f6e03dd01`; SHA256 `886cf360b4f14f12334d8911ec2cb91af1e9acebd8e5d9b9eda24f77f8846132`. Public asset archive SHA256 `d02ecac676702217b7a8d39bae3b589e3fc3fdad4b94d7b140c1ed3a34022863`.

The real CMS DB fault test exposed a judging recovery defect. Fix commit **`349d1e9559023b57b28d3e0dac95ca2b97c4a0dc`** adds SQLAlchemy 1.3 `pool_pre_ping=True` and a real terminated-connection regression. Both changed files were deployed, CMS reinstalled into its own venv, and CMS-owned services restarted. The final installed/source database module hashes match (`5e06cd8057f1b49b56960049aed2afcdf4c62732876bb5d837bad78e15f9aa1c`). Initial core/feedback/load evidence predates that fix; the successful DB retest, restricted-role outages, restore, final browser, failure verdicts and 350-account context retest use the fix. No adapter/frontend redesign or dependency upgrade was made.

[Environment and process ownership](evidence/linux-staging/environment-results.json), [source procedures](../../olympiad_ide/tools/linux_staging/README.md), and the sanitized files under [evidence/linux-staging](evidence/linux-staging/) make the result reviewable. Raw secrets, generated credentials, browser profiles, private configs and database dumps stay outside Git.

## Actual host and dependency compatibility

| Item | Observed version/configuration |
| --- | --- |
| OS / kernel / architecture | Ubuntu 26.04.1 LTS /7.0.0-1014-aws /x86_64 |
| Capacity of this fixture | 2 logical CPUs; 3,996,524,544 bytes RAM; ~28 GB root filesystem; no swap |
| CMS interpreter / key packages | Separate Python 3.12.16; SQLAlchemy 1.3.24, Tornado 4.5.3, gevent 25.5.1, pytest 9.2.0 |
| IDE runtime interpreter / packages | Separate Python 3.12.16; FastAPI 0.150.0, SQLAlchemy 2.1.5, Alembic 1.20.0, Uvicorn 0.54.0, pytest 9.1.1 |
| Actual contestant toolchains | G++ 15.2.0; system CPython 3.14.4; OpenJDK/javac 17.0.20.1 |
| Frontend / ingress / DB | Node 22.22.1; nginx 1.28.3; PostgreSQL 18.6 |
| Isolate | 2.7, commit 8f185bb37f3f23e29b33b0c7727c91c13429abe3; helper SHA256 75b512f66baa9c291282e5f2546193175d964f9f5f694a286e0d5edbcd80a837 |

System Python 3.14 was not used for old CMS dependencies. Python 3.12.16 was compiled from the [official release](https://www.python.org/downloads/release/python-31216/) after verifying tar.xz SHA256 `b5796915dc45ff745cfb4e990a7e7c93d6f546328a102ce31448d69ebc37575c`. CMS and IDE venvs remain `/opt/cms-ide-stage/{cms,runtime}-venv`; both `pip check` passed before and after deployment. This is an observed compatible test installation, not a future resolver or vulnerability-audit guarantee.

The pinned gevent emits ignored after-fork threading assertions on Python 3.12.16 and logging-finalization warnings. Functional tests completed, but these compatibility warnings remain a release-review concern. Later upstream fixes are described in the [gevent changelog](https://docs.gevent.org/changelog.html); no unreviewed version change or monkeypatch bypass was introduced. Existing pkg_resources/datetime deprecations and frontend chunk-size advisories also remain. The CMS-wide old dependency stack still needs a deployment security review.

## Security prerequisites and process ownership

The helper's final mode is 4750, root:isolatestage. Only official `cmsjudgestage` and custom `ideworkerstage` accounts can execute it; native/CWS `cmsstage`, API `ideapistage` and ingress `cmsingressstage` cannot. Main ResourceService 0 owns CWS/native/ES/SS/Admin/Proxy; separate ordinary ResourceService 1 owns CMS Worker 0 on 127.0.0.2. Web-side units have NoNewPrivileges. The separate CMS judge config omits cookie signing, native assertion and ranking secrets. Official judging and custom execution use different accounts, supervisors, Python environments and box ranges.

The custom controller has PrivateNetwork, no CMS DB CONNECT privilege, no workspace SELECT privilege, no readable CMS/native/runtime key/config or judge cache; execution job SELECT is allowed. Real TCP connection attempts from its network namespace to CMS RPC, CWS, native and private runtime fail. PostgreSQL is Unix-socket-only with peer authentication and four restricted application/migration roles. API cannot read the CMS config/key. [Boundary results](evidence/linux-staging/boundary-results.json).

Isolate keeper runs in `/isolate.slice/isolate.service` with `Delegate=yes`; cgroup v2 CPU/cpuset/memory/pids controllers are present. A 2 GiB ext4 loop filesystem mounted `quota,usrquota` enforces actual disk quotas. Explicit unused sandbox UID/GID 60000–60999 replaces the image's unconfigured subordinate-user default. No swap, unrestricted subprocess fallback, network-sharing flag or security-prerequisite skip was used. Direct probes through unchanged `Sandbox.run --syscalls=31` returned ENOSYS for keyctl/io_uring/flock, EAFNOSUPPORT for AF_VSOCK and EPERM for fcntl locking. [Syscall results](evidence/linux-staging/syscall-results.json).

The 26 mandatory real tests passed **before** approval was recorded, with approval explicitly unset. Results were reviewed, then only the root-owned custom worker environment received `WORKER_SANDBOX_APPROVED=1`. After restricting helper access, all 26 ran again successfully. This one-host disposable layout tests account/network separation; production still needs the documented dedicated-worker-host risk boundary and its own review. A compromised root helper on a shared kernel threatens the whole staging host.

## Executed tests and commands

| Check | Actual result / durable output |
| --- | --- |
| Mandatory real Linux worker suite | **26 passed, 7 deselected, 9.79 s**; [initial output](evidence/linux-staging/linux-worker-mandatory.log) |
| Same suite after helper/account restriction | **26 passed, 7 deselected, 9.81 s**; [final output](evidence/linux-staging/linux-worker-restricted-helper.log) |
| Remaining worker policies | **6 passed, 1 expected non-Linux denial skip, 26 deselected**; [output](evidence/linux-staging/linux-worker-policy.log) |
| Linux complete CMS suite after pool fix | **746 passed, 9 skipped, 28 subtests passed, 30.14 s**; [output](evidence/linux-staging/cms-linux-unit-after-pool-fix.log) |
| Focused real PG idle-disconnect regression | **1 failed before fix →1 passed after fix**; [red](evidence/linux-staging/db-pool-before-fix.log), [green](evidence/linux-staging/db-pool-after-fix.log); included in 746, not an extra distinct pass |
| Separate IDE PostgreSQL suite | **75 passed**, exit 0; [output](evidence/linux-staging/backend-linux-tests.log) |
| Linux frontend | **81 passed**; npm ci/typecheck/lint/build passed on Node 22; [output](evidence/linux-staging/frontend-check.log) |
| Real native Chromium scenario | **14 checks passed, zero page errors**, initially and after restore; [final browser report](evidence/linux-staging/browser-post-restore.json), [stdout](evidence/linux-staging/browser-post-restore.log) |

The 26 cover real C++17/20/Python 3/Java 17 success and compilation/runtime/time errors, fork/output/network/path/recursion containment, credentials, neighboring boxes, disk quota, memory exhaustion and bounded JVM overhead. The single policy skip asserts rejection on non-Linux and correctly does not apply here; none of 26 security cases skipped. Existing 9 CMS environment/platform skips are retained, not counted as passes. Linux shared-mime-info resolves the six historical macOS baseline MIME failures.

Exact Linux commands (all configuration below belongs solely to disposable staging):

```sh
cd /opt/cms-ide-stage/source/olympiad_ide
sudo runuser -u ideworkerstage -- env -u WORKER_SANDBOX_APPROVED \
 PATH=/usr/local/bin:/usr/bin:/bin PYTHONPATH=backend:. \
 WORKER_BOX_ID_BASE=400 RUN_LINUX_SANDBOX_TESTS=1 \
 /opt/cms-ide-stage/runtime-venv/bin/python -m pytest worker/tests -k real_ -vv -p no:cacheprovider

cd /var/lib/cms-ide-stage/unit-run
sudo runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/cms-unit.conf \
 PYTHONPATH=/opt/cms-ide-stage/source /opt/cms-ide-stage/cms-venv/bin/python \
 -m pytest /opt/cms-ide-stage/source/cmstestsuite/unit_tests -q --tb=short

cd /opt/cms-ide-stage/source/olympiad_ide/backend
sudo runuser -u idemigratestage -- env \
 TEST_DATABASE_URL='postgresql+psycopg://idemigratestage@/ide_linux_staging?host=/run/cms-ide-stage-pg&port=15432' \
 /opt/cms-ide-stage/runtime-venv/bin/python -m pytest -q --tb=short

cd /opt/cms-ide-stage/source/olympiad_ide/frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

The CMS tests use `cmside_linux_unitfortesting` plus distinct writable unit state directories, not the contest DB. The runtime suite uses isolated schemas. Local Chromium 133.0.6943.16 ran against real remote services over the SSH tunnel, using the committed `frontend/tools/verify-linux-staging.cjs` and a protected fixture/certificate. `PLAYWRIGHT_CHROMIUM_PATH` selected the existing cached executable; Node 24.19.0 runs the browser driver. The standalone 13-pass suite is historical local evidence and is not added to this 14-check native result.

## End-to-end requirement matrix

| Requested work | Real outcome and evidence |
| --- | --- |
| 1. Linux compatibility/separate environments | Passed installation/import/pip check, Linux regressions and actual programs; pinned gevent warnings remain for release review |
| 2. Reproducible commands/config/lifecycle | Staging sources and command order preserved; root-owned code/secrets, separate accounts, native ResourceService owns children. Consolidated fresh-host scripts were syntax-checked; no second-host full provisioning run claimed |
| 3. cgroup v2/quota/syscalls/toolchains | Passed actual keeper/delegation/quota tests, syscall denials and measured compiler/interpreter versions |
| 4. Complete 26 worker suite |26/26 passed twice; approval absent during tests, enabled only after review |
| 5. Independent CMS judging | Official Worker owned by ResourceService 1/cmsjudgestage; custom worker separately supervised/isolated; official judging continues during custom/API outage |
| 6. Disposable contest/tasks | Contest 1 `ide-load-linux-staging`, tasks cppsum/pysum, 1 public+3 hidden cases per task, Sum 25/case, finite 2 tokens; 351 generated participants including primary and 350 load users |
| 7. Native C++/Python official submission | Actual Monaco browser capture/POST 201, exact bytes and SHA256; both actually compiled/evaluated, not admission-only |
| 8. Results/CWS/Admin/ranking | Both correct programs 100 full operator score/25 public score; four measured evaluations each; CWS and authenticated Admin show results; Proxy publishes ranking changes. Real CE/WA/RTE/TLE also confirmed |
| 9. Feedback/tokens/rejudge/dataset | Restricted hidden data absent; actual CWS token exposes permitted full score; actual evaluation IDs change on rejudge; alternate dataset produces 40 full/10 public and ranking 40; original dataset restored |
| 10. Real-worker browser |14 successful native checks, including measured custom stdout 5, Run All Accepted/Whitespace Wrong Answer, running Stop→CANCELLED, reload/history, immutable C++, lost Python ACK/reload with exactly one POST, official public scores, task switch, offline Monaco/auth/logout recovery |
| 11. Outages/durability/restore/CWS fallback | Actual worker/API/ES/native outages, separate DB faults after fix, normal sweep/restart, same durable receipts, ordinary multipart CWS fallback judged, both DBs restored into new names and application/browser recovered |
| 12. 300–350 load plan/scripts | Progressive 1→350 accounts, 350 autosave/telemetry, 5 custom/5 official, 10 deadline mixture and final 350 context retest executed only here. Short bounded tests; sustained 350 editor/compile/final-minute capacity remains unproved |

[Core judging/Admin/ranking](evidence/linux-staging/core-results.json), [feedback/token/rejudge/dataset](evidence/linux-staging/feedback-results.json), [official failure verdicts](evidence/linux-staging/verdict-results.json), [component outages](evidence/linux-staging/outage-results.json), [DB faults](evidence/linux-staging/database-fault-results.json), [deadline](evidence/linux-staging/final-minutes-results.json).

Untokened participant status omitted full hidden scores while operators verified 100. Public 25/25 appeared in the actual browser. Hidden judge inputs/outputs were absent from feedback, token responses and unauthorized attachment downloads. Controlled official compilation failure returned state 2 with compiler diagnostics; WA/RTE/TLE returned actual evaluated state 5 and zero score, with four real evaluations for each executable fixture. No hidden test labels/bytes are dumped into these reports. These checks cover the supplied standalone Batch/Sum plugin only.

## Outage and database recovery findings

With the custom worker stopped, custom admission 503/worker_unavailable while native official 201 reached a real CMS result and CWS remained 200. With ASGI stopped, runtime gateway 503 while context/CWS 200 and official 201 judged; the exact workspace survived restart. EvaluationService intentionally stopped through normal ResourceService controls; admission 201/retry 200 remained durable, and ordinary restart/sweep produced the real result in 7.373 s in the final restricted-role run. No manual `new_submission` recovery hint was inserted. Native intentional stop remained honored; ordinary CWS multipart submission 302 was really judged and appears in native history with null IDE correlation.

The first real CMS DB fault exposed more than the historical Mac first-request 500: a dead idle pooled connection raised OperationalError during a queued operation, leaving committed submission 24 uncompiled; the 117 s sweep found no new work because execution bookkeeping still considered it active. The original 150 s judging wait failed. The focused killed-idle-connection regression reproduced failure before `pool_pre_ping` and passed afterward. After deployment/restart, normal durable startup discovery recovered the previously stuck work. The complete fault retest then passed without fabricating feedback or retrying a transaction.

During CMS DB loss: liveness 200/readiness 503/context 500/official 500; after recovery the unadmitted intent was 404, an explicit same-body deliberate retry 201, duplicate 200 and real judging completed. During IDE DB loss: private readiness 503/gateway 503, native context/CWS 200, official 201 and actual judging completed; the old workspace returned unchanged. Both connection flags were restored. Connection pre-ping discards dead **idle** connections; it does not replay in-flight SQL/POSTs or promise success during a live database failure.

## Backup/restoration actually executed

All application writers, both ResourceService owners, custom worker, runtime and ranking were quiesced. PostgreSQL 18 custom-format snapshots restored into new empty databases, preserving numeric CMS IDs and the original installation/key identity. Every table's sorted row fingerprint, column/constraint/index/sequence state and all large-object bytes matched before application restart.

| Source → retained active restored DB | Verified contents at restore |
| --- | --- |
| `cmside_linux_fortesting` → `cms_restore_21c7bd2d5bfortesting` |28 tables; 30 submissions, 28 native receipts, 32 result rows, 128 evaluations, 19 large objects; 28 native file byte/SHA1/SHA256 comparisons; 917,046 byte dump |
| `ide_linux_staging` → `ide_restore_d4008d5dedfortesting` |21 tables; 351 principal mappings, 353 workspace/task bindings, 23 execution jobs, 1,022 telemetry events; Alembic f5a001; 623,755 byte dump |

Original databases remain retained. Same participant session, 2 workspace fingerprints and 2 original receipts/judged responses matched through the restarted application; ordinary CWS 200. The complete real-worker browser passed again against these restored DBs. Later browser/verdict tests added new rows only to the restored copies. [Restore report including exact pg commands](evidence/linux-staging/restore-application-results.json).

Protected config/ranking archive remains `/var/lib/cms-ide-stage/backups/protected-config-and-ranking.tar.gz`; raw dumps/reports are in `/var/lib/cms-ide-stage/backups/restore-b5f6v766`, 0700 directory/0600 dumps. They were not downloaded to Git. This is local logical PostgreSQL dump/restore into the same cluster, with independently exported snapshots while writers were quiesced; no atomic cross-database transaction, remote disaster recovery, production backup, or restored secret archive on a second machine is claimed.

## Measured load and limits

Main run 15:38:35.473379Z–15:43:32.764151Z used 350 distinct accounts progressively, max 12 concurrent HTTP actors, global rates 3/10/20 HTTP/s, simple 671 byte C++ source/~1 KiB editor documents, 3 fresh autosaves and 2 fresh visibility events per participant. Custom run cost was one small C++20 compile/one case; official cost one small C++17 compile/four Batch cases. Runner and services shared the host; TLS was real but transport was loopback. This is not 350 concurrent browsers, sustained keystroke telemetry or 350 parallel compilers.

| Scenario | Accounts / HTTP requests | HTTP p 50 / p 95 / p 99 ms | Outcome |
| --- | --- | --- | --- |
| Context stage 300 |300 /600 |13.156 /1784.966 /2106.695 |0 errors |
| Context stage 350 |350 /500 |11.267 /1571.680 /2209.732 |0 errors; reused earlier authenticated actors; includes 50 fresh logins |
| Autosave |350 /1400 |27.766 /32.293 /36.722 |new workspaces +3 new revisions/person; 0 errors |
| Telemetry |350 /1050 |25.087 /29.297 /31.206 |new session/checkpoint/batch/status, 2 events/person; 0 errors |
| Custom runs |5 /25 |25.161 /34.580 /34.753 |all FINISHED with actual result assertion |
| Official submissions |5 /25 |13.675 /24.400 /26.874 |all 201 admitted; 5 short-poll terminal assertions failed; later all real 100 |
| Final 120 s deadline mixture |10 /420 |See raw report |0 HTTP/operation errors; 10 custom and 10 official terminal checks, late committedGET 200/new intent 422 |
| Final post-fix/post-restore context |350 /1400 |39.663 /2054.814 /2476.711 |350 fresh logins+context, 0 errors; 16:59:43.115461Z–17:01:23.826666Z |

The main 11 scenarios produced **4,561 HTTP requests, zero HTTP errors, zero unknown official outcomes, 5 failed final-state assertions**. Exit 1 and those failures remain in [main report](evidence/linux-staging/load/main-report.json). Only~2 seconds elapsed before its final official feedback poll; evaluation was still pending. A later read-only reconciliation verifies the same 5 original submissions IDs 5–9, source hashes, four actual evaluations, operator 100/public 25 and participant state 5: [reconciliation](evidence/linux-staging/load-reconciliation-results.json). This does not change the original result to a pass or retry any official POST. Service logs observed approximately 5 seconds for the last such result; no end-to-end judging percentile or 2 second SLA is claimed.

The separate [final mixture report](evidence/linux-staging/load/final-report.json) used longer bounded feedback polling with a genuinely configured 120 second contest deadline; 10/10 receipts arrived before it, last 15:50:53.918711Z against 15:51:42.352971Z. Post-deadline reconciliation and late rejection were exercised. The old contest stop was restored. [Final 350 report](evidence/linux-staging/load/post-restore-report.json) proves restored identity/login/context availability, with no new capacity claim. Combined authentication/read latency includes BCrypt and must not be labeled pure context latency.

Independent one-second metrics collected 897 samples from 15:37:38 to 15:52:38 UTC. In the [main 296-sample window](evidence/linux-staging/main-report-metrics.json), CPU peaked at 61.3% (mean 34.38%); used RAM peaked at 1,300,697,088 bytes and available RAM stayed above 2,253,180,928 bytes. The custom queue reached depth 1 and oldest age 0.208662 seconds. CMS/IDE connections peaked at 25/7; allocated database growth was 0/+5,718,016 bytes.

In the [final 83-sample window](evidence/linux-staging/final-report-metrics.json), CPU peaked at 80.7%, used RAM at 1,308,659,712 bytes, and the custom queue at depth 1/age 0.120313 seconds. CMS/IDE connections peaked at 21/7 and allocated growth was +40,960/+73,728 bytes. Zero allocated growth can mean reused pages, not no writes. CPU includes the load generator and connections include observers. The load harness's metrics remain null; these were sampled independently. Raw 443KB samples remain protected on-host at `/var/lib/cms-ide-stage/metrics/load.json`.

The committed [load procedure](../../olympiad_ide/tools/linux_staging/README.md) preserves generated fixture construction and exact flags plus a representative sustained 350-participant test plan. No additional resources or higher-risk burst were silently authorized. Production arrival rates/source sizes/hidden-suite cost, sustained editor/telemetry load, 350-person final-minute burst, competing compiles, WAN/TLS/auth tail budgets, and disk-pressure behavior remain release gates.

## Retained failures and release blockers

- Fresh install corrections: unconfigured isolate subordinate user prevented keeper start until explicit nonconflicting UID range; non-root nginx lacked owned FastCGI/uWSGI/SCGI temp dirs until configuration corrected. Consolidated scripts retain both fixes.
- Initial unit setup used empty async coordinates, then insufficient fixture/writable-directory/default-port configuration. These caused 33 and 6 setup/test failures; the corrected isolated unit fixture passed 745 before the new regression and 746 after. No failures were removed or converted to skips.
- First browser attempts hit a 20 second cold bundle-load timeout; gzip and a 120 second startup allowance produced successful real runs. Initial Stop fixture's short busy loop hit TLE before the click; a bounded 4 second sleeping fixture then demonstrated running cancellation without increasing server limits. No fake worker result was used.
- The genuine stale-pool judging failure and five short-poll load failures are preserved above. The pool failure is fixed and retested; the original load report remains nonzero. Scripts were consolidated from executed operations and syntax-checked; fresh installation was not repeated on a second VM.
- Production release still requires old-stack vulnerability/compatibility review (including gevent warnings), original IDE licensing/attribution review, calibrated judging hardware/isolate advisories, dedicated production execution hosts, TLS/ingress/rate/backup/access/retention policy, sustained representative 350-participant capacity and final-minute contention/recovery testing. SMT/timing/ASLR/THP advisories were recorded; security protections were not disabled to improve benchmark output.
- No reboot/autostart, off-host encrypted backup restore, total-host/disk exhaustion/failure, external file-storage restore, multi-contest routing, unsupported CMS task/score-plugin policy, or production rollout is certified. These limits do not negate the completed disposable beta E2E workflow.

## Running beta and artifacts

Participant/native: `https://localhost:28443/ide/`; Admin 28444; ranking 28445, reachable through the existing task-owned SSH tunnel only. Protected local access details are `/private/tmp/cms-linux-staging/STAGING_ACCESS.txt` (0600 within 0700 directory); no credentials are in this report. TLS uses the dedicated 7 day localhost certificate, not a publicly trusted certificate. No OS trust store change was made. The contest expires 2 days after creation.

All 8 task-owned application/database units and isolate are active; original/restored databases and protected backups are retained. Test clients and sampler completed; no recurring workload was installed. No production merge, push or PR was created. The original IDE source remains unchanged. See [IMPLEMENTATION_STATE](IMPLEMENTATION_STATE.md) for the current release decision and [VERIFICATION](VERIFICATION.md) for historical/local comparisons.
