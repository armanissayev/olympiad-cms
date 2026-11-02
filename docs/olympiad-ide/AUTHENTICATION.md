# Authentication and authorization

## CMS session authority

Native API handlers inherit the pinned ContestHandler and use authenticate_request. CWS alone handles password login and logout. Its signed cookie is named <contest.name>_login with path /. Every native request rechecks participation, cookie/password validity, IP restrictions/autologin and hidden participation rules. No administrator impersonation or second password database exists.

Ownership is a deterministic UUIDv5(URL namespace, compact ASCII JSON array of installation UUID and user/contest/participation numeric-ID strings). Display names and task names are not ownership keys. The stable installation UUID must survive physical restore; duplicating an installation for a separate trust domain requires a new UUID.

Authenticated bootstrap supplies the expected principal. Subsequent requests carry X-Olympiad-Principal; mismatch returns409 identity_changed before any upload/admission. This header detects account switching; it cannot authorize a participant. Runtime routes additionally carry a task ID, which CMS resolves against its current contest and actual phase. Official admission uses the CMS current user and task policy directly.

Native mutations enforce Tornado XSRF. Background polling does not refresh the login cookie; manual official POST refreshes it like CWS submission. Logout is a real XSRF-protected CWS POST. Expiry, password change, removed participation and account switching pause server operations while retaining local data. IP autologin follows original CMS semantics and may authenticate again when configured; logout does not override an administrator's IP-auth policy.

The original CMS1.5.1 login cookie does not set all desired deployment flags. The supplied HTTPS ingress adds Secure, HttpOnly and SameSite=Strict to login cookies and Secure/SameSite to XSRF cookies. These production nginx settings require Linux rehearsal; the live local test uses a generated trusted TLS certificate. No private bearer is exposed to JavaScript or persisted in IndexedDB. Bootstrap CSRF values are not saved in offline context.

## Private assertion contract

Only the native service calls the private runtime. PyJWT HS256 uses a dedicated32–4096-byte secret, separate from CMS secret_key. Store identical bytes in two protected files owned separately by cmsuser and olympiad-api, each mode0600 or0400; different service users cannot share a mode0600 file owned by one of them. Example config paths are documented in DEPLOYMENT.md. Symlinks/public permission bits are rejected.

Required claims:

| Claim | Binding |
| --- | --- |
| iss / aud | Stable CMS installation UUID / olympiad-ide-runtime |
| sub, contest, participation, task | Server-derived positive numeric ID strings |
| principal / scope | Recomputed stable principal / runtime |
| iat, nbf, exp | Integer seconds; nbf=iat, lifetime at most30s,2s validation leeway |
| jti | Canonical fresh UUID |
| method, path | Exact translated private request |
| query_sha256, body_sha256 | Exact raw query/body byte hashes |

Private middleware validates all claims before invoking application logic. A unique nonce is committed in the IDE database before the requested operation; a failed operation cannot replay the same assertion. Concurrent consumption permits one winner. Retry must obtain a new assertion through freshly authenticated CMS; application idempotency keys still govern mutation replay.

CMS mode never accepts the development cookie as authority, never creates development sessions, and disables API documentation endpoints. Existing ownership foreign keys are retained through a backing DevelopmentIdentity row with an unusable random token hash and expired date, plus explicit CMSPrincipal mapping. Workspace reservations bind a UUID to principal and task; legacy existing workspaces cannot be claimed. Job and telemetry access follows their actual bound workspace.

Revocation is checked on every CMS request. An already issued unused private assertion can remain valid up to32s including leeway; an already admitted in-flight operation is not recalled. There is no long-lived browser/runtime token. Restart both native and private runtime when rotating the shared key, invalidate pending internal requests, and reconcile idempotent requests through CMS.

## Trust and recovery boundaries

Only configured immediate proxy IPs may supply forwarded client IP/protocol with the configured hop count. Ingress overwrites forwarding headers and strips client Authorization. CMS RPC/private runtime bind loopback. On multiple hosts, this initial loopback-only topology requires a separately reviewed authenticated network design, not relaxed validation.

Server ownership isolation does not encrypt browser IndexedDB against another person with access to the same OS/browser profile or developer tools. Use separate OS/browser sessions in a shared contest lab. Signing in as another participant selects another scoped database and cannot upload old queues, but local backups remain recoverable by the machine's owner.

Cross-origin legacy migration is explicit source export/import only. Old server telemetry/receipts remain with their original owner; proof-based historical adoption is not implemented. See DATA_MIGRATION.md.
