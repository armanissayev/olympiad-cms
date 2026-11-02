# Verification and acceptance status

Updated 2 November 2026. Tests used a new PostgreSQL14 cluster on127.0.0.1:55459, disposable databases/schemas, generated users/secrets and temporary browser profiles. No AWS/live contest or existing user database was used. macOS arm64 has no approved Linux isolate/CMS Worker environment.

## Observed results

| Check | Actual outcome |
| --- | --- |
| Untouched CMSv1.5.1 complete unit baseline | 670 passed,9 skipped,6 shared-mime-info failures |
| Final integrated CMS complete unit suite | **739 passed,9 skipped,6 same failures;28 load/fault-safety subtests passed** |
| Focused CMS admission/feedback/migration/dump tests | 46 passed |
| Existing CWS submission/phase tests | 99 passed,1 existing environment skip |
| Native context/lifecycle plus original ResourceService | 28 passed (25 new plus3 existing) |
| Database fault harness safety guards | 3 passed,10 subtests |
| Imported private runtime PostgreSQL suite | **75 passed** |
| Frontend unit suite | **81 passed**; lint/typecheck/build passed on Node24.19.0 |
| Retained standalone production browser suite | **13 passed,1 real-worker skip** |
| Imported worker policy/sandbox collection | **7 passed,26 Linux tests skipped** |
| Real-process native HTTPS smoke | Passed actual CWS login, runtime persistence, C++/Python admission, source bytes, receipt/restart/deadline/logout, two-shard lifecycle and runtime outage |
| Real native Chromium acceptance | Passed immutable snapshot, lost response/reload with one POST, history, /ide offline assets/Monaco workers, logout/local retention |
| Progressive load tool | 9 tests/18 subtests; tiny TLS run1 participant,2 logins,5 context reads,11 HTTP requests,0 errors |
| Clean package/install | See evidence/PACKAGING.md for final distribution verification |
| Local PostgreSQL backup/restore | Passed exact28CMS/21IDE tables, source/receipt/principal IDs; see evidence/RESTORE.md |
| Separate CMS/IDE DB outage and recovery | Passed installed-wheel actual-process faults; see evidence/DATABASE_FAULTS.md |
| Real custom Linux execution and CMS judging | **Not run; blocked by unavailable authorized Linux environment** |
| 300–350 participants, production final minutes/deployment | **Not run; no capacity claim** |

Targeted tests overlap the full CMS suite; totals must not be added as unique coverage. Original IDE baseline and historical Phase4/AWS reports remain separate in BASELINE.md and evidence/{FRONTEND,BACKEND,BROWSER}.md.

The six complete-suite failures are the same untouched-CMS failures in cmscommon/mimetypes_test.py (icon/name/file-name lookup). This Mac lacks the configured Linux shared-mime-info database. They were not removed or turned into skips. The integrated suite is therefore not reported as entirely green. Existing pkg_resources/Python3.12 deprecations and upstream fake-sweeper teardown logging warnings remain; the latter originates in io/triggeredservice_test.py's untracked loop. New recovery tests do not start a sweeper.

## Executed commands

These exact local paths describe this verification environment, not production secrets/configuration templates. Configuration files contain only generated disposable credentials and are intentionally not committed.

~~~sh
# CMS complete integrated regression, from the CMS checkout
CMS_CONFIG=/private/tmp/cms-regression.conf PYTHONPATH=/Users/isaevarman/Developer/cms /private/tmp/cms-integration-venv/bin/python -m pytest cmstestsuite/unit_tests -q --tb=short

# Private runtime; the suite creates isolated PostgreSQL schemas
cd /Users/isaevarman/Developer/cms/olympiad_ide/backend
TEST_DATABASE_URL=postgresql+psycopg://isaevarman@127.0.0.1:55459/ideruntime /private/tmp/olympiad-runtime-venv/bin/python -m pytest -q --tb=short

# Worker collection: no approval bypass and no Linux execution on macOS
cd /Users/isaevarman/Developer/cms
PYTHONPATH=/Users/isaevarman/Developer/cms/olympiad_ide:/Users/isaevarman/Developer/cms/olympiad_ide/backend /private/tmp/olympiad-runtime-venv/bin/python -m pytest olympiad_ide/worker/tests -q --tb=short

# Frontend under Node24 on PATH
cd /Users/isaevarman/Developer/cms/olympiad_ide/frontend
npm ci
npm test
npm run typecheck
npm run lint
npm run build
~~~

The frontend/native/standalone browser exact fixture commands and results are in evidence/FRONTEND_INTEGRATION.md. The real-process harness command is in evidence/NATIVE.md; it refuses a populated/non-fortesting CMS database and starts only its own LogService/ResourceService/CWS/native processes. It requires a separately started private runtime and builds a temporary local TLS ingress. It does not start judging/sandbox workers.

Admission/dump/race commands are in evidence/ADMISSION.md; load inputs/rates/runner metadata and percentiles are in evidence/LOAD.md. Temporary raw logs are under /private/tmp; durable sanitized summaries are committed. Initial sandbox-denied socket attempts are not test passes; authorized local reruns are distinguished.

## Requirement matrix

| Requirement | Evidence and test location | Status/limit |
| --- | --- | --- |
| Audited pin/import/build/installed launchers | BASELINE, SOURCE_IMPORT, PACKAGING; build tool and setup registration | Implemented; final packaging evidence |
| Optional config, valid/invalid settings, disabled discovery | service/OlympiadIDEServiceTest.py | Passed; core config absent/disabled preserved |
| RS launch/status/log/restart/intentional stop/duplicate prevention/two shards | cmstestsuite/olympiadide_smoke.py; NATIVE | Actual processes passed |
| CWS login, expiry/password/participation/IP rules, forged principal | service/OlympiadIDEContextTest.py and existing authentication_test.py; real browser | Passed targeted/retained tests; follows upstream IP autologin semantics |
| Assertion signature/audience/expiry/request/replay/direct rejection | backend/tests/test_cms_identity.py | Passed real PostgreSQL, including concurrent nonce consumption |
| User/task/contest/job/telemetry/workspace isolation, no legacy claim | test_cms_identity.py; frontend CMS tests | Passed; source-only legacy import |
| Live snapshots, UTF-8/file/language map and exact CMS bytes | native admission_test.py, frontend cms tests, real browser | Passed C++/Python admission; no actual compilation claim |
| Shared count/interval/deadline/extra-time policy | admission_test.py, existing workflow/phase tests | Passed including independent-process CWS/native races |
| Duplicate/changed intent, before-commit rollback, after-commit lost response, restart | admission_test.py, real browser and native smoke | One durable submission per intent; no blind CWS retry |
| Missed/duplicate notification recovery | admission tests and upstream recovery enumeration | Durable work discovered; actual worker execution still blocked |
| Public/token/full/active-dataset/rejudge feedback | feedback_test.py, shared CWS serializers | Fixture results passed; real judge/score/ranking remains blocked |
| Offline /ide reload, exact service-worker scope, Monaco workers | frontend/offline tests and real native Chromium | Passed |
| Split editor, persistence, replay, custom contracts | original63 frontend retained, backend/browser/worker-policy suites | Passed available suites;26Linux+1browser skips |
| Runtime failure independent of official/CWS | final actual-process outage injection | runtime503 while context/CWS200 and official201 |
| Missing worker capacity and workspace quotas | backend CMS tests, native browser | Passed; no unrestricted execution fallback |
| CMS DB failure/commit errors, identity-store failure | actual installed-wheel fixture plus guarded readiness/rollback tests | Actual separate CMS/IDE DB outages and receipt/workspace recovery passed; see DATABASE_FAULTS |
| Telemetry quota/gaps without submission dependency | existing telemetry tests, separate receipt path, UI tests | Passed available contracts; production quota-stress not run |
| Additive migrations, dump-v45 and logical roundtrip | admission/receipt_dump tests, Alembic checks | Passed available tests; see RESTORE for physical-ID rehearsal |
| Separate roles/network/helper privileges | source/config review, worker-role.sql | Actual Linux restricted-role/network verification remains |
| CWS/Admin/judging/scoring/ranking disabled-feature regression | full CMS unit suite, disabled old-schema CWS, actual CWS smoke | Admin/scoring unit coverage; full real distributed judging/ranking not run |
| Progressive login/autosave/telemetry/run/submit/final minutes | cms_load.py + validated fixture scenarios | Only tiny login/context measured;350 and mutating runs untested |

## Required Linux acceptance

Use authorized disposable Linux infrastructure and the committed sources/locks. First validate installation, nginx configuration/cookies, separate roles and health. Restore disposable backups and verify original identity IDs/source hashes. Run RUN_LINUX_SANDBOX_TESTS=1 with the retained worker suite under its documented approved isolation conditions, then the REAL_LINUX_WORKER=1 browser scenario with real worker capacity. Record kernel/isolate/toolchain versions, limits, cancellation, fresh boxes and cleanup. Do not set sandbox approval merely to make tests start.

Next run actual CMS EvaluationService, judging Workers, scoring and configured ranking for C++ and Python submissions created through /ide/. Verify real diagnostics/score visibility, CWS/Admin/ranking appearance, token disclosure, rejudging/dataset switches and deadline fault cases. Repeat separate CMS/IDE DB outage/recovery and runtime/worker fallback on the deployment topology. Local DB fault checks passed; CWS temporarily returned500 from an upstream stale connection before recovering, as recorded in DATABASE_FAULTS.md.

Finally ramp the load tool on300–350 distinct disposable participants with realistic arrival rates and separate custom compilation limits. Execute autosave, telemetry, custom Run, official submission and final_minutes fixtures; collect p50/p95/p99, queue age, DB connections, disk growth, CPU/RAM and errors. Current unknown metrics are null, not zero. Acceptance requires evidence for all eight user steps; real custom execution and real official feedback are still outstanding.
