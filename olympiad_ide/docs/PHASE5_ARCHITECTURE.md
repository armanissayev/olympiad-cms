# Phase 5 — Editing history replay

The History activity view now reads actual saved recording sessions for the currently opened workspace from its existing IndexedDB. CMS already selects a distinct database for each installation, principal and task. No other browser database is enumerated and no historical ownership is reassigned. The view explicitly says these are recordings saved in this browser; it does not claim cross-device discovery or recover events that are no longer retained.

## Replay model

`frontend/src/history/timeline.ts` is independent of React. `HistoryTimeline.create` takes the original recording session, ordered telemetry events and periodic snapshots. It checks the initial snapshot hash/tree, event IDs, sequence continuity, clock, timestamps and session/workspace scope. It validates recorded checkpoint hashes and compares reachable checkpoint states against reconstructed event history. The existing UTF-16 transaction engine implements edits, undo/redo and workspace/file operations.

Seeking starts from the nearest verified checkpoint, not the beginning. Only checkpoints and source events are retained; the model does not materialize a full workspace after every key event. Returned snapshots are copies, so preview mutations cannot change the stored recording. The frame reports requested/verified sequence, checkpoint origin, replayed event count, recorded active file and exact event. Existing collector checkpoint cadence remains configurable (60 seconds or 500 document-changing events by default), with file creation/execution/manual persistence checkpoints retained.

A missing or invalid event stops reconstruction at the last verified state. A self-consistent later recorded checkpoint can show that recorded later state while all gap/integrity notices remain visible; it does not invent the missing edits or pretend the recording is complete. Invalid checkpoint hashes or disagreement with a reconstructable prefix cause that checkpoint to be rejected. Interrupted reload sessions are disclosed separately from valid visible prefix data. Active-file identity becomes unknown across a sequence gap until another active-file event is recorded.

## Participant controls

The History sidebar provides recording selection, refresh, previous/next event, timeline slider, Play/Pause, 0.5×/1×/2×/4×/8× playback, timestamp, event description, active-file identity, preview-file selector and integrity notices. Large inserts and undo/redo have explicit descriptions. Playback advances dense events by recorded monotonic time rather than delaying every key event by a rendering frame.

Open replay expands a read-only Monaco viewer with a separate `inmemory://olympiad-history/...` model URI. It never joins the live model registry, changes workspace state, attaches live editing telemetry, saves historical text or overwrites current files. The dialog traps focus, supports Escape, and blocks global Run/Debug shortcuts while reviewing history. Closing it restores prior focus. The sidebar preview remains useful without opening the larger viewer.

## Verification

Executed on 3 November 2026 using the existing Node24 frontend runtime:

```sh
npm test -- src/history
npm run typecheck
npm run lint
```

Twelve focused tests passed: ten deterministic timeline checks and two React/real-fake-IndexedDB integration checks. They cover Unicode/large insert/undo/redo, create/rename/move/delete across files, forward/back seek, checkpoint-distance work, initial and periodic hash consistency, missing tail/intermediate events, recovery only at a recorded checkpoint, stale active-file identity after gaps, invalid scope/clock/duplicate IDs, dense time-based advancement, actual saved-recording UI selection and read-only live/storage boundaries. Typecheck and lint passed after integration with the current debugger sources. These unit/DOM checks are not claimed as a deployed browser acceptance run; root deployment evidence records that separately.
