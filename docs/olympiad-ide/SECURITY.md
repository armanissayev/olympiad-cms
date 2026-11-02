# Security boundaries and release review

| Boundary compromised | Consequence and containment |
| --- | --- |
| Participant/browser | Can modify its own source and fabricate/drop browser telemetry. CMS rechecks session/task/policy; input owner IDs, clocks, hashes and official flags grant no authority. Local storage is not encrypted against the browser profile's owner. |
| Native CMS service | Trusted with CMS session validation, database and source admission; compromise threatens contest authority. Keep it unprivileged, on loopback behind TLS, with reviewed CMS dependencies and no sandbox-helper access. |
| Private runtime | Can read/change IDE data and possesses the dedicated HS256 secret, so compromise can forge IDE principal assertions. It has no CMS database/RPC credentials or CMS cookie signing key and cannot create official submissions. HS256 is not asymmetric isolation from a compromised verifier. |
| CMS database/storage | Can alter official source/receipts/results; protect roles/backups and audit access. Unique receipts protect concurrency, not a malicious DBA. |
| IDE database | Can alter workspace/telemetry/custom jobs and nonce records; no direct CMS authority. Separate roles and database prevent migration overlap. |
| Trusted worker/controller/helper | Handles untrusted custom programs through isolate; helper compromise threatens its dedicated worker host. No CMS DB, judge data or RPC route should exist there. |
| Untrusted program | Limited to an approved fresh isolate sandbox, bounded CPU/wall time/memory/processes/output and no credentials/network. Linux tests must verify this on the actual worker host; never substitute unrestricted subprocess execution. |

## Enforced controls

- Real CWS session/participation/phase checks, XSRF mutations, expected-principal switch detection and server task membership.
- Request-bound PyJWT assertions with issuer/audience/expiry, exact query/body hashes and durable one-use nonce. Direct unauthenticated private calls fail closed.
- Fixed loopback private origin; method/path/query allowlist, no redirects, no arbitrary RPC or environment proxies. Incoming identity headers do not become trusted claims.
- Body/source/file/import limits, strict UTF-8, canonical UUIDs and file mapping, current ownership checks for workspace/telemetry/job/receipt identifiers. HTML is never injected into the workbench; existing terminal control-sequence restrictions remain.
- Separate native/runtime connection limits/timeouts; official requests have reserved HTTP capacity and ingress rate zone. PostgreSQL locks serialize quota admission across CWS and native shards.
- Private workspace reservations are bounded per stable principal (CMS_MAX_WORKSPACES default100, maximum1000); existing telemetry/execution quotas and retention remain. Reservations from malformed/abandoned creates count toward this conservative limit rather than creating an unlimited metadata channel.
- API responses use no-store; service worker caches only exact public application assets. No CMS secrets, assertions, cookies or passwords are included in source snapshots, journals or recording.
- Dedicated mode0600/0400 assertion files, no symlink key paths, no example secrets, no credentials in source-import/package manifest.

## Deployment controls requiring rehearsal

TLS is mandatory; use the supplied nginx cookie/forwarding protections and private listener rules. Allow participant network access only to443; restrict administrator access separately. PostgreSQL, CMS RPC, private runtime and worker control ports must not be contestant-accessible. SSH/monitoring access is operator-controlled. No AWS security group or other live network setting was changed in this task.

Use a dedicated API OS account without isolate privileges and a dedicated worker host/account with execution-only IDE DB grants. The native CMS account has no private IDE DB credentials. The CMS and IDE migration roles are separate. Worker network policy must prevent CMS RPC/database/judge-data access; SQL grants alone do not constrain network reachability. Required Linux isolate privilege/cgroup setup stays explicitly gated by WORKER_SANDBOX_APPROVED; do not broadly disable system protections.

Configure storage quotas/retention and monitor database size, queue age, failed worker leases, request latency and authentication errors. Existing telemetry retention maintenance is an operator job; retaining raw telemetry indefinitely is not implied. Logs must redact cookies/assertions/request bodies and not copy participant code into CMS LogService. Browser recording scope/disclosure and manipulability remain visible.

## Limitations

CMS1.5.1's old stack and upstream authentication semantics remain; this is not a CMS-wide security modernization. Pinning dependencies is not a vulnerability audit. Review deployment dependency advisories and imported-source licensing before release. The nginx/systemd templates, real helper isolation, worker least-privilege credentials, load limits, backup restoration and final-minute failure behavior require the Linux acceptance rehearsal described in VERIFICATION.md.

Unit tests with fixture scores do not certify hidden-data isolation in every third-party CMS task/score plugin. Unsupported task types fall back explicitly. The first supported topology is one contest and loopback runtime; multi-host runtime transport needs a new reviewed authenticated-channel design.
