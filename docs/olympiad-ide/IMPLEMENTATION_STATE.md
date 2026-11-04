# Implementation state

Updated 4 November 2026. Checkout `/Users/isaevarman/Developer/cms`, branch `feature/olympiad-ide-integration`. CMS base `CMSv1.5.1`, `7c9fec8aa1a25ec93d624aebf815804dd93df9db`; initial integration `7c2bd34d16a6ae9bc263feb660bb60505c31bfab`. Current deployed application: **`5106855e3c0cb003bd1558d163f7bcda46d35018`**. No push, PR or merge was performed.

## Current participant experience

- The CMS contest overview has a prominent **Olympiad IDE** box and **Open Olympiad IDE** link above General information. It is enabled only for the supported configured contest. Desktop and 390 px mobile browser checks passed.
- The bottom panel contains large **STDIN File** and **STDOUT File** panes. Terminal, Problems, Test Cases, Run All and saved-run selection are removed from the participant flow. Compiler/stderr diagnostics remain separate from exact stdout; copy/download/clear are available.
- **Run active file** captures the currently focused file every time. Switching C++→Python produced actual outputs 5→22 using different immutable entry IDs. Old persisted configurations/test data are retained, not automatically selected or deleted.
- **History is administrator-only in CMS.** Participants have no History/diagnostics window or history-read API. Full CMS Admin users select a participant/problem/recording and replay uploaded server history across browsers. Actual writing-event before/after source reconstruction passed; gaps/expiry are disclosed. Standalone local history remains available.
- **Phase 6** provides real isolated C++, Python and Java DAP debugging: gutter breakpoints, persistence, source navigation, current execution marker, call stack, local/child variables, Start/Stop, Pause/Continue and all three steps. Captured source remains immutable. Line-number clicks, F9 and explicit line controls work; live changes apply to unchanged captured source, while edited source requires restart. Actual debug actions are recorded without arbitrary evaluation input.

The green top-right **Submit** opens a simple problem/file form with language inference, retaining immutable intents and receipt recovery. Problem changes stay in the same document and preserve task-scoped source/STDIN; failure and removed-task rollback preserve local code without granting authority. The CWS token-render 500 and numeric recording-upload 422 bugs are fixed and verified on the actual host.

## Running AWS beta

Participant CMS: **https://54.206.171.67/**. Direct IDE: **https://54.206.171.67/ide/**. Use the normal CMS participant login. Admin is available at **https://54.206.171.67/admin/** with native CMS Admin login; code history is **https://54.206.171.67/admin/contest/1/ide-history** and requires full permission. Native service/RPC/database listeners remain private; the optional localhost 28444 tunnel remains available. Protected access details are in `/private/tmp/cms-linux-staging/STAGING_ACCESS.txt`, 0600, outside Git.

Only the explicitly authorized disposable EC2 instance `i-0ade1f8ddf0b0dad8` was accessed. Trusted public-IP TLS, automatic certificate renewal and normal browser TLS validation remain enabled. All nine task-owned PostgreSQL/log/resource/judge/runtime/custom-worker/debug-worker/ranking/ingress units are active and enabled at boot. `cms-staging-ops` tmux retains operations/log windows; systemd and native ResourceService own service processes independently of SSH. No reboot was performed.

CMS ResourceService 0 owns native/CWS/ES/SS/Admin/Proxy as cmsstage; ResourceService 1 owns official judging as cmsjudgestage. Custom Run and the dedicated debug controller use ideworkerstage with private networking and execution-only grants. The debug worker uses its own box range and approval flag. Native service ownership and separate Python/SQLAlchemy environments are preserved.

The active restored databases remain `cms_restore_21c7bd2d5bfortesting` and `ide_restore_d4008d5dedfortesting`. The prior matched 28 CMS/21 IDE-table restoration was at f5a001. The new additive f6a001 migration adds three debug tables after a protected backup; no new f6 restore rehearsal is claimed. Original databases and backups remain retained.

## Verification

Current [PARTICIPANT_ACCEPTANCE](PARTICIPANT_ACCEPTANCE.md) records commands, failures and the requirement matrix; its evidence is in [participant-polish](evidence/participant-polish/). Earlier [WORKBENCH_ACCEPTANCE](WORKBENCH_ACCEPTANCE.md), [phase6](evidence/phase6/) and [Java](evidence/java-debugger.json) evidence remains dated separately. [VERIFICATION](VERIFICATION.md) lists current and historical results.

- Linux CMS: 759 passed, 9 skipped, 28 subtests; includes the earlier four entry-card checks plus the new three token-render and six Admin checks.
- Final runtime: 97 passed against real PostgreSQL on Linux and locally. Frontend: 130 passed, typecheck/lint/build green.
- Original Linux Run gate: 26 passed, 7 deselected, no security prerequisite skipped. Final debugger gate: 10 passed, no skips, both approval flags unset during the run.
- Earlier Phase5/6 browser, before participant replay removal: actual active-file C++/Python Run, local history playback, C++/Python/Java breakpoint/local/step/Continue/output checks, persisted breakpoints after refresh, and a new official CMS submission reaching real scored status and public score 25/25 with restricted feedback preserved. Zero page errors.
- Earlier separate lifecycle browser: real Pause and counter/stack inspection in all three languages, C++/Python explicit Stop→owned STOPPED, Java active refresh/disconnect→owned STOPPED with source recovery, and mobile entry visibility. Exactly three sessions; zero page errors.

The earlier [Linux acceptance](LINUX_ACCEPTANCE.md) retains actual C++/Python 100/25 scores, CE/WA/RTE/TLE, CWS/Admin/ranking, tokens/rejudge/dataset, component/DB faults, receipt durability, CWS fallback and matched restoration. Admission alone is never reported as judging.

## Remaining release work

This completes the requested staging feature milestone. It does not certify a live contest or 350 concurrent debuggers. Existing release gates remain: dependency/advisory and release-wide licensing review, dedicated production execution hosts, representative sustained 300–350-editor/compile/deadline tests, timing calibration, production access/retention, off-host recovery, f6 backup restoration and reboot rehearsal. The prior short 350-account workload had five short-poll assertion failures; later exact submissions scored 100, with the original failure report preserved. At most 12 HTTP actors ran concurrently.

Debug sessions have five-minute wall and 30 CPU-second limits, one active session/principal and 20 starts/hour; debug retention/pruning is operator work. Browser buffers remain scoped locally; Admin review reads retained uploaded server history and cannot invent missing telemetry. Pinned gevent still emits ignored fork/thread/finalization warnings on Python 3.12; no broad dependency/security bypass was introduced.

All 124 authoritative original source hashes match. Original source and key were preserved. Dependencies, credentials, databases, compiled Java classes and generated service configuration are excluded from Git. Corrected deployment and recovery procedures are retained in [linux_staging](../../olympiad_ide/tools/linux_staging/README.md).

Final cleanup: the task-owned local regression PostgreSQL cluster is stopped. AWS remains running with public readiness 200, no failed units and cleaned debug box 600.

Current participant/Admin follow-up: 759 Linux CMS passes, 97 Linux/runtime passes, 130 frontend passes; real live-breakpoint entry methods, six in-place problem changes, three actual scored C++/Python submissions, exhausted-token CWS 200, recording-upload 200/participant-read 403, and separate Admin actual writing-event replay all passed. [Admin history](https://54.206.171.67/admin/contest/1/ide-history) uses public HTTPS and full CMS Admin login; the prior private-tunnel acceptance remains dated separately. [Current evidence](evidence/participant-polish/).

## Public Admin HTTPS — 4 November 2026

**Deployed and verified:** https://54.206.171.67/admin/ and https://54.206.171.67/admin/contest/1/ide-history now work through trusted public HTTPS without a tunnel. Existing enabled CMS Admin authentication and full-permission history checks remain required. Real-browser guest/participant cookie/credential denial, actual Admin uploaded source/hash replay, timeline, CSRF rejection, cookie protection, prefix paths and logout all passed (ten grouped checks; zero page/server errors or history mutations). Only ingress reloaded; all nine service PIDs/start times stayed unchanged and all are active/enabled. Native ports remain private, existing tmux/renewal remain active, and CMS/IDE readiness are 200. Repeat installer run reported unchanged; bounded loopback rate test returned ten 200 and four 429 responses. Initial SSH timeouts were resolved by the operator before deployment. [Exact commands, environment, evidence and rollback](PUBLIC_ADMIN_HTTPS.md).
