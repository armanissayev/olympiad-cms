# Administrator-only code history

The CMS Admin contest sidebar has **Code history**. The authorized staging entry point is **https://54.206.171.67/admin/contest/1/ide-history**, without an SSH tunnel; Admin home is **https://54.206.171.67/admin/**. Sign in with an enabled full-permission CMS administrator account. The optional private localhost port 28444 tunnel remains available. Public HTTPS authentication/denial/source-replay acceptance passed on **4 November 2026** for the earlier recording-oriented viewer; see [public HTTPS evidence](PUBLIC_ADMIN_HTTPS.md).

The submitted-file workflow below was implemented on **5 November 2026**. Its final deployment status and current Linux/browser evidence belong to [FILE_HISTORY_ACCEPTANCE](FILE_HISTORY_ACCEPTANCE.md); the historical results below do not certify this new viewer.

## Choose the submitted file

Choose a participant and problem. The file list loads automatically from actual CMS submissions, showing the source filename, submission number, time and language. Select a submitted file to open its writing timeline. Repeated submissions remain separate selectable versions. **Refresh files** updates the list; **Load older submissions** pages backward. A page covers at most 50 submissions and 200 files, keeping ordinary multi-file submissions together. If a single submission exceeds the bounded file view, its normal CMS submission page remains available and the omission is disclosed.

An IDE submission uses the exact receipt's workspace, file UUID, recording boundary and submitted-byte hash. The viewer does not ask the administrator to find a recording UUID or manually match a file. Standard CWS submissions and files without a valid IDE capture link still appear, with **History unavailable** and a link to the normal CMS submission. No history is guessed from a similar filename or timestamp. A valid capture link cannot recover browser-only, expired or missing uploaded data.

## Review writing periods

The timeline groups occupied editing periods into **5-second intervals** by default, with 1/5/10/30-second choices. Source transactions, recorded paste/copy cues and explicit creation/recovery context remain useful review points. Cursor movement, focus, key releases, navigation and execution events do not become individual timeline steps. Initial recorded states and the immutable submission snapshot are explicit boundaries.

Use the activity overview or slider, **Previous period**/**Next period**, and **Play/Pause** at 0.5/1/2/4/8× speed. **Skip waiting time** avoids watching long idle gaps; disabling it uses recorded spacing with a bounded playback delay. **Compare previous period** shows read-only before/after source. **Marked periods only** keeps review cues and boundary snapshots; clicking a review marker seeks to its period. The viewer clears previous source immediately when the participant, problem, submitted file or replay request changes, and fences delayed requests/playback continuations.

Each browser refresh/recording is a separate editing session, ordered by server registration. Sessions are not presented as uninterrupted writing. The captured session stops at the receipt's exact sequence. Earlier sessions are restricted to the same authorized workspace/file and stop before the first event uploaded after submission. This conservative cutoff may exclude earlier offline edits uploaded later; the viewer explains that limitation. Only retained uploaded data can be reviewed from another device.

## Review markers and their limits

Markers prioritize human inspection; they are **not plagiarism findings**, proof of authorship, or an automatic basis for sanctions. The interface calls them review cues and displays the rules. Inserted editor text, including pasted text, is already recorded. Raw clipboard contents outside the editor, OS-wide keys, other applications and paste-source websites/apps are not collected. A paste is labeled **source unknown**; the system cannot classify its source as trusted or untrusted.

| Cue | Current rule and meaning |
| --- | --- |
| Paste · source unknown | A recorded Monaco paste action, correlated with its source transaction when available. A large insertion alone never proves paste. |
| Copy shortcut | Recorded Ctrl/Cmd+C without Alt/Shift. It identifies a shortcut, not a confirmed clipboard transfer or destination. |
| Large insertion | At least 200 UTF-16 code units inserted in one ordinary editor transaction. Completion, formatting and legitimate paste can explain it. |
| Rapid source growth | At least 1000 inserted UTF-16 code units across two or more ordinary editor transactions within 10 seconds. It is a descriptive volume cue, not an inference about source or authorship. |
| Long pause | At least 120 seconds between ordinary source edits within one recording. Thinking, reading or working elsewhere may explain it. |
| Slow recorded editing | Fewer than 20 inserted UTF-16 code units/minute across at least 300 elapsed seconds and 10 keyboard-linked edits. Elapsed time includes pauses. Linked observed paste transactions, undo/redo and generated changes are excluded from this rate. |
| Creation/recovery or generated-change context | Explicit file creation/import/restored state, undo/redo or programmatic change. These are labeled as context and are not inferred typing or paste. Undo/redo and programmatic changes are excluded from large/rapid/slow writing cues. |

Counts follow Monaco's **UTF-16 code units**, so a non-BMP character may count as two units. The displayed key-linked-edit total counts source transactions linked to recorded key-down events; it is not a count of all physical keystrokes or a measure of effort. Rates and timestamps describe browser observations that the participant can manipulate. Sparse data, accessibility tools, editor completions and ordinary thinking can explain unusual activity. Absence of markers is not an authorship assessment. Current thresholds are descriptive defaults, not statistically validated plagiarism thresholds.

## Authorization boundary

The page and every data request use the real CMS Admin cookie and `permission_all`, check the current contest's Participation and Task, and only then sign the private request. The runtime uses a separate `olympiad-ide-admin-history` audience, `admin-history` scope and a 30-second one-use assertion with administrator ID, exact target installation/participant/contest/task, method/path/query/body hashes and nonce. Forged browser role headers and ordinary participant assertions never authorize this namespace. No administrator role is accepted from client payloads or promoted into participant identity mappings.

The read-only runtime namespace exposes recording list/replay and submitted-file timeline/replay GETs. Native transport accepts only the configured loopback HTTP runtime, disables environment proxies and redirects, uses four independent slots, existing request/response bounds and a non-symlink private signing key. No browser receives the assertion/key or direct database access. Admin sessions are not created as development/participant owners. Existing principals/workspace bindings are checked, not adopted by username.

Submitted-file requests first load the real CMS File through its current Submission, Participation and Task. The native service validates installation/identity scope and the exact immutable receipt manifest. It constructs the workspace/file/capture-session/sequence/hash/submission-time query from that receipt; browser-supplied capture fields never replace it. The signature covers the exact resulting path/query. The runtime rechecks the scoped principal/workspace/task and period boundaries before returning only the selected file, rather than the workspace tree. Missing or malformed links return an explicit unavailable response. No new database table, migration, grant, administrator role or collection permission is introduced.

CMS participant GETs for telemetry event/checkpoint history return 403; writer POSTs and minimal status/acknowledgement/retry endpoints remain available. Standalone development own-history behavior is retained. Participant History/recording diagnostic UI is separately removed by the participant interface update. The browser profile owner still controls their own source/buffers; UI removal does not make client-side recording buffers cryptographically inaccessible to that owner.

## Reconstruction, bounds and integrity

Each seek starts at a retained checkpoint whose tree, content and hash agree. Sequence-count checks detect missing stored events without loading dense cursor/key streams. At most 5,000 source/navigation events are loaded per reconstruction segment; excess work returns an explicit notice and the verified checkpoint, rather than inventing a target state. Corrupt checkpoints/events and known missing prefixes are disclosed. A later independent verified checkpoint can show that checkpoint's recorded state while the gap remains disclosed. Gaps clear inferred active-file identity until new recorded navigation. A corrupt later event cannot cause partial nodes to be mislabeled as an earlier checkpoint.

File analysis covers the captured recording and at most 30 earlier retained periods, with an overall limit of 10,000 relevant rows and 6,000,000 serialized payload bytes. The captured period receives the analysis budget first; remaining periods are displayed in chronological registration order. Truncation and incomplete integrity are disclosed, while the submission boundary is always retained as a review point. Dense key/cursor streams are excluded from analysis queries, unused session replay states are deferred, and checkpoint candidates are streamed rather than all materialized at once.

The submitted-byte badge compares the verified uploaded source at the exact captured boundary with the immutable CMS receipt's SHA-256. A missing prefix, unavailable future sequence, reported gap or failed reconstruction prevents a matched result. A mismatch is an integrity diagnostic, not a cheating verdict. A matching snapshot does not establish who wrote it or prove a continuous history.

Historical source is assigned through textarea.value/textContent, never injected as HTML or executed. Recording data is not edited by review. Hashes check consistency, not authorship or resistance to a malicious database administrator/browser.

## Historical verification through 4 November 2026

The following counts, commands and browser tools describe the earlier recording-oriented viewer. For the submitted-file implementation and final deployment/current evidence, use [FILE_HISTORY_ACCEPTANCE](FILE_HISTORY_ACCEPTANCE.md). No new Linux deployment or test outcome is claimed by these historical entries.

Eight focused real-PostgreSQL runtime tests cover administrator versus participant/development authorization, signed target separation, request binding/replay/expiry, CMS participant history denial, server-only cross-browser reconstruction, nearest checkpoints, gaps/corruption, active-file uncertainty and expired-read exclusion without deletion. Six native CMS WSGI/PostgreSQL tests cover actual admin cookies, enabled/full permission, selectors/read-only rendering, contest membership, separate signing audience, private bounded transport and ordinary disabled-feature startup without optional PyJWT. These are included in full-suite totals and do not by themselves prove the deployed browser UI.

Commands (from their indicated source roots):

```sh
# olympiad_ide/backend; isolated schemas in the task-owned local PostgreSQL database
TEST_DATABASE_URL=postgresql+psycopg://isaevarman@127.0.0.1:55459/ideruntime /private/tmp/olympiad-runtime-venv/bin/python -m pytest tests/test_admin_history.py -vv -p no:cacheprovider
# CMS checkout; separate CMS test database
CMS_CONFIG=/private/tmp/cms-regression.conf /private/tmp/cms-integration-venv/bin/python -m pytest cmstestsuite/unit_tests/server/olympiadide/admin_history_test.py -vv -p no:cacheprovider
# Run only after a separate authorized participant acceptance has uploaded its fixture source.
node olympiad_ide/frontend/tools/verify-admin-history.cjs /private/tmp/cms-linux-staging/ui-acceptance.json /private/tmp/cms-linux-staging/admin-history-final /private/tmp/cms-linux-staging/participant-ui-final/results.json
```

The browser tool is limited to the exact authorized fixture and private localhost ports. It pins only the existing localhost certificate public key for private Admin/CWS; it does not disable public TLS validation. It verifies guest and real participant-cookie denial, an actual admin reading the fresh participant's uploaded source/hash in a separate browser, timeline/Play/Pause, read-only source and no history mutation requests. Deployed results are recorded separately by the owning staging acceptance report; an unexecuted script is not claimed as a pass.

Deployed private-browser acceptance passed: actual guest/participant denial, separate Admin source/hash match, timeline/read-only behavior and actual writing-event before/after reconstruction. [Results and access command](PARTICIPANT_ACCEPTANCE.md).
