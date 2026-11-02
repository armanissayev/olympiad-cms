# Implementation state

Updated 2 November 2026. Checkout `/Users/isaevarman/Developer/cms`, branch `feature/olympiad-ide-integration`. CMS base `CMSv1.5.1`, `7c9fec8aa1a25ec93d624aebf815804dd93df9db`; original integration `7c2bd34d16a6ae9bc263feb660bb60505c31bfab`. The deployed application includes `349d1e9559023b57b28d3e0dac95ca2b97c4a0dc`, the verified idle-connection recovery correction. A following commit records the completed Linux rehearsal. No push, PR or production merge was performed.

## Status

| Dimension | Classification |
| --- | --- |
| Native integration | Implemented; original source preserved; CMS authentication, lifecycle, admission, feedback and fallback retained |
| Linux custom execution and official judging | **Passed on authorized disposable staging**, including all 26 mandatory sandbox tests and actual C++/Python CMS results |
| Browser and recovery milestone | **Passed**, including real Run/Stop/Submit, refresh, offline and lost-response recovery after database restoration |
| Outage, backup and role rehearsal | Passed component/DB faults, CWS fallback, execution-account restrictions and matched database/application restoration |
| Participant workload | Progressive 350-account short workload and final 350-account login/context check executed; five original short-poll assertions remain failures, with later actual scores of 100 verified |
| Live contest readiness | **Not certified**: sustained representative 350-editor/compile/deadline capacity and production security, licensing, timing, TLS, backup and recovery gates remain |

[LINUX_ACCEPTANCE](LINUX_ACCEPTANCE.md) contains the complete 12-requirement acceptance report. [VERIFICATION](VERIFICATION.md) records current and historical counts. Sanitized logs/JSON are in [evidence/linux-staging](evidence/linux-staging/); [staging commands and scripts](../../olympiad_ide/tools/linux_staging/README.md) retain corrected provisioning and acceptance steps. Earlier evidence remains labeled as historical local verification.

## Current running beta

Only the explicitly authorized `ec2-54-206-171-67.ap-southeast-2.compute.amazonaws.com` was accessed. It runs Ubuntu 26.04.1/x86_64 with two logical CPUs and approximately 3.7 GiB RAM. Python 3.12.16 runs in separate CMS and IDE venvs; SQLAlchemy 1.3 and 2.1 remain separate. PostgreSQL is 18.6; execution uses isolate 2.7, G++ 15.2, CPython 3.14.4 and OpenJDK 17.0.20.1.

All eight task-owned application/database units and isolate are active. CMS ResourceService 0 owns native/CWS/ES/SS/Admin/Proxy under cmsstage; ResourceService 1 owns the official Worker under cmsjudgestage. The custom worker uses ideworkerstage, PrivateNetwork and execution-only DB grants. The root:isolatestage helper has mode 4750 and is unavailable to web/API accounts. Worker approval was enabled only after all 26 real tests passed and were reviewed; all 26 passed again after permissions were tightened.

Participant/native: `https://localhost:28443/ide/`; admin port 28444; ranking port 28445, through the task-owned SSH tunnel. All application/RPC listeners are loopback, and PostgreSQL uses a Unix socket only. Protected local access details: `/private/tmp/cms-linux-staging/STAGING_ACCESS.txt`, mode 0600. No credentials are in Git. The dedicated localhost certificate lasts seven days and the fixture contest two days. No public HTTP ingress, DNS, security group, firewall or other AWS resource was changed.

Contest 1, `ide-load-linux-staging`, contains cppsum/pysum with public and hidden Batch tests and 351 generated participants. Staging now runs from restored copies `cms_restore_21c7bd2d5bfortesting` and `ide_restore_d4008d5dedfortesting`; the original databases remain retained. Restoration compared all 28 CMS and 21 IDE tables, row/schema/sequence/large-object bytes, 28 native source references, 351 principals and 353 workspace bindings. Protected dumps/configuration archives remain on the host. The real browser and 350-account login/context check passed afterward.

## Verification and remaining issues

Linux CMS: **746 passed, 9 skipped, 28 subtests passed**. Runtime: 75 passed. Frontend: 81 passed plus lint/typecheck/build. Mandatory worker suite: 26 passed twice. Remaining worker policies: six passed and one expected non-Linux skip. Native browser: 14 checks and zero page errors. Actual correct C++/Python solutions scored 100; real CE/WA/RTE/TLE, CWS/Admin/ranking, tokens, rejudging, dataset switching, outages, deadline behavior and restored application recovery passed. Admission alone is never reported as successful judging.

A real CMS DB outage exposed a dead pooled connection that stranded judging. Commit 349d1e95 validates idle connections; a terminated-backend regression failed before and passed after the fix, followed by the complete CMS suite and real fault retest. It does not retry in-flight work. Pinned gevent 25.5.1 still emits ignored fork/thread and finalization warnings with Python 3.12.16; compatibility/security review remains necessary.

The main progressive run produced 4,561 HTTP requests with zero HTTP errors, but five final-state assertions expired before real scoring. All five known admissions later scored 100; the original exit 1 report is preserved. The independent ten-actor deadline mixture produced 420 HTTP requests with zero errors; the final 350 fresh logins/context check produced 1,400 with zero errors. At most 12 HTTP actors ran concurrently with small programs and short telemetry. This does not establish sustained capacity for 350 simultaneous Monaco editors, compilers or final-minute submissions.

## Release work remaining

1. Review the Linux report, recovery fix, diffs and gevent warnings; complete dependency/advisory and original IDE licensing/attribution review.
2. Agree representative contest source sizes, test costs, arrival rates and latency/queue budgets. Explicitly authorize any additional resources before sustained 300–350-editor, compile-contention, deadline-burst and disk-pressure tests.
3. Rehearse dedicated production worker hosts/networking, timing calibration, production TLS/ingress/rates/roles/retention, off-host encrypted recovery and reboot/autostart.
4. Review release gates and schedule deployment, retaining CWS fallback and matched installation/identity/key backups. This rehearsal does not authorize a live contest migration or rollout.

All 124 original authoritative IDE source hashes still match. The original key and source were preserved. Historical local fixture processes/cluster remain stopped. Linux test clients and sampler completed; no recurring automation was created. The beta, tunnel and protected artifacts remain for review. Packaging includes the new regression, staging tools and sanitized evidence; dependencies, secrets, dumps and generated configurations remain excluded.

## Public access follow-up — 3 November 2026

The reported localhost outage was a lost SSH tunnel; AWS CMS services remained active. The tunnel was restored. A persistent `cms-staging-ops` tmux session and boot enablement for the existing supervisors are configured. Public HTTPS by IP is prepared, but external HTTP validation currently times out and no AWS IAM role is available to change ingress rules. Public access and certificate issuance remain pending the requested AWS TCP80/443 rule change. See [PUBLIC_HTTPS](PUBLIC_HTTPS.md) for exact state, scripts and remaining validation.
