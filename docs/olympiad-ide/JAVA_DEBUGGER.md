# Java interactive debugger

`olympiad_ide/worker/adapters/OlympiadJavaDAP.java` is a self-contained JDK17 JDI adapter. It uses the real launched JVM and implements DAP initialization, fixed-snapshot launch, source breakpoints, thread/stack/scopes/variables inspection, Continue, Pause, Step Over, Step Into, Step Out and Disconnect. It does not emulate breakpoint or variable state.

Build the trusted adapter as the installer, then expose its compiled files read-only inside approved debug sandboxes:

```sh
javac --add-modules jdk.jdi -d /usr/local/share/olympiad-debug olympiad_ide/worker/adapters/OlympiadJavaDAP.java
```

The sandbox starts it with the resolved JDK17 executable and arguments `--add-modules jdk.jdi -Xmx128m -cp /usr/local/share/olympiad-debug OlympiadJavaDAP`. Do not execute participant programs outside isolate. The launching connector starts the debuggee using that JDK's `java.home`, a fixed `/box/__debug_build` classpath and bounded heap/metaspace/code cache. Source paths must belong to the immutable `/box` Java snapshot. Fixed stdin comes only from `/box/__debug_stdin` and is asynchronously fed to the debuggee, so a large input cannot deadlock the suspended launch handshake.

JDI uses loopback inside the sandbox's fresh network namespace. The pinned isolate initializes only that namespace's loopback; host networking is not shared. Adapter and debuggee remain in the same bounded cgroup and sandbox UID. No CMS/API credentials are passed. The trusted controller and API own the allowed launch settings and DAP command set.

DAP messages are Content-Length framed UTF-8 JSON with a64KiB bound, finite JSON depth and no external Java dependencies. Array/object/local lists are bounded to100 children and aggregate frame size. Object inspection reads JDI fields without invoking participant methods or `toString()`. Identifier/field-path inspection exists in the adapter; arbitrary evaluation/function calls/conditional breakpoints are not advertised. Standard-platform frames are not falsely mapped to same-basename participant files. References expire when execution resumes. VMStart and repeated Pause/configuration handling preserve real JDI suspension counts.

## Actual Linux acceptance

On the authorized staging host, a trusted `javac17` compiled this adapter and the non-root ideworkerstage controller ran a real Java fixture through unchanged isolate box650, cgroup1GiB,64-process, syscall31, quota and fresh-netns controls. Both service approval environment variables were unset during the prerequisite probe. No CMS service was restarted by this test.

Eight actual checks passed:

1. Breakpoint at source line10.
2. Locals `a=2,b=3` and read-only identifier inspection.
3. Step Into enters `Main.add`.
4. Step Over exposes computed local `z=5`.
5. Step Out returns to `Main.main`.
6. Continue reads fixed stdin and emits actual stdout5.
7. Pause suspends the running JVM.
8. Disconnect terminates debuggee and adapter.

The portable acceptance helper is `worker/tests/java_debugger_probe.py`; from `olympiad_ide`, use `PYTHONPATH=backend:. python worker/tests/java_debugger_probe.py` on an approved disposable Linux host with box650 reserved. The early deployment probe loaded the exact trusted controller module from an external temporary file before the complete worker deployment. It found `/usr/bin/java` and `/usr/bin/javac` symlinks traverse `/etc/alternatives`, absent inside the sandbox. Worker toolchain paths now resolve to their real `/usr` locations, matching the retained normal execution adapter. No security mount or unrestricted fallback was added.

These tests establish real JDI control behavior, not CMS browser end-to-end debugger authorization, concurrent session capacity or all sandbox-abuse cases. Combined worker/security/browser acceptance is required before enabling the dedicated debug service.

## Adapter licensing and standalone deployment audit

Checked against the packages actually installed on the authorized staging host on 3 November 2026:

| Component | Installed provenance and licensing | Standalone use |
| --- | --- | --- |
| GDB native DAP | Ubuntu `gdb 17.1-2ubuntu1`; `/usr/share/doc/gdb/copyright` identifies the main sources as GPL-3+. Some bundled/packaging files have additional notices. | GDB's own Python-enabled `--interpreter=dap`, with user initialization/auto-load/debuginfod disabled; no VSCode C++ extension is required. The real C++ isolate probe passed. |
| Python debugpy | Ubuntu `python3-debugpy 1.8.19+ds-1ubuntu3`; installed copyright identifies the core as Expat/MIT and versioning support as CC0. The package also owns the installed vendored `pydevd.py`; no deployment patch or copied pydevd tree was used. | `/usr/bin/python3 -m debugpy.adapter` plus the small project-owned fixed-input wrapper; no VSCode Python extension is required. The real Python isolate probe passed. |
| Vendored PyDev.Debugger | Upstream debugpy's ThirdPartyNotices identifies PyDev.Debugger under EPL-1.0 and includes further third-party notices. The distro metadata lists a repacking exclusion, yet `dpkg-query -S` confirms this installed vendored tree belongs to python3-debugpy. Treat the overall component inventory as more than MIT alone. | It remains the distro-installed dependency inside the sandbox; its code is not copied into CMS or relicensed by this integration. |
| OpenJDK/JDI | Ubuntu `openjdk-17-jdk-headless 17.0.20.1+1-1~26.04`; its installed copyright states GPL2 with Classpath exception and includes third-party notices. The JDI module's installed legal directory retains its Assembly Exception. | The project-owned adapter uses the standard `jdk.jdi` module and launching connector. No Eclipse/JDT server, Microsoft Java extension, marketplace binary, Maven download or external IDE process is needed. |
| OlympiadJavaDAP and wrappers | New project source carries AGPL-3.0-or-later SPDX, consistent with CMS. It has no external JSON library and does not copy another Java debug adapter. | Trusted helper files are installed into a root-owned 0755 directory; actual Java class and Python wrappers were verified root:root 0644. Worker/controller UIDs cannot modify them. |

Primary references: [GDB interpreter documentation](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Interpreters.html), [debugpy upstream MIT licence](https://github.com/microsoft/debugpy/blob/main/LICENSE), [debugpy upstream third-party notices](https://github.com/microsoft/debugpy/blob/main/src/debugpy/ThirdPartyNotices.txt). The two upstream debugpy links describe current upstream notices; the exact installed package/version and the vendored-file ownership were separately checked above. Retain the distributor's full copyright/notice/source information if redistributing those packages; the short table is not a substitute for it. This inventory establishes provenance and standalone deployment suitability, not a new legal compatibility certification or a complete transitive licence/advisory review.

### Reproducible Java helper installation

Compare the reviewed source to `evidence/java-debugger.json` before compiling. For the accepted adapter revision its SHA256 is `76c7a3bf13621909f0d814f503f5548ae62d6e068e8fb9c8c0bbe53ca429cc3d`. Run these installer commands as root on the dedicated debug host, from the reviewed CMS source checkout:

```sh
stage_java_source="$PWD/olympiad_ide/worker/adapters/OlympiadJavaDAP.java"
printf '%s  %s\n' '76c7a3bf13621909f0d814f503f5548ae62d6e068e8fb9c8c0bbe53ca429cc3d' "$stage_java_source" | sha256sum --check
stage_java_build="$(mktemp -d /tmp/olympiad-jdi-build.XXXXXX)"
/usr/bin/javac --add-modules jdk.jdi -d "$stage_java_build" "$stage_java_source"
install -d -o root -g root -m 0755 /usr/local/share/olympiad-debug
for stage_java_class in "$stage_java_build"/*.class; do
    install -o root -g root -m 0644 "$stage_java_class" /usr/local/share/olympiad-debug/
done
install -o root -g root -m 0644 olympiad_ide/worker/adapters/python_entry.py /usr/local/share/olympiad-debug/python_entry.py
install -o root -g root -m 0644 olympiad_ide/worker/adapters/stdin_wrapper.py /usr/local/share/olympiad-debug/stdin_wrapper.py
```

Install **all** generated Java classes, including `OlympiadJavaDAP$Json.class`; copying the top-level class alone is incomplete. The protected temporary compiler output can be retained for operator inspection. A changed source revision requires a newly reviewed hash and fresh actual probe; do not reuse this digest blindly. Compile trusted adapter code only. Participant Java sources are compiled later inside isolate with fixed `javac --release 17 -g` settings by the debug controller, never by these host installer commands.

The source archive's MANIFEST explicitly includes Java/Python adapter sources and the real probe. Compiled `.class` files belong to the debug-host installation and are excluded from source delivery. A read-only packaging audit built a working-source snapshot outside the repository: required CWS/templates/styles, backend migration, replay/debug frontend and all three helper sources were present; all 13 generated public asset hashes matched the source archive and CMS wheel; no generated dependencies, private keys, environment files, dumps or compiled Java classes were included. Temporary audit report: `/private/tmp/cms-phase56-package-review-u8th39_l/report.json`. This was an in-progress source snapshot; the final combined release should rebuild from its final commit.
