# Phase 4 architecture and deployment

## Release status

**Phase 4 is incomplete.** The API, durable queue/resources, immutable snapshots and UI are implemented and locally testable. Linux worker/toolchain code and real language/security tests are supplied, but no Linux VM, Docker engine or execution host was available. The user confirmed this environment blocker. No participant code was executed as an unrestricted macOS subprocess and no successful compiler/output/resource result is fabricated. Real Linux sandbox and deployment verification remain release-blocking.

## Boundaries and source contract

The API never imports the executor or launches submitted processes. It accepts typed, bounded snapshots and queues durable jobs. A separate trusted non-root Linux worker imports the shared queue contracts, claims a lease and uses a root-owned setuid `isolate` helper. Participant compilers/interpreters/programs run only in isolate boxes; the controller, its credentials, database and API do not.

Run captures the currently selected configuration, test buffers and source text synchronously before awaiting hashing, local persistence or HTTP. Text is read from existing shared Monaco models, falling back to the workspace store for unopened files. It includes unsynchronized edits. Neither Monaco/model lifecycle nor Phase 2 workspace revisions/journals are rewritten. File identity stays UUID-based; the snapshot stores the exact historical relative paths as well as content. A subsequent rename/edit cannot change the queued manifest.

The SHA-256 hash covers canonical sorted-key ASCII JSON `{files, configuration}` using the existing Phase 3 canonical algorithm. Files are sorted by ID. Tests are immutable on the job but not part of the source hash; the complete submission has a separate server idempotency digest. The backend checks hash, stable IDs, exact included-file set, entry extension, duplicate IDs/paths, parent-file collisions, reserved names, traversal and source/input limits. Source must be valid UTF-8; lone UTF-16 surrogates remain valid recorded editor history but are explicitly rejected for toolchain submission rather than replaced.

Supported configuration contracts are `cpp17`, `cpp20`, `python3`, `java17`, an entry file ID, explicit included IDs, release profile, optional Java main class and optional default test. Default C++/Java includes only the selected file; unrelated `main()` solutions are not compiled. Python defaults include workspace Python modules. Headers and extra translation units are explicit choices. Compiler arguments cannot be supplied by participants. File arguments use absolute `/box/...` paths so dash-prefixed filenames cannot become switches.

## Additive storage

Alembic `f4a001` follows `f3a001`; old workspace/telemetry tables are untouched:

| Table | Purpose / indexes |
| --- | --- |
| `execution_resources` | Revisioned configuration/test documents and deletion tombstones; workspace index |
| `execution_resource_receipts` | Owner-scoped immutable operation digest and response |
| `execution_snapshots` | Immutable configuration, files, source hash and creation time; workspace index |
| `execution_jobs` | Owner/workspace/snapshot, idempotency digest, limits, tests, state, lease/token/cancellation, durable result and sequence; queue (status,time), owner/status, workspace and lease indexes |
| `execution_events` | Unique (job,sequence), server timestamp, typed status/output/case/result messages; job index |
| `execution_workers` | Controller heartbeat, configured capacity and sandbox label |

Run All is one job with one snapshot and up to 50 immutable tests. One compilation is reused only within that job, in controller memory, not across owners/jobs/toolchain configurations. Each case gets a new sandbox and fresh artifact copy. Completed case events are committed immediately; if the worker later fails, those events/partial results remain available even though the overall job is infrastructure-error.

Dexie v4 reuses the existing `testCases` store and upgrades legacy flat test rows without deleting their inputs/expectations. It adds `runConfigurations`, `executionResourceOperations`, `executionSubmissions`, and `executionEvents`. Active configuration/test selection and fixed stdin use namespaced metadata. This resource journal is independent from the Phase 2 workspace journal and the Phase 3 telemetry journal.

Resource writes have a local version guard for competing tabs. Unsent pending updates may compact, but a payload is reread and marked sending atomically before HTTP; sending operations are immutable. Later edits append at the next base revision. Server compare-and-swap rejects stale edits with the current resource. The UI keeps both versions, exposes explicit Keep Local/Use Server, and archives both before resolution. Failed local writes remain in memory/export rather than being silently replaced by a background pull. Explicit export includes the current configurations/tests. Uncommitted changes cannot survive process death. Tombstones and receipts are retained in this development implementation; establish administrative retention before long-running deployment.

## APIs

All workspace/job/resource routes use the existing authenticated development cookie and owner checks. Workers are not exposed through a public unauthenticated execution endpoint.

- `POST /api/v1/executions`: typed immutable submission with caller-selected UUID idempotency key; returns a real queued job after commit.
- `GET /api/v1/executions/{id}`: durable current status, immutable source manifest/hash/configuration/tests and optional measured result.
- `POST /api/v1/executions/{id}/cancel`: idempotent cancellation request; queued jobs cancel immediately; active jobs are stopped by their leased worker.
- `GET /api/v1/executions/{id}/events?after=N`: typed pages of up to 200 ordered events, with nextAfter.
- `GET .../events?stream=true&after=N`: SSE with sequence IDs, Last-Event-ID resume, heartbeat and bounded connection lifetime.
- `GET /api/v1/workspaces/{id}/executions`: most recent 30 owned jobs for reload/history recovery.
- `GET/POST /api/v1/workspaces/{id}/execution-resources`: typed configuration/test listing and idempotent revisioned upserts/deletion tombstones. These equivalent resource routes deliberately consolidate the suggested separate CRUD endpoints without altering workspace sync.
- `GET /api/v1/execution-capacity`: live controller count/configured capacity and owner-scoped queued/active/failed/cancellation counts.

Requests and responses use Pydantic models. API admission bounds: 100 files, 4 MB source UTF-8, 2 million UTF-16 units per file, 50 tests, 256 Ki characters per stdin/expected buffer, 1 MB aggregate test buffers, and the existing 9 MB request boundary. A source snapshot does not imply official judging/submission or a workspace upload.

Submission is persisted locally before HTTP; retries use the exact job ID, configuration, files and input. Reusing that ID with changed content is a 409. A lost acknowledgement does not create another job. Uncertain pending submissions retry after reload. The UI can cancel real queued work even with no worker available; it labels that state explicitly and does not present it as a successful run.

## Scheduling, leases and failure semantics

Legal path: QUEUED → PREPARING → COMPILING (compiled languages) → RUNNING → terminal. Terminal statuses include FINISHED, compilation/runtime/time/memory/output errors, CANCELLED and INFRASTRUCTURE_ERROR. Python skips compilation. Finishing with missing/unknown/duplicate successful case results is rejected; the backend recomputes comparisons from the original job expectations.

A short PostgreSQL transaction advisory lock serializes claim decisions, with row locks and SKIP LOCKED for candidates. FIFO selection plus bounded admission prevents unlimited submissions. At most one active job per owner, three queued jobs per owner, and 100 submissions per owner/hour are the development defaults. One job can contain at most 50 sequential tests; this is bounded admission, not a weighted/preemptive fair scheduler.

The worker has an independently configured capacity (`WORKER_CONCURRENCY`, 1–16). Each running slot has a distinct box ID; separate controller processes on the same host must use non-overlapping `WORKER_BOX_ID_BASE` ranges. Prefer a dedicated VM per node. A claim gets a UUID fencing token and 15-second lease. Heartbeats extend it every two seconds; every mutation/result write checks that token and lease under a lock. Losing the DB/token stops the active sandbox, rather than continuing as a healthy worker.

Expired active leases become INFRASTRUCTURE_ERROR (or CANCELLED if requested), explicitly recording an unresolved worker outcome. There is **no automatic re-execution** of an uncertain run; a user retry is a new job/snapshot. This avoids falsely treating a worker crash as success or promising exactly-once physical execution after a crash. Old workers cannot commit after fencing. Queued jobs have a configurable 600-second deadline. API lifespan maintenance checks deadlines/leases every five seconds; claim/read paths also reconcile them. Durable queue/results do not depend on a browser staying connected.

Limits are server-captured at admission, not accepted from participant controls. Environment variables use prefix `EXECUTION_`:

| Setting | Default |
| --- | --- |
| CPU_SECONDS / WALL_SECONDS | 2 / 5 |
| MEMORY_MIB | 256 |
| JAVA_MEMORY_MIB | 512 |
| OUTPUT_BYTES | 1,048,576 (hard upper bound in this version) |
| COMPILE_SECONDS / COMPILE_MEMORY_MIB | 30 / 1024 |
| MAX_QUEUED_PER_OWNER / MAX_SUBMISSIONS_PER_HOUR | 3 / 100 |
| QUEUE_TIMEOUT_SECONDS | 600 |

Execution memory uses cgroup memory accounting, not Java's virtual-address reservation. Java additionally uses a 256 MiB heap, bounded stack/metaspace/code cache, one reported processor and SerialGC; its cgroup limit includes native overhead. Compilation gets a separate allowance. CPU/wall/peak memory values come only from isolate metadata; absent values remain null. The UI says unavailable, never zero. Compiler time, queue time (started-created), run timings and worker/queue/failure counts are distinct metrics.

## Worker security and unverified boundary

The adapter requires Linux, a root-owned setuid isolate helper, a non-root controller, cgroup v2 and disabled swap. Box initialization requires disk quota support (65,536 blocks / 1,024 inodes). Before advertising capacity, the worker requires explicit deployment approval and successfully runs a sandbox prerequisite probe with cgroups, quotas and syscall restrictions. Unsupported facilities fail startup/claims; there is no fallback to unrestricted subprocess execution.

Default isolate namespaces/privilege separation are retained: network sharing, full environment inheritance, inherited extra FDs and special-file preservation are never enabled. Only allowlisted environment entries are passed. Code sees its box and standard read-only toolchain mounts, not controller paths, DB credentials, other boxes or runtime sockets. Java binaries resolve through alternatives to real `/usr` paths; only the non-secret Java 17 configuration directory is additionally bound read-only. The helper applies `--syscalls=31`; the selected audited isolate revision must support those restrictions. Programs get bounded process/thread/file descriptors, per-file sizes, box disk quota, CPU/wall time and aggregate output. Java/compiler process allowances are explicit.

Build artifacts are read only after the build process ends, with symlinks/special/oversized files rejected and no-follow opens; total reusable artifacts are capped at 32 MB / 1,000 files. Sandbox cleanup is in finally blocks; failed cleanup is an infrastructure error. stdout/stderr use bounded pipes rather than participant-selected file paths. Output is UTF-8 text with replacement for invalid byte sequences, not an arbitrary binary transport.

This is a security-sensitive implementation, **not a production-security certification**. The real Linux tests must verify namespace behavior, quota delegation, descendants/cancellation cleanup, compiler/JVM mounts and resource attribution on the deployment kernel. A privileged container is not supplied as a shortcut. Upstream documents cgroup delegation requirements and discourages ordinary container deployment; use a dedicated Linux VM unless a separately reviewed container arrangement passes the same suite. [Official isolate manual](https://raw.githubusercontent.com/ioi/isolate/master/isolate.1.txt), [upstream installation/Makefile](https://github.com/ioi/isolate).

## Native UI/API plus Linux VM setup (unverified here)

1. Provision a dedicated Ubuntu 24.04+ or comparable Linux VM on the Mac using a VM product of your choice. No VM was provided/created in this task. Keep unrelated workloads/secrets off the execution node. Use Linux kernel/cgroup v2 facilities supported by the chosen isolate revision, disable swap, and provision a quota-enabled filesystem for isolate boxes. Consult the upstream isolate setup for cgroup delegation and filesystem quota activation; do not bypass a failed quota/cgroup check.
2. On the VM install GCC/G++, CPython, OpenJDK 17, Python venv/build tools, libcap/libseccomp/libsystemd development packages, pkg-config and git. Audit/pin a full 40-character isolate commit supporting the adapter flags; build/install its helper and systemd units. Example build (administrator action, VM only):

```bash
git clone https://github.com/ioi/isolate.git /opt/isolate-src
cd /opt/isolate-src
git checkout --detach "$ISOLATE_REVISION"
sudo make install
sudo systemctl daemon-reload
sudo systemctl enable --now isolate.service
isolate-check-environment
```

3. Install this repository at `/opt/olympiad`, create a non-root `olympiad` service account, and create `backend/.venv` with the existing backend dependencies. Let only administrators modify the installed code/configuration. Give the service account appropriate isolate access per the audited installation. Reserve a box-ID range per controller.
4. Run PostgreSQL on the VM/private network, not publicly. Apply migrations using the API role. Give the trusted worker a separate DB role with SELECT on execution_jobs/execution_snapshots, UPDATE on execution_jobs, SELECT/INSERT on execution_events and SELECT/INSERT/UPDATE on execution_workers, plus schema USAGE. It does not need workspace/telemetry data or API credentials. Keep the worker connection secret in a protected environment file readable by the service account, outside sandbox mounts.
5. For native Mac API/frontend development, tunnel the private VM database rather than publishing it:

```bash
ssh -N -L 15432:127.0.0.1:5432 workeradmin@VM_ADDRESS
```

Use the usual native API commands with DATABASE_URL pointing to `127.0.0.1:15432`; the worker on the VM uses its private local DB endpoint. The browser still accesses Vite on localhost. Both API and worker share the same PostgreSQL database/schema, but participant processes cannot reach its network namespace or credentials.
6. Run the mandatory suite on that dedicated Linux host, **not on the Mac**:

```bash
cd /opt/olympiad
PYTHONPATH=backend:. RUN_LINUX_SANDBOX_TESTS=1 backend/.venv/bin/pytest worker/tests -v
```

When the real-test flag is set, missing isolate prerequisites are failures, not skips. Record environment, isolate commit, toolchain versions, commands and results. Review any failures rather than weakening the sandbox. Only after passing/reviewing the deployment set `WORKER_SANDBOX_APPROVED=1`, `WORKER_CONCURRENCY`, `WORKER_BOX_ID_BASE`, and the least-privilege DATABASE_URL in `/etc/olympiad/worker.env`. Install the supplied `worker/olympiad-worker.service` and start it. The root-owned setuid helper is needed; setting NoNewPrivileges on the controller would disable it.
7. Verify UI capacity reflects a real heartbeat, then run actual browser acceptance with `REAL_LINUX_WORKER=1`. Extend security testing/review beyond this initial suite before exposure to untrusted public participants.

`worker/Dockerfile` is also provided as an **unverified build recipe** and requires a full `ISOLATE_REVISION` build argument. It does not include a privileged runtime, Docker daemon socket, host root mount or a working cgroup-delegation assumption. Default Compose continues to start the API/frontend/PostgreSQL, not an insecure substitute worker. Worker container deployment is not verified; the dedicated native Linux VM path is the recommended boundary.

## UI, streaming and telemetry

The existing Run and Debug sidebar now manages configurations; Debug remains unavailable until Phase 6. Run/Stop and keyboard shortcuts submit/cancel actual API jobs. The terminal is xterm.js with no interactive input/shell, fixed stdin, clear/copy, scrollback and follow/manual-scroll behavior. Untrusted OSC clipboard/link/title/notification sequences are disabled. Compiler/stdout/stderr streams are distinguished; process exit and unavailable/measured statistics are explicit. Source manifest/configuration/hash are displayed. History reattaches to durable jobs after reload.

SSE and periodic REST polling share a serialized event consumer. Sequence duplicates are ignored, gaps trigger polling recovery, and committed local event prefixes resume without duplication. SSE does not hold a DB connection/transaction for its lifetime. A closed stream reconnects from the last committed cursor; job execution does not depend on it.

Custom tests support create/edit/rename/duplicate/delete/select, optional exact expectations, one test and Run All, partial case results and cancellation. Comparison normalizes CRLF to LF only; whitespace and empty output are significant. Accepted means the user's custom expectation matched, not official CMS judging.

Existing RUN_STARTED/RUN_FINISHED contracts gain an optional typed execution correlation object, preserving old schema-v1 payload compatibility. It includes job/snapshot/hash/configuration/language/status/server timestamp; workspace identity is in the envelope. Events are emitted only when real server lifecycle changes are observed, not when clicking a mocked Run or merely queuing work. Reload baselines historical lifecycle state without inventing new starts/finishes. Per-job persisted flags plus a serialized observer prevent ordinary duplicate recording. A telemetry storage failure does not block job submission or authoritative server results; recording remains explicitly degraded.

## Files and next steps

New modules: backend `execution_schema.py`, `execution_models.py`, `execution_service.py`, `execution_api.py`; migration `f4a001_execution.py`; `worker/app/{main,sandbox,executor,languages}.py`, worker tests/Dockerfile/service; `src/execution/{types,snapshot,resources,controller,TerminalOutput,RunPanel,TestCasesPanel}.tsx/ts`; frontend/API/browser tests; `tools/execution_load.py`; this document and verification report. Integration edits are confined to API route/model registration, the additive Dexie migration, optional RUN correlation fields, existing toolbar/sidebar/bottom panel/shortcut/startup wiring and styles/dependencies. Source/model ownership and workspace sync contracts are retained.

Next release blockers: real Linux language/security/cancellation/cleanup verification, Docker/VM deployment verification, sustained worker-load/300-editor measurements, operational execution-history retention/quota policy and production authentication/TLS/rate limiting. Phase 5 history visualization and Phase 6 DAP debugging are not implemented here.
