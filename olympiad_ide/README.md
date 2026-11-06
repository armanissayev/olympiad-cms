# Olympiad IDE inside CMS

This directory preserves the original React/Monaco workbench, persistence, telemetry and isolated custom execution. The CMS-facing service is cms/server/olympiadide with the installed cmsOlympiadIDEService launcher. It reuses CMS participant authentication and official admission; the private FastAPI environment owns background IDE operations.

Start with [deployment](../docs/olympiad-ide/DEPLOYMENT.md), [architecture](../docs/olympiad-ide/ARCHITECTURE.md) and [verification](../docs/olympiad-ide/VERIFICATION.md). The feature is disabled by default. Ordinary CMS installation does not require Node.

Use Node22/24 (24.19.0 tested), Python3.12 and separate CMS/runtime environments. Run python3 tools/build_olympiad_ide.py from the repository root to install locked frontend dependencies and stage production /ide/ assets before packaging. No Vite server is used in production.

Real Linux isolated execution, CMS judging, public HTTPS and Admin file-history review have passed staging acceptance. See ../INSTALL_CUSTOM_CMS.md for source/bundle installation and docs/olympiad-ide/FILE_HISTORY_ACCEPTANCE.md for the current history report. This branch is not yet approved for a live contest. Source origin/hashes and licensing questions are recorded in docs/olympiad-ide/SOURCE_IMPORT.json and BASELINE.md. Original reports, including the standalone README, are historical material under docs/, not native deployment instructions.
