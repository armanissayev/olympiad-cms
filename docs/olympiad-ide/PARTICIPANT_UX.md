# Participant interface and task switching

Updated 3 November 2026. This follow-up simplifies the CMS participant workbench. The standalone IDE retains its history and recording diagnostics views. No stored source, recordings, legacy configurations or submission intents are deleted to hide participant controls.

## Participant changes

- History is removed from the CMS activity bar. A saved `activeView: history` renders Explorer instead of opening replay.
- The recording indicator is a quiet disclosure: **Editor activity recorded**. Participants do not receive the recording diagnostics dialog, session identifiers, raw backend errors or recording export controls. Code-history review belongs in the separately authorized CMS Admin interface.
- A green **Submit** box sits at the right of the contest header. Its panel contains Problem, File and Submit solution. The CMS language is inferred from the selected file and the permitted language/profile mapping; a language selector appears when inference is unavailable. Multi-file submission contracts retain one file selector per required filename.
- Source hashes, recording comparisons, migration tools and detailed intent bookkeeping are removed from the submission form. Submission receipt/result messages and permitted compiler diagnostics remain. Recent results are concise; the ordinary CMS submissions page remains available.
- Changing a problem uses the current browser document and React root. It opens no tab or window and does not reload the page. Each problem retains its own source, STDIN, workspace identity and persisted editing state.

Simplification does not change CMS task, phase, language or participant authorization. Submit still captures exact live source, saves an immutable local intent before the POST, verifies the receipt against the captured bytes, and reconciles uncertain outcomes before retrying that same intent. An unresolved submission prevents a second new intent until it is checked. A receipt means CMS received the source; only CMS result status establishes judging.

## Task-scope handoff

`frontend/src/cms/taskWorkspace.ts` coordinates the transition:

1. Block editing/actions during the handoff and unmount the old editor while retaining the surrounding workbench shell.
2. Prepare the target's separate IndexedDB using its CMS installation/principal/task name. This is a local preflight; it does not change HTTP authority.
3. Stop the old debugger and require confirmation. Request cancellation of the old custom run.
4. Suspend and drain old persistence, resource, execution, telemetry upload and official receipt work before changing task headers. Failed source/resource writes keep the current task open for recovery.
5. Complete and flush the old recording. Recheck the current CMS identity/availability before binding the new scope.
6. Bind new controller instances to the target database, restore its workspace, load its breakpoints and start its recording. Background synchronization starts after local initialization succeeds.
7. Close the old database only after the new local scope is ready. Retain both databases on a failed handoff. Restore the previous workspace/controllers. If the old problem has been removed from the authorized roster, restore only its local recovery locator and pause remote operations; never restore task membership or change the principal.

Controllers are replaced through live module bindings, rather than changing a database underneath in-flight operations. Old upload requests therefore keep their original task authority and database. Official submission capture/reconciliation also captures its database reference; a delayed receipt cannot write into the newly selected problem. The handoff drains those receipt writes before closing the old database.

The editor model registry is cleared between scopes. The editor remounts against the restored workspace identity; breakpoints and recording sessions are loaded for that scope. Stopped controllers do not continue timers after replacement. Local writes remain independent of server availability.

## Executed local verification

Node 24.22.1, existing frontend dependencies, fake IndexedDB transactions and React DOM fixtures:

```sh
cd olympiad_ide/frontend
npm test
npm run typecheck
npm run lint
python3.12 ../../tools/build_olympiad_ide.py --skip-install
```

The complete frontend suite passed **130 tests in 17 files**. Typecheck and lint passed. The optional native frontend build staged all **13 public assets**. Focused tests overlap that total; they are not additional executions to add to it.

New coverage includes:

- Same-document task changes and return trips preserving separate source, STDIN and workspace IDs.
- Old HTTP upload completion before task authority changes.
- Target storage failure, failed handoff rollback, old-task removal during rollback without remote authority, and unconfirmed debugger Stop.
- A failed legacy resource write remaining in memory despite a later successful preference write; task suspension refuses until that resource is saved.
- Delayed official receipts writing to the original task database.
- A simple form, inferred C++/Python language, durable intent before POST, captured source unaffected by later edits and duplicate-click protection.
- Hidden participant History, persisted-history fallback and recording diagnostics/error suppression.

Local outputs are `/private/tmp/cms-participant-full-tests.log`, `/private/tmp/cms-participant-final-typecheck.log`, `/private/tmp/cms-participant-final-lint.log` and `/private/tmp/cms-participant-final-build.log`. They contain unit/build evidence, not claims of real Linux execution.

## Verification boundary

The owning deployment report records the actual source commit, Linux results and public-browser acceptance. Those checks were pending when this architecture note was written. No new database migration, service ownership arrangement or interpreter environment is required by these frontend changes.

History access controls must be enforced by the CMS Admin/native gateway and private runtime, not merely by hiding a button. The participant's own browser profile can inspect its existing IndexedDB; hiding UI cannot make browser-owned historical bytes unreadable. Data is preserved rather than erased. A participant recording remains an observation with disclosed gaps and integrity limits, not proof that browser telemetry is complete or honest.
