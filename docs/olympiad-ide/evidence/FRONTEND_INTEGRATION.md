# Native CMS frontend implementation and verification

Historical local-phase evidence. Later authorized Linux results, including the idle-connection correction and real judging, are recorded in [LINUX_ACCEPTANCE](../LINUX_ACCEPTANCE.md).
Date: 2026-11-02. Target: `/Users/isaevarman/Developer/cms/olympiad_ide/frontend`. Original `/Users/isaevarman/Developer/olympiad-ide` was not edited. Root owns Git provenance, source import, native service, runtime and CMS database implementation.

## Implemented

- `src/cms/types.ts`, `session.ts`: versioned bootstrap/intent/receipt contracts; authenticated bootstrap before editor/storage/controller initialization; stable principal and task scope; expected principal/task headers and CMS CSRF; pause after expiry/identity changes; same-tab offline recovery without server authority; cached recovery metadata contains no CSRF token. Reopening selects the current authenticated account's independent IndexedDB. Receipt access remains possible after deadline/task visibility ends; private runtime access requires currently authorized task scope.
- `src/main.tsx`, `boot.tsx`, `persistence/database.ts`, `controller.ts`, `api.ts`: deferred startup, principal/installation/task database partition, additive Dexie v5 official-intent store, no automatic legacy adoption, and runtime route/header adaptation while preserving the existing journals. Existing v1/v2 migration tests now expect v5 and check the new intent store is empty while original data survives.
- `src/cms/CMSWorkbench.tsx`, `cms.css`, `App.tsx`: compact participant/contest/task/phase/countdown strip; same-origin authorized statement/attachment and ordinary CWS links; task workspace switch with local flush; exact CMS language/file mapping; reviewable immutable source confirmation; pending/unknown/rejected/admitted labels; local intent reconciliation and paginated official history; shared CMS status and scores plus inert compilation/details text; CWS tokens/download/clarification fallback. Real CWS logout is a CSRF POST after local flush. Existing VS Code-style editor and layout remain intact.
- `src/cms/submissions.ts`: live Monaco capture before async work, lossless UTF-8 validation, exact file hashes, durable immutable intent before transmission, duplicate-send deduplication, receipt lookup before uncertain retry, strict receipt/file mapping validation. Identity-change 409 keeps an intent uncertain rather than permanently rejecting it. Reopening the panel performs bounded receipt-only reconciliation and never creates a new submit action. Official submission is independent of autosave, telemetry and custom-worker capacity.
- Source-to-history comparison: the captured boundary is checked against the durable initial checkpoint and replayed local event prefix. Exact selected file-byte hashes yield verified/mismatch/unknown; missing/buffered/interrupted history gives unknown. This diagnostic never blocks Submit and is not a cheating verdict.
- `telemetry/types.ts`, `replayEngine.ts`: compatible passive CMS intent/admission/rejection observations. Original distinct workspace/telemetry/execution journals remain intact. Admission receipt remains authoritative.
- `src/cms/transfer.ts`: bounded source export and dry-run import from old recovery/workspace JSON, strict tree/name/UUID/size validation, UUID preservation where safe, collision remapping, digest-derived recovery folder and durable repeated-import marker. No import claims prior server ownership or silently reassigns legacy telemetry/receipts. Original browser/server data is retained; recording export remains separate.
- `vite.config.ts`, `build/offlineShell.ts`, `persistence/offlineShell.ts`: default production `/ide/` build; dedicated path validation; worker scoped exactly to IDE path; exact static asset cache; no API/login/admin/ranking interception. Monaco workers work on production subpath. CMS-mode custom output uses bounded polling because EventSource cannot send required scope headers; standalone SSE remains.
- `execution/controller.ts`, `resources.ts`, toolbar/bottom panel: task-aware custom Run gate, zero-worker disabled Run with explicit explanation, flush on task switch. Stop remains custom-only. Original standalone queued-without-worker behavior remains for its control-plane tests.
- `.nvmrc`, frontend `README.md`, `tools/verify-native-browser.cjs`: reproducible supported Node setup, independent optional frontend build, detailed data/auth scope notes, and portable real native browser acceptance harness.

## Fresh local verification

Runtime: bundled Node **24.19.0**, npm **10.9.2**, Vite **6.4.4**, Vitest **4.1.12**, TypeScript **5.7.3**. `/opt/homebrew/opt/node@22` was discovered to be a stale alias to Node23; it was not treated as a supported Node22 verification. Final commands prepend `/Users/isaevarman/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin` to PATH.

- Plain `npm ci --no-audit --cache /private/tmp/olympiad-npm-cache`: passed with lifecycle scripts and normal peer validation. No `--legacy-peer-deps`, lockfile update or broad dependency upgrade. One existing eslint9 package deprecation notice; no vulnerability-scan claim.
- `npm run typecheck`: passed.
- `npm run lint`: passed with zero allowed warnings.
- `npm test`: **81 passed in 10 files** (63 preserved +18 additions), final run 1.38 s.
- `npm run build`: passed. Existing large Monaco/xterm chunk advisory remains.
- `python3 tools/build_olympiad_ide.py --skip-install`: passed; **13 public assets** safely staged in `cms/server/olympiadide/static/` for packaging. Final staged application bundle `boot-BemkXN87.js`, root bundle `index-CMP1IjdL.js`. Root's builder owns asset manifest validation and packaging.

New tests cover scoped identity/task headers, account-switch pause, offline recovery versus explicit denial, post-deadline local task recovery/receipt access, link-scheme/origin rejection, exact source capture, invalid Unicode/file-language mapping, immutable intent reuse, concurrent sends, lost acknowledgement, receipt hash mismatch, receipt-only404, cross-principal replay refusal, validated import collisions/traversal, durable telemetry match/mismatch/missing history, identity-change409 recovery, and service worker exclusion of every protected route category.

## Preserved real production browser suite

Separate standalone build created in `/private/tmp/olympiad-standalone-dist` with `VITE_CMS_MODE=false`; native `dist/` was retained. A dedicated disposable PostgreSQL database `idebrowser` in the task-owned cluster at127.0.0.1:55459 was migrated with imported backend Alembic. Imported FastAPI ran development auth on18001; temporary production static/proxy fixture on4179. No CMS live database or AWS touched.

Command:

```sh
E2E_PRODUCTION=1 E2E_BASE_URL=http://127.0.0.1:4179 \
PLAYWRIGHT_CHROMIUM_PATH='/Users/isaevarman/Library/Caches/ms-playwright/chromium-1155/chrome-mac/Chromium.app/Contents/MacOS/Chromium' \
npm run test:e2e
```

Observed **13 passed, one explicit real-Linux-worker skip**,45.6s. Covers exact editing/reload, independent split state, offline full reload, same-browser/server conflict handling, workspace acknowledgement loss, storage export, real Monaco Unicode/paste/multicursor replay, telemetry retry, custom run snapshot/configuration/test resources, Run All queued contract, queued cancellation and custom-job acknowledgement loss. No compiler or sandbox execution claimed. Both temporary services were stopped after testing; their disposable DB remains in root's temporary cluster until root cleanup.

## Real native browser acceptance

Used the native agent's generated loopback HTTPS ingress and disposable test certificate, CMS+CWS services launched through ResourceService, real private runtime and actual PostgreSQL admission tables. Chromium trusted only the generated certificate's SPKI. Lost-response transport trusted that same test CA in the child Node process only; no user/OS trust was changed.

Observed success with **zero browser page errors**:

1. Real CMS login, native context, full Monaco workbench and correct geometry.
2. Custom Run disabled without approved workers while official submission stays available.
3. C++ capture from live editor, subsequent edit, real native POST201; receipt and request bytes matched the original capture's SHA-256 exactly.
4. Python real native admission followed by deliberately dropped HTTP acknowledgement; reload reconciled the committed receipt, with **one POST**.
5. Real participant submission history displayed, including ordinary CWS fallback submissions with absent IDE correlation.
6. Actual `/ide/` service-worker scope, static cache entries only, entire-connection-offline reload including Monaco worker, retained source, and subsequent authentication recovery.
7. Real CSRF-protected CWS POST logout denied later IDE bootstrap while retaining scoped local IndexedDB.

Evidence: `/private/tmp/cms-native-browser-results.json`, `/private/tmp/cms-native-submit.png`, `/private/tmp/cms-native-editor.png`. No passwords/cookies appear in the results. Native fixture owner was signaled done and owns cleanup.

The successful ad hoc script's core verification is retained in portable `frontend/tools/verify-native-browser.cjs`; its parameterized wrapper was syntax-checked. Re-run it using a newly generated disposable native browser-handoff fixture, with a Chromium executable installed or `PLAYWRIGHT_CHROMIUM_PATH` set. The last later production changes were only clearer zero-worker copy and wrapping long opaque IDs; final lint/tests/build passed after those changes.

## Honest limits

- This establishes actual native authenticated admission, source integrity and browser recovery, **not actual CMS judging or official scores**. Fixture submissions remained in CMS's real pending/compiling status. No Linux worker or isolate execution was run.
- No350-participant load evidence, native task-switch browser scenario with multiple tasks, real multi-account shared-browser native scenario, or full cross-origin historical-journal migration was measured here. Unit tests cover principal/task partition boundaries and source import safety; native authorization tests belong to the other agents.
- Source import does not migrate or relabel legacy telemetry, execution receipts or server ownership. They remain retained in the original source storage, with explicit export/adoption workflows documented. No automatic destructive browser/database migration.
- Telemetry replay verification is an integrity check over the available durable prefix, not tamper-proof evidence or proof of complete event capture.
- Actual toolchain version equivalence remains explicitly unverified in the UI; custom and CMS compilers remain independent.
