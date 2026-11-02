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

DATABASE_URL must be loaded securely for that command, never copied from the CMS database configuration. Existing chain9773627aa90c→f3a001→f4a001 is preserved; f5a001 adds cms_principals, cms_workspace_bindings and cms_assertion_nonces. It leaves all old workspace/file/receipt/telemetry/job rows and UUIDs untouched. Offline SQL is a review artifact, not proof that an existing database is at the expected revision; inspect current first. No startup autogeneration or reset occurs.

Downgrade f5a001 refuses if any new table contains rows. Feature-disable rollback retains all mappings and historical receipts. API role receives DML only; schema owner runs migrations. Execution workers receive only the grants in olympiad_ide/deployment/worker-role.sql, no CMS access.

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

## Rollback

Disable olympiad_ide_enabled, intentionally stop native service using ResourceService, remove its ingress route, and stop the independent runtime/worker units when no longer needed. CWS remains the fallback. Retain new tables, backups, installation UUID, user code, local storage and private key backups. Re-enabling restores the same scopes. Do not downgrade CMS dump-model readers over newly written version45 exports without an explicit conversion.
