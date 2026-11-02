# Progressive-load tooling and tiny local measurement

Historical local-phase evidence. Later authorized Linux results, including the idle-connection correction and real judging, are recorded in [LINUX_ACCEPTANCE](../LINUX_ACCEPTANCE.md).
On2026-11-02 the new `olympiad_ide/tools/cms_load.py` ran against the final disposable native CMS HTTPS fixture at `https://localhost:18443`. It used one generated participant, separate fresh login sessions, and no workspace/telemetry/run/official submission mutations. Credentials were read from an external mode0600 file, never printed or committed. TLS was verified against the fixture's certificate. Hardware: local macOS/Darwin25.5.0 arm64,8logicalCPUs, Python3.12.6. Worker toolchains and representative test-suite cost were not measured because no participant program executed.

Command (external generated target manifest and credentials; UUID here identifies only that disposable run):

```sh
/private/tmp/cms-integration-venv/bin/python olympiad_ide/tools/cms_load.py \
  --target /private/tmp/cms-native-load/target.json \
  --credentials /private/tmp/cms-native-load/credentials.json \
  --plan /private/tmp/cms-native-load/plan.json \
  --confirm-disposable 933d34ed-0b39-455f-b38a-df45b4e24a67 \
  --report /private/tmp/cms-native-load/report-local-tls.json
```

Observed exit0. Global offered rate2HTTP/s, concurrency1, no ramp,15s duration ceiling per scenario,3s request timeout. Built-in login performs CWS root GET, CWS `/login` POST and native context GET. Separate context-read stage reused the authenticated session.

| Scenario | Actual operations | HTTP requests | HTTP status | HTTP latency p50/p95/p99 (ms) | Elapsed | Errors |
|---|---:|---:|---|---|---|---:|
| login_burst |2freshlogins |6 |4×200,2×302 |23.793 /61.815 /63.777 |2.524s |0 |
| context_read |5 |5 |5×200 |21.995 /23.939 /24.112 |2.028s |0 |

The achieved count/elapsed throughput was2.377 and2.465HTTP/s respectively; the first request starts immediately, so a short finite run's average can exceed the configured spacing rate. Operation latency includes client pacing (login p95=1444.088ms; context p95=513.134ms). HTTP latency excludes pacing. These small sample percentiles describe only these11requests, not capacity or normal production tails. The sanitized machine-readable report is `load-local-tls.json` beside this file.

Initial sandboxed invocation could not open local sockets, reported two ConnectionErrors, and exited1. No HTTP reached the service. A scoped authorized local-network escalation then produced the successful result above; this is not a hidden functional retry or official submission replay.

No server CPU/memory, queue age, DB connection count or storage growth was measured; those fields remain null. One participant is not two participants merely because it logged in twice. The350participant test, telemetry ingestion load, sustained autosave, custom-worker execution load, official submission bursts and final-minute mixed workload are **not executed**. Fixture-driven paths exist and require real valid external protocol payloads plus explicit custom-run/official flags, but CLI/fixture validation is not evidence they passed. See `olympiad_ide/tools/CMS_LOAD.md` for actual inputs, boundaries and progressive scenarios.

Network-free test command:

```sh
/private/tmp/cms-integration-venv/bin/python -m pytest \
  cmstestsuite/unit_tests/server/olympiadide/load_test.py -q --tb=short -p no:cacheprovider
```

Initial observed result:9passed,18subtests passed in0.13s (one sandbox pytest-cache write warning, avoided by the command above). Tests validate disposable confirmations/TLS/scope, remote opt-in, quotas, distinct participant count, mutation opt-ins, route/traversal rejection, scenario categories, private external credentials, typed fixture variables, response identity checks, null metrics and validate-only no-network/no-secret output. `--help` also exits0.
