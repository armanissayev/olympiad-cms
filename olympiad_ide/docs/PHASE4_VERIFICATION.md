# Phase 4 verification report

## Release decision: INCOMPLETE

The execution control plane, persistence, UI and worker source are implemented. **Phase 4 is not accepted as complete.** This macOS host has no Docker/Colima/isolate or existing Linux execution VM; the user confirmed that no Linux target is available and requested documenting the blocker. Therefore actual C++17/C++20/Python/Java execution, worker resource/isolation guarantees and Docker/VM deployment are **not verified**. No unrestricted macOS program execution or fabricated successful output was substituted.

## Implemented and locally verified

- Immutable source snapshots from live Monaco/store state, including unsynchronized edits, stable file identities, exact captured paths/configuration/tests and SHA-256 verification.
- Typed owner-scoped submission/read/cancel/events/history, configuration/test resources and capacity APIs.
- Durable PostgreSQL scheduling, idempotency, bounded admission, concurrent claim serialization, worker capacity/owner limits, leases/fenced writes, cancellation races and explicit infrastructure-error recovery.
- Additive Alembic migration `f4a001`, with no changes to Phase 2 workspace or Phase 3 telemetry tables.
- Reuse/migration of the existing IndexedDB testCases store; new configuration/submission/event tables and independent revisioned resource journal. Offline conflicts preserve both versions and require an explicit decision.
- Run Configuration creation/edit/delete/select, explicit included files, language and Java main class selection, fixed stdin, Run/Stop, xterm.js output plumbing, real queue status, reload/history and clear/copy controls.
- Custom test CRUD/duplication, optional exact expectations, one-test/Run All submission, shared source snapshot, result/partial-result presentation and CRLF-only comparison policy.
- Existing RUN event contracts extended compatibly with job/snapshot/hash/configuration/language/status/server-time correlation. Observer tests check deduplication and no invented historical events on reload; no start/finish events are emitted merely for a queued job.
- Real browser flows against PostgreSQL APIs for source/input submission, configuration persistence, tests/Run All, reload/cancel and retry after lost acknowledgement.

## Worker implementation supplied, not certified

`worker/app/` contains an independent non-root controller, Linux-only isolate adapter, allowlisted GCC/CPython/OpenJDK command vectors, compile-once Run All executor, per-case fresh boxes, quota/resource flags, bounded stdout/stderr streaming, safe artifact extraction and measured toolchain/metadata handling. Cancellation/lost lease stops the sandbox; abandoned jobs are not reported successful or automatically re-executed. Missing Linux/helper/cgroup/quota/syscall prerequisites fail closed. Deployment requires explicit approval after the real suite passes.

The worker Dockerfile requires an audited full isolate commit and is an unverified build recipe, not a privileged-container shortcut. The systemd unit and dedicated Linux VM path are documented in `PHASE4_ARCHITECTURE.md`. The API never launches participant processes.

## Actual results

Native macOS arm64, PostgreSQL 14 dedicated local cluster, project Python 3.12 venv, installed Node.js and Chromium. API tests migrate independent temporary PostgreSQL schemas. No SQLite execution-queue substitute was used.

| Check | Result |
| --- | --- |
| Frontend unit/integration | **63 passed** (all 51 prior tests retained) |
| PostgreSQL API/control-plane | **49 passed** (all 25 prior tests retained) |
| Worker policy/argument/artifact unit tests | **4 passed** |
| Real Linux language/security tests | **24 skipped — environment blocker, not passing** |
| Production browser regressions/control-plane | **13 passed** (all 10 prior scenarios retained) |
| Real Linux worker browser smoke | **1 skipped — environment blocker, not passing** |
| Strict TypeScript | Passed |
| ESLint, zero warnings | Passed |
| Production build | Passed; Monaco/xterm bundle-size advisories remain |
| Alembic upgrade and ORM drift check | Passed; no new upgrade operations detected |
| Actual API-process restart | Passed; the existing restart test now also verifies a durable queued execution and identical idempotent submission |
| Actual PostgreSQL cluster restart | Snapshot count/content checksum unchanged: 16 snapshots, `10a6184a3a799097634133227df20540` before and after |
| Docker/VM worker deployment | **Not performed / not verified** |

Totals: **129 passing tests/scenarios, 25 explicit skips**. These totals do not certify the Linux sandbox. Unit/control-plane fixtures are labeled as such and are not claimed to be compiler output or real execution metrics. npm dependency installation reported zero audit vulnerabilities at that check; Node 23 emitted existing engine-range warnings, so use the README's supported Node 22/24 setup for normal development.

Commands actually run from the repository root (backend commands from `backend/` as shown):

```bash
npm install @xterm/xterm @xterm/addon-fit --legacy-peer-deps
npm run typecheck
npm run lint
npm test
npm run build

cd backend
TEST_DATABASE_URL=postgresql+psycopg://olympiad@127.0.0.1:55432/olympiad_phase2 .venv/bin/pytest --tb=short
DATABASE_URL=postgresql+psycopg://olympiad@127.0.0.1:55432/olympiad_phase2 .venv/bin/alembic upgrade head
DATABASE_URL=postgresql+psycopg://olympiad@127.0.0.1:55432/olympiad_phase2 .venv/bin/alembic check
cd ..
PYTHONPATH=backend:. backend/.venv/bin/pytest worker/tests -q --tb=short

# API + production preview were served locally; Chromium executable path set to the installed browser:
E2E_PRODUCTION=1 E2E_BASE_URL=http://127.0.0.1:5174 PLAYWRIGHT_CHROMIUM_PATH='/Users/isaevarman/Library/Caches/ms-playwright/chromium-1155/chrome-mac/Chromium.app/Contents/MacOS/Chromium' npm run test:e2e

# Small real admission workload, NOT compilation or 300-participant capacity validation:
PYTHONPATH=backend:. backend/.venv/bin/python tools/execution_load.py --participants 10 --timeout 2
```

The dedicated cluster was restarted using `pg_ctl ... restart -m fast`; the aggregate checksum includes snapshot IDs, source hashes and file JSON content. This checks persistence across that observed restart, not immunity to storage loss. Test workspaces/data were not destructively reset.

## Test coverage details

Frontend tests cover capture-before-await immutability, C++ explicit manifests without unrelated solutions, Python module defaults, deleted identities, configuration selection/fixed stdin persistence, test CRUD/duplicates/tombstones, whitespace preservation, legacy test migration, sticky/exportable local storage errors, immutable sending resource operations, retained remote conflicts and explicit rebasing, output duplicate/gap recovery and reload-safe execution telemetry correlation.

Backend tests cover all four language manifest contracts (admission, not real toolchains), traversal/reserved path rejection, source hash/entry/flags/input validation, owner isolation on job/resource/stream/cancel APIs, snapshot separation from workspace revisions, submission/resource idempotency, resource compare-and-swap/tombstones, queue quotas/cancel, concurrent claims, legal transitions, fenced expired leases, unresolved infrastructure state, result validation, ordered resumable SSE, exact comparisons and one-snapshot Run All. The existing process test starts/stops/restarts actual API subprocesses and confirms workspace, telemetry and execution records survive.

The four worker unit tests verify no non-Linux native fallback, dash-prefixed source paths cannot turn into compiler flags, no-follow/size checks on artifacts and rejection of a symlink artifact root. These are file/argument policy checks only. The 24 skipped Linux tests contain real C++17/C++20 compile/run/sum/multifile/errors/crash/loop programs, Python I/O/import/exception/loop programs, Java classes/packages/errors/memory programs, and real fork/output/network/filesystem/credential/recursion/memory probes. They must run on the dedicated deployment; setting the explicit test flag makes missing prerequisites fail rather than skip.

The three new browser tests use real APIs and PostgreSQL, not mocked success responses. They verify queued status with no worker (and no fake result), fixed stdin/source submission, configuration reload, real queued cancellation, saved test management/Run All, and a committed HTTP submission whose response is lost and retried with the same UUID. The optional worker browser scenario must run against actual Linux capacity. Existing production offline-shell, conflict, split-state, telemetry, quota-export and reconnect scenarios continue passing.

## Admission-only measurement

10 independent development identities submitted to the local API simultaneously. All were admitted; median execution-submission request time was **33.09 ms**, observed p95 **34.43 ms**. Jobs remained QUEUED because no worker was connected. Queue wait, compilation, execution and memory measurements were **null/unavailable**, not zero or simulated. This small test does not exercise continuous telemetry at 300 editors, 300 participants, compiler bursts or worker throughput. The supplied tool supports progressive larger real deployments and reports real job timestamps/results when workers exist.

## Outstanding release blockers / known limits

1. Provision a dedicated Linux VM/worker. Build an audited isolate revision, correctly delegate cgroup v2, configure quota-enabled box storage, disable swap, install toolchains and run every real language/security test. Review syscall policy, JVM configuration mounts, resource measurement, descendant cleanup, worker crashes, active cancellation and build-artifact isolation on that exact kernel. **No production-secure claim is made.**
2. Run the actual worker browser scenario, active-process cancellation/reload, worker/API/DB outage combinations, and deployment setup. Only queued cancellation and control-plane lease fencing are locally verified here.
3. Verify Docker/VM deployment; no Docker engine was available and the worker image was not built. Default Compose intentionally does not start an unsafe privileged substitute. Native API/frontend operation was tested.
4. Benchmark sustained worker throughput, fairness under 50-test batches and 300 concurrent editor/telemetry workloads. The initial bounded FIFO scheduler is not a preemptive weighted contest scheduler.
5. Establish production authentication/TLS/rate limiting, audited least-privilege worker DB roles, execution-history retention/storage operations and monitoring. Development admission quotas are not production capacity or long-term storage policy.
6. Browser storage/connection limits still apply: a failed uncommitted local resource write requires export, and uncertain durable submissions retry the exact payload when connectivity returns. Source/model and telemetry durability limitations from Phases 2/3 remain unchanged.

Phase 5 visual history, Phase 6 DAP debugging, official judging/CMS, ML and unrestricted interactive shells remain out of scope. The current Run/Stop UI should not be mistaken for proof that a compiler ran: the authoritative job/result state and measured worker data determine that.
