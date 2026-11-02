# Implementation state

Updated 3 November 2026. Checkout `/Users/isaevarman/Developer/cms`, branch `feature/olympiad-ide-integration`. CMS base `CMSv1.5.1`, `7c9fec8aa1a25ec93d624aebf815804dd93df9db`; initial integration `7c2bd34d16a6ae9bc263feb660bb60505c31bfab`. Current deployed application: **`e9044e7b03032018b038a03c8fad2abf4d551bfa`**. No push, PR or merge was performed.

## Current participant experience

- The CMS contest overview has a prominent **Olympiad IDE** box and **Open Olympiad IDE** link above General information. It is enabled only for the supported configured contest. Desktop and 390 px mobile browser checks passed.
- The bottom panel contains large **STDIN File** and **STDOUT File** panes. Terminal, Problems, Test Cases, Run All and saved-run selection are removed from the participant flow. Compiler/stderr diagnostics remain separate from exact stdout; copy/download/clear are available.
- **Run active file** captures the currently focused file every time. Switching C++→Python produced actual outputs 5→22 using different immutable entry IDs. Old persisted configurations/test data are retained, not automatically selected or deleted.
- **Phase 5** provides deterministic read-only editing-history replay, verified checkpoints, multi-file reconstruction, seeking, previous/next, Play/Pause and 0.5/1/2/4/8×. Gaps/integrity failures are disclosed. Recording discovery is for the current browser and CMS principal/task scope; no cross-device history discovery is claimed.
- **Phase 6** provides real isolated C++, Python and Java DAP debugging: gutter breakpoints, persistence, source navigation, current execution marker, call stack, local/child variables, Start/Stop, Pause/Continue and all three steps. Captured source remains immutable; later edits/relocations apply to the next session. Actual debug actions are recorded without arbitrary evaluation input.

## Running AWS beta

Participant CMS: **https://54.206.171.67/**. Direct IDE: **https://54.206.171.67/ide/**. Use the normal CMS participant login. Admin/RPC/DB remain private; admin is available through the task-owned SSH forward on localhost 28444. Protected access details are in `/private/tmp/cms-linux-staging/STAGING_ACCESS.txt`, 0600, outside Git.

Only the explicitly authorized disposable EC2 instance `i-0ade1f8ddf0b0dad8` was accessed. Trusted public-IP TLS, automatic certificate renewal and normal browser TLS validation remain enabled. All nine task-owned PostgreSQL/log/resource/judge/runtime/custom-worker/debug-worker/ranking/ingress units are active and enabled at boot. `cms-staging-ops` tmux retains operations/log windows; systemd and native ResourceService own service processes independently of SSH. No reboot was performed.

CMS ResourceService 0 owns native/CWS/ES/SS/Admin/Proxy as cmsstage; ResourceService 1 owns official judging as cmsjudgestage. Custom Run and the dedicated debug controller use ideworkerstage with private networking and execution-only grants. The debug worker uses its own box range and approval flag. Native service ownership and separate Python/SQLAlchemy environments are preserved.

The active restored databases remain `cms_restore_21c7bd2d5bfortesting` and `ide_restore_d4008d5dedfortesting`. The prior matched 28 CMS/21 IDE-table restoration was at f5a001. The new additive f6a001 migration adds three debug tables after a protected backup; no new f6 restore rehearsal is claimed. Original databases and backups remain retained.

## Verification

See [WORKBENCH_ACCEPTANCE](WORKBENCH_ACCEPTANCE.md) for commands, versions, failures and the new requirement matrix. [VERIFICATION](VERIFICATION.md) lists current and historical results. Sanitized new evidence is in [workbench-vnext](evidence/workbench-vnext/), with direct adapter evidence in [phase6](evidence/phase6/) and [Java](evidence/java-debugger.json).

- Linux CMS: 750 passed, 9 skipped, 28 subtests; the four new real WSGI/PostgreSQL entry-card checks are included.
- Final runtime: 87 passed against real PostgreSQL on Linux and locally. Frontend: 113 passed, typecheck/lint/build green.
- Original Linux Run gate: 26 passed, 7 deselected, no security prerequisite skipped. Final debugger gate: 10 passed, no skips, both approval flags unset during the run.
- Public browser: actual active-file C++/Python Run, history playback, C++/Python/Java breakpoint/local/step/Continue/output checks, persisted breakpoints after refresh, and a new official CMS submission reaching real scored status and public score 25/25 with restricted feedback preserved. Zero page errors.
- Separate lifecycle browser: real Pause and counter/stack inspection in all three languages, C++/Python explicit Stop→owned STOPPED, Java active refresh/disconnect→owned STOPPED with source recovery, and mobile entry visibility. Exactly three sessions; zero page errors.

The earlier [Linux acceptance](LINUX_ACCEPTANCE.md) retains actual C++/Python 100/25 scores, CE/WA/RTE/TLE, CWS/Admin/ranking, tokens/rejudge/dataset, component/DB faults, receipt durability, CWS fallback and matched restoration. Admission alone is never reported as judging.

## Remaining release work

This completes the requested staging feature milestone. It does not certify a live contest or 350 concurrent debuggers. Existing release gates remain: dependency/advisory and release-wide licensing review, dedicated production execution hosts, representative sustained 300–350-editor/compile/deadline tests, timing calibration, production access/retention, off-host recovery, f6 backup restoration and reboot rehearsal. The prior short 350-account workload had five short-poll assertion failures; later exact submissions scored 100, with the original failure report preserved. At most 12 HTTP actors ran concurrently.

Debug sessions have five-minute wall and 30 CPU-second limits, one active session/principal and 20 starts/hour; debug retention/pruning is operator work. History is scoped local-browser data and cannot invent missing telemetry. Pinned gevent still emits ignored fork/thread/finalization warnings on Python 3.12; no broad dependency/security bypass was introduced.

All 124 authoritative original source hashes match. Original source and key were preserved. Dependencies, credentials, databases, compiled Java classes and generated service configuration are excluded from Git. Corrected deployment and recovery procedures are retained in [linux_staging](../../olympiad_ide/tools/linux_staging/README.md).
