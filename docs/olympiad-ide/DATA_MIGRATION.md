# Data migration, backup and recovery

No installation command resets databases or clears browser storage. CMS and IDE use separate databases, interpreters, metadata and migration owners.

## CMS migration

The pinned CMS uses SQLAlchemy metadata creation and versioned logical dumps, not Alembic. The optional cmsOlympiadIDEMigrate command follows that mechanism, targets only olympiad_ide_receipts, uses an advisory installer lock, validates existing columns/unique constraints, and defaults to dry-run.

~~~
CMS_CONFIG=/etc/cms/cms.conf /opt/cms-venv/bin/cmsOlympiadIDEMigrate --dry-run
CMS_CONFIG=/etc/cms/cms.conf /opt/cms-venv/bin/cmsOlympiadIDEMigrate --apply
~~~

Run --apply only after a verified backup using the CMS schema owner. It creates the receipt table/constraints; repeated application reports already_present. It never drops or alters core data and is not run during service startup. Submission's lazy receipt relationship lets feature-disabled CWS operate against old schema without querying the optional table.

Receipts enforce unique installation/participation/intent, submission relationship and opaque external ID. They persist source hashes, immutable mapping/correlation and authoritative timestamp in the admission transaction. CMS dump-model version changes44→45; update_45 supplies empty receipt backreferences when importing old dumps. CMS product version remains1.5.1.

## IDE migration

Use only the separate IDE database and its migration role:

~~~
cd /opt/cms/olympiad_ide/backend
/opt/olympiad-runtime/bin/alembic current
/opt/olympiad-runtime/bin/alembic upgrade head --sql > /secure-backups/ide-migration-review.sql
/opt/olympiad-runtime/bin/alembic upgrade head
/opt/olympiad-runtime/bin/alembic check
~~~

DATABASE_URL must be loaded securely for that command, never copied from the CMS database configuration. The linear chain9773627aa90c→f3a001→f4a001→f5a001→f6a001 is preserved. Revision f5a001 adds cms_principals, cms_workspace_bindings and cms_assertion_nonces; f6a001 adds only the three debugger tables described below. Existing workspace/file/receipt/telemetry/job rows and UUIDs remain untouched. Offline SQL is a review artifact, not proof that an existing database is at the expected revision; inspect current first. No startup autogeneration or reset occurs.

Downgrades f5a001 and f6a001 each refuse if any table introduced by that revision contains rows. Feature-disable rollback retains all mappings and historical receipts. API role receives DML only; schema owner runs migrations. Ordinary execution workers receive the grants in olympiad_ide/deployment/worker-role.sql, with no CMS access. That file covers the pre-debug execution tables; the separate debug controller additionally requires the narrow f6 grants below.

### f6 debugger data and role grants

`f6a001` introduces `debug_sessions` (owned immutable source/configuration/STDIN capture, fixed expiry, worker lease/status, output counters and attachment-token hash/expiry), `debug_messages` (bounded per-session input/output DAP journal, unique direction/sequence) and `debug_workers` (worker heartbeat and supported languages). It creates no CMS table and changes neither CMS receipts nor official judging. Source snapshots, runtime values and DAP output are private participant data. Five-minute execution expiry does not delete these persisted records; debug retention/pruning and backup policy remain an operator responsibility. Breakpoint/history UI observations use existing telemetry storage; the new strict breakpoint event requires no additional migration.

For the tested staging accounts, after the IDE owner applies f6a001:

```sql
GRANT SELECT,INSERT,UPDATE,DELETE ON debug_sessions,debug_messages,debug_workers TO ideapistage;
GRANT SELECT ON debug_sessions,debug_messages,debug_workers TO ideworkerstage;
GRANT UPDATE(status,lease_token,heartbeat,cancelled,output_bytes,last_event,error) ON debug_sessions TO ideworkerstage;
GRANT INSERT ON debug_messages TO ideworkerstage;
GRANT INSERT,UPDATE ON debug_workers TO ideworkerstage;
```

Adapt role names for another installation. The controller receives no ownership/snapshot/attachment-token updates or schema privileges. No account receives CMS authority through these grants. The API/migration/controller remain separate roles; the staging custom Run and debug units share the dedicated execution account, using separate processes and boxes.

The actual f6 rollout first took protected custom-format dumps of the active restored IDE DB under `/var/lib/cms-ide-stage/backups/debug-rollout-20261103` (directory0700, dumps0600), then upgraded as idemigratestage and passed Alembic check. The first candidate archive contained AppleDouble metadata and failed during migration-module parsing before DDL; removing only candidate `._*` files allowed the recorded retry. CMS data was untouched. See [Phase6 architecture](../../olympiad_ide/docs/PHASE6_ARCHITECTURE.md) and the credential-free one-time [provisioning procedure](../../olympiad_ide/tools/linux_staging/provision-debug.py). The consolidated procedure was syntax-checked; it was not rerun on a second host.

## Legacy browser/server data

The old origin's IndexedDB cannot be automatically read from the CMS origin. Export a recovery archive there, retain an untouched copy, then use the native workbench's Inspect source import. Preview shows bounded files/bytes and collisions. Confirm performs one scoped local mutation; malformed UUIDs/names/tree cycles/oversize archives are rejected. File UUIDs survive when free; collisions are explicitly remapped. A digest-derived recovery folder/import receipt prevents duplicate copies after crash/retry.

This imports source as a copy into the currently authenticated CMS scope. It does not transfer authority over old server workspaces or reassign historical telemetry, journals, receipts or jobs. Export recordings separately, retain the original database/browser backup, and keep old server data quarantined with its original owner. No first-login adoption or username matching is implemented. A future proof-based adoption would require both identities, a dry-run mapping, collision audit and explicit transactional migration; it is not silently attempted here.

## Backup and restore

Before schema rollout, pause mutating service traffic and back up both databases plus CMS file storage, protected configuration and installation identity. Physical PostgreSQL recovery is the identity-preserving path: restore the same user/contest/participation IDs and signing/configuration identity, and the matching IDE DB. PostgreSQL custom-format pg_dump/pg_restore preserves table IDs as well; test restore to newly named databases first. Never run test reset fixtures against a production name.

Example operator commands below are templates, not a production backup performed during this task. Use protected libpq service/pgpass files rather than passwords in shell arguments:

~~~
pg_dump --format=custom --dbname=service=cms-backup --file=/secure-backups/cms.dump
pg_dump --format=custom --dbname=service=ide-backup --file=/secure-backups/ide.dump
pg_restore --exit-on-error --no-owner --dbname=service=cms-restore-test /secure-backups/cms.dump
pg_restore --exit-on-error --no-owner --dbname=service=ide-restore-test /secure-backups/ide.dump
~~~

The restore-test services must refer to new empty databases. Restore protected CMS source storage/cache backend if files are not in DBBackend, and verify actual source hashes/receipts, both migration versions, ownership and pending jobs before switching. Consistent backups are required for cross-database correlations; no cross-DB atomicity is promised.

CMS's logical DumpExporter/Importer is different: it can remap numeric IDs. Tests prove source bytes, receipt relationships and original scope/hash/correlation survive logical export/import, but original scope is then provenance, not authority to adopt runtime data under new IDs. Stable receipt lookup resolves its owned stored relationship first. Do not assume identical runtime principal after logical import; use a new installation trust domain or an explicitly reviewed mapping/reconciliation. Production restore and this cross-system reconciliation remain release gates.

## Completed Linux staging restoration

On 2 November 2026, both ResourceService owners and runtime/custom worker/ranking writers were quiesced. PostgreSQL18.6 restored the task-owned CMS/IDE databases into new empty `cms_restore_21c7bd2d5bfortesting` and `ide_restore_d4008d5dedfortesting` databases. At the historical f5a001 revision, all28CMS/21IDE tables, row fingerprints, schema/constraints/indexes/sequences, large-object bytes and28native source hashes matched. The later f6a001 rollout adds three IDE tables to that21-table schema; those debug tables were not part of the earlier restore rehearsal. Exact IDs, 351 principals, 353 workspace mappings and Alembic `f5a001` were preserved. Originals remain retained. The application switched to the restored copies and the same participant recovered workspaces, receipts and judged responses. The real-worker browser and 350-account login/context checks passed afterward.

This is an executed same-cluster logical PostgreSQL dump/restore. A physical basebackup, cross-database atomic snapshot and off-host disaster recovery were not tested. Protected configuration/ranking state was archived but not restored onto a second host. Exact commands/counts/limits are in [LINUX_ACCEPTANCE](LINUX_ACCEPTANCE.md) and [restore evidence](evidence/linux-staging/restore-application-results.json). Production recovery remains a separate gate. A complete f6 backup/restore rehearsal including populated debug journals has not been performed. Quiesce the debug unit alongside other writers for a new consistent backup; after restoration inspect deadlines/leases before starting it. A restored source/journal is not a live VM checkpoint and must not be presented as resumed debugger state.

## Rollback

Disable olympiad_ide_enabled, intentionally stop native service using ResourceService, remove its ingress route, and stop the independent runtime/custom/debug worker units when no longer needed; remove the exact DAP WebSocket route along with other IDE routing. CWS remains the fallback. Retain new tables, backups, installation UUID, user code, local storage and private key backups. Re-enabling restores the same scopes. Do not downgrade CMS dump-model readers over newly written version45 exports without an explicit conversion.

## Participant/Admin workflow follow-up

This update keeps f6a001 unchanged and needs no schema migration or new grants. Numeric CMS observation task IDs and legacy strings are accepted without rewriting envelopes or digests, allowing retained queued batches to retry. Per-problem browser database names/workspace IDs and existing records remain retained during in-place switching. Server Admin review checks existing identity bindings; it never adopts records by username. No participant files, old local recordings or existing passwords were deleted/reset. [Actual acceptance](PARTICIPANT_ACCEPTANCE.md).

## Submitted-file history review — 5 November 2026

The new Admin viewer reads existing native submission receipts and retained IDE telemetry. It adds no schema migration, table, grant or identity mapping, and does not rewrite raw recordings or official source files. Review markers and grouped intervals are computed on read; existing retention remains unchanged. Source and installed native package rollback are sufficient for this viewer. [Actual acceptance and deployment](FILE_HISTORY_ACCEPTANCE.md).
