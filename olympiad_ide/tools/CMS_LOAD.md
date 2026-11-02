# Progressive native CMS load harness

`cms_load.py` exercises the real CWS password-login flow and native APIs over verified HTTPS. It does not access databases, start services/workers, execute participant code locally, alter contest clocks, or simulate successful responses. Use only generated users and source in an explicitly disposable contest. The separate `execution_load.py` is the retained standalone-development workload and does not authenticate to native CMS.

Run with the CMS environment's `requests` dependency (or a separate Python3.12 environment with requests). CLI validation needs no running services:

```sh
python olympiad_ide/tools/cms_load.py --help
python olympiad_ide/tools/cms_load.py \
  --target /absolute/private/target.json \
  --credentials /absolute/private/credentials.json \
  --plan /absolute/private/plan.json \
  --confirm-disposable TARGET_UUID \
  --report /absolute/private/validation.json --validate-only
```

These paths are examples to replace with files that you prepare; they are not installed fixtures. Inputs must be outside the repository. Credentials must have mode0600 or0400. `--confirm-disposable` must equal the target manifest's UUID. Reports are newly created mode0600 and never overwrite an existing file. Omit `--validate-only` to issue requests. Add `--allow-official-submissions` for any official POST, `--allow-custom-runs` for custom-run POST, and a separate `--allow-remote-disposable` for non-loopback hosts. Never use an existing/live contest or production credentials. The custom-run flag does not relax the server's approved-worker gate.

A target manifest:

```json
{
  "schemaVersion": 1,
  "disposable": true,
  "targetId": "GENERATED_CANONICAL_UUID",
  "origin": "https://localhost:18443",
  "installationId": "ACTUAL_DISPOSABLE_INSTALLATION_UUID",
  "contestId": 1,
  "contestName": "ide-load-example",
  "cwsBasePath": "/",
  "caBundle": "/absolute/private/test-ca.crt",
  "serverHardware": null,
  "toolchains": null,
  "testSuiteCost": null
}
```

Use actual values; placeholders fail validation. Contest name must start `ide-load-` or be the native fixture's `ide-smoke`. `caBundle` may be omitted to use the normal trust store; there is no insecure TLS switch. Supply measured server hardware/toolchains and a description of custom-run/official-test cost when available. A supplied metadata label is not a measurement by this tool.

Credentials are an external JSON array of distinct generated participants:

```json
[
  {
    "username": "GENERATED_DISPOSABLE_USERNAME",
    "password": "GENERATED_DISPOSABLE_PASSWORD",
    "taskId": 1,
    "variables": {"cmsLanguage": "C++17 / g++", "source": "int main(){return 0;}\n"}
  }
]
```

The harness GETs the CWS root to obtain its XSRF cookie, POSTs `username,password,_xsrf` to `login`, then verifies `/ide/api/context` against the target's installation/contest/name and the expected username/task. All subsequent requests send that authenticated context's `X-Olympiad-Principal`, `X-XSRFToken`, and `X-Olympiad-Task`. Identity changes stop that actor. Actors have separate cookie jars; duplicate usernames are rejected so sessions are not misreported as distinct participants.

A small read-only plan:

```json
{
  "schemaVersion": 1,
  "scenarios": [
    {"name":"login_burst","participants":1,"iterations":2,"concurrency":1,"ratePerSecond":2,"rampSeconds":0,"durationSeconds":15,"timeoutSeconds":3},
    {"name":"context_read","participants":1,"iterations":5,"concurrency":1,"ratePerSecond":2,"rampSeconds":0,"durationSeconds":15,"timeoutSeconds":3}
  ]
}
```

`login_burst` opens a new cookie jar for each iteration, including a context verification; one operation comprises three HTTP requests. `context_read` reuses the authenticated jar. A later stage can increase participants, concurrency, arrival rate, ramp and iterations. Each scenario executes in order. The rate is a global HTTP request rate for that scenario, including authentication and setup, not a per-participant rate. Ramp assigns participant start offsets; executor concurrency bounds active actors. Duration stops scheduling, and in-flight HTTP uses bounded connect/read timeouts and response-size checks. It is not a distributed wall-clock deadline guarantee against a noncooperative server.

Limits:1–350 distinct participants, concurrency at most participant count,1–10000 iterations,0.01–1000 HTTP requests/s, scenario duration1–3600s, ramp0–600s and no longer than duration, timeout0.1–30s, at most30 scenarios, at most100000 planned HTTP requests and4 hours of configured duration. These are safety bounds, not capacity targets.

## Fixture-driven workloads

Names `autosave`, `telemetry`, `custom_runs`, `official_submissions`, and `final_minutes` require `requestsFile` in the scenario. The external JSON fixture contains `schemaVersion:1`, optional `actorIds`, optional ordered `setup`, and nonempty ordered `steps`. Setup runs once per actor per fixture path. Each iteration executes the steps in sequence. Route families are restricted to native workspace, telemetry, execution and official participant endpoints; arbitrary URLs, traversal, admin and CMS RPC routes are rejected. Scenario names restrict their allowed route families; `final_minutes` permits their deliberate mixture.

Request fields are `method,path,json?,expect?,assert?,capture?,newIds?`. `expect` is an array of HTTP statuses, default `[200]`. `assert` maps dotted JSON response paths to exact expected values. `capture` maps a new variable name to a dotted response path. `newIds` generates UUIDs immediately before that request; `actorIds` generates stable per-actor UUIDs once. Whole-string `{{variable}}` preserves the variable's JSON type, while embedded placeholders become strings. Paths percent-encode substituted values. Available variables include `taskId`, `principalId`, zero-based `participantIndex` and `iteration`, plus external credential variables, generated IDs and response captures. Authority variables cannot be overwritten. Unrecognized variables fail the actor, and source strings retain their exact JSON text.

A valid empty-workspace/autosave fixture, using actual server revision captures:

```json
{
  "schemaVersion":1,
  "actorIds":["workspaceId"],
  "setup":[
    {"method":"POST","path":"/ide/api/runtime/v1/workspaces","expect":[201],
     "json":{"id":"{{workspaceId}}","document":{"name":"Disposable load workspace","nodes":{},"settings":{},"editorState":{}}},
     "capture":{"revision":"revision"}}
  ],
  "steps":[
    {"method":"PATCH","path":"/ide/api/runtime/v1/workspaces/{{workspaceId}}","expect":[200],"newIds":["operationId"],
     "json":{"operationId":"{{operationId}}","baseRevision":"{{revision}}","document":{"name":"Disposable load workspace","nodes":{},"settings":{},"editorState":{}}},
     "capture":{"revision":"revision"}}
  ]
}
```

An official-submission request step (complete it with actual task source mapping and source variables, and include stable `workspaceId,fileId` in `actorIds`):

```json
{
  "method":"POST","path":"/ide/api/submissions","expect":[201],
  "newIds":["intentId","snapshotId"],
  "json":{"schemaVersion":1,"intentId":"{{intentId}}","snapshotId":"{{snapshotId}}","workspaceId":"{{workspaceId}}","taskId":"{{taskId}}","language":"{{cmsLanguage}}","telemetry":null,
          "files":[{"filename":"main.%l","sourceFilename":"main.cpp","fileId":"{{fileId}}","content":"{{source}}"}]},
  "assert":{"state":"admitted","intentId":"{{intentId}}"},
  "capture":{"submissionId":"submissionId"}
}
```

Subsequent bounded feedback steps can GET `/ide/api/submissions/status/{{submissionId}}?taskId={{taskId}}`. Admission is not successful judging. No official request is automatically retried; transport errors,5xx and unusable success responses are counted as unknown outcomes. Stop and reconcile the exact original intent through the real receipt endpoint before deciding what to do next. Save external fixture-generated IDs separately if running official fault scenarios; this harness reports aggregate data and does not act as a durable official-intent journal. For loss/retry acceptance use the native resilience tests and browser intent journal, not this load driver.

Telemetry fixtures must contain valid actual Phase3 session/checkpoint/event envelopes, contiguous sequences and canonical digests. Custom-run fixtures must contain valid actual Phase4 immutable source/configuration/test payloads and source hash. The harness intentionally does not invent protocol content or replace missing digests. You can supply a whole precomputed body as `"json":"{{telemetryBody}}"` using per-participant external variables, or supply ordered valid request bodies. Repeated unchanged batches/jobs measure idempotent replay, not fresh telemetry or compilation; document that distinction. Do not claim telemetry ingestion/custom execution coverage unless the real responses and required result assertions passed.

`final_minutes` is a workload label for interleaving valid autosave, telemetry, custom-run, official-submission and feedback steps. Run it against a genuinely configured disposable deadline; the harness never modifies contest times or bypasses policy. Existing CMS count/interval rules remain effective and rejection statuses remain visible.

## Evidence and interpretation

Each executed scenario reports actual operation and HTTP p50/p95/p99/max latency, statuses/error counts, attempted/failed operations, achieved throughput, response bytes, participants with HTTP activity, duration-limit status and unknown official outcomes. Authentication and setup HTTP are included; operation latency covers the requested iteration including client rate-limit pacing; HTTP latency excludes that pacing. `queueAgeSeconds`, `databaseConnections`, `storageGrowthBytes`, server CPU/memory are null because this tool does not measure them. Collect those independently using authorized test-host/database observers and preserve their timestamps. Runner OS/machine/Python/CPU count is measured locally. Credentials, cookie/header values, source/request/response bodies and usernames never enter the report.

An expected4xx remains in `httpErrors` as `expected_http_STATUS`; choosing it as an expected contract does not turn a rejected submission into success. A nonzero exit indicates failed operations; validation failures exit2. `validation_only` reports contain no scenario measurements. Neither validation nor tiny localhost traffic establishes350-participant capacity. Run progressive isolated10/50/100/200/300/350 participant stages only after lower stages and real worker/judging safety are established, with measured arrival rates, queues, DB pools/storage and representative test costs. Do not interpret350 active editors as350 simultaneous compilations.
