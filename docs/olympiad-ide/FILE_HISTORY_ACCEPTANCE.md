# Submitted-file history and review-marker acceptance

Deployed and verified **5 November 2026**, only on the authorized disposable EC2 instance `i-0ade1f8ddf0b0dad8` (`54.206.171.67`). Open **https://54.206.171.67/admin/contest/1/ide-history** with a full-permission CMS Admin account. Refresh an already-open page. Choose a participant and problem; the actual submitted files load automatically. Select a file/version, then use the grouped writing timeline, playback, marker jumps/filter and optional before/after comparison. No recording UUID selection or SSH tunnel is needed.

Current application commit: **`505c1a4b401da9662775efa3020621dfca344349`**. Core implementation is `ca93f0c9`; complete Linux suites ran from immutable verification snapshot **`84f42f02aa872b01a77c6280695f077437fa2a07`**. The later `505c1a4b` change only collapses detailed recording notes and updates its browser regression. Final installed-package tests and real public-browser acceptance cover that final UI. No push, PR or merge occurred.

## Delivered behavior

| Request | Actual result |
| --- | --- |
| Participant/problem → submitted files → file history | Passed actual CMS submission/file listing and exact immutable receipt mapping; repeated submissions are separate versions. Standard CWS or missing-link files remain visible with an honest unavailable reason and normal submission link. |
| Useful keyboard/editing periods | Occupied 5-second periods by default; 1/5/10/30-second choices. Cursor/focus/key-up/navigation/execution noise is omitted from timeline steps. Initial and submitted snapshots remain explicit. Counts describe key-linked source changes, not every physical key. |
| Comfortable playback | Activity overview, slider, Previous/Next period, Play/Pause/speed, idle skipping, marked-period filter and before/after source. Detailed notes are collapsed without discarding limitations. Delayed requests and playback changes cannot replace another selection or schedule duplicate advances. |
| Review cues | Recorded paste, copy shortcut, large/rapid insertions, long pauses, slow recorded editing and explicit import/recovery/generated-change context. Rules, quantities and benign explanations are visible. |
| Untrusted paste source | **Not observable.** Paste is marked **source unknown**. Inserted editor text is recorded; external clipboard contents, applications and source websites are not collected. No source trust or plagiarism verdict is invented. |
| Restricted access and source integrity | Full CMS Admin permission remains mandatory. Guest/actual participant denial passed. Receipt-built signed queries bind the file/workspace/capture/target; missing, corrupt, expired or truncated history stays explicit. Matching bytes do not prove authorship. |

Thresholds and detailed bounds are documented in [ADMIN_HISTORY](ADMIN_HISTORY.md). Markers are human-review cues, without automatic sanctions, plagiarism scores or new collection permissions. No database migration, table, grant or history-data rewrite was needed.

## Actual verification

Focused checks overlap complete suites; do not add their counts together.

| Check | Outcome and evidence |
| --- | --- |
| Local CMS IDE regression suite | **54 passed, 18 subtests**, 118 warnings, 6.57s. [Output](evidence/file-history/native-local.log). |
| Final local runtime suite | **116 passed**, one existing Starlette/httpx deprecation warning, 22.70s. [Output](evidence/file-history/runtime-local.log). |
| Runtime history/analysis focus | **27 passed**: 16 real-PostgreSQL Admin/history cases and 11 analysis cases. Includes boundaries, tampering, other-file separation, gaps, malformed checkpoints, Unicode/multicursor units, paste correlation, benign generated changes and budget priority. [Output](evidence/file-history/runtime-focused.log). |
| Complete Linux CMS suite, isolated source snapshot | **766 passed, 9 skipped, 28 subtests**, 479 legacy warnings, 32.68s. Existing nine unit skips are retained; this was not a rerun of the mandatory sandbox gate. [Output](evidence/file-history/native-linux.log). |
| Complete Linux runtime suite | **116 passed**, one existing warning, 24.15s. Real PostgreSQL schemas in the retained non-active test database. [Output](evidence/file-history/runtime-linux.log). |
| Final installed native package | **13 passed**, 100 legacy warnings, 1.84s, explicitly importing CMS/history from `site-packages` with `PYTHONPATH` unset and an isolated unit DB. [Output](evidence/file-history/native-installed.log). |
| Local synthetic browser UI | **Six grouped checks passed**, including delayed response/playback races, inert HTML-like filenames, marker jumps, comparison, empty-start playback, identity clearing and 390px layout. Final notes stay collapsed, expandable and reset on file change. Synthetic fixtures are UI tests, not real participant evidence. [Results](evidence/file-history/local-browser-results.json), [desktop](evidence/file-history/synthetic-markers.png), [mobile](evidence/file-history/synthetic-mobile.png). |
| Final real public HTTPS browser | **Four grouped checks passed**, normal TLS validation, zero page/server errors and zero history mutation requests. [Results](evidence/file-history/browser-results.json), [output](evidence/file-history/browser.log), [screenshot](evidence/file-history/submitted-file-history.png). |

The real public browser authenticated the existing disposable actor **352** and confirmed participant denial, then used a separate full Admin browser. It listed that actor's actual C++ submissions, selected CMS file/submission **43**, and reconstructed source SHA-256 **`704fa61aae911881a42e2ffb330f44a6e388efb52ed2ba42c07df1f538c8faf5`**. The result contained **six timeline points**, one editing period, and observed **paste** and creation/recovery-context markers. Playback, regrouping to 30 seconds, marker filtering with boundary preservation, previous-period comparison and selection clearing passed. Larger/rapid/slow patterns are covered by deterministic database/analysis and synthetic UI tests; they are not falsely reported as observed misconduct by real users. No new submission or judging workload was created in this follow-up.

## Environments and isolation

AWS retains Python **3.12.16** in separate CMS/runtime environments, CMS **1.5.1**, runtime SQLAlchemy **2.1.5**, FastAPI **0.150.0**, Pydantic **2.14.1**, and pytest **9.1.1**. No dependency was updated on AWS; native package installation used `--no-deps`. [Captured environment](evidence/file-history/environment.log).

Local test environments were recreated after temporary files had been cleared: Python **3.12.6**, PostgreSQL **14**, CMS SQLAlchemy **1.3.24**, and a separate runtime with SQLAlchemy **2.1.8**, FastAPI **0.162.0**, Pydantic **2.14.3**, psycopg **3.3.8**, pytest **9.2.0**. CMS required compatible setuptools **80.9.0** for its existing `pkg_resources` loader. These are test-only environments; Linux compatibility was independently verified against the existing AWS versions.

Local databases were `cmside_history_unitfortesting` and `ide_history_runtime`, role `idehistorytest`, loopback `127.0.0.1:55459`. The CMS test configuration pinned that exact database and task-owned directories/coordinates. AWS native tests used mandatory `/etc/cms-ide-stage/cms-unit.conf` and **`cmside_linux_unitfortesting`**, distinct from the active CMS database. Runtime tests created/dropped only generated `test_*` schemas in retained **`ide_linux_staging`**, distinct from the active restored IDE database. Guards verified database names, roles and socket/port before test resets.

The task-owned local PostgreSQL cluster is now **stopped**. [Cleanup](evidence/file-history/local-cleanup.log). All **124** authoritative original source hashes still match; the original IDE and SSH key were preserved. [Preservation check](evidence/file-history/original-source.json). Credentials, environments, databases and dependencies were excluded from Git.

## Reproduce the checks

From the CMS checkout, while the explicitly isolated test cluster/environments exist:

```sh
CMS_CONFIG=/private/tmp/cms-file-history/cms-unit.conf \
  /private/tmp/cms-file-history/cms-venv/bin/python -m pytest \
  cmstestsuite/unit_tests/server/olympiadide -q --tb=short -p no:cacheprovider

cd olympiad_ide/backend
TEST_DATABASE_URL=postgresql+psycopg://idehistorytest@127.0.0.1:55459/ide_history_runtime \
  /private/tmp/cms-file-history/runtime-venv/bin/python -m pytest -p no:cacheprovider
```

The browser commands run from the CMS checkout and require the protected **existing** disposable fixture, never a committed password:

```sh
PLAYWRIGHT_CHROMIUM_PATH=/Users/isaevarman/Library/Caches/ms-playwright/chromium-1155/chrome-mac/Chromium.app/Contents/MacOS/Chromium \
  /Users/isaevarman/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  olympiad_ide/frontend/tools/verify-file-history-ui.cjs \
  /private/tmp/cms-file-history/viewer-notes-polish

PLAYWRIGHT_CHROMIUM_PATH=/Users/isaevarman/Library/Caches/ms-playwright/chromium-1155/chrome-mac/Chromium.app/Contents/MacOS/Chromium \
  /Users/isaevarman/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  olympiad_ide/frontend/tools/verify-file-history.cjs \
  /private/tmp/cms-file-history/ui-acceptance.json \
  /private/tmp/cms-file-history/browser-final-compact \
  docs/olympiad-ide/evidence/participant-polish/participant-results.json
```

Exact guarded Linux snapshot, activation, package and audit procedures are retained in [history_review](../../olympiad_ide/tools/linux_staging/history_review/README.md). They are historical one-off commands for this exact host/base/commit, intentionally refuse different or already-applied state, and are not a generic production deployment script. Native installed-package checks preload `cms`/`idehistory` from `site-packages`, then run the retained test file with `--import-mode=importlib` in the CMS-owned unit-run directory; optional integration tests are not importable wheel modules.

## Deployment, failures and corrections

The source delta was applied first to a separate immutable verification copy, leaving the running application unchanged during complete Linux suites. Protected source and installed-package backups were taken. No Run or debug session was active. Runtime API restart and **native ResourceService `kill_service(AdminWebServer,0)`** preserve native process ownership. Participant CWS, IDE native service, Evaluation/Scoring, official Worker and both ResourceServices kept their original PIDs/start times. Run/debug workers and ingress also stayed running. [Source activation](evidence/file-history/source-activation.log).

The live browser caught an important deployment mistake: updating `/opt/cms-ide-stage/source` did **not** update the native console script's installed package. The new guest file endpoint returned **404**, which was correctly rejected as acceptance, not treated as successful denial. The active import was still `cms-venv/lib/python3.12/site-packages/cms`. [Failure](evidence/file-history/browser-before-package.json), [import diagnostic](evidence/file-history/installed-path-diagnostic.log). The verified CMS wheel was then built offline and installed with `--no-index --no-deps --force-reinstall`; only Admin was restarted through ResourceService. Actual installed routes, source hashes, 13 installed-target tests and public-browser acceptance then passed.

The final native wheel SHA-256 is **`14808366e201a34f8ce0b3e61bce52c8df7412bc2623f781d2ee98d1fedfe87a`**. [Initial corrected package install](evidence/file-history/native-package-install.log), [final compact-notes package](evidence/file-history/native-notes-install.log). Copying a checkout alone is not a valid native CMS deployment. Both virtual environments passed `pip check`; no environment merging or dependency change occurred.

Other observed procedure failures were retained rather than counted as passes: the initial archive helper used a non-iterator TarFile and stopped before any file/test changes; the first source activation's supervisor-response assertion triggered a successful source/runtime rollback, whose old hashes/marker were checked before retry; an installed-package test attempt entered a CMS-owned directory as ubuntu and failed permission checks, and a subsequent `--pyargs` attempt found no optional test module in the wheel. The final check used a root-entered test working directory, explicitly imported the installed code, and ran the retained test file: 13 passes. No database guard was weakened. [Preparation failure](evidence/file-history/preparation-failure.log), [initial activation failure](evidence/file-history/source-activation-first-failure.log). Bounded cold-connection handling and fresh-PID/readiness reconciliation are in the retained helper; the first failing RPC payload itself was not retained, so its exact remote error is not invented.

## Final state and remaining limits

[Final audit](evidence/file-history/host-final.json) confirms all **nine** staging units active and boot-enabled, separate environment checks green, unchanged non-Admin native PIDs, private networking retained for Run/debug, valid public-IP TLS with renewal active, and `cms-staging-ops` with three tmux windows. Public CMS, native IDE readiness and Admin login return **200**. The native Admin listener remains loopback; public access uses the existing authenticated `/admin/` proxy. No DNS, firewall/security-group or production change was performed by the agent. SSH was restored by the operator after the initial timeout.

Protected rollback copies include `/opt/cms-ide-stage/backups/file-history-84f42f02aa87-retry2`, `native-wheel-before-file-history-84f42f02aa87` and `native-wheel-before-file-history-505c1a4b401d`. A complete rollback must restore matching source **and installed native package**, then restart the API and native-supervised Admin as applicable; restoring only a source marker is insufficient. The earlier verified native wheel is retained under the core verification directory. No database rollback is needed for this additive read-only viewer.

Only uploaded retained recordings can be reviewed. Browser-controlled observations, unknown paste provenance, missing/late/offline history and heuristic false positives remain explicit. No statistical plagiarism validation, cross-participant source similarity detector or automated misconduct decision is claimed. No new load, sandbox, judging, outage, backup-restore or reboot rehearsal was run; unchanged production isolation, dependency/licence, retention/recovery and 300–350 participant capacity release gates remain in IMPLEMENTATION_STATE.md.
