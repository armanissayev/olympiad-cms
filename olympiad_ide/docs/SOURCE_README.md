# Olympiad IDE

VS Code-inspired competitive-programming workspace implementing Phases 1–3 of [SPEC.md](./SPEC.md): Monaco, nested files, split editing, IndexedDB recovery, PostgreSQL synchronization, explicit conflict resolution and disclosed editor telemetry with headless replay verification.

Phase 4 execution control-plane, configuration/test management, terminal integration and Linux worker source are now added. **Phase 4 is not release-complete.** An AWS Ubuntu worker was deployed and verified on 22 October 2026 with real language, sandbox, API and browser tests. See the [AWS worker report](./docs/AWS_WORKER_REPORT.md) for results, limitations and reconnect instructions. No native macOS execution fallback exists.

## Run with Docker Compose

Requires Docker with Compose:

```bash
docker compose up --build
```

Open **http://localhost:8080**. PostgreSQL uses a named volume and the API applies Alembic migrations before starting. `docker compose down` preserves the database volume; `docker compose down -v` deletes it. Default credentials are for local development only. Set `POSTGRES_PASSWORD` to override the local password.

## Run natively

Use Node.js 22 LTS or 24+, Python 3.12+, and PostgreSQL. Start PostgreSQL and create an `olympiad` role/database (or start only the database with `docker compose up -d db`).

Backend, in its own terminal:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export DATABASE_URL='postgresql+psycopg://olympiad:olympiad-local-dev@127.0.0.1:5432/olympiad'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

Frontend, from the repository root:

```bash
npm ci --legacy-peer-deps
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` to `127.0.0.1:8000`, keeping session cookies same-origin. The frontend still opens and commits to IndexedDB if the API is unavailable. The API documentation is at **http://localhost:8000/docs**.

For a built local preview:

```bash
npm run build
npm exec vite -- preview --host 127.0.0.1 --port 4173
```

Include `http://127.0.0.1:4173` in the API's `ALLOWED_ORIGINS` environment variable. Production builds cache their app shell after the first successful load, allowing a complete offline reload. Dev mode needs Vite to serve the page on reload.

## Persistence and recovery

Edits immediately enter memory and are committed asynchronously to IndexedDB together with an ordered sync operation. Uploads wait about 400 ms after activity. Local durability always runs. Setting Server Auto Save to Manual pauses automatic uploads; Ctrl/Cmd+S or Save checkpoint flushes local work and requests a server upload. Closing or refreshing before a local transaction commits cannot guarantee recovery; outstanding writes trigger an unload warning where the browser supports it.

Click the synchronization status in the toolbar/status bar to inspect pending operations, the last server acknowledgement, retries, snapshots and preserved conflict branches. A Save Error provides JSON export of in-memory work and the untouched legacy backup. Snapshot Restore creates an ordinary new edit; deleted files restore as recovered files.

Conflicts show both versions side by side. Choose local, server, or save local as a separate recovered folder. The backend rechecks revisions on replacement. The Phase 1 localStorage key is migrated exactly once into versioned IndexedDB without deleting the original key; stable UUIDs and split state are retained.

## Editor recording (Phase 3)

The permanent recording disclosure and status-bar indicator explain collection and show session, sequence, pending events, server acknowledgement, gaps and last checkpoint. Click the indicator for privacy details, retry and JSON recording export. Keys are captured only in focused Monaco code editors; source transactions, navigation, file/tree operations and lifecycle observations are recorded separately. No compilation, debugging, ML classifications or history timeline are implemented.

Telemetry has its own append-only IndexedDB journal and authenticated PostgreSQL tables. Offline events upload independently of workspace autosave once the workspace has a server identity. Ordinary reloads start a new clock/session and retry old durable batches. Required events are never compacted. Failed storage keeps the recoverable memory prefix available for export and permanently marks that session incomplete. Browser eviction or a crash before a local commit cannot be guaranteed recoverable.

Apply the new additive Alembic migration using the same `alembic upgrade head` command above; IndexedDB v3 upgrades automatically without deleting Phase 2 data. Server retention defaults to 30 days and is configurable via `TELEMETRY_RETENTION_DAYS`. Expiration is not a background promise: administrators must run `.venv/bin/python -m app.telemetry_maintenance --delete-expired` from `backend/` to delete expired telemetry and its dependent rows. It does not delete workspaces. Browser journals are not automatically age-pruned.

See [Phase 3 architecture](./docs/PHASE3_ARCHITECTURE.md) for event/schema contracts, limits, batching/chunking, integrity and privacy, and [verification report](./docs/PHASE3_VERIFICATION.md) for delivered features, results and remaining limits.

## Execution, configurations and custom tests (Phase 4 — incomplete)

Apply `alembic upgrade head` as usual; IndexedDB upgrades to v4 automatically and retains existing tests, workspace data and telemetry. Open **Run and Debug** to manage named C++17/C++20/Python 3/Java 17 configurations, explicit entry points/included files, Java main class and optional default test. The first Run can create an active-file default; unrelated C++ solutions are not compiled automatically.

Run captures live unsynchronized source into an immutable hashed snapshot, then durably submits an idempotent job. The bottom panel contains xterm.js output (not a shell), fixed stdin, real status/history/cancellation and saved custom tests. **Run with stdin** always uses that buffer; regular Run may use the selected/default test. **Run All** captures one source snapshot and queues one bounded batch intended to compile once and run tests in separate boxes. Expected output comparison is exact after CRLF→LF normalization only; spaces are not trimmed. Resource sync has its own revisioned outbox and explicit conflict choices, without changing workspace synchronization.

The API never runs participant code. A separately installed, approved Linux `isolate`/cgroup-v2/quota worker is required for actual programs. Default Compose does not start a privileged substitute. See [Phase 4 architecture and Linux VM setup](./docs/PHASE4_ARCHITECTURE.md) and [verification report](./docs/PHASE4_VERIFICATION.md). The supplied worker Dockerfile is an unverified build recipe requiring an audited full isolate commit; native worker deployment in a dedicated Linux VM is the recommended path for Mac development.

Worker control/contract tests can run on this Mac, but the real security/toolchain suite requires Linux and explicit opt-in:

```bash
PYTHONPATH=backend:. backend/.venv/bin/pytest worker/tests -v
# Dedicated Linux host only; missing sandbox facilities must fail, not be bypassed:
PYTHONPATH=backend:. RUN_LINUX_SANDBOX_TESTS=1 backend/.venv/bin/pytest worker/tests -v
```

After a real worker passes the suite and is running, set `REAL_LINUX_WORKER=1` for the worker-dependent browser smoke test. Admission/load tooling is in `tools/execution_load.py`; start small and never claim 300-participant execution capacity from admission-only measurements.

## Checks

```bash
npm run typecheck
npm run lint
npm test
npm run build
```

Backend integration tests need a dedicated PostgreSQL database. Each test creates, migrates and removes its own temporary schema:

```bash
cd backend
export TEST_DATABASE_URL='postgresql+psycopg://olympiad:olympiad-local-dev@127.0.0.1:5432/olympiad'
.venv/bin/pytest
```

Without `TEST_DATABASE_URL`, database tests are explicitly skipped, not counted as verified. Tests include real transaction rollback, concurrent writers, session isolation, snapshots, and an actual API-process restart.

Browser tests need the frontend and backend running:

```bash
npm exec playwright -- install chromium
npm run test:e2e
```

To use an existing Chromium executable, set `PLAYWRIGHT_CHROMIUM_PATH`. To test the built offline shell, serve the production preview, permit its origin in `ALLOWED_ORIGINS`, and run:

```bash
E2E_PRODUCTION=1 E2E_BASE_URL=http://127.0.0.1:4173 npm run test:e2e
```

Browser scenarios cover split editing, exact-content reloads, backend outages, reconnect, same-browser conflicts, server conflicts, lost acknowledgements and storage-failure export. Complete network-offline reload runs only against a production build.

## Architecture and scope

See [docs/PHASE2_ARCHITECTURE.md](./docs/PHASE2_ARCHITECTURE.md) for schemas, transaction boundaries, migrations, synchronization, conflict resolution and durability limitations.

File changes, folder operations and settings use atomic workspace documents through `PATCH /api/v1/workspaces/{id}` or `POST /api/v1/sync/batches`. The backend also exposes workspace CRUD/listing, files/settings reads, sync status and snapshot retrieval. Ownership comes from a server-established HttpOnly development-session cookie, not a frontend user ID. CMS/production authentication is not implemented.

Run/Stop now call durable execution APIs; actual compilation/program output still requires the separately verified Linux worker. Phase 4 remains incomplete until that deployment and its security/language tests pass. Debugging, ML and the full history timeline remain later phases. Phase 1–3 editing, persistence and telemetry remain intact.

The full-document protocol intentionally supports small workspaces: at most 1,000 nodes, 2 MB per file and 8 MB total. Conflicts are workspace-wide and resolved explicitly. Undo stacks are not restored across a full reload. Browser storage may be evicted or unavailable; successful local and remote commits have different guarantees. Monaco still causes a production bundle-size advisory.
