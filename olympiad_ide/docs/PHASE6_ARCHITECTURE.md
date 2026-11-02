# Phase6 — actual restricted interactive debugging

The debugger uses real GDB DAP, debugpy and a standalone Java JDI adapter. It does not synthesize pause/variable/step state or run participant programs in the HTTP API. Source is captured from live Monaco models once; debug execution uses that immutable manifest even if the editor changes afterward. Breakpoints belong to stable file IDs and remain in the scoped local workspace. Best-effort live line relocation applies to the next session, not an already captured program.

## Transport and authorization

1. Native CMS validates the participant cookie, XSRF, principal, task membership and phase. Existing task capabilities restrict debugging to the same standalone stdin/stdout Batch slice as custom Run. Official Submit remains independent.
2. Versioned POST `debug/sessions` accepts a validated ExecutionSubmit source envelope, recomputes its canonical source hash, checks ownership and rejects reserved `__debug_` paths/invalid UTF-8. The input envelope retains the existing Run configuration schema; actual debug compilation is always the fixed debug profile below, irrespective of its compatibility `compilerProfile: release` field.
3. The private runtime stores snapshot, session, DAP command/event journal and worker liveness in three additive IDE-only tables. No CMS table or SQLAlchemy environment is shared.
4. Authenticated POST `debug/sessions/{id}/attach` issues an opaque random token. Only its SHA256 is stored; it expires in30seconds and is consumed once under a row lock. Issuance rechecks CMS owner/task binding. Tokens never enter URL/query/access logs.
5. An exact nginx WebSocket route maps `/ide/api/debug/sessions/{UUID}/dap` to the private ASGI debug gateway. This is a bounded authenticated queue broker, not a debugger daemon. It requires an exact configured Origin, no query string and a valid token in its first frame. The browser refreshes authorization through CMS every20seconds. Expired authorization or authenticated disconnect cancels the session; the worker deadline/lease is an independent fallback.
6. Gateway messages are bounded to32KiB and20commands/second. A strict allowlist permits initialize/launch/breakpoints/configuration/threads/stack/scopes/variables/control/disconnect. Attach, arbitrary adapter configuration, expression evaluation, host commands, memory writes and reverse runInTerminal are unavailable. The worker replaces all initialize/launch arguments with trusted fixed settings. Source breakpoints must name captured files.

Queue admission is globally serialized and bounded to32active/unexpired sessions; each principal has one active session and20starts/hour. Each session accepts at most1000commands,5000events and1MiB total adapter output. DAP frames cap at64KiB; oversized/malformed output terminates the real session rather than inventing results. Frames/variables returned to React are inert text. Persisted high-level DEBUG_STARTED/ACTION/FINISHED observations use the retained telemetry schema; DEBUG_BREAKPOINT_CHANGED records stable file IDs and a nullable real session ID before Start, without inventing a debugger session; source-changing histories remain independent.

## Worker boundary and profiles

`worker.app.debug_main` is a separate service under the existing dedicated ideworkerstage execution account, PrivateNetwork and no CMS credentials/helper keys. It uses box600, separate from ordinary custom200, native judging0 and prerequisite610–650 ranges. No direct DAP TCP port exists outside isolate. IDE DB grants permit SELECT of execution/debug inputs, INSERT protocol events and UPDATE only status/lease/cancellation/result columns, not ownership, snapshots or attach-token columns.

Both `WORKER_SANDBOX_APPROVED=1` and the separate `DEBUG_SANDBOX_APPROVED=1` are required before advertising capacity or claiming sessions. The new approval belongs only to root-owned `/etc/cms-ide-stage/debug.env`, after actual language/isolation prerequisites are reviewed. Missing toolchains or sandbox facilities fail closed. There is no unrestricted subprocess fallback.

Each real adapter and its debuggee share a fresh isolate box with its own network/PID/filesystem namespaces, cgroup v2,64MiB/1024-inode disk quota and `--syscalls=31`. Only the isolated namespace's loopback is up, which debugpy/JDI need internally; neither host networking nor CMS sockets are shared. Controller environment is reduced to PATH, and the sandbox receives an explicit non-secret environment. Adapter/debuggee defaults are300seconds wall,30seconds CPU,1GiB aggregate memory,64processes/threads,128file descriptors,1MiB per-file write limit and1MiB aggregate protocol output. Compilation uses the existing Sandbox compile profile (512MiB memory,64file descriptors,64MiB per-file limit), still inside the same64MiB filesystem quota. These are debug-only limits and do not loosen ordinary Run policy. Cleanup terminates adapter/debuggee together on stop, timeout, output failure, DB heartbeat loss or transport cancellation.

- C++17/20: official distro GDB17.1 native DAP; fixed `g++ -g -O0 -fno-omit-frame-pointer`, correct standard, no arbitrary flags. Trusted stdin exec wrapper reads `/box/__debug_stdin`, then execs the fixed captured executable. User initialization/auto-load/debuginfod are disabled.
- Python: official distro debugpy1.8.19 in systemPython3.14.4; internal console/redirected output, no subprocess debugging. A trusted runpy entry installs the captured fixed STDIN and retains real user source locations. Runtime/CMS interpreters remain separate Python3.12 environments.
- Java17: project-owned standalone JDI DAP adapter, no Maven/network dependency. JDI and debuggee communicate only inside the box. Javac emits real line/local metadata; JVM heaps are bounded. Executables resolve `/etc/alternatives` links to real `/usr` paths before entering isolate. See JAVA_DEBUGGER.md for actual tests and adapter provenance/licensing.

GDB is GPL-3.0-or-later; debugpy uses MIT with separate vendored dependency notices; OpenJDK17/JDI uses GPLv2 with Classpath Exception; the new adapter follows the repository's source licence. Installed distro licences remain under `/usr/share/doc`. Their official protocols/code were inspected; the adapter is verified standalone rather than requiring VSCode or a public debug daemon. Release-wide licence/advisory review remains separate from these observations.

## Additive migration and staging commands

The linear IDE chain advances f5a001→f6a001. Before applying it, a protected custom-format dump of the active restored IDE DB was taken under `/var/lib/cms-ide-stage/backups/debug-rollout-20261103`,0700directory/0600dumps. Alembic upgrade and check succeeded. The first candidate tar accidentally included Mac AppleDouble files, causing an early null-byte migration-module parse failure; only candidate `._*` metadata was removed before the successful run. No core schema was reset, no CMS DB was migrated, and rollback refuses to delete populated debug history.

Install official `gdb python3-debugpy`, compile `worker/adapters/OlympiadJavaDAP.java` using javac17 into root-owned `/usr/local/share/olympiad-debug`, and install the two trusted Python wrappers there0644. Keep the helper directory root-owned/non-writable. Then build/install the source and apply only the IDE migration as its owner. Grant API DML on the3new tables and execution controller the narrow grants above. The dedicated debug systemd unit uses the same source tree and separate runtime venv, with private networking and an independent box range. Do not start it until review enables its separate flag.

Run real prerequisites **without** either approval variable:

```sh
cd /opt/cms-ide-stage/debug-candidate
sudo runuser -u ideworkerstage -- env -u WORKER_SANDBOX_APPROVED -u DEBUG_SANDBOX_APPROVED \
 PYTHONPATH=backend:. PATH=/usr/local/bin:/usr/bin:/bin RUN_LINUX_DEBUG_TESTS=1 \
 /opt/cms-ide-stage/runtime-venv/bin/python -m pytest worker/tests/test_debugger.py -vv -p no:cacheprovider
sudo runuser -u ideworkerstage -- env -u WORKER_SANDBOX_APPROVED -u DEBUG_SANDBOX_APPROVED \
 PYTHONPATH=backend:. PATH=/usr/local/bin:/usr/bin:/bin \
 /opt/cms-ide-stage/runtime-venv/bin/python worker/tests/debugger_language_probe.py cpp20
# Repeat with python3, then worker/tests/java_debugger_probe.py.
```

The candidate sources are isolated from live deployments. Once installed, equivalent paths use `/opt/cms-ide-stage/source/olympiad_ide`. Tests must reserve their ranges and never collide with active sessions. Java probe650 is documented separately. A full application deployment/restart belongs to the owning ResourceService/runtime supervisors, not this candidate probe.

### Retained one-time provisioning and approval

`tools/linux_staging/provision-debug.py` retains the executed setup as a credential-free, parameterized consolidation. It was syntax-checked locally; the entire consolidation has not been rerun on a second host. It requires the disposable marker and a reviewed exact IDE database name, refuses an existing debug unit/environment, takes a new protected dump, upgrades only through f6a001, checks Alembic, installs root-owned helpers and creates the independent unit. It never sets DEBUG_SANDBOX_APPROVED or starts/enables the worker. Existing hosts already provisioned must use the separate reviewed update procedure, not rerun this one-time installer.

```sh
# Fresh authorized staging only; choose the exact reviewed IDE database, never CMS DB.
sudo python3 /opt/cms-ide-stage/source/olympiad_ide/tools/linux_staging/provision-debug.py \
 --expected-database ide_linux_staging --install-packages
# For the historical restored DB, use its exact protected configuration name instead.
```

The precise grants are:

```sql
GRANT SELECT,INSERT,UPDATE,DELETE ON debug_sessions,debug_messages,debug_workers TO ideapistage;
GRANT SELECT ON debug_sessions,debug_messages,debug_workers TO ideworkerstage;
GRANT UPDATE(status,lease_token,heartbeat,cancelled,output_bytes,last_event,error) ON debug_sessions TO ideworkerstage;
GRANT INSERT ON debug_messages TO ideworkerstage;
GRANT INSERT,UPDATE ON debug_workers TO ideworkerstage;
```

After all mandatory26 Run prerequisites, all10 debug prerequisites and the three real language probes pass, review their exact logs, hashes, helper permissions and security results. Record the reviewer/date/evidence in root-owned `/opt/cms-ide-stage/DEBUG_SANDBOX_REVIEW`. Only after that review may the operator append `DEBUG_SANDBOX_APPROVED=1` to root-only `/etc/cms-ide-stage/debug.env`, then run:

```sh
sudo systemctl enable --now cms-ide-stage-debug.service
sudo systemctl status cms-ide-stage-debug.service --no-pager
sudo journalctl -u cms-ide-stage-debug.service --no-pager -n 30
```

Enabling a unit does not certify reboot recovery. Missing approval/toolchains fail closed. Keep the existing ResourceService/native judging units independent. The final ASGI service also needs transport-level WebSocket size/queue bounds, alongside application validation; these are deployment settings and do not expose a public adapter port.

### Full runtime verification command

```sh
cd /Users/isaevarman/Developer/cms/olympiad_ide/backend
TEST_DATABASE_URL=postgresql+psycopg://isaevarman@127.0.0.1:55459/ideruntime \
 /private/tmp/olympiad-runtime-venv/bin/python -m pytest -ra --tb=short
# Final:87passed,1warning,14.07s. Each test creates/drops its own schema.
```

## Actual evidence and limits

- Real GDB isolate610: fixed STDIN2, breakpoint, stack/local a=2, StepInto/StepOut/StepOver/Continue, stdout3, normal termination. Initial GDB pending-source diagnostic precedes symbol load; the actual later breakpoint and values prove binding.
- Real debugpy isolate611: same fixed input, actual breakpoint, locals/stack and four controls, stdout3, normal termination.
- Real Java isolate650: eight actual JDI checks including locals a2/b3/z5, call-stack transitions, all steps, fixed input/output5, Pause and Disconnect; final source matches compiled adapter.
- Initial debug-specific Linux prerequisite suite:8passed, no skips,5.13seconds, both approval variables unset. Two later nonblocking-pipe policy checks passed locally, bringing the collected suite to10 (4policy/6real); the final deployed10-case run is recorded in the deployment report. It checks incremental/bounded frames/reverse-RPC rejection, actual debugpy credential/network/syscall denial, cancellation cleanup, output-budget cleanup, debug process-limit quota enforcement, real1GiB cgroup OOM containment and neighboring box isolation.
- Initial real PostgreSQL control plane:8targeted tests passed. Final full runtime suite:87passed,1Starlette TestClient deprecation warning,14.07seconds, using Python3.12.6 and real PostgreSQL isolated schemas. It includes11debug cases plus strict pre-session breakpoint telemetry validation, alongside the pre-existing runtime cases. It checks worker availability, exact source digest, ownership/budget/idempotency, source/command allowlisting, one-use/replayed/expired WS tickets, Origin rejection, disconnect cancellation, CMS task/participant isolation and durable terminal state after worker faults. Control-plane fault doubles execute no participant code and are separate from actual Linux adapter probes.
- The first final-suite attempt was84passed/1failed: replay-token cleanup was observed before the asynchronous disconnect commit completed. A deterministic test then reproduced direct ASGI task cancellation abandoning a delayed real DB cleanup commit. The fix shields cleanup from AnyIO and direct asyncio cancellation and propagates cancellation after the commit. The final87case run includes that regression; the earlier failure is preserved, not discarded.

Sanitized outputs live under docs/olympiad-ide/evidence/phase6 and java-debugger.json. Public browser integration is verified separately by the root deployment report; direct adapter probes do not alone prove public WebSocket login/UI operation. Session retention/pruning and sustained350debugger capacity remain operator/release work. Adapter/runtime failures are explicit; no fabricated values or success states are substituted.

Adapter licence/standalone-install audit: see [JAVA_DEBUGGER.md](../../docs/olympiad-ide/JAVA_DEBUGGER.md). The deployed API also caps Uvicorn WebSocket messages at32768bytes with a4message queue, before application limits.
