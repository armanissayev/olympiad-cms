# Phase 3: recording, durability and integrity

## Scope

This is an observable editor-history recorder, not a keylogger outside the editor and not a cheating detector. It records browser/Monaco observations, not every physical key under every OS/IME. Source changes are authoritative even when no corresponding key is exposed. Client clocks, event IDs and hashes cannot prove honesty against a malicious client.

Phase 2 remains the workspace recovery/synchronization system. Its compactable journal, local CAS, conflict archives, snapshots and server receipts are unchanged. Telemetry has independent tables, ordering, uploader, receipts and checkpoints. The only reconciliation integration is a dependency-free origin context around model hydration/server adoption/recovery/conflict application.

Both uploaders use the shared API helper's single-flight, cross-tab-locked development-cookie establishment. This prevents simultaneous first-visit session requests from racing to assign different owners; it does not change workspace synchronization or ownership rules.

## Frontend modules and integration

| Module | Responsibility |
| --- | --- |
| `src/telemetry/types.ts` | Versioned discriminated event union; typed execution/debug integration contracts |
| `collector.ts` | Session clock/sequence; shared-model tracking; structural store observation; checkpoint scheduling; diagnostics/export |
| `keyboardTracker.ts` | Monaco/browser keyboard normalization, modifiers, repeat, composition flag |
| `navigationTracker.ts` | Pane-local keys, cursor, selections, focus, composition, explicit paste correlation |
| `origin.ts` | Synchronous programmatic-change context, with no dependency on either journal |
| `eventQueue.ts` | Serialized buffered IndexedDB transactions; retained failed prefix; sticky incomplete state |
| `telemetrySync.ts` | Immutable byte-bounded batches, chunk transport, receipts, retries and reload draining |
| `replayEngine.ts` | Pure immutable UTF-16 replay, canonical hashing and checkpoint verification |
| `components/TelemetryPanel.tsx` | Status-bar diagnostics, permanent disclosure, retry and local archive export |

Integration points are `main.tsx`, `editor/modelRegistry.ts`, `components/editor/EditorPane.tsx`, `components/StatusBar.tsx`, `index.css`, the additive Dexie migration in `persistence/database.ts`, and origin labels in `persistence/controller.ts`. Monaco's lightweight API entry now explicitly registers find/replace and multi-cursor contributions, so these real editing actions can be exercised rather than simulated by a UI-only placeholder.

## Envelope and transaction ordering

Every event includes `schemaVersion: 1`, UUID `eventId/sessionId/workspaceId`, nullable stable `fileId`, session-local sequence starting at 1, ISO wall-clock `clientTimestamp`, monotonic `performance.now()` offset, discriminated `eventType`, and its specific typed payload. Sequence assignment is synchronous; async hashing, writes and HTTP never assign or reorder it. Wall-clock time is correlation only. A reload creates a new UUID and monotonic origin, never appends reset clock values to an old session.

One `ITextModel.onDidChangeContent` subscription owns each live shared model. This is the model-level source of Monaco's `onDidChangeModelContent` notification; it intentionally does not subscribe to content separately in both panes. Registry adoption and pane model changes attach through the same deduplicating map. Model disposal removes both subscriptions; pane disposal removes its independent input/navigation subscriptions. Closing tabs and renames retain the same model/file identity. Telemetry revisions belong to the recorded document state, not a pane, a filename, an undo version, or the Phase 2 upload revision.

Each content notification is one transaction: UUID, before/after revision (+1, including undo/redo), every BEFORE-document UTF-16 offset/deleted length/inserted text/range, resulting EOL convention, and optional recent same-file keyboard event ID. Replay sorts descending offsets, preserving original array order for ties, and rejects overlap/out-of-range edits. This is important for multi-cursor edits. EOL-only changes are recorded, too. Python uses UTF-16LE with surrogate preservation rather than slicing Unicode code points. JSON storage preserves escaped surrogate code units.

Undo/redo are actual recorded changes, not commands that require reproducing Monaco's undo stack. Programmatic reconciliation replaces an explicitly labeled snapshot (`server-sync`, `conflict-resolution`, `recovery-snapshot`, `recovery-archive`, or hydration), rather than pretending it was typing. Other non-model store edits are labeled `programmatic-store-update`.

Keyboard and content records stay separate. A recent key reference is temporal correlation, not a claim of causation. Explicit Monaco paste notifications contain only the inserted range and an optional matching model-version transaction ID; clipboard contents are never read by the recorder. An arbitrary large insert is never classified as paste. Composition start/end and the observed key's composition flag are recorded without inventing missing IME keys. No navigation coalescing is currently applied: all observed cursor/selection notifications are retained.

Structural events contain stable node identities and complete initial node data. Rename/move update one identity; folder deletion lists its exact subtree atomically. Parent creation precedes child creation. Active group/file, tab changes, split changes, focus and visibility are separate observations. Run/debug payloads are contracts only; unavailable buttons emit no execution events.

## Local schema, queue and failure contract

Dexie v3 only adds tables to the existing v1/v2 database:

| Table | Keys/indexes | Meaning |
| --- | --- | --- |
| `telemetrySessions` | id, workspaceId, tabId, startedAt | Initial checkpoint, durable sequence/ack watermarks, lifecycle, retention/error |
| `telemetryEvents` | [sessionId+sequence], unique eventId, sessionId | Append-only required events |
| `telemetryBatches` | id, sessionId, [sessionId+firstSequence] | Durable immutable payload/digest and ack state |
| `telemetryCheckpoints` | id, sessionId, [sessionId+sequence] | Exact sequence-bound snapshots/hashes |
| `telemetryAcknowledgements` | batchId, sessionId | Verified matching server receipt |

Writes are buffered for 16 ms then serialized. Each transaction commits its exact event prefix, checkpoints and session metadata atomically. Hashing happens outside Dexie transactions. The editor never waits for a network request. Required records are not compacted. Failed transactions retain the prefix in memory for retry/export; local creation can be retried after an initial storage failure. There is no claim of write durability before commit.

`telemetryConfig` configures the 60-second active-edit timer, 500-change threshold, 20,000-event in-memory high-water mark, 32 MB failed-buffer threshold and 30-day development retention display. Exhaustion explicitly stops further capture, retains the captured prefix and labels the session interrupted. It does not silently discard events while showing a healthy recorder. Storage failures are sticky incomplete-session markers, even if a later retry commits the retained data. Archive export includes retained durable sessions/events/checkpoints/batches plus the current in-memory prefix, deduplicated by ID.

Each browser runtime has a unique session. SessionStorage identifies the prior runtime of a tab; reload marks its unclosed session interrupted. Web Locks disambiguate `window.open` cloning SessionStorage so an active parent isn't mistaken for a reloaded runtime. Without Web Locks, unique sessions still isolate events, but cloned tab metadata cannot provide the same prior-runtime identification guarantee. A page which never returns may remain server-side `recording`; this is an open prefix, not a certified completed session. No server heartbeat-based stale-session adjudication is implemented.

## Independent upload protocol

`uploadConfig`: 2-second interval, up to 200 events, 256,000-byte normal body budget and 8 MB assembled batch budget. Crossing 200 pending events requests an early flush. Size takes priority over count. JSON is canonical ASCII for portable byte accounting/digests. Oversized individual events/checkpoints produce an explicit error and remain exportable; they are not silently skipped.

1. Authenticate using the existing development cookie. Register the telemetry session and exact initial checkpoint only after its Phase 2 workspace exists remotely.
2. Select a contiguous committed prefix after the local ack. Reuse any already-durable unacknowledged batch verbatim. Persist a new UUID/body/SHA-256 digest before making its HTTP request.
3. Small batches go to `POST /api/v1/telemetry/batches`. Large inserts remain a single event: transport splits their immutable serialized batch into <=32 KB chunks, each sent to `POST /api/v1/telemetry/batches/{id}/chunks` with index/total/digest. The request budget includes encoding overhead. PostgreSQL stages chunks durably and rejects conflicting retries. A partially uploaded batch resumes after browser/API restart.
4. The last chunk assembles, bounds and validates the original batch. No event acknowledgement is returned for partial staging. Sequence/replay/checkpoint validation, event insertion, session watermark and committed receipt are one transaction.
5. The client verifies receipt session, UUID, digest and watermark. It atomically commits the receipt, batch ack and monotonically increasing local watermark. Lost acknowledgements retry the same batch. Different batches containing identical prior event IDs are also deduplicated; changed reuse is rejected.

Web Locks serialize telemetry uploaders across tabs independently of the Phase 2 lock. Server receipts and monotone local acknowledgement updates protect retries when locks are unavailable. Retries use capped exponential backoff with jitter and an online trigger; pending records survive reload. A single turn drains at most four batches per session. There is no timer-dependent local save.

The initial session-registration request is bounded by the 8 MB API assembly limit, not chunked. Initial snapshots whose canonical representation exceeds it cannot upload; the UI reports the limit and retains the local journal. A new offline/manual-save workspace must first receive its ordinary Phase 2 server registration; telemetry never silently enables workspace autosave or creates a competing server workspace. These are explicit current protocol limits.

## Checkpoints and replay

Initial checkpoint is sequence 0; later checkpoints capture file creation, every 60 seconds with document activity or 500 document changes, before deletion, page hiding and explicit completion. Snapshot capture and sequence capture are synchronous; SHA-256 and persistence are asynchronous and ordered. Later pending edits do not change that checkpoint's boundary. Full snapshots are not serialized on ordinary key events. This is separate from recovery snapshots.

The checkpoint hash covers canonical, sorted-key ASCII JSON of the whole node map (including exact source, revision, parent, name and type). Canonical escaping includes astral/lone surrogate code units; Python and JS hashes agree. Hashes establish consistency, not authenticity.

`replay(initialNodes, events, throughSequence)` is pure and does not touch Zustand or Monaco. `verifyCheckpoint(state, checkpoint)` verifies both stored checkpoint content and reconstructed state hashes. Tests use both utilities at intermediate boundaries. The server independently replays accepted transactions and can reconstruct a historical prefix when a delayed checkpoint arrives. Integrity states are Complete, Missing Events, Revision Mismatch, Checkpoint Mismatch, Recording Interrupted and Invalid Event. Complete means the accepted prefix is internally consistent; the separate lifecycle status distinguishes open, completed and interrupted sessions.

## Backend schema and API

`backend/app/telemetry_schema.py` builds a Pydantic discriminated union with one concrete payload per event type. Unknown event types/fields, malformed UUIDs, invalid ranges, non-finite timing, excessive counts and oversized text are rejected. `telemetry.py` enforces ownership, sequence, clocks, revisions, tree identities, UTF-16 offsets/ranges, key/paste references and checkpoint hashes. Diagnostic integrity state survives a rejected batch; its partial events/receipts do not.

Alembic `f3a001` follows `9773627aa90c` and freezes explicit additive definitions. `telemetry_models.py` defines:

- `telemetry_sessions`: owner/workspace FKs and indexes, client/server creation times, completion/lifecycle, integrity, contiguous sequence, monotonic watermark, replay state, logical byte usage, gaps, indexed expiration.
- `telemetry_events`: unique event UUID, unique (session, sequence) B-tree index, typed event metadata, payload/envelope, server ingestion timestamp. File IDs deliberately have no FK to live workspace rows: deleted historical files remain replayable.
- `telemetry_checkpoints`: session and sequence indexes, workspace revision, exact document state/hash, client envelope and server timestamp.
- `telemetry_batches`: session index, immutable digest, first/last sequence, staging chunks/limits and committed acknowledgement state.

All child telemetry rows cascade on session deletion. Phase 2 tables are unchanged. Writers take an owner `FOR NO KEY UPDATE` lock, then the telemetry-session lock, enforcing quotas and ordering across tabs while permitting Phase 2's owner-FK `KEY SHARE` locks. A stronger owner `FOR UPDATE` lock would create a cross-protocol lock-order hazard and is deliberately not used. Server timestamps are independent from client time.

Routes: POST sessions, POST batches, POST batch/{id}/chunks, POST session/{id}/close, GET policy, and owner-scoped GET session/{id}/status, /events, /checkpoints under `/api/v1/telemetry`. Events use `after` sequence and `pageSize` (default 100, max 500). Checkpoints use an opaque `after` checkpoint ID and pageSize (default 20, max 100). Responses supply `nextAfter`. No endpoint exposes another cookie identity's telemetry.

Server environment configuration (also retention/byte budgets wired through Compose):

| Variable | Default |
| --- | --- |
| `TELEMETRY_RETENTION_DAYS` | 30 |
| `TELEMETRY_MAX_BATCH_BYTES` | 8,000,000 |
| `TELEMETRY_MAX_EVENT_BYTES` | 4,000,000 |
| `TELEMETRY_MAX_SESSION_BYTES` | 100,000,000 |
| `TELEMETRY_MAX_SESSION_EVENTS` | 1,000,000 |
| `TELEMETRY_MAX_OWNER_BYTES` | 1,000,000,000 |
| `TELEMETRY_MAX_OWNER_SESSIONS` | 200 |

Chunks are limited to 64 KB, 1,024 chunks and two in-progress staged batches per session. Storage quotas measure logical canonical payload bytes, not PostgreSQL physical disk amplification. The existing API boundary limits requests to 9 MB. A production ingress proxy should additionally bound streaming bodies, request rate and concurrent work. Budget reductions below the frontend defaults cause explicit pending/local errors, not data truncation.

## Privacy, retention and remaining production work

A persistent disclosure and status-bar panel explain collection scope, research/replay purpose, IndexedDB/PostgreSQL storage, owner-cookie access, administrator access, development retention and browser limits. Only focused code-editor keys are captured; find/search/other form keys are excluded. Source changes from Replace All are still recorded. There is no OS/browser-UI monitoring, raw clipboard read, classification, score, telemetry jury dashboard or full replay timeline.

Expiration is set from server ingestion, using configurable retention. Run explicitly from `backend/` with DATABASE_URL set:

```bash
.venv/bin/python -m app.telemetry_maintenance --delete-expired
```

This deletes only expired telemetry sessions and cascades their events/checkpoints/receipts/staging. Workspace data is not deleted. Schedule this command operationally later; no hidden scheduler is installed. Browser copies are not automatically pruned, including acknowledged ones; unsent records are never age-deleted. Explicit browser data clearing remains possible and can destroy unuploaded history.

Development cookie identities are not CMS authentication. Before production: real accounts/recovery, authorization policy for researchers/jury, TLS, deployment consent/retention policy, rate limiting/streaming ingress bounds, operational maintenance scheduling, storage monitoring, worker-based hashing/large-workspace optimization, real OS/IME matrix and sustained performance testing. A crash before the 16 ms buffered write commits can lose observations; no browser-only design can promise capture after OS/process death or deliberate storage clearing. Phase 4 execution can emit the existing typed run contracts only after real workers exist; debugging and the history timeline remain later phases.
