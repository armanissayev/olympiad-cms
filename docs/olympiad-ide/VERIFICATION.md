# Verification and acceptance status

Updated 3 November 2026. The current feature follow-up is recorded below; the 2 November rehearsal remains separately labeled. **The disposable beta end-to-end workflow passed.** The same CMS participant used Monaco, real isolate Run/Stop, official C++/Python Submit and actual CMS judging/public scores, with receipt, outage and restored-database recovery. Live contest readiness remains conditional.

Read [LINUX_ACCEPTANCE](LINUX_ACCEPTANCE.md) for exact commands, versions, failures, the 12-requirement matrix, load figures, restore proof and release gates. Sanitized outputs are under [evidence/linux-staging](evidence/linux-staging/); reproducible commands/configuration/test sources are in the [staging guide](../../olympiad_ide/tools/linux_staging/README.md).

## Initial 2 November Linux results

| Check | Actual outcome |
| --- | --- |
| Mandatory isolate tests, approval unset during tests | **26 passed, 7 deselected**, twice; none of the 26 skipped |
| Remaining worker policies | 6 passed, 1 expected non-Linux-denial skip, 26 deselected |
| Complete CMS suite after DB recovery fix | **746 passed, 9 skipped, 28 subtests passed**; Linux MIME checks pass |
| Separate IDE PostgreSQL suite | **75 passed** |
| Frontend under Node 22 | **81 passed**; npm ci, typecheck, lint and build passed |
| Real-worker native Chromium | 14 checks passed initially and after restoration; zero page errors |
| Actual official judging | Correct C++/Python scored 100 operator/25 public; four evaluations each; real CE/WA/RTE/TLE and permitted diagnostics verified |
| CWS/Admin/ranking; tokens/rejudge/dataset | Passed actual visibility, token disclosure, fresh rejudging, alternate dataset scores 40/10 and ranking 40, then original dataset restored |
| Component outages and CWS fallback | Passed custom worker, private API, EvaluationService and native outages; ordinary CWS fallback was really judged |
| Separate CMS/IDE DB faults | Passed after idle-connection validation fix 349d1e95; no false success or in-flight transaction replay |
| Matched database/application restoration | Passed 28 CMS/21 IDE tables, source/large-object bytes, 351 principals and 353 workspace mappings; restored copies active; browser passed afterward |
| Progressive 1→350-account workload | 4,561 HTTP requests, zero HTTP errors; **five short-poll terminal assertions failed**; those exact five admissions later scored 100; original report retained |
| Actual 120-second deadline mixture | 10 actors, 420 HTTP requests, zero errors; real custom/official results; post-deadline receipt GET 200 and new intent 422 |
| Final 350-account login/context check | 350 fresh logins, 1,400 HTTP requests, zero errors; not a sustained editor-capacity test |
| Host security boundaries | Actual cgroup v2, user quotas, seccomp and toolchains; execution-only helper 4750; web/API denied; custom network, DB and file restrictions verified |

Focused checks overlap full suites and are not added as distinct tests. Logs retain warnings. All application listeners are loopback. Only the explicitly authorized EC2 host was accessed; no production data, DNS, networking/security-group change or other AWS host was involved.

## Failures and correction

The first Linux CMS DB outage left a committed submission stuck after a stale pooled connection failed in the judging path. A real PostgreSQL regression failed before and passed after `pool_pre_ping=True`, commit `349d1e9559023b57b28d3e0dac95ca2b97c4a0dc`. The full CMS suite and complete fault/recovery retest then passed. The fix does not replay in-flight transactions or official POSTs.

Five official POST 201 responses in the main load run were known admissions, but its roughly two-second final feedback window expired before scoring. The exit 1 report and five failures remain intact. Separate read-only source/result/participant reconciliation proves those exact submissions later scored 100. Longer bounded polling in the independent final-minute run passed. Cold browser startup, a Stop fixture race, isolate UID provisioning, nginx temp permissions and unit-fixture corrections are recorded in LINUX_ACCEPTANCE.

## Historical local verification

The earlier Mac phase used generated PostgreSQL 14 databases on 127.0.0.1:55459 and no remote worker. Its individual evidence documents remain preserved and labeled as historical. Their “Linux not run” limits are superseded only by the new Linux report.

| Earlier local check | Historical outcome |
| --- | --- |
| Untouched CMS v1.5.1 | 670 passed, 9 skipped, 6 shared-mime-info failures |
| Integrated CMS | 739 passed, 9 skipped, the same 6 Mac MIME failures; 28 subtests |
| Runtime/frontend/standalone browser | 75/81/13 passed; one real-worker browser skip |
| Worker on Mac | 7 policy passes, 26 Linux skips |
| Native HTTPS/process/browser | Real login, admission, receipt, lifecycle and offline/recovery; no judging claim at that stage |
| Tiny local load | 1 participant, 11 HTTP requests, zero errors |
| Local restore, faults and packaging | Earlier identity-preserving restore and clean-wheel checks; see individual evidence |

All 124 original source hashes still match SOURCE_IMPORT.json. Historical checks are not added to Linux totals.

## Remaining release gates

The beta is now available through trusted public HTTPS; its private SSH tunnel remains available. A live contest requires dependency/security/licence review, dedicated production execution isolation, timing calibration, production TLS/access/retention/backup policy, off-host recovery and representative sustained 300–350-editor/telemetry/compile/deadline stress tests. Short same-host measurements do not certify that capacity. No reboot, production rollout, merge, push or PR was performed.

## Public HTTPS follow-up — 3 November 2026

[PUBLIC_HTTPS](PUBLIC_HTTPS.md) records the completed public-IP deployment. The real-worker native browser repeated all14checks with zero page errors through trusted public HTTPS, without a tunnel or TLS bypass. Public readiness200, CWS login, C++/Python actual judging, Run/Stop/recovery and renewal dry-run passed. All eight existing supervisor units are enabled at boot; tmux provides the persistent operations/log session. The original failed public asset load and its corrected proxy-buffer ownership are retained as evidence. No reboot test or new production capacity claim is made.

## Earlier workbench and Phase 5/6 — 3 November 2026

Deployed source `e9044e7b03032018b038a03c8fad2abf4d551bfa`. See [WORKBENCH_ACCEPTANCE](WORKBENCH_ACCEPTANCE.md) for commands, environment versions, the complete new requirement matrix and preserved failures.

| Check | Actual final outcome |
| --- | --- |
| Linux CMS | 750 passed, 9 skipped, 28 subtests; new 4 entry-card tests included |
| IDE PostgreSQL runtime | 87 passed on Linux and locally; cancelled-task cleanup regression failed before and passed after shielding |
| Frontend | 113 passed; typecheck/lint/build passed; 13 history/15 debug focused checks overlap this count |
| Original mandatory Linux Run suite | 26 passed, 7 deselected; approval unset; no prerequisite skipped |
| Final debug-specific Linux suite | 10 passed, 5.05 s; both approval flags unset; 4 policy + 6 real isolation tests; no skips |
| Real adapters | GDB/debugpy breakpoints/locals/steps/stdin-output passed; Java 8 real JDI checks passed |
| Public main browser | CMS box, large STDIN/STDOUT, active-file switch, actual read only replay Play/Pause/seeking, 3 languages real debugging, persisted breakpoints and new official submission scored with public 25/25 and hidden feedback restricted; zero page errors |
| Public lifecycle/mobile browser | 390×844 entry visible; real Pause + stack/locals in all 3 languages; C++/Python explicit Stop confirmed STOPPED; Java active refresh disconnect STOPPED + source recovery; exactly 3 sessions/zero errors |
| Service/process checks | 9 task-owned units active+boot-enabled, tmux retained, both pip checks green; official CMS judge separate from Run/debug |

Public links: https://54.206.171.67/ and https://54.206.171.67/ide/. [Sanitized evidence](evidence/workbench-vnext/) includes final JSON/logs/screenshots and earlier browser failures. The primary actual variable bug and backend disconnect cancellation failure were fixed and retested; harness paste/toggle/Step Out/selector mistakes are labeled separately. No GDB paging patch was applied. History recording discovery remains local-browser only. All 124 original source hashes match. Earlier 350 account measurements do not establish 350 concurrent editor/debugger capacity.

Final source/native distribution audit passed for exact commit 7dee52dc plus 13 manifest-verified assets, including both browser scripts and 9 sanitized screenshots, with no dependencies/credentials/databases/compiled classes. [Packaging evidence](evidence/workbench-vnext/package-check.json). Final read-only host check found 9 healthy boot-enabled units, no failed units, debug box 600 clean and public HTTPS readiness 200. Local regression PostgreSQL was stopped; AWS staging remains running.

## Current participant workflow/Admin history follow-up

Deployed `5106855e3c0cb003bd1558d163f7bcda46d35018`. [PARTICIPANT_ACCEPTANCE](PARTICIPANT_ACCEPTANCE.md) records all requested behaviors, actual commands, source hashes, role denials and failures. **759 Linux CMS tests passed (9 skipped, 28 subtests); 97 runtime tests passed locally/Linux; 130 frontend tests passed with lint/typecheck/build.** All totals include focused tests; do not add them again.

Real public participant acceptance passed six problem changes with the same document and restored source/STDIN, all three breakpoint entry methods and real live adapter stop locations 5/6/5, three CMS-judged C++/Python submissions scoring public 25/25, two allowed token uses and exhausted-token CWS HTTP 200. Numeric observation uploads passed 200; participant history reads were 403. Separate private Admin browser verified target ownership, real before/after TEXT_INSERT source reconstruction, timeline/Play/Pause and read-only behavior. No page/server errors or popups in final browser runs.

The initial full Linux invocation used a missing config path and failed safety checks; the retained correct cms-unit.conf and strict preflight produced the final 759/97 pass run. [Initial failure and final evidence](evidence/participant-polish/). No application configuration or database guard was weakened. Admin remains private and participant history/diagnostic UI is removed. Only uploaded retained data can be replayed. Existing release/capacity gates remain unchanged.

## Public Admin HTTPS — 4 November 2026

**Deployed and verified:** https://54.206.171.67/admin/ and https://54.206.171.67/admin/contest/1/ide-history now work through trusted public HTTPS without a tunnel. Existing enabled CMS Admin authentication and full-permission history checks remain required. Real-browser guest/participant cookie/credential denial, actual Admin uploaded source/hash replay, timeline, CSRF rejection, cookie protection, prefix paths and logout all passed (ten grouped checks; zero page/server errors or history mutations). Only ingress reloaded; all nine service PIDs/start times stayed unchanged and all are active/enabled. Native ports remain private, existing tmux/renewal remain active, and CMS/IDE readiness are 200. Repeat installer run reported unchanged; bounded loopback rate test returned ten 200 and four 429 responses. Initial SSH timeouts were resolved by the operator before deployment. [Exact commands, environment, evidence and rollback](PUBLIC_ADMIN_HTTPS.md).
