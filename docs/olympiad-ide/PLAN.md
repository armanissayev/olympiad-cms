# Decisions and implementation stages

The owner requires a real CMS service, maintained inside the pinned CMS repository. We retain the existing IDE rather than replace it. Separate Python environments preserve CMS's gevent/Tornado/SQLAlchemy1 stack and the IDE's ASGI/SQLAlchemy2 stack. The native service owns CMS authority; the private runtime cannot admit official submissions.

| Stage | Implementation and evidence | Remaining gate |
| --- | --- | --- |
| A: baseline/native service | Safe manifest import, optional installed launcher, configured service coordinates, ResourceService start/status/restart/intentional stop, built installed assets | Linux installation rehearsal |
| B: identity/workspaces | Reused CWS authentication, request-bound signed private assertions, additive principal/task mappings, scoped local queues, source-only import | Shared lab/browser operational policy |
| C: official slice | Exact C++/Python admission into real CMS DB, shared policy/locking, transactional intent receipt, safe feedback serializers, live HTTPS/browser test | Real CMS Worker compile/evaluate/score/ranking |
| D: resilience | Unknown-result reconciliation, restart, concurrent CWS/IDE quota races, fallback, dataset/token feedback tests, runtime outage, worker outage | Real sandbox failure and production restore rehearsal |
| E: operations | Opt-in build/package, separate units/roles, migrations, backups/rollback guide, progressive load tool, regression evidence | Linux worker suite, actual judging, 300–350 participant load |

## Architecture decisions

1. Native WebService subclass with its own RPC/HTTP ports, registered through actual CMS core_services configuration. ResourceService owns CMS children; systemd owns ResourceService and the private runtime separately.
2. One explicit contest per native service. Reject ALL/missing contest and invalid shard configuration at startup. Multiple native shards share database locking and receipts; multi-contest URL multiplexing is not implemented.
3. Reuse ContestHandler/authenticate_request, original phase calculations and participant-visible serializers. Do not forward passwords, CMS login cookies, admin overrides or arbitrary RPC.
4. HS256 assertions use PyJWT, a dedicated secret, 30-second lifetime, request hashes and durable single-use nonce. Key compromise reaches IDE storage authority, not CMS admission.
5. PostgreSQL receipt and Submission commit together. CMS EvaluationService's existing recovery sweep repairs missed notifications; no second distributed queue or fictitious cross-database transaction.
6. Additive migrations only. Old development-owned server data is retained; proof unavailable means explicit validated source copy, never automatic ownership transfer.
7. First native official slice is standalone Batch with one language-dependent source file. Unsupported task modes expose CWS fallback. Custom Run remains separate and narrower.
8. Preserve ordinary CWS even when the native feature is disabled. Telemetry/worker/runtime failure cannot become a requirement for official admission.

Source-import, architecture, authentication, migration, deployment and security details are in the adjacent documents. IMPLEMENTATION_STATE.md records the exact remaining acceptance steps.
