# Native integration architecture

## Ownership and processes

The browser loads the production React/Monaco workbench at /ide/ through HTTPS ingress. OlympiadIDEService is a CMS WebService with normal logging, RPC echo/quit, coordinates and ResourceService monitoring. It authenticates through CMS, serves participant context and official APIs, and forwards a bounded allowlist of background operations to the private FastAPI runtime.

CMS owns users, participations, tasks, timing, source storage, official submissions, judging and scores. The IDE database owns workspaces, journals, telemetry, custom resources/jobs and its stable identity mapping. Cross-database identifiers are references; they are not foreign keys or atomic cross-database transactions.

Systemd owns cmsResourceService; ResourceService owns native/CWS and other configured CMS service processes. Systemd separately owns the private ASGI runtime. Dedicated Linux worker units own custom-run workers. CMS judging Workers remain in their original CMS execution pipeline. No PID has two supervisors. Native web code neither launches ASGI nor executes participant programs.

## Public/private route map

| Route | Authority and behavior |
| --- | --- |
| /ide/ and exact build assets | Public immutable application shell; no task data embedded |
| /ide/api/context | CMS-authenticated identity, current phase/timing, authorized tasks/languages and CWS asset links |
| /ide/api/submissions POST | CMS authentication, XSRF, expected principal, exact intent validation and shared admission |
| /ide/api/submissions GET | Owned participant history, task/phase checks |
| /ide/api/submissions/INTENT GET | Owned durable receipt; accessible after deadline |
| /ide/api/submissions/status/OPAQUE_ID GET | Current permitted feedback; ownership/phase and active dataset checked |
| /ide/api/runtime/v1/... | Exact method/path/query allowlist, task gate, fresh internal assertion; bounded polling |
| /ide/health/live, /ide/health/ready | Liveness separate from CMS DB/schema/assets readiness |
| / and task/communication links | Original authenticated CWS; tokens/source/clarifications remain available |
| 127.0.0.1:8801 | Private runtime /api/v1 and /health/live,/health/ready only; never ingress exposed |
| Configured CMS RPC and PostgreSQL ports | Internal only; no browser route |

The private API gateway uses no redirects or environment proxy settings, sends no browser cookie/authorization headers, rejects arbitrary destinations, and closes the CMS SQL session before network I/O. HTTP capacity defaults to128, private operations16, total private timeout8s, body9MB and response12MB. Runtime ASGI concurrency and DB pools are separately bounded. Official admission has a separate ingress rate budget. Those values are starting limits, not measured 350-participant capacity.

## Native registration

cms/conf.py supplies optional defaults and excludes native coordinates when disabled. config/cms.conf.sample exposes opt-in enablement. A configured core_services entry defines actual RPC shards; HTTP lists are separate. scripts/cmsOlympiadIDEService uses CMS's existing argument parser and validates a numeric contest. setup.py installs both the service and migration launchers.

ResourceService's generic process matcher already recognizes cmsOlympiadIDEService. Its integration changes add the contest-dependent start behavior, enabled check, bounded native restart budget, and bounded connection wait before intentional stop; other services retain their lifecycle. Checker and Admin resource status consume the generic configured service map. Startup rejects absent assets/key/contest, default CMS secret, public native listeners, invalid pools/ports/proxies, and conflicting shard ports.

## Official transaction

1. Browser captures selected live Monaco text synchronously, before awaiting hashes. It shows task, actual CMS language, file map, bytes and immutable snapshot for confirmation.
2. Confirmation persists an intent UUID and exact request in identity/task-scoped IndexedDB before transmission. Pending, rejected, admitted and outcome-unknown are transport states independent of judging.
3. CMS validates strict JSON/UTF-8, UUIDs, selected file mapping, per-file/total byte limits and a canonical digest covering authenticated scope plus immutable request. No workspace upload or custom-run completion is required.
4. Shared policy locks the Participation row with PostgreSQL FOR NO KEY UPDATE. CWS and IDE admissions use the same count/interval boundary. The same committed intent returns its receipt; changed input returns409. Distinct intents may submit identical source.
5. Submission, source File relationships and OlympiadIDEReceipt commit in one CMS transaction. The receipt stores authoritative identity/task/language, per-file SHA256 and byte lengths, snapshot/workspace and optional telemetry boundary.
6. Only after commit does the service notify EvaluationService. The upstream117s sweeper enumerates durable submissions needing work. Duplicate hints are handled by CMS queues. This gives one committed Submission per intent; it is not a claim of exactly-once distributed evaluation.
7. Lost responses stay unknown. Reload/retry first performs authenticated GET reconciliation with the original intent, without creating a new POST. A committed receipt remains available after the deadline. An unadmitted late intent gets current CMS policy.

CMS's CommonRequestHandler request timestamp is used for both policy and Submission.timestamp, preserving pinned request-time semantics. Ingress arrival, database commit and response time occur later; client clocks/offline clicks never reserve admission.

## Capability matrix

| Task/profile | Official Submit | Custom Run |
| --- | --- | --- |
| Standalone Batch, one main.%l, stdin/stdout | Supported with contest-enabled CMS languages | Supported with healthy approved worker |
| Standalone Batch, file I/O | Supported; CMS judges its configured I/O | Explicitly unavailable |
| Grader-based Batch | CWS fallback | Unavailable in native task context |
| Multiple source formats, OutputOnly | CWS fallback | Unavailable |
| Communication/interactive | CWS fallback | Unavailable |

Explicit profile mappings are cpp17→C++17 / g++, cpp20→C++20 / g++, python3→Python 3 / CPython and java17→Java / JDK. A mapping does not certify compiler/interpreter versions. Java appears officially only if CMS enables it; Python is not silently replaced with PyPy. No judge managers, private tests or compiled IDE binaries enter official admission or workspace downloads.

## Feedback and local behavior

CWS and IDE share participant serializers for public/full scores, token disclosure, analysis/unofficial states, precision, partial aggregates and the current active dataset. The native adapter converts permitted plugin HTML to bounded inert text; React renders text. Completed results continue polling for rejudging. CWS-only submissions have null IDE correlation, not invented history.

Bootstrap selects installation/principal/task storage before uploaders start. Account mismatch pauses old queues. Task changes flush local state and restart scoped controllers. Offline recovery can reopen the current tab's cached scope with server operations paused. The /ide/ service worker caches exact application assets only, including Monaco workers; it bypasses APIs and CWS routes.

Submission observations extend the existing telemetry schema. Durable local prefix reconstruction compares exact selected-file bytes when available and reports verified/mismatch/unknown. Missing recordings never block Submit and are not misconduct evidence. Source-file hashes are distinct from custom-run/configuration snapshot hashes.
