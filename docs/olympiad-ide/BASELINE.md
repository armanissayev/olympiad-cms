# Baseline and provenance

Recorded 2 November 2026. The authoritative original IDE remains at /Users/isaevarman/Developer/olympiad-ide. It has no Git metadata: its historical commit and pre-existing uncommitted changes cannot be determined. No original application file was removed or overwritten. The initial audit added documentation there before the CMS checkout was supplied.

CMS was cloned from https://github.com/cms-dev/cms into /Users/isaevarman/Developer/cms. Official releases and remote tags were inspected; the selected stable release is [v1.5.1](https://github.com/cms-dev/cms/releases/tag/v1.5.1), commit **7c9fec8aa1a25ec93d624aebf815804dd93df9db**. Work is on **feature/olympiad-ide-integration**, starting from a clean checkout. The release's isolate submodule is pinned at 758ab000e3a1bcf1e57ffddea2340ffa1a5af49b. It was fetched, not built or run. No applicable AGENTS.md was found in either checkout or the checked ancestors.

The initial 124-file source inventory contains 778,658 bytes with aggregate SHA-256 **5836b0cdbcd812bdcd7f88ed42eeec08648dea62291080c05e35d94b822aa2a1**. SOURCE_INVENTORY.json records the original hashes; SOURCE_IMPORT.json maps each imported file to its target. This fingerprint is not a Git commit. The import excluded dependencies, environments, private keys, PEM files, local databases, browser state, AWS scripts/results and participant data. Subsequent integration changes occur only in CMS.

## Source and runtime audit

Read the original SPEC, README, Phase 2/3/4 architecture, plans and verification reports, and the later AWS worker report; inspected their actual implementations. Original documentation is retained under olympiad_ide/docs. The current request supersedes the old SPEC's exclusion of official CMS submission.

The retained frontend uses React 18.3.1, TypeScript 5.7.3, Monaco 0.52.2, Zustand 5.0.15, Dexie 4.4.6 and Vite 6.4.4. The initial source baseline used installed Node 23.10.0; the integrated clean npm ci/build/tests use supported Node **24.19.0**. The opt-in build accepts Node 22 or 24 and commits package-lock.json.

CMS retains its release requirements: Python 3.12.6 was tested with SQLAlchemy 1.3.24, Tornado 4.5.3, Werkzeug 0.16.1 and gevent 25.5.1. Optional PyJWT 2.10.1 handles private assertions; setuptools 80.9.0 preserves CMS's existing pkg_resources import. requirements-olympiad-ide.lock records the observed CMS/test environment, without upgrading the release's core requirements.

The private runtime retains a separate Python 3.12 environment with FastAPI 0.150.0, SQLAlchemy 2.1.5, Alembic 1.20.0 and psycopg 3.3.6, pinned from the observed original environment plus PyJWT. Its lock is olympiad_ide/backend/requirements.lock. Both environments passed pip check. PostgreSQL 14, using a new loopback cluster and generated test credentials only, supplied all database tests.

## Preserved behavior

- UUID-based file/model identity, Explorer, split panes sharing Monaco models with independent view state, settings, shortcuts, themes and resizable workbench.
- Atomic IndexedDB document/journal changes, immutable sending operations, revision conflicts, recovery snapshots, PostgreSQL receipts and offline reload.
- Separate append-only telemetry sessions, UTF-16 coordinates, document transactions, checkpoint hashes, chunked ingestion, integrity diagnostics and replay.
- Exact live-text custom-run snapshots, run configurations, tests, compile-once Run All, durable jobs, leases/fencing, cancellation and output limits.
- Separate gated Linux isolate workers and C++17/C++20/Python3/Java17 custom profiles. No web-service subprocess execution fallback.

The original gaps—development-cookie ownership, root-only service worker/API URLs, missing CMS identity/context/admission and missing validated cross-origin import—are implemented in the integrated source. The original source remains available for comparison.

## Historical and fresh evidence

| Evidence | Results |
| --- | --- |
| Historical Phase 4 report | 63 frontend, 49 backend, 4 worker-policy and 13 browser passes; 24 Linux and 1 worker-browser skips |
| Historical later AWS report | Reports 32 Linux passes/1 non-Linux skip, 27 backend execution passes, 10 HTTP worker jobs and browser acceptance; not repeated here |
| Fresh original IDE baseline | 63 frontend, 52 PostgreSQL backend, 7 worker-policy and 13 browser passes; 26 Linux and 1 worker-browser skips |
| Untouched CMS v1.5.1 snapshot | 670 passed, 9 skipped, 6 failures in shared-mime-info dependent tests on macOS |
| Integrated result | See VERIFICATION.md and evidence; do not add overlapping targeted and full-suite totals |

No AWS connection, live contest/database operation, DNS, firewall, billing or production deployment was performed. Prior AWS reports do not prove this integrated branch's execution or judging.

## Attribution and licensing

CMS retains LICENSE.txt (AGPL-3.0-or-later) and its upstream attribution. Imported original reports and README are retained. No root LICENSE, COPYING or NOTICE was present in the original IDE; the owner's authority to import does not establish its redistribution licence. Maintainers must resolve original-source licensing and review distributed dependency/toolchain notices before release. Lock metadata lists MIT for React/Monaco/Zustand/Vite/xterm and Apache-2.0 for Dexie; this is not a complete legal review.
