# Build, deployment and operations

## Tested boundary

The integration passed a real disposable Ubuntu 26.04.1 staging rehearsal on the explicitly authorized host, including all 26 Linux sandbox tests, actual CMS C++/Python judging, real-worker native browser recovery, separate service/database outages and matched database/application restoration. See [LINUX_ACCEPTANCE](LINUX_ACCEPTANCE.md) and the [staging procedure](../../olympiad_ide/tools/linux_staging/README.md) for exact commands, versions, corrected configuration and remaining limits. Earlier macOS/local evidence remains historical.

The generic /opt/nginx/systemd templates below require adaptation and review for production. The tested staging layout uses separate official/custom execution accounts, ResourceService owners and restricted helper permissions. Dedicated production worker hosts and production sizing remain release gates. No production host, DNS or AWS networking was changed.

## Install and build

Use the committed feature branch based on CMSv1.5.1, not moving upstream master. Install the release's OS dependencies from docs/Installation.rst (Python3.12 development headers, libpq/libcups/libffi/libyaml, PostgreSQL, shared-mime-info and CMS sandbox/toolchain prerequisites). Add a supported Node22/24 build runtime and nginx with proxy_cookie_flags support. Keep the original CMS configuration, installation and task/judging setup; do not replace core services with the snippet below.

Example assumes a reviewed clone at /opt/cms and dedicated existing service accounts cmsuser, olympiad-api and worker account olympiad, with code owned by the administrator:

~~~
cd /opt/cms
python3.12 -m venv /opt/cms-venv
/opt/cms-venv/bin/python -m pip install -r requirements-olympiad-ide.lock
/opt/cms-venv/bin/python -m pip install -r requirements.txt -r requirements-olympiad-ide.txt
python3.12 tools/build_olympiad_ide.py
/opt/cms-venv/bin/python -m pip wheel --no-deps --no-build-isolation --wheel-dir /opt/cms-artifacts .
/opt/cms-venv/bin/python -m pip install --no-deps /opt/cms-artifacts/cms-1.5.1-py3-none-any.whl
/opt/cms-venv/bin/python -m pip check

python3.12 -m venv /opt/olympiad-runtime
/opt/olympiad-runtime/bin/python -m pip install -r olympiad_ide/backend/requirements.lock
/opt/olympiad-runtime/bin/python -m pip install --no-deps ./olympiad_ide/backend
/opt/olympiad-runtime/bin/python -m pip check
~~~

The lockfiles record tested versions; validate their availability/platform compatibility on the target host. No broad dependency bypass or coreCMS upgrade is required. The separate environments intentionally contain different SQLAlchemy versions. Frontend npm ci is opt-in through the build tool; ordinary CMS and worker Python installation does not invoke Node. --skip-install only reuses a prior successful npm ci.

The native wheel contains service code, launchers and built /ide/ assets. The source distribution/repository also contains the separate runtime, worker, frontend source, tests and tools; keep that source tree for the supplied units. Do not run Vite in production. Assets are generated/ignored in Git and must be built before constructing the optional native distribution; missing assets cause enabled-service startup to fail clearly.

## Databases, accounts and secrets

Use separate cms and olympiad_ide databases. Existing CMS configuration owns the CMS DB. IDE migrations use a separate schema-owner role, API uses an IDE DML-only role, and worker uses ide_worker with only execution-table privileges from deployment/worker-role.sql. No worker CMS credentials, source-test storage mount or RPC network access.

Provision the database roles using your protected PostgreSQL administration workflow. Grant API SELECT/INSERT/UPDATE/DELETE on IDE application tables and necessary sequence usage; do not grant schema creation. Run Alembic as the schema owner and refresh grants for new tables. Revoke PUBLIC database/schema privileges where appropriate to your installation; ensure both API and worker can connect only to the intended database. Worker grants must be tested with the actual restricted role before deployment. Passwords belong in protected service environments/libpq files, never the repository.

Generate one installation UUID and a separate64-byte random assertion key. The two service users need identical bytes in distinct files:
- /etc/cms/ide-native-assertion.key owned cmsuser, mode0600.
- /etc/cms/ide-runtime-assertion.key owned olympiad-api, mode0600.

Use a protected administrator temporary file to distribute it, then remove that temporary copy. Do not print it or reuse CMS secret_key. Parent directories must allow each intended user to traverse them while files remain private. The runtime unit reads the second path; native configuration reads the first. Preserve the installation UUID/key references in backups. Rotation requires coordinated service restarts.

Adapt deployment/runtime.env.example into /etc/cms/ide-runtime.env and resource.env.example into /etc/cms/resource.env, owned root with restricted access. Replace all REPLACE_WITH values, use the same installation UUID in CMS and runtime, and set the IDE database URL, canonical HTTPS origin and numeric contest ID. Systemd reads the environment files; only service accounts read their own key. CMS_CONFIG points to the protected ordinary CMS config. Never run CMS-mode runtime with IDE_AUTH_MODE=development.

## CMS configuration

Merge these fields into the existing JSON CMS configuration; add only the new core_services coordinate alongside existing services:

~~~json
{
  "core_services": {
    "OlympiadIDEService": [["127.0.0.1", 21101]]
  },
  "olympiad_ide_enabled": true,
  "olympiad_ide_installation_id": "REPLACE_WITH_STABLE_INSTALLATION_UUID",
  "olympiad_ide_listen_address": ["127.0.0.1"],
  "olympiad_ide_listen_port": [8891],
  "olympiad_ide_runtime_url": "http://127.0.0.1:8801",
  "olympiad_ide_signing_key_file": "/etc/cms/ide-native-assertion.key",
  "olympiad_ide_request_timeout": 8,
  "olympiad_ide_max_runtime_requests": 16,
  "olympiad_ide_max_http_connections": 128,
  "olympiad_ide_max_body_bytes": 9000000,
  "olympiad_ide_max_response_bytes": 12000000,
  "olympiad_ide_trusted_proxy_addresses": ["127.0.0.1", "::1"],
  "olympiad_ide_num_proxies": 1,
  "olympiad_ide_cws_base_path": "/",
  "olympiad_ide_restart_limit": 5,
  "olympiad_ide_restart_window": 300
}
~~~

This is a merge fragment, not a complete bootable CMS config. Keep real secret_key, CMS DB/files/log paths, existing service coordinates, contest_listen_address/port and trusted ingress settings. The supplied ingress expects CWS127.0.0.1:8888. Keep AdminWebServer private on its separately protected route/network. The native service does not accept ALL. ResourceService is started as cmsResourceService 0 -a NUMERIC_CONTEST_ID and supplies -c ID to children. Direct diagnostic launcher form is cmsOlympiadIDEService SHARD -c ID.

Multiple native shards require distinct RPC entries and corresponding HTTP address/port list elements; no native HTTP/RPC or runtime listener may collide. The local two-shard smoke tested separate listeners and lifecycle. The ingress example directs one native shard; multi-shard balancing requires an operator upstream configuration and measured capacity. All shards in this supported instance use the same contest/installation/receipt database. Multi-contest routing is not implemented.

Before enablement, take backups and apply only the additive migrations in DATA_MIGRATION.md. Native readiness checks contest, receipt schema and installed assets; runtime readiness checks its own DB/mapping schema.

## Process ownership and ingress

Install the reviewed unit templates from olympiad_ide/deployment and edit paths/accounts to match the host. ResourceService is the sole owner of the native/CWS child PIDs; do not add a second direct native systemd unit or simultaneously run manual launchers.

~~~
sudo systemctl daemon-reload
sudo systemctl enable --now olympiad-runtime.service
sudo systemctl enable --now cms-resource-ide.service
sudo nginx -t
sudo systemctl reload nginx
~~~

The nginx.conf example belongs inside nginx's http block, uses real TLS certificate paths, forwards /ide/ to native and / to CWS, overwrites forwarding headers, strips client Authorization, and protects CMS cookies. It exposes no DB/RPC/private-runtime/admin route. Confirm Secure/HttpOnly/SameSite flags with an actual browser. Request-rate examples are per IP and need shared-NAT testing; they are not participant quota policy. Measure final-minute official traffic separately from background upload budgets before tuning.

Runtime is a Wants dependency, not a hard dependency that shuts CWS down. ResourceService bounds native restarts and stops retrying after the configured limit; repair the error and explicitly re-enable autorestart through CMS resource controls. Intentional stop disables autorestart before quit. Runtime systemd restart policy is separately bounded. Process groups are cleaned by their owning supervisors.

## Custom workers and CMS judging

Install the retained worker only on an approved dedicated Linux host. Review olympiad_ide/docs/PHASE4_ARCHITECTURE.md against the actual worker source: isolate helper flags/commit, root ownership/setuid helper, non-root controller, cgroupv2, quota support, no unrestricted fallback, compiler paths/versions, reserved box-ID range, CPU/memory/output/cancellation behavior and no secret mounts.

The CMS-pinned isolate submodule is not automatically a certified IDE helper/toolchain combination. Verify compatibility rather than changing CMS's pin to suit IDE workers. Preserve WORKER_SANDBOX_APPROVED gating. Run the real worker suite before setting approval for service operation. Retained worker unit paths now target /opt/cms/olympiad_ide and its separate interpreter. Do not put the API's DB secret or assertion key on the worker.

CMS judging Workers/EvaluationService/ScoringService/ProxyService retain upstream setup. For acceptance, import disposable standalone Batch C++/Python tasks with public sample and hidden judging data, enable the actual CMS language names, submit through native, and observe Worker evaluation, permitted feedback, CWS/Admin visibility and configured ranking updates. Test rejudge/token/dataset switches. Custom successful output is not evidence of CMS judging or an official score.

## Diagnostics and failure behavior

~~~
curl --fail http://127.0.0.1:8891/ide/health/live
curl --fail http://127.0.0.1:8891/ide/health/ready
curl --fail http://127.0.0.1:8801/health/live
curl --fail http://127.0.0.1:8801/health/ready
sudo journalctl -u cms-resource-ide -u olympiad-runtime --since today
~~~

CMS also writes per-coordinate logs and forwards to LogService; Checker/Admin resource status lists configured native shards. Avoid logging request bodies/cookies/assertions. A runtime503 pauses background sync; local source remains recoverable and CMS submission/CWS stay available. No worker capacity disables custom Run while official Submit stays available. CMS DB failure prevents authentication/admission and yields unavailable, never fabricated success. Telemetry gaps remain disclosed. Receipt reconciliation after ambiguous failure is GET by immutable intent before any deliberate same-body retry.

The real Linux CMS DB fault exposed stale pooled connections stranding judging. Fix 349d1e95 enables SQLAlchemy1.3 pool_pre_ping. It validates idle connections only and never replays an in-flight transaction or official POST. Preserve receipt reconciliation after ambiguous failures and review pinned gevent fork/finalization warnings before release.

Schedule existing telemetry retention maintenance using the IDE role and documented policy; monitor database/storage growth, connection use, queue age/leases, error rates and percentile latency. Use olympiad_ide/tools/CMS_LOAD.md for progressive disposable-target load, with explicit mutating flags. Linux evidence includes a progressive 350-account short workload, ten-actor deadline mixture and 350 fresh logins/context checks after restoration. These do not certify sustained 350-editor/compile capacity; see LINUX_ACCEPTANCE.

## Rollout and rollback

Complete Linux and load gates, rehearse both-database restore, verify role/network restrictions, and confirm CWS fallback before a live contest. Deploy disabled first, build/migrate/health-check, then enable during a controlled maintenance window. Back up identity/configuration and source storage with the databases.

To roll back, disable native config and intentionally stop it through ResourceService, remove /ide ingress routing, and stop independent runtime/custom workers as appropriate. Preserve all new tables, code/source archives and local browser data. Ordinary CWS continues; its fallback submissions have no invented IDE correlation. See DATA_MIGRATION.md for restored-ID caveats.
