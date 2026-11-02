# Native CMS service evidence — 2026-11-02

Historical local-phase evidence. Later authorized Linux results, including the idle-connection correction and real judging, are recorded in [LINUX_ACCEPTANCE](../LINUX_ACCEPTANCE.md).
## Scope and environment

This evidence concerns the native `OlympiadIDEService` added to CMS v1.5.1 (base commit `7c9fec8aa1a25ec93d624aebf815804dd93df9db`). Tests used macOS arm64, Python 3.12, the CMS requirements in a dedicated virtual environment, separately installed private-runtime dependencies, disposable PostgreSQL databases on loopback, and production frontend assets under `/ide/`. No AWS tunnel, existing application process, live contest database, or production credentials were used.

Real-process tests use installed CMS launchers with `PYTHONPATH` pointing to the integration checkout. This verifies actual process discovery, RPC and HTTP behavior of the current source through the installed launchers. It does not replace the separate built-wheel/package check. Local socket/process restrictions required scoped automatic approval; no sandbox security was disabled.

## Focused tests

The final focused runs passed: **28 tests** (25 new native tests and 3 existing ResourceService tests).

```sh
CMS_CONFIG=/private/tmp/cms-native-context.conf \
PYTHONPATH=/Users/isaevarman/Developer/cms \
/private/tmp/cms-integration-venv/bin/python -m pytest \
  cmstestsuite/unit_tests/service/OlympiadIDEContextTest.py \
  -q --tb=short -p no:cacheprovider
# 9 passed

CMS_CONFIG=/Users/isaevarman/Developer/cms/config/cms.conf.sample \
PYTHONPATH=/Users/isaevarman/Developer/cms \
/private/tmp/cms-integration-venv/bin/python -m pytest \
  cmstestsuite/unit_tests/service/OlympiadIDEServiceTest.py \
  cmstestsuite/unit_tests/service/ResourceServiceTest.py \
  -q -p no:cacheprovider
# 19 passed
```

The context suite uses its own disposable `cmsnativecontextfortesting` database and real CMS authentication/WSGI handlers. It covers CMS signed-cookie validity, password change and expiry rejection, hidden/removed/IP-restricted participation, CMS IP autologin, participant extra time and precontest task visibility, expected-principal and XSRF checks, numeric task/contest metadata, CPython language mapping, unsupported task fallback, and no background login-cookie refresh. A deliberate official POST refreshes the cookie. Missing receipt migration makes native readiness return 503 while liveness remains 200.

Service tests cover disabled-by-default discovery, explicit single-contest selection, independent HTTP/RPC shard bindings, private runtime/key/ingress validation, native HTTP capacity reserved beyond the runtime pool, stable principal derivation, trusted peer forwarding, request-size bounds, installed launcher recognition, bounded native restart attempts, intentional stop, duplicate-start avoidance and the initial asynchronous RPC connection race.

## Actual processes, TLS and PostgreSQL

The reusable opt-in harness is `cmstestsuite/olympiadide_smoke.py`. It requires a new empty disposable database whose name ends in `fortesting`, loopback CMS processes, a separately started private runtime, and actual installed CMS launchers. It starts only LogService, ResourceService, native IDE shards, CWS and a temporary test-local TLS ingress. The TLS certificate is explicitly trusted by the test client; certificate verification is not disabled.

Final invocation:

```sh
PYTHONPATH=/Users/isaevarman/Developer/cms \
/private/tmp/cms-integration-venv/bin/python \
  cmstestsuite/olympiadide_smoke.py \
  --config /private/tmp/cms-native-final.conf \
  --bin-dir /private/tmp/cms-integration-venv/bin \
  --report /private/tmp/cms-native-final-result.json \
  --browser-handoff-file /private/tmp/cms-native-final-fixture.json \
  --check-runtime-outage
```

The final configuration uses a new `cmsidesmokefinalfortesting` database. ResourceService runs with `cmsResourceService 0 -a <contest-id>` and supplies `-c <contest-id>` to native child services. Two native HTTP/RPC shards share the same CMS contest. The private runtime is separately supervised; its outage is injected only by the owner of that disposable process. Handoff credentials and configuration secrets remain in private temporary files and are not included in this evidence.

Passed process/HTTP checks:

- ResourceService launches native IDE and CWS, recognizes singleton native processes, and reports native status over its real RPC interface.
- Both native shards become ready with different HTTP/RPC bindings and process IDs.
- Real CWS password login authenticates native context through the shared TLS origin; task and participant scopes match.
- Native gateway calls the actual private-runtime session and workspace APIs. A workspace survives write/read; a wrong expected principal is rejected.
- C++17 and Python submissions create ordinary CMS submissions with exact UTF-8 file bytes. Identical retries return the same receipt, including retries through the other native shard. Reusing the intent with changed source is rejected.
- Native pending feedback/history and the normal CWS submissions page are available. No duplicate CMS submission is created by replay.
- ResourceService restarts shard 0 to a new singleton PID while shard 1 remains unchanged. Committed receipts survive the restart and remain readable after the contest deadline.
- Real CWS logout makes native context return 401. Turning native autorestart off and stopping it leaves it stopped past the restart interval; ordinary CWS remains available.

The final run **passed**. During an actual stop of the private runtime, its workspace route returned 503 while native context returned 200, a new official C++ submission was admitted with 201, and the ordinary CWS submissions page returned 200. The runtime was then restarted by its owner. The final report records two shards and eleven successful lifecycle/HTTP checks.

## Real browser and small load evidence

The frontend auditor used the live disposable native fixture with the existing Chromium cache and fresh browser contexts. All native scenarios passed: CWS login, context, Monaco, official history, immutable C++ source capture, Python response-loss/reload receipt reconciliation with one POST, `/ide/` offline shell and Monaco workers, reauthentication, and real CSRF logout with local work retained. Run was correctly disabled with zero real workers. Browser errors were empty. See `FRONTEND_INTEGRATION.md`; temporary detailed results were `/private/tmp/cms-native-browser-results.json`.

A separate bounded load-tool smoke used **one distinct participant**, two fresh logins and five context reads, concurrency 1, configured rate 2 HTTP requests/second and request timeout 3 seconds. All 11 HTTP requests succeeded. Login HTTP latency p95 was 61.815 ms; context-read HTTP latency p95 was 23.939 ms. These are same-host local measurements of these few requests only. No runtime/official mutation was part of this load run. Server resource/queue/storage metrics and contest-scale capacity were not measured. Detailed temporary report: `/private/tmp/cms-native-load/report-local-tls.json`.

## Limits and cleanup

No CMS Worker or approved Linux isolate worker was available. This proves official admission, durable receipt reconciliation and pending feedback, not actual compilation, accepted/wrong-answer results, scoring, custom program execution or isolation. Compiler/interpreter versions remain unverified. Java/JDK does not establish Java 17, and CPython is not silently mapped to PyPy. Multi-contest native `ALL` startup is deliberately rejected; this slice supports an explicit contest with multiple service shards. The 300–350-participant target is untested.

The harness stopped only its own CMS process groups and TLS ingress. Independent post-run checks found no remaining exact smoke launcher processes and no reachable test ports (34100, 34101, 34102, 34103, 34106, 18888, 18891, 18892, 18443). PostgreSQL databases were retained for the separate backup/restore rehearsal; the private runtime remains owned by its separate supervisor. Raw final report: `/private/tmp/cms-native-final-result.json`. Temporary service logs: `/var/folders/xl/037wlwyd03v9swhc14t074mw0000gn/T/cms-ide-smoke-8fh4xkad`.

The pinned upstream stack emits existing Python 3.12 deprecation warnings; an earlier process run also emitted a gevent logging-finalization warning at interpreter shutdown. Tests and owned-process cleanup succeeded. The broader upstream suite has separate macOS shared-mime-info failures documented by the root audit; this focused pass does not imply all upstream tests pass.

## Installed-wheel database-fault follow-up

A subsequent run used the clean installed CMS wheel with `PYTHONPATH` unset and two new disposable databases. Actual CMS and IDE database faults and recovery passed, including no false official admission and independent CMS admission during IDE database loss. Three safety tests (10 subtests) passed. CWS first-request stale-pool recovery was observed as 500 then 200 and is explicitly retained as a limitation. See [DATABASE_FAULTS.md](DATABASE_FAULTS.md) for exact results, guards, commands and cleanup.
