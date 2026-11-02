# Workbench, Phase 5 and Phase 6 acceptance

3 November 2026. Authorized disposable staging only: `ec2-54-206-171-67.ap-southeast-2.compute.amazonaws.com`, EC2 `i-0ade1f8ddf0b0dad8`. Public CMS **https://54.206.171.67/**; IDE **https://54.206.171.67/ide/**. Browser TLS validation remained enabled throughout.

## Deployed source and environment

CMSv1.5.1 base `7c9fec8aa1a25ec93d624aebf815804dd93df9db`. Feature core `76b36469`; inspection/backpressure correction `bf0c3d97`; final deployed application **`e9044e7b03032018b038a03c8fad2abf4d551bfa`**. Later commits contain acceptance tools/docs/evidence only. Branch remains `feature/olympiad-ide-integration`.

Ubuntu 26.04.1/x86_64, 2 logical CPUs, approximately 3.7 GiB RAM; PostgreSQL 18.6. Separate CMS/runtime Python 3.12.16 environments retain SQLAlchemy 1.3.24 versus 2.1.5. CMS uses Tornado 4.5.3/gevent 25.5.1. Contestant tools: G++ 15.2, CPython 3.14.4, OpenJDK 17.0.20.1. Debug adapters: GDB 17.1 native DAP, debugpy 1.8.19, project standalone Java JDI adapter. Isolate 2.7 commit `8f185bb37f3f23e29b33b0c7727c91c13429abe3`; real cgroup v2/user quotas/seccomp remain enforced. Frontend build: Node 24.22.1. [Adapter licence/installation audit](JAVA_DEBUGGER.md).

## Requirement outcomes

| Requirement | Actual result and evidence |
| --- | --- |
| Prominent contest-page IDE entry | Passed authenticated desktop and 390×844 mobile browser; CTA within initial viewport; 4 real rendering/contest-scope tests included in CMS 750 |
| Simple larger input/output | Passed; only STDIN File/STDOUT File, each >300 px wide/>100 px high in desktop test; old tabs/config selector absent; diagnostics separate |
| Active-file Run | Passed actual C++ stdout 5 and switched Python stdout 22; one captured source each, distinct entry IDs; no selected historical configuration |
| Phase 5 replay | Passed actual saved-recording read-only modal, forward/backward seek, Play/Pause/speed and unchanged live text; 13 focused tests cover multi-file/integrity/checkpoint/gap behavior |
| Real C++ debugger | Passed actual gutter breakpoint, main/add stack transitions, arguments/locals result 5, all three steps, Continue and stdout 5 |
| Real Python debugger | Passed the same controls/real variables/output through debugpy |
| Real Java debugger | Passed the same controls/real variables/output through standalone JDI; direct isolated adapter also passed 8 controls |
| Breakpoint persistence/navigation | Reload persistence passed public browser; stable-file-ID Go to and relocation/consumed split-pane navigation have focused coverage; immutable captured source/hash checked |
| Pause and Stop | Actual Pause/counter/stack passed in all 3 languages; C++/Python Stop confirmed owned STOPPED; Java active refresh/disconnect confirmed STOPPED and recovered saved source, debugger idle |
| API/session security | 87 real-PostgreSQL backend tests on Linux (also passed locally) include ownership, task isolation, one-use/expired token, Origin, strict command/source bounds, disconnect cancellation and cancelled-task durable cleanup |
| Actual Linux isolation | Original 26 Run prerequisites passed without skips; final 10 debug prerequisites passed 5.05 s without skips with both approval flags unset; separate actual 3 language probes passed |
| Official judging regression | New official C++ submission through native IDE reached CMS scored status 5 and public score 25/25 after real judging; participant feedback contained one public Correct result and three hidden N/A placeholders, without full score or hidden results; original complete C++/Python verdict/score/policy/fallback evidence retained in LINUX_ACCEPTANCE |
| Persistence/service lifecycle | 9 staging units active and boot-enabled; tmux retained; official judge/CWS owned by native ResourceService, IDE run/debug workers separate; two Python environments preserved |

[Exact official feedback](evidence/workbench-vnext/official-feedback.json), [final main browser JSON](evidence/workbench-vnext/browser-results.json), [lifecycle JSON](evidence/workbench-vnext/debug-lifecycle-results.json), [screenshots and logs](evidence/workbench-vnext/) retain actual IDs/hashes/output. Both browser runs reported zero page errors. Scripted unit DAP responses are kept separate from these real-program claims.

## Reproducible commands

Run only against a reviewed disposable target with protected credentials. No password/token belongs in a command or report. Exact source, configuration ownership, migration and approval procedure: [staging guide](../../olympiad_ide/tools/linux_staging/README.md), [Phase 6](../../olympiad_ide/docs/PHASE6_ARCHITECTURE.md), [data migration](DATA_MIGRATION.md).

```sh
# Local frontend in olympiad_ide/frontend, Node24.22.1
npm test
npm run typecheck
npm run lint
python3.12 ../../tools/build_olympiad_ide.py --skip-install
# Local backend in olympiad_ide/backend; generated test schemas in dedicated PG
TEST_DATABASE_URL=postgresql+psycopg://isaevarman@127.0.0.1:55459/ideruntime \
 /private/tmp/olympiad-runtime-venv/bin/python -m pytest -ra --tb=short
# Authorized Linux, from source/olympiad_ide, same helper/security prerequisites
sudo runuser -u ideworkerstage -- env -u WORKER_SANDBOX_APPROVED \
 PYTHONPATH=backend:. PATH=/usr/local/bin:/usr/bin:/bin \
 WORKER_BOX_ID_BASE=400 RUN_LINUX_SANDBOX_TESTS=1 \
 /opt/cms-ide-stage/runtime-venv/bin/python -m pytest worker/tests/test_worker.py -k real_ -vv -p no:cacheprovider
sudo runuser -u ideworkerstage -- env -u WORKER_SANDBOX_APPROVED -u DEBUG_SANDBOX_APPROVED \
 PYTHONPATH=backend:. PATH=/usr/local/bin:/usr/bin:/bin RUN_LINUX_DEBUG_TESTS=1 \
 /opt/cms-ide-stage/runtime-venv/bin/python -m pytest worker/tests/test_debugger.py -vv -p no:cacheprovider
# Local browser from checkout; normal trusted TLS. Protected fixture supplied separately.
node olympiad_ide/frontend/tools/verify-workbench-vnext.cjs /private/tmp/cms-linux-staging/browser-public.json /private/tmp/cms-linux-staging/vnext-browser-final
node olympiad_ide/frontend/tools/verify-debug-lifecycle.cjs /private/tmp/cms-linux-staging/browser-public.json /private/tmp/cms-linux-staging/debug-lifecycle-final
```

Local browser launches used `PLAYWRIGHT_CHROMIUM_PATH=/Users/isaevarman/Library/Caches/ms-playwright/chromium-1155/chrome-mac/Chromium.app/Contents/MacOS/Chromium`. Protected fixture mode 0600 points only to the authorized public IP. CMS regression ran as cmsstage with `/etc/cms-ide-stage/unit.conf`, source PYTHONPATH and independent writable unit directory, using `python -m pytest .../cmstestsuite/unit_tests -q --tb=short`: 750 passed, 9 skipped, 28 subtests in 30.90 s. The Run gate passed 26/7 deselected in 10.08 s. Focused test counts overlap full suites.

Deployment ran inside `cms-staging-ops` using the retained `update-workbench.sh`, Git archive and hash-manifest-verified public assets. It used umask 022 for application package installs and protected secret files remained 0600. Both pip checks passed. The additive f6 migration was separately backed up/applied/checked as the IDE schema owner. Only after review of real language and isolation results was the separate debug approval enabled. Uvicorn now bounds WS transport messages to 32768 bytes/4 queued messages before application parsing.

The final runtime suite also ran on AWS Linux as idemigratestage with `TEST_DATABASE_URL=postgresql+psycopg://idemigratestage@/ide_linux_staging?host=/run/cms-ide-stage-pg&port=15432`, `python -m pytest -q --tb=short -p no:cacheprovider`, exit 0, all 87 tests passed. Each test used a generated `test_*` schema; the active restored IDE database was not used for this test run. [Linux output](evidence/workbench-vnext/backend-linux.log). One Starlette TestClient deprecation warning remains.

## Failures retained and corrected

- Candidate Mac AppleDouble migration files caused an early null-byte parse failure before DDL. Removing only candidate `._*` metadata allowed the additive migration/check to pass.
- Initial package installation inherited umask 077, making newly installed application packages unreadable to service accounts and briefly returning 502. Automatic approval rejected broad recursive virtualenv permission changes. A narrower repair byte-verified only application source and changed its package/launcher modes; no dependencies/configuration/keys were touched. The updater now installs public code under 022. [Initial failure](evidence/workbench-vnext/deployment-initial-failed.log).
- Real GDB browser stepping exposed stale scope reads and first-scope-only rendering (Arguments hid Locals). Inspection is now serialized until all non-register scopes complete. Real probes accepted count 100/child expansion unchanged; no speculative paging translation was applied. Final browser verifies result 5 in all three languages.
- The final backend run initially had 84 passes/1 disconnect-cleanup timing failure. A deterministic Task.cancel regression failed before cancellation shielding and passed afterward; the full final 87 passed. [Backend initial/final/cancellation evidence](evidence/phase6/).
- Browser harness corrections were necessary for Explorer/Run-and-Debug toggle behavior, actual clipboard paste preserving Python indentation, exact variable-name matching and Step Out pausing before caller assignment. Earlier failed runs remain as `browser-*-failed.log`; the final main and lifecycle runs exited 0. Invalid Python produced its actual IndentationError, never a fake breakpoint.
- A first unit invocation could not traverse its 0700 test directory as ubuntu; changing directory inside the intended cmsstage run fixed the harness. No application permission was weakened.

## Boundaries and release work

History lists recordings retained in this browser/principal/task scope. There is no invented gap content or cross-device discovery. Debug sessions are limited to 300 wall/30 CPU seconds and 1 GiB adapter/debuggee memory, 64 processes, 128 FDs, 64 MiB/1024 inode quota and bounded protocol/output; compile profile remains separate. No unrestricted process fallback, arbitrary host evaluation, direct public debugger port or production database/network change was introduced.

This report completes the requested feature milestone on staging. It does not establish sustained 350-editor/debugger capacity, release-wide dependency/licensing review, dedicated production host isolation, off-host recovery, f6 restore or reboot behavior. The earlier progressive-load five short-poll failures and ignored gevent fork/finalization warnings remain in their original reports. Original 124 source hashes still match; secrets/dependencies/dumps/compiled classes are excluded from source packages. Earlier CWS/Admin/ranking/token/rejudge/dataset/fault/restore claims refer to their dated [Linux report](LINUX_ACCEPTANCE.md), not a repeat of every prior rehearsal in this feature update.
