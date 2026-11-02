# Local PostgreSQL dump/restore rehearsal

**Passed on 2026-11-02.** PostgreSQL 14.15 (Homebrew) tools restored both task-owned databases into newly created, empty databases in the same temporary local cluster at `127.0.0.1:55459`. This verifies database preservation in this local fixture. It does not certify production backup operations, Linux execution, external file storage, secret restoration, cross-database atomicity, or application failover.

The native agent had stopped all final CMS fixture processes/listeners; the IDE runtime was quiescent. The only source databases were `cmsidesmokefinalfortesting` and `ideruntime`. Neither source database was modified. Each source used its own exported repeatable-read, read-only PostgreSQL snapshot, held open through dump and verification. There is no implied atomic transaction spanning the two databases. No existing destination was overwritten, no `--clean`/drop command was used, and no other user/live database was used as a test target.

| Source | New destination | Tables compared | Relevant restored counts | Schema/version |
|---|---|---:|---|---|
| `cmsidesmokefinalfortesting` | `cms_restore_4b3437a4ecfortesting` | 28 | 1 contest, 1 user, 1 participation, 1 task/dataset, 3 submissions, 3 receipts, 3 file references, 2 deduplicated large objects | CMS model/dump version 45; CMS has no database version table |
| `ideruntime` | `ide_restore_e8a3c39271fortesting` | 21 | 1 CMS principal, 5 workspace bindings, 5 workspaces, 11 file nodes, 9 recovery snapshots, 7 sync operations/revisions, 1 telemetry session/checkpoint, 3 assertion nonces | Alembic `f5a001` |

All public-table row counts and sorted row fingerprints matched, including receipt primary keys, intent UUIDs, opaque external submission identifiers, request digests, per-file manifests, identity scope and workspace/snapshot/telemetry correlation. Column definitions, constraints, indexes, and sequence `last_value/is_called` state matched. All PostgreSQL large-object OIDs, sizes and byte hashes matched. The source contains no judged results or execution jobs; equal zero counts are not execution evidence.

For all three official file references, verification read actual large-object bytes from each database, compared the raw bytes directly, and checked normal CMS SHA-1 digests plus receipt SHA-256 and byte sizes. Duplicate source storage explains three file references but only two large objects. Source text and per-file contents were never printed. For the IDE database, verification compared principal and workspace UUIDs/task/owner mappings directly and recomputed the principal UUIDv5 from the persisted installation/user/contest/participation tuple. All five actual workspace mappings retained the same principal, task, owner and revision.

The source and restored snapshots contained matching rows in every table, including historical IDE snapshots and telemetry records. Native identities survived this PostgreSQL restore because numeric CMS IDs were retained. This differs from CMS's application-level JSON DumpImporter, which can remap IDs; the earlier admission evidence documents that separate case.

## Actual commands and protected artifacts

The driver `/private/tmp/cms-restore-rehearsal.py` set umask0077, refused unknown source/target database names, verified server host/port, used a new empty mode0600 password file rather than reading user credentials, and kept each exported source snapshot open while running the commands below. Exported snapshot identifiers shown here were valid only during that live transaction; they are historical evidence, not reusable values. A repeat rehearsal must create and hold new snapshots or use an explicitly quiescent source with a new dump.

```sh
/opt/homebrew/opt/postgresql@14/bin/createdb -h 127.0.0.1 -p 55459 -U isaevarman --no-password --maintenance-db=cmsidesmokefinalfortesting --template=template0 cms_restore_4b3437a4ecfortesting
/opt/homebrew/opt/postgresql@14/bin/pg_dump -h 127.0.0.1 -p 55459 -U isaevarman --no-password --format=custom --snapshot=00000004-00001751-1 --file=/private/tmp/cms-native-restore-tzgu778p/cmsidesmokefinalfortesting.dump cmsidesmokefinalfortesting
/opt/homebrew/opt/postgresql@14/bin/pg_restore -h 127.0.0.1 -p 55459 -U isaevarman --no-password --exit-on-error --single-transaction --dbname=cms_restore_4b3437a4ecfortesting /private/tmp/cms-native-restore-tzgu778p/cmsidesmokefinalfortesting.dump

/opt/homebrew/opt/postgresql@14/bin/createdb -h 127.0.0.1 -p 55459 -U isaevarman --no-password --maintenance-db=ideruntime --template=template0 ide_restore_e8a3c39271fortesting
/opt/homebrew/opt/postgresql@14/bin/pg_dump -h 127.0.0.1 -p 55459 -U isaevarman --no-password --format=custom --snapshot=00000004-00001753-1 --file=/private/tmp/cms-native-restore-tzgu778p/ideruntime.dump ideruntime
/opt/homebrew/opt/postgresql@14/bin/pg_restore -h 127.0.0.1 -p 55459 -U isaevarman --no-password --exit-on-error --single-transaction --dbname=ide_restore_e8a3c39271fortesting /private/tmp/cms-native-restore-tzgu778p/ideruntime.dump
```

All six commands exited0. CMS dump:107477 bytes; IDE dump:51121 bytes. Both custom-format dumps and local diagnostics are mode0600 inside `/private/tmp/cms-native-restore-tzgu778p` (mode0700). Dumps were not copied to the repository. The sanitized count/command report is `restore-local.json` beside this document. The restored databases remain task-owned temporary inspection artifacts and can be removed with the temporary cluster; no production endpoint was repointed to them.

A preliminary safety assertion stopped before any destination creation because PostgreSQL rendered `inet_server_addr()::text` as `127.0.0.1/32`. The driver was corrected to compare `host(inet_server_addr())` with the expected host, then the complete rehearsal passed. No test was weakened to allow another host/port/database.

Remaining production work includes independent off-host encrypted backups, role/secret/configuration and external file-store recovery, retention/access controls, a coordinated two-database recovery plan, application restart/readiness and receipt reconciliation after restore, and rehearsal on the actual deployment OS and database/storage topology. This local result does not remove those release gates.
