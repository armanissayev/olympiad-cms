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
