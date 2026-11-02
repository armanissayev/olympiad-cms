# Native CMS frontend

This imported frontend preserves the original Olympiad workbench. Its default build targets the native CMS service at `/ide/`; it is not an iframe or a standalone public API client. The native service supplies participant context and gates all private-runtime traffic.

Use Node 24 (tested with 24.19.0) and the included lockfile:

```sh
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

No peer-dependency bypass is required. The ordinary CMS Python install does not invoke these commands. Install the resulting `dist/` using the CMS deployment instructions. The production service does not start Vite. For standalone IDE development/tests only, use `VITE_CMS_MODE=false npm run dev` or `VITE_CMS_MODE=false npm run build`. A configurable `VITE_IDE_BASE` must be a dedicated absolute directory path and must match native service routing; `/ide/` is the supported deployment path.

The same-origin API routes are `/ide/api/context`, `/ide/api/submissions`, and `/ide/api/runtime/v1/...`. CSRF and expected principal/task headers come from authenticated CMS context; browser headers do not grant authority. Only the native service can assert identity to the private runtime. The frontend never receives private runtime credentials.

CMS bootstrap completes before opening a database or starting uploaders. Each installation/principal/task uses a separate IndexedDB database. A server-detected account switch pauses every upload and retains the old local queue. Reopening after signing in selects the new principal's storage. An offline reload can reopen only the current tab's cached recovery scope, with all server operations paused. CSRF tokens are not persisted. A task change flushes local workspace/resources/telemetry, stops controllers and reloads the newly selected task scope. No old standalone workspace is automatically adopted by a CMS account.

The Submit panel selects the exact CMS language and one source per required CMS filename, captures live Monaco text before asynchronous work, validates lossless UTF-8, hashes each file and shows an immutable source confirmation. Confirm persists the intent before transport. Pending/unknown/rejected/admitted remain separate from CMS judging status. A retry first checks the authenticated intent receipt and retains the original body even after subsequent edits. Only a matching CMS receipt marks admission. The captured files are separately compared against reconstruction of the durable local telemetry prefix at the captured boundary: verified, mismatch or unknown. Buffered/missing/interrupted history reports unknown and never blocks Submit; this is an integrity diagnostic, not a cheating verdict. Receipt lookup is available after task visibility ends. Native CMS admission remains authoritative for timing and policy.

The panel displays participant-safe CMS status and scores. It links to existing CMS task-specific feedback, tokens, source downloads, statements, announcements and clarifications. All links are restricted to the current origin. React renders compiler output as text. History refresh has a bounded interval/backoff and continues refreshing completed results for rejudging. Native history remains subject to CMS phase gates. Custom Run uses the private IDE worker and is disabled when no approved capacity or supported task harness is available. Custom Stop only cancels an IDE job. CMS-mode custom output uses bounded polling because EventSource cannot send the required scope headers.

The service worker is scoped to `/ide/`, precaches only exact build assets and recovers only `/ide/` or `/ide/index.html`. It cannot intercept CMS login/admin/ranking, official submissions or runtime APIs. It does not cache authenticated API responses or participant source.

## Moving existing source

Export from the old browser origin with the existing recovery export. At the CMS origin use “Inspect source import,” review file/byte/collision counts, then confirm. The import accepts bounded JSON source trees, rejects invalid identities/names/cycles, preserves file UUIDs when safe, remaps collisions and adds a recovery folder. The digest-derived folder and an import receipt prevent duplicate import after a crash/retry. Imported source is a copy owned by the current authenticated scope; it does not claim old server ownership or reassign telemetry/history. Existing original IndexedDB and server records remain intact. Export and retain telemetry separately using the existing recording export. Proof-based legacy server adoption is an explicit backend migration operation, not a browser name match.

## Verification boundary

Unit tests cover snapshot bytes, duplicate intent/retry/response loss, changed-body reuse, account switching, expiry/offline boundaries, source-import validation and worker scope. These tests do not prove real CMS authentication, native admission transaction behavior, official evaluation, Linux execution or deployment capacity. The full native-service/real-PostgreSQL/browser acceptance results belong in `docs/olympiad-ide/VERIFICATION.md`.


A reproducible real native browser verifier is included at `tools/verify-native-browser.cjs`. Start the disposable CMS smoke harness in its browser-handoff mode; pass the generated local fixture JSON, which supplies only disposable credentials and a generated local TLS certificate:

```sh
node tools/verify-native-browser.cjs /private/tmp/cms-native-browser-fixture.json /private/tmp/ide-native-browser-evidence
```

Set `PLAYWRIGHT_CHROMIUM_PATH` only when using an existing Chromium. The script accepts loopback HTTPS fixtures only, pins that fixture's certificate for Chromium, and starts its child Node process with that certificate as its explicit additional CA for lost-response transport tests. It does not alter OS trust, persistent browser profiles or application TLS settings. The test performs real CWS login/logout and native C++/Python admission, preserves immutable source after edits, drops an actual Python admission response then reconciles after reload, verifies history, scoped production offline reload and retained local data, and checks missing-worker Run behavior. It does not claim that CMS Workers compiled or judged those submissions. Output contains receipts and a screenshot; no passwords or session cookies are written to the evidence file.
