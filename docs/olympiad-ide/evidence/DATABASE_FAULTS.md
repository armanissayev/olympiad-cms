# Native CMS and IDE database fault evidence — 2026-11-02

Historical local-phase evidence. Later authorized Linux results, including the idle-connection correction and real judging, are recorded in [LINUX_ACCEPTANCE](../LINUX_ACCEPTANCE.md).
The bounded fault run **passed** using the clean installed CMS wheel, two native service shards, actual CWS login over verified test-local TLS, a separate private runtime process, and two newly created PostgreSQL databases. `PYTHONPATH` was unset. CMS and native service imports resolved under `/private/tmp/cms-native-clean-venv/lib/python3.12/site-packages/`, not the source checkout. All services used explicit contest IDs. The test harness came from the integration checkout; no application code was changed for this test.

## Safety and exact scope

The opt-in `--check-database-outages` mode in `cmstestsuite/olympiadide_smoke.py` requires `--runtime-database-url-file`. The helper `cmstestsuite/olympiadide_smoke_safety.py` rejects remote hosts, absent ports/users, non-PostgreSQL URLs, connection query overrides, database names not ending in `fortesting`, identical CMS/IDE databases, and differing clusters/owners. Before mutation it checks that the target is currently available, is not a template, and belongs to the current role.

Fault injection uses an administrative connection to `postgres`, sets `ALLOW_CONNECTIONS false` on exactly one quoted target name, and terminates sessions only where `pg_stat_activity.datname` equals that target. A `finally` block restores `ALLOW_CONNECTIONS true`. The outer test runner independently restores the flags again on cleanup. No cluster stop, role change, database deletion or existing source/restore-database mutation was performed.

Final targets were `cmsidedbfault_1f20e8571bfortesting` and `idefault_1f20e8571bfortesting` in the disposable loopback cluster on port 55459. Runtime port 18901, native ports 18991/18992, CWS port 18988, RPC ports 34200/34201/34202/34203/34206 and TLS ingress 18543 were all separately allocated. The runtime used a newly generated installation ID and private signing-key file; credentials and key bytes are omitted here.

## Observed HTTP results

| Condition | Native liveness | Native readiness | Native context | Official POST | Private runtime readiness | Runtime gateway | Normal CWS |
|---|---:|---:|---:|---:|---:|---:|---:|
| CMS database unavailable | 200 | 503 | 500 | 500, no admission | Not part of this fault | Authentication unavailable | Recovers as described below |
| IDE database unavailable, CMS recovered | 200 previously verified | 200 | 200 | 201 admitted | 503 | 503 | 200 |

The private runtime's own liveness remained 200 during its database outage. Native and private readiness both probe their actual database tables rather than reporting a successful process-only check.

After restoring the CMS database, existing immutable receipts reconciled with the same submission identifiers. The intent attempted during the outage was absent (404), then admitted once (201), and an identical replay returned the existing receipt (200). During the IDE database outage, a separate official submission was admitted by CMS. After restoring the IDE database, the previously stored workspace returned the exact original source text. The final CMS database contained four submissions and four receipts, accounting for the original C++/Python submissions and the two explicit recovery/outage admissions.

## Recovery detail and first run

The first run reached the successful CMS fault/recovery assertions but failed when the normal CWS page was first accessed during the next test. Logs showed a terminated connection from the preceding CMS database fault: upstream CMS configures SQLAlchemy pooling without `pool_pre_ping`. Its first request after recovery can return 500 while the pool invalidates the stale connection.

The final harness records CWS recovery before injecting the independent IDE fault. The observed CWS sequence was **500, then 200** on a bounded retry. This result is retained in the report as `cmsDatabaseRecovery.cwsStatuses`; it is not described as uninterrupted CWS availability across a CMS database failure. No broad change to upstream CMS connection pooling was made. The final fault run completed with exit status 0 after this explicit recovery boundary.

## Reproduction and focused safety tests

Use the dedicated fixture's private configuration and runtime URL file, with its private runtime already started on the configured loopback origin:

```sh
# Run from a directory outside the source checkout; do not set PYTHONPATH.
env -u PYTHONPATH /private/tmp/cms-native-clean-venv/bin/python \
  /Users/isaevarman/Developer/cms/cmstestsuite/olympiadide_smoke.py \
  --config /private/tmp/cms-db-fault-1f20e8571b/cms.conf \
  --bin-dir /private/tmp/cms-native-clean-venv/bin \
  --report /private/tmp/cms-db-fault-1f20e8571b/result.json \
  --tls-port 18543 \
  --check-database-outages \
  --runtime-database-url-file /private/tmp/cms-db-fault-1f20e8571b/runtime-database-url
```

This exact completed fixture cannot be rerun in place: the harness rejects a populated CMS database. A rerun must allocate new disposable database names, config, state directories and signing key. The temporary runner `/private/tmp/cms-db-fault-run.py` performed those allocations, migrated the new IDE database, started and stopped its private runtime, and restored both connection flags in its outer cleanup. It did not print credentials or source contents.

`cmstestsuite/unit_tests/service/OlympiadIDESmokeSafetyTest.py` passed **3 tests with 10 subtests**, without network access:

- `test_only_distinct_disposable_databases_on_one_loopback_cluster_allowed`
- `test_exception_restores_target_and_termination_is_database_scoped`
- `test_unowned_or_already_disabled_database_is_never_altered`

These supplement the 28 focused native tests in `NATIVE.md` (31 focused tests total). The existing lifecycle, authentication, exact-file official admission, replay, two-shard and intentional-stop checks also ran again through the installed wheel before the database faults.

## Cleanup and remaining limits

Independent verification found no reachable fault-test ports, no exact test-owned CMS launcher processes, no active sessions on either run's newly allocated databases, and `datallowconn=true` for all four new databases. The dedicated private runtime stopped. The databases remain available for inspection; the shared disposable PostgreSQL cluster and unrelated databases were left untouched. Raw final report: `/private/tmp/cms-db-fault-1f20e8571b/result.json`; cleanup evidence: `/private/tmp/cms-db-fault-cleanup.json`. The initial failed run remains under `/private/tmp/cms-db-fault-057d3cd0c5/`.

The pinned stack emitted non-fatal Python 3.12/gevent fork and interpreter-shutdown warnings. No worker program was executed. This test does not establish Linux sandbox isolation, official judging/score correctness, compiler versions, target contest capacity, or successful behavior under a filesystem/disk failure.
