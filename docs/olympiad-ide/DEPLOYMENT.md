# Build, deployment and operations

## Tested boundary

The integration passed a real disposable Ubuntu 26.04.1 staging rehearsal on the explicitly authorized host, including all 26 Linux sandbox tests, actual CMS C++/Python judging, real-worker native browser recovery, separate service/database outages and matched database/application restoration. See [LINUX_ACCEPTANCE](LINUX_ACCEPTANCE.md) and the [staging procedure](../../olympiad_ide/tools/linux_staging/README.md) for exact commands, versions, corrected configuration and remaining limits. Earlier macOS/local evidence remains historical.

The generic /opt/nginx/systemd templates below require adaptation and review for production. The tested staging layout uses separate official/custom execution accounts, ResourceService owners and restricted helper permissions. Dedicated production worker hosts and production sizing remain release gates. No production host or DNS was changed; the explicitly authorized staging80/443 follow-up is recorded below.

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

Use separate cms and olympiad_ide databases. Existing CMS configuration owns the CMS DB. IDE migrations use a separate schema-owner role, API uses an IDE DML-only role, and the ordinary custom worker uses ide_worker with execution-table privileges from deployment/worker-role.sql. The separate debug controller also needs the additive f6 grants in DATA_MIGRATION.md; the earlier worker-role.sql alone does not grant debug access. No worker CMS credentials, source-test storage mount or RPC network access.

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

The nginx.conf example belongs inside nginx's http block, uses real TLS certificate paths, forwards /ide/ to native and / to CWS, overwrites forwarding headers, strips client Authorization, and protects CMS cookies. It exposes no generic private-runtime/DB/RPC/admin route. The sole direct ASGI exception is the exact UUID DAP WebSocket queue route described below, protected by a CMS-issued one-use capability. Confirm Secure/HttpOnly/SameSite flags with an actual browser. Request-rate examples are per IP and need shared-NAT testing; they are not participant quota policy. Measure final-minute official traffic separately from background upload budgets before tuning.

Runtime is a Wants dependency, not a hard dependency that shuts CWS down. ResourceService bounds native restarts and stops retrying after the configured limit; repair the error and explicitly re-enable autorestart through CMS resource controls. Intentional stop disables autorestart before quit. Runtime systemd restart policy is separately bounded. Process groups are cleaned by their owning supervisors.

## Custom workers and CMS judging

Install the retained worker only on an approved dedicated Linux host. Review olympiad_ide/docs/PHASE4_ARCHITECTURE.md against the actual worker source: isolate helper flags/commit, root ownership/setuid helper, non-root controller, cgroupv2, quota support, no unrestricted fallback, compiler paths/versions, reserved box-ID range, CPU/memory/output/cancellation behavior and no secret mounts.

The CMS-pinned isolate submodule is not automatically a certified IDE helper/toolchain combination. Verify compatibility rather than changing CMS's pin to suit IDE workers. Preserve WORKER_SANDBOX_APPROVED gating. Run the real worker suite before setting approval for service operation. Retained worker unit paths now target /opt/cms/olympiad_ide and its separate interpreter. Do not put the API's DB secret or assertion key on the worker.

CMS judging Workers/EvaluationService/ScoringService/ProxyService retain upstream setup. For acceptance, import disposable standalone Batch C++/Python tasks with public sample and hidden judging data, enable the actual CMS language names, submit through native, and observe Worker evaluation, permitted feedback, CWS/Admin visibility and configured ranking updates. Test rejudge/token/dataset switches. Custom successful output is not evidence of CMS judging or an official score.

## Phase6 debugger deployment

The current workbench exposes Run active file, larger STDIN File/STDOUT File, diagnostics and the separate history/debug views. It no longer exposes an interactive Terminal, Problems/Test Cases tabs, saved run list or Run All. Existing baseline/evidence documents retain the earlier behavior as historical observations.

Keep CMS's Python3.12 environment separate from the IDE runtime. On the tested Ubuntu host, distro GDB17.1 supplies native DAP, systemPython3.14.4 supplies debugpy1.8.19, and OpenJDK17 supplies JDI. C++ is compiled with a fixed `-g -O0` profile inside isolate; Python uses a trusted fixed-STDIN wrapper; the project-owned standalone Java adapter and all generated inner classes are installed root:root0644 under root-owned0755 `/usr/local/share/olympiad-debug`. Compile only trusted helper source during host installation. Participant code always compiles/executes inside isolate. Exact package provenance, Java helper commands and licensing limits are in [JAVA_DEBUGGER](JAVA_DEBUGGER.md).

Apply IDE-only migration f5a001→f6a001 after a protected IDE backup and Alembic review/check, then grant the API DML and debug controller's narrow column/table access from [DATA_MIGRATION](DATA_MIGRATION.md). The three new tables are debug_sessions/debug_messages/debug_workers; no CMS migration is added. The one-time credential-free [provision-debug.py](../../olympiad_ide/tools/linux_staging/provision-debug.py) retains the staging helper/install/backup/migration/grants/environment/unit procedure. It requires a disposable marker and exact reviewed database name, refuses existing debug configuration and never approves/starts the worker. Its consolidation was syntax-checked, not rerun on a second host.

Use a distinct `worker.app.debug_main` service with the non-root execution account, separate box600, PrivateNetwork and its own root-only debug.env. Do not add a native CMS launcher or change ResourceService child ownership. The controller needs no CMS DB/RPC credentials or assertion key. Both WORKER_SANDBOX_APPROVED and DEBUG_SANDBOX_APPROVED must equal1 before it advertises capacity. Review the unchanged26mandatory Run prerequisites, the debug suite and all three actual language probes before recording separate debug approval. Do not enable either approval merely to collect tests.

The initial actual debug prerequisite run passed8cases/5.13s. The final deployed-source run passed10cases/5.05s, both approval variables unset, no skips; its4policy checks and6real Linux cases are distinct from the26Run cases. The actual command used by the reviewed update is:

```sh
cd /opt/cms-ide-stage/source/olympiad_ide
sudo runuser -u ideworkerstage -- env -u WORKER_SANDBOX_APPROVED -u DEBUG_SANDBOX_APPROVED \
 PYTHONPATH=backend:. PATH=/usr/local/bin:/usr/bin:/bin RUN_LINUX_DEBUG_TESTS=1 \
 /opt/cms-ide-stage/runtime-venv/bin/python -m pytest worker/tests/test_debugger.py -vv -p no:cacheprovider
# Separate actual language probes use reserved610/611/650 boxes; do not collide with live sessions.
```

See [Phase6 architecture](../../olympiad_ide/docs/PHASE6_ARCHITECTURE.md) for security limits, exact language probes, grants and the initial approval/start commands. `update-workbench.sh` is a separate reviewed update path: it requires an existing DEBUG_SANDBOX_REVIEW and approval, stops only owned staging supervisors, reruns all10cases with approvals unset, installs CMS/runtime independently with umask022, checks both environments and starts the original owners. It retains approval; it does not grant initial approval or apply a missing migration. Run the staging update inside tmux as described in [PUBLIC_HTTPS](PUBLIC_HTTPS.md).

Native REST requests, including debug session creation and ticket renewal, still pass CMS cookie/XSRF/principal/task/phase authorization. Because the pinned native WSGI stack cannot upgrade WebSockets, nginx has one exact canonical-UUID route `/ide/api/debug/sessions/{UUID}/dap` to the private ASGI queue broker. Use the reviewed nginx template or staging `install_debug_ws.py`: reject query strings, overwrite forwarding/upgrade headers, strip Authorization, disable buffering and allow330seconds proxy read time. Keep the private runtime listener on loopback; expose no generic ASGI or adapter endpoint. Set Uvicorn `--ws-max-size 32768 --ws-max-queue 4`, as in the retained runtime unit.

The browser authenticates that socket using a30second one-use token obtained through native CMS; only a hash is stored, and authorization refreshes every20seconds through CMS. Tokens must never enter URLs/logs. The server enforces exact Origin, source-bound controls, five-minute session expiry, quotas and cancellation; workers run real adapters/debuggees in fresh isolate with debug-specific limits. No direct debugger daemon is public. See [SECURITY](SECURITY.md) for the full boundary and avoid widening the path allowlist to make a failing adapter work.

Final deployment source is `e9044e7b03032018b038a03c8fad2abf4d551bfa`. Both Python pip checks passed, owned services were active and systemctl reported no failed units after deployment. These operational checks and direct adapter prerequisites do not alone establish public-browser Pause/Stop or representative debugger capacity. Final public acceptance is recorded separately in [WORKBENCH_ACCEPTANCE](WORKBENCH_ACCEPTANCE.md) and [final prerequisite evidence](evidence/workbench-vnext/debug-security-final.log).

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

To roll back, disable native config and intentionally stop it through ResourceService, remove /ide ingress routing, and stop independent runtime/custom/debug workers as appropriate, including the exact DAP WebSocket ingress route. Preserve all new tables, code/source archives and local browser data. Ordinary CWS continues; its fallback submissions have no invented IDE correlation. See DATA_MIGRATION.md for restored-ID caveats.

## Public staging access

The authorized 3 November follow-up added public HTTPS at https://54.206.171.67/ and /ide/, with a trusted IP certificate, isolated Certbot environment, automatic renewal and boot-enabled supervisors. See [PUBLIC_HTTPS](PUBLIC_HTTPS.md) for actual evidence, configuration and preserved failures. Admin/RPC/DB endpoints remain private. This changes the earlier loopback-only staging boundary and does not certify production readiness.

## Participant/Admin workflow follow-up

Current application 5106855e is deployed using the existing tmux updater and unchanged supervisors. [PARTICIPANT_ACCEPTANCE](PARTICIPANT_ACCEPTANCE.md) records actual 130/97/759 frontend/runtime/Linux-CMS results and both browser flows. Admin code history is served by the existing private AdminWebServer with lazy optional PyJWT import; feature-disabled ordinary Admin startup is tested. No schema migration/new grants or additional public port is required. Run the retained reverify_linux.py preflight before the isolated suites; cms-unit.conf must exist rather than silently falling back.
