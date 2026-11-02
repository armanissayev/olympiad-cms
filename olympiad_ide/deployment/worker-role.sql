-- Run against the separate IDE database using its migration/administration role.
-- Roles/passwords are provisioned separately. Do not run against the CMS DB.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ide_worker;
GRANT USAGE ON SCHEMA public TO ide_worker;
GRANT SELECT ON execution_snapshots TO ide_worker;
GRANT SELECT, UPDATE ON execution_jobs TO ide_worker;
GRANT SELECT, INSERT ON execution_events TO ide_worker;
GRANT SELECT, INSERT, UPDATE ON execution_workers TO ide_worker;
