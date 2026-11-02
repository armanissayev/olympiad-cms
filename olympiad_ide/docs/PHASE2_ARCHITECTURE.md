# Phase 2 persistence design

Historical Phase 2 baseline. Phase 3 now adds the separate telemetry journal described in [PHASE3_ARCHITECTURE.md](./PHASE3_ARCHITECTURE.md); the Phase 2 synchronization protocol below is preserved.

## Data ownership

Zustand and Monaco hold the immediate working copy. IndexedDB is the acknowledged local recovery source. The controller is the sole reconciliation boundary between these and PostgreSQL. The legacy `olympiad-ide-phase1` localStorage key is read for migration only and is never rewritten or deleted.

Dexie schema v1 defines workspaces, normalized file nodes, editor sessions, workspace settings, prepared test-case records, sync operations, recovery snapshots and migration metadata. Version 2 adds persisted conflicts and upgrades retry metadata. Workspace metadata and file rows are authoritative; editor/session/settings tables are assembled into a single working copy at startup. `savedContents` is only a UI marker, not another durable document store.

Every substantive local mutation runs through a serialized promise chain. A transaction updates the workspace and nodes, snapshots if due, settings, and the sync journal together. Hashes are prepared before entering IndexedDB transactions; WebCrypto waits inside a transaction can deadlock or close it in real browsers. Local commits begin immediately, including when the upload setting is off. Navigation state is committed locally and included in queued workspace state. No edit depends on a debounce callback for local durability. Uploads are debounced by 400 ms, configurable in `PersistenceController`.

The UI distinguishes Saving (writes outstanding), Saved locally, Syncing, Synced, Offline, Conflict and Save Error. `Synced` requires matching operation acknowledgements to be recorded in IndexedDB. A pending write or save failure activates the browser's unload warning where supported. Visibility/pagehide events request a flush; they are not used as a durability guarantee.

## Server model and transaction contract

PostgreSQL tables: `development_identities`, `workspaces`, `file_nodes`, `workspace_settings`, `synchronization_operations`, `workspace_revisions`, `recovery_snapshots`. Alembic owns schema creation. Node identity is `(workspace_id, file_id)`, so migrated stable file UUIDs can coexist in different workspaces. A deferred composite parent foreign key prevents cross-workspace parent references. Pydantic validates names, UUIDs, languages, content limits, settings, editor state, parent existence, unique siblings and cycles before mutation.

Development identities use server-generated random bearer secrets stored in HttpOnly, SameSite=Strict cookies. Only a SHA-256 token digest is stored in PostgreSQL. Sessions last 30 days. Cookie ownership checks protect every workspace resource, including snapshots and idempotent replay. Client-supplied owner IDs never authorize requests. Same-origin reverse proxies avoid cross-origin cookie configuration; mutating requests with an Origin header are checked against `ALLOWED_ORIGINS`. Set `COOKIE_SECURE=true` behind HTTPS. This is development authentication; CMS login/account recovery and production rate limiting are future work.

All tree/settings mutations use complete, bounded workspace documents through PATCH or the sync endpoint. Per-file POST/PATCH routes are intentionally consolidated into this atomic document contract: rename/move/delete and settings changes share the same revision check. This prevents partially applied parent/child mutations and makes dependencies deterministic.

`POST /api/v1/sync/batches` accepts one workspace and up to 20 ordered operations. Each has a UUID, expected workspace revision and document. The server locks the workspace row, verifies ownership and prior operation receipts, checks the expected revision, applies changes, records snapshots/revision/receipt and commits. Responses are sent after commit. A failed operation rolls back the entire batch. Replaying an operation with the same payload returns its original acknowledgement; using its ID with different content is rejected. Revision receipts are durable, not an in-memory cache.

## Journal and retry algorithm

IndexedDB operations have an auto-incrementing sequence, operation UUID, base revision, document, pending/sending state and retry count. Only the final unsent operation can be compacted. Once marked sending, its payload is immutable forever, including across reloads and uncertain HTTP failures. New changes append behind it with the next base revision. Requests send the earliest operation first. A successful matching acknowledgement removes that operation and advances the local server watermark in one transaction.

HTTP request results establish API reachability. Retries use capped exponential backoff with jitter (approximately 1 second initially, at most 36 seconds including jitter), plus a 10-second idle connectivity check and an online-event trigger. Requests have an 8-second timeout. Web Locks serialize uploads across same-origin tabs when available; durable operation IDs protect replay without Web Locks. No keyboard telemetry is collected.

## Conflict handling

Workspace-level optimistic concurrency is deliberately conservative: unrelated edits in separate files can conflict, but stale rename, move, delete, settings and source changes cannot silently overwrite one another. HTTP 409 includes the latest server document. The local journal and local branch remain durable while synchronization pauses.

IndexedDB localVersion is a second compare-and-swap guard for tabs sharing the same database. A stale tab's source mutation creates a persisted conflict rather than replacing the canonical head. Navigation state may be last-write-wins as a device preference; source text may not. When additional branches are encountered, previous conflict branches are retained in bounded recovery archives.

The resolution dialog compares file contents side by side and displays structural differences. Keep local, keep server and save local as a recovered folder all operate on the complete workspace. Resolution fetches the current server document and refuses an outdated reviewed revision. A new operation uses that fresh revision, so another intervening write still produces a 409. A localVersion check also protects against another tab changing the local head during resolution. Before replacing anything, both conflict versions are archived locally. Archived local branches can be restored as separate recovered folders from synchronization details.

## Recovery and Monaco

Recovery snapshots contain stable file ID, name, exact content, SHA-256 hash, revision, reason and timestamp. Initial and pre-structure/delete snapshots are created transactionally. A configurable 60-second timer captures modified files, and snapshots are also checked during commits. Unchanged content is deduplicated. Local and server per-file retention defaults to 20; local conflict archives are also bounded to 20. Server snapshot interval and retention use `SNAPSHOT_INTERVAL_SECONDS` and `SNAPSHOT_RETENTION`. Soft-deleted content remains in file rows and snapshots. This is recovery storage, not a full editing event log.

The app hydrates before mounting editors. Stable UUIDs and `olympiad://` URIs are preserved. Existing Monaco models are reconciled in place for explicit recovery/server adoption; closing tabs does not dispose shared models. Undo history survives normal use and no full text-model recreation is needed. Undo-stack restoration after a full browser reload is not promised.

Production builds include a service worker that precaches only app assets, Monaco workers and language contributions. API responses and source code never enter Cache Storage. After one successful installation, the app shell can reload with the network entirely offline. Development mode requires the Vite server for reload, although backend outages are supported. IndexedDB contents remain subject to browser eviction, private-mode limits, quota and device failures. Storage errors keep in-memory work available and expose JSON export. There is no claim that an uncommitted keystroke survives abrupt process termination.

## Current limits

- Synchronization uses bounded complete documents (1,000 nodes, 2 MB/file, 8 MB/workspace), trading bandwidth for straightforward consistency. It is not designed for large repositories.
- No automatic text merge; conflicts require review.
- Development sessions are browser-cookie identities. Clearing cookies without an account/recovery flow does not grant access to the old server workspace. Clearing IndexedDB does not delete PostgreSQL records; importing/listing server workspaces is exposed by the API, but there is not yet a workspace-selection UI.
- Acknowledged operation receipts and workspace revision metadata are retained indefinitely in this development implementation. Configure an administrative retention policy before a long-running production rollout.
- The recovery UI lists local snapshots; server snapshots are available through the ownership-protected REST endpoint. There is no full history/replay UI.
- No execution workers, telemetry pipeline, custom test execution, DAP debugging or CMS integration is implemented.
