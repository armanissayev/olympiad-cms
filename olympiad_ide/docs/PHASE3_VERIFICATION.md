# Phase 3 completion and verification report

## Delivered

- Strongly typed schema-v1 event envelopes with UUID identities, synchronous session ordering, wall-clock correlation and independent monotonic timing.
- Monaco-scoped key down/up recording, repeat/modifiers/navigation/delete keys, composition observations, separate authoritative document transactions, explicit paste correlation, undo/redo, exact multi-cursor offsets and independent split-pane navigation.
- One document subscription per shared model, stable file identities and revisions across pane/tab/rename operations, disposed listeners, and explicit hydration/recovery/conflict origins.
- File/folder creation, rename, move and atomic subtree deletion; active-file/tab/split/focus/page visibility observations. Real find/replace and multi-cursor Monaco contributions are registered.
- Independent append-only local telemetry journal, buffered serialized writes, migration-safe Dexie v3 tables, retained failed prefixes, sticky incomplete sessions, visible recording errors/backpressure interruption and safe JSON export.
- Independent ordered uploader: durable immutable batches, 200-event/byte budgets, early count flush, two-second scheduling, jittered retries, cross-tab upload lock, idempotent receipts, reload draining, durable chunk staging for large transactions and offline recovery.
- PostgreSQL SQLAlchemy models and additive frozen Alembic migration; typed request validation; owner-cookie isolation; transactional ingestion/acknowledgements; sequence/revision/file/range/clock/hash/reference verification; bounded storage and pagination.
- Pure multi-file headless replay at intermediate sequences, portable SHA-256 checkpoint hashing, exact UTF-16 replay in JS and Python, and explicit integrity/lifecycle status.
- Initial, file-create, active-time/change-threshold, pre-delete, hidden-page and completion checkpoints; no per-key full-workspace checkpoint serialization.
- Compact status-bar indicator, diagnostics/disclosure panel and persistent recording notice, with no generic dashboard or history timeline.
- Configurable development retention and an explicit expired-session deletion command, including dependent event/checkpoint/receipt/chunk cleanup without deleting workspace data.
- Typed run/debug contracts only. No fabricated run/debug events, execution, debugging, cheating scores, ML or jury/history UI.

The full file map, schema/index inventory, migration ordering, protocol, replay semantics, checkpoint strategy, retention configuration and architectural decisions are in `PHASE3_ARCHITECTURE.md`. README includes setup, migration, recording and maintenance instructions. Phase 2 verification documents describe the historical Phase 2 baseline; the new architecture supersedes their statement that telemetry is unimplemented.

## Verification environment and results

Verified natively on this macOS workspace with local PostgreSQL 14, project-local Python 3.12, Node.js and installed Chromium. PostgreSQL integration tests use independent temporary schemas, never SQLite substitutes. All temporary test schemas are removed by their fixtures.

| Check | Final result |
| --- | --- |
| Frontend unit/integration tests | 51 passed, including the existing 28-test baseline |
| PostgreSQL API/integrity tests | 25 passed, including the existing 12-test baseline |
| Production Chromium scenarios | 10 passed, including all 7 prior scenarios |
| Strict TypeScript | Passed |
| ESLint, zero warnings allowed | Passed |
| Production build | Passed; existing large-Monaco-chunk advisory remains |
| Alembic migration / ORM drift | Passed; no new upgrade operations detected |

Total: 86 passing automated tests/scenarios. Test code is in `src/telemetry/telemetry.test.ts`, `src/persistence/api.test.ts`, the expanded `src/persistence/repository.test.ts`, `backend/tests/test_telemetry.py`, the extended real-process restart test, and `e2e/telemetry.spec.ts`, alongside the prior suites.

## What was actually exercised

Frontend tests verify key/code normalization, repeated/modified/non-text keys, Unicode and composition flags, one content subscription for a shared model, revision continuity through tabs/rename/undo/redo, multi-edit BEFORE offsets, large insertions without inferred paste, programmatic recovery labeling, seeded randomized multi-file traces at every intermediate sequence, structural operations and checkpoint verification. They also test invalid offsets/revisions/gaps, configured checkpoint thresholds/timers/completion, ordinary reload with immutable pending batches, size-prioritized batching, quota/transaction failures, sticky incomplete state, recoverable export and explicit backpressure interruption.

Both existing IndexedDB v1 and v2 are upgraded to v3 while verifying exact source nodes, settings, split/tab state and queued operations survive. PostgreSQL migration tests create Phase 2 workspace data before the telemetry upgrade and compare the complete API response afterward.

PostgreSQL tests verify astral Unicode and UTF-16 positions/ranges, escaped lone surrogate preservation through ingestion/replay/reads, multi-cursor/undo/redo transactions, delayed historical checkpoints, pagination and server timestamps, payload/count/size validation, missing-sequence rollback and diagnostic state, revision/checkpoint mismatch, duplicate events/batches and changed-ID reuse, engine/application reload, durable chunk staging across application recreation, owner checks on every resource type, interrupted close, and expiration cascades that leave workspaces intact. The existing subprocess test now terminates/restarts a real Uvicorn API process and verifies both workspace persistence and telemetry idempotent replay after restart.

The three new production-browser scenarios use real Monaco, not a text-input mock. They verify actual multi-cursor transactions and Replace All, ordinary keys/repeat/modifiers/deletion/navigation, Unicode input, synthetic composition start/end observations, large real clipboard paste with transaction correlation/chunk upload, split shared models, tabs, undo/redo, replay/checkpoint consistency, offline reload with a new clock domain, lost HTTP acknowledgement retries without duplicate events, and IndexedDB quota errors with downloadable in-memory export. An unrelated form's sentinel value is confirmed absent from the exported recording. Existing browser scenarios verify conflicts, recovered copies, independent cursor state, lost workspace acknowledgements, backend outages and a production shell reload with the entire connection offline.

During verification, real browser navigation exposed an overly broad server `_MOVED` dispatch branch that treated `CURSOR_MOVED` as structural. It was corrected and covered by a dedicated server test. A stricter browser assertion also identified missing lightweight Monaco contributions; find/replace and multi-cursor are now explicitly imported, and the test asserts an actual multi-change transaction. UTF-16 edge testing exposed normal Pydantic string validation rejecting isolated surrogate code units; bounded typed source validation and ASCII JSON responses now preserve them exactly.

The final regression run also exposed a first-visit cookie race between the two uploaders. The shared API helper now deduplicates concurrent identity requests and uses a separate cross-tab identity lock; a unit regression verifies one cookie establishment for concurrent callers. Workspace mutation/sync semantics were not changed.

Server-log inspection also identified quota-owner `FOR UPDATE` locks conflicting with Phase 2 owner foreign-key checks. Telemetry now uses `FOR NO KEY UPDATE`: telemetry quota writers still serialize, while Phase 2's `KEY SHARE` references remain compatible. A concurrent PostgreSQL regression holds the quota lock and verifies a real workspace sync can commit before it is released.

## Architectural decisions

1. Keep Phase 2's compactable workspace journal and telemetry's append-only event history entirely separate. No keyboard/document events are synthesized from workspace upload documents.
2. Track content on shared models and navigation on panes. Telemetry document revisions are independent of Phase 2 upload revisions and Monaco undo version numbers.
3. Use new runtime sessions on reload. Never splice a reset monotonic clock into an old session; retain and drain its committed events and label an unclosed history interrupted.
4. Record full change transactions with original UTF-16 coordinates; do not infer characters from keys or paste from insertion size.
5. Keep transactions/events intact for replay. Chunk only their serialized transport and durably stage it on the server.
6. Commit receipts only with validated events/checkpoints. Client acknowledgements advance atomically and cannot regress across tabs.
7. Treat hashes as consistency checks and open-session Complete as a consistent prefix, not a completed contest or proof of authentic behavior.

## Incomplete or explicitly not guaranteed

- Docker is not installed on this verification host; the updated Compose deployment was not built/launched. Native production-build/API/PostgreSQL operation was tested.
- Synthetic browser composition events test the observable hooks, not actual OS IME candidate windows or every mobile/browser/keyboard combination. A real OS/IME/accessibility matrix remains manual acceptance work.
- No sustained large-workspace performance benchmark or browser-eviction/OS-power-loss guarantee is claimed. The large-paste scenario passes, but workspaces remain the bounded contest-sized design from Phase 2.
- Initial session snapshots are not chunked and must fit the 8 MB canonical assembly budget. Individual events have a server-default 4 MB limit and assembled batches/checkpoints an 8 MB limit. Exceeding supported limits reports an error and retains the local log for export, rather than silently skipping required records.
- A newly created offline/manual-save workspace needs its ordinary Phase 2 server registration before telemetry can register. Telemetry does not bypass manual workspace synchronization or replace its ownership workflow.
- Interrupted sessions that never return can remain server-side open recordings; no stale-session heartbeat adjudicator is implemented. Reloads explicitly mark their prior runtime interrupted. Without Web Locks, cloned SessionStorage has weaker prior-tab identification, though UUID session/event identities remain isolated.
- Browser retention is not automatic: acknowledged and unsent journals remain local until deliberate maintenance/browser clearing. Server expiration requires the documented maintenance command; no recurring task was installed.
- Development cookie ownership is not production/CMS identity or research-access governance. Production deployment still needs TLS, real authentication/recovery, consent/retention policy, rate limiting/streaming request limits, operational maintenance and monitoring.
- Events buffered in memory at sudden termination may be lost. A committed prefix survives normal reload; the UI never equates that with guaranteed capture after process death or malicious data clearing. Undo stacks themselves are not restored across full reloads.

## Phase 4 extension points

Execution workers can call the collector with typed `RUN_STARTED`/`RUN_FINISHED` events only when real jobs start/finish. Debug contracts are prepared for their later DAP phase. Source/model ownership, telemetry sequencing and the Phase 2 journal need no replacement. Full History timeline UI, research exports/permissions and ML remain later work.
