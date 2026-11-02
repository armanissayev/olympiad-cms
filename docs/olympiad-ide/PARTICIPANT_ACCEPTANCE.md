# Participant workflow and administrator history acceptance

3 November 2026. Deployed application **`5106855e3c0cb003bd1558d163f7bcda46d35018`**, branch `feature/olympiad-ide-integration`, on the explicitly authorized disposable EC2 staging instance only. [Public CMS](https://54.206.171.67/) · [IDE](https://54.206.171.67/ide/). Public TLS validation remained enabled. No production database, DNS, networking, helper security or service ownership was changed.

## Requested behavior

| Request | Implemented behavior and real result |
| --- | --- |
| Remove participant History Replay | History activity and persisted History sidebar are hidden in CMS participant mode. Recording diagnostics, session IDs, errors and export controls are absent; a quiet accurate recording disclosure remains. Actual participant event/checkpoint history reads returned 403. Standalone development behavior is retained. |
| Fix breakpoints | Line-number clicks, F9 and explicit Add breakpoint line controls work. Live changes reach the actual adapter for unchanged captured source. A real GDB session paused, added/removed breakpoints and stopped at lines 5/6/5, then confirmed STOPPED; source hash remained unchanged. Edited source explicitly requires restart rather than changing the captured program. |
| Change problem in the same window | Six actual problem changes preserved the same document and browser tab with zero popups. Source and STDIN remained separate per problem and restored on returning. Old request drains, delayed receipt writes, failed storage and removed-problem recovery have focused coverage. |
| Simple Submit, green top-right box | Actual browser verified placement and green styling. Participant chooses problem/file; supported language is inferred. One Submit click captures immutable source, saves the intent and sends it with existing receipt/recovery safeguards. Hashes, correlation internals and migration controls are absent from this form. |
| CWS submissions 500 | Fixed missing `tokens_info` across both submission macro layers. Real C++/Python/C++ submissions were judged, then two permitted native token uses exhausted contest tokens. The unplayed C++ submission row rendered HTTP 200 on the formerly failing branch. Three real WSGI regressions cover exhausted/future/available tokens and official/unofficial rows. |
| Remove the pictured diagnostics window | CMS participant recording indicator is a non-interactive disclosure. No diagnostic modal or raw backend error is exposed there. Fixed the underlying numeric CMS task-ID validation mismatch; unchanged durable observation batches now upload successfully without rewriting their digests. |
| Admin-only writing history | Private CMS Admin → contest → Code history. A separate authenticated Admin browser selected the exact participant/problem and replayed uploaded server records. Guest and actual participant cookies were denied. Server reconstruction and source are read-only. Actual TEXT_INSERT event 11 changed empty source at event 10 into the exact 83-character submitted file at event 11; hashes matched the participant fixture. |

[Participant JSON](evidence/participant-polish/participant-results.json), [Admin JSON](evidence/participant-polish/admin-results.json), [actual edit replay](evidence/participant-polish/admin-replay-edit.json), [screenshots/logs](evidence/participant-polish/). Both browser runs had zero page errors; participant run also had zero server errors/popups. Admin issued zero history mutation requests. The participant run used exactly one debug session, three official submissions and two token uses.

The three actual official submissions reached CMS scored status 5 and public score 25/25 each. Full score was restricted before permitted token use. These are real CMS judging outcomes, not merely submission admission or custom-run output. All six numeric INTENT/ADMITTED observations in the recorded successful batches were accepted. Seven real recording sessions were registered during task changes. No existing participant password or source was changed for acceptance; a new disposable actor was used.

## How administrators open history

Open [private Admin code history](https://localhost:28444/contest/1/ide-history) through the existing Admin SSH tunnel. Sign in with the existing full-permission CMS administrator, select Participant and Problem, Load recordings, then select a recording. Use the timeline/Play/Pause and source-file selector. [Administrator guide](ADMIN_HISTORY.md) contains authorization, retention and reconstruction details.

If the private tunnel is closed, run from the Mac containing the existing key:

```sh
ssh -i /Users/isaevarman/Developer/olympiad-ide/olympiad-worker-key.pem -N -L 28444:127.0.0.1:28444 ubuntu@ec2-54-206-171-67.ap-southeast-2.compute.amazonaws.com
```

The private listener uses the existing localhost certificate; browser automation pinned that exact public key, limited to private localhost ports. Public participant HTTPS used ordinary certificate validation. No public Admin route/port was opened. Only retained uploaded recordings appear: browser-only, pending, expired or unmapped legacy recordings are not invented. Old durable browser batches remain retained and can resume uploading with the schema fix.

## Verification and commands

| Check | Actual result |
| --- | --- |
| Frontend |130 passed across 17 files; typecheck/lint/build passed;13 public assets staged |
| Full runtime, separate real PostgreSQL |97 passed locally and on Linux; one TestClient deprecation warning |
| Full Linux CMS |759 passed, 9 skipped, 28 subtests, 32.12s; 399 warnings retained |
| Focused native/Admin |6 Admin WSGI/PostgreSQL and 3 CWS token-render tests passed; overlap full counts |
| Focused runtime/Admin and recording |8 Admin tests and 17 telemetry tests passed; overlap full counts |
| Actual public participant and private Admin browsers |Passed all requested flows, actual source edit reconstruction and role denial |
| Deployment/host |Both independent venv pip checks passed; all 9 units active and boot-enabled, tmux retained, no failed units, debug box 600 clean, key/env modes 0600, PrivateNetwork retained |
| Source and packaging |124 original hashes unchanged; exact 5106855e source/native packages include all 13 matching public asset hashes and new Admin files, with no forbidden secrets/dependencies/databases/classes |

From `olympiad_ide/frontend`: `npm test`, `npm run typecheck`, `npm run lint`. Native assets: `python3.12 tools/build_olympiad_ide.py --skip-install` from checkout. Local build used Node 24.22.1. CMS/runtime remain separate Python 3.12.16 environments on Ubuntu 26.04.1, retaining SQLAlchemy 1.3/2.1; existing isolate 2.7, GDB 17.1, debugpy 1.8.19 and Java 17 remain unchanged. No new database migration or grants are required; f6a001 and the existing identity/telemetry/nonce tables remain in use.

The exact guarded Linux runner is [reverify_linux.py](../../olympiad_ide/tools/linux_staging/reverify_linux.py). It requires `/etc/cms-ide-stage/cms-unit.conf`,0600 cmsstage, verifies the exact isolated CMS unit database/socket/paths/mock coordinates and imported engine before tests, then uses generated test schemas in the retained, non-active `ide_linux_staging` database for the runtime suite. It never changes application lifecycle or active contest data. The preflight and final logs are retained in evidence.

```sh
# Already-authorized staging only; after reviewed installation, as root:
sudo /opt/cms-ide-stage/cms-venv/bin/python /opt/cms-ide-stage/source/olympiad_ide/tools/linux_staging/reverify_linux.py
# Local browser, protected fresh-actor fixture, normal public TLS:
node olympiad_ide/frontend/tools/verify-participant-polish.cjs /private/tmp/cms-linux-staging/ui-acceptance.json /private/tmp/cms-linux-staging/participant-ui-final
node olympiad_ide/frontend/tools/verify-admin-history.cjs /private/tmp/cms-linux-staging/ui-acceptance.json /private/tmp/cms-linux-staging/admin-history-final /private/tmp/cms-linux-staging/participant-ui-final/results.json
node olympiad_ide/frontend/tools/verify-admin-edit-replay.cjs /private/tmp/cms-linux-staging/ui-acceptance.json /private/tmp/cms-linux-staging/admin-history-final /private/tmp/cms-linux-staging/participant-ui-final/results.json
```

Browser launches used the known local Chromium through `PLAYWRIGHT_CHROMIUM_PATH`. The participant tool requires a fresh authorized fixture and empty prior submission history; it refuses excess mutating attempts. [Exact executed actor provisioning](../../olympiad_ide/tools/linux_staging/create_ui_acceptance.py) refuses to replace existing fixture/account data and guards the restored staging database/contest. Credentials are generated into protected 0600 files and never emitted. Use a reviewed fresh output path for another rehearsal; do not delete/reset an existing participant to rerun tests.

Deployment used the existing `cms-staging-ops` tmux session and retained `update-workbench.sh`, umask 022 public code installs, separate CMS/runtime packages and unchanged native ResourceService owners. Existing debug approval was retained; its 10 prerequisite tests passed again with both approval flags unset in the test process. Actual Run/judge/debug security profiles were not weakened. Local test PostgreSQL was stopped after verification; AWS remains running.

## Failures, corrections and limits

- The two bugs were reproduced before correction: exhausted/future-token CWS rows returned 500 because `tokens_info` was undefined, and numeric submission observations returned 422 with the pictured two string-type errors. Red/green logs and the final real 200 flows are retained.
- An initial full Linux regression invocation referenced nonexistent `unit.conf`; CMS silently fell back to defaults. Database-name safety checks blocked initialization. It produced 21 failures/293 errors rather than a valid test run. The actual retained file is `cms-unit.conf`; strict file/ownership/URL/path/coordinate/imported-engine preflight and the final 759/97 pass rerun corrected the test procedure. The sanitized failure excerpt and unchanged raw private artifact remain retained. No test guard was bypassed and no config/application changes were needed for the correction.
- The old protected load-account password was stale; no existing password was reset. Acceptance used a new actor and required authenticated context identity, not a login redirect 200.
- History access is enforced by actual CMS Admin permission_all plus a separate, request-bound one-use signed runtime namespace. Removing participant UI does not make browser-owned local buffers cryptographically inaccessible to their profile owner. No username-based record adoption occurs.
- Server retention/upload gaps remain disclosed. Hashes prove consistency, not authorship. Existing release gates for sustained 350-editor/debugger capacity, dedicated production workers, advisory/licensing review, off-host/f6restore and reboot remain; this UI/Admin update adds no capacity or production-readiness claim.
