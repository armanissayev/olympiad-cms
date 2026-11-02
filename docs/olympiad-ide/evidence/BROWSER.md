# Production browser baseline — 2026-11-02

Source: `/Users/isaevarman/Developer/olympiad-ide`, no source changes made.

## Observed result

`13 passed, 1 skipped (45.9s)`; exit status 0. Chromium 133.0.6943.16 from the existing Playwright cache, fresh browser contexts. No remote worker, AWS connection, existing database, browser profile, or existing `test-results/` directory was used.

The skipped test is `e2e/execution.spec.ts:87`, `real Linux worker produces measured output and custom-test verdicts`. `REAL_LINUX_WORKER` and `RUN_LINUX_SANDBOX_TESTS` were explicitly unset. The skip is not a pass.

Passed scenarios:

- `e2e/execution.spec.ts:5`: configuration, exact live source, stdin, durable queued job, reload and real queued cancellation.
- `e2e/execution.spec.ts:37`: saved test CRUD, duplication, exact expectations and one-snapshot Run All admission.
- `e2e/execution.spec.ts:65`: lost execution acknowledgement retries the identical durable job without duplicate admission.
- `e2e/persistence.spec.ts:20`: files, shared split state, exact text, offline queue and reconnect survive reload.
- `e2e/persistence.spec.ts:51`: two browser tabs preserve concurrent work and recovered copy.
- `e2e/persistence.spec.ts:77`: explicit server conflict resolution preserves chosen branch.
- `e2e/persistence.spec.ts:102`: reload after server commit safely replays operation.
- `e2e/persistence.spec.ts:127`: storage failure remains visible and work exportable.
- `e2e/persistence.spec.ts:140`: independent cursor positions survive tab/split reload.
- `e2e/persistence.spec.ts:164`: production app shell reloads with entire network offline.
- `e2e/telemetry.spec.ts:27`: real Monaco input and shared split replay exactly.
- `e2e/telemetry.spec.ts:95`: offline reload/lost acknowledgement retain immutable telemetry without duplicates.
- `e2e/telemetry.spec.ts:126`: telemetry storage failures visible; unrelated form typing excluded.

## Isolation and exact commands

The backend auditor created a fresh local PostgreSQL 14.15 cluster at `127.0.0.1:55449`, under `/private/tmp/olympiad-cms-audit-pg.EFIZ9Y`. This browser audit used its own new database. Local TCP/listening restrictions required sandbox escalation; automatic approval allowed these explicitly isolated test operations.

```sh
/opt/homebrew/opt/postgresql@14/bin/createdb -h 127.0.0.1 -p 55449 -U isaevarman olympiad_browser_baseline_jxyvxq

# From /Users/isaevarman/Developer/olympiad-ide/backend:
DATABASE_URL='postgresql+psycopg://isaevarman@127.0.0.1:55449/olympiad_browser_baseline_jxyvxq' .venv/bin/alembic upgrade head
DATABASE_URL='postgresql+psycopg://isaevarman@127.0.0.1:55449/olympiad_browser_baseline_jxyvxq' ALLOWED_ORIGINS='http://127.0.0.1:14173' .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 18000

# From /Users/isaevarman/Developer/olympiad-ide:
node /private/tmp/olympiad-browser-baseline.JXYvxQ/preview.mjs
curl --fail --silent http://127.0.0.1:14173/api/v1/health
env -u REAL_LINUX_WORKER -u RUN_LINUX_SANDBOX_TESTS E2E_PRODUCTION=1 E2E_BASE_URL=http://127.0.0.1:14173 PLAYWRIGHT_CHROMIUM_PATH='/Users/isaevarman/Library/Caches/ms-playwright/chromium-1155/chrome-mac/Chromium.app/Contents/MacOS/Chromium' npm run test:e2e -- --output=/private/tmp/olympiad-browser-baseline.JXYvxQ/results --reporter=line
```

The health check returned `{"service":"olympiad-ide-api","status":"ok","version":"0.2.0"}`. The existing built `dist/` was served using this temporary `preview.mjs`:

```js
import { preview } from '/Users/isaevarman/Developer/olympiad-ide/node_modules/vite/dist/node/index.js';
const server = await preview({
  configFile: false,
  root: '/Users/isaevarman/Developer/olympiad-ide',
  preview: {
    host: '127.0.0.1', port: 14173, strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:18000' },
  },
});
server.printUrls();
console.log('Isolated preview proxy: /api => http://127.0.0.1:18000');
```

`configFile: false` deliberately excluded the repository's default `:8000` proxy, which could otherwise connect to an existing AWS tunnel. Both test ports were unused before launch. No request to `:8000` was made.

## Cleanup

Stopped only the two processes created by this audit using their tool-owned sessions. Uvicorn reported graceful shutdown; preview exited on SIGINT. Confirmed no listener remained on `18000` or `14173`. Removed only this audit's newly created database:

```sh
/opt/homebrew/opt/postgresql@14/bin/dropdb -h 127.0.0.1 -p 55449 -U isaevarman olympiad_browser_baseline_jxyvxq
```

Notified backend auditor that it could stop its cluster. Temporary preview script and Playwright result metadata remain under `/private/tmp/olympiad-browser-baseline.JXYvxQ`.

## Verification boundary

This is the existing IDE at its production root path, with its actual development-cookie API and isolated PostgreSQL. It verifies custom-execution admission/control-plane behavior, not compilation or official judging. The source still hardcodes root `/api/v1`, `/sw.js`, and root service-worker behavior. No CMS checkout was available, so CMS authentication, native lifecycle, official submissions/feedback, account/contest isolation, CMS production subpath and 300–350-participant capacity remain untested. No false successful execution or mocked worker output was substituted.
