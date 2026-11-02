# Contest Management System - http://cms-dev.github.io/
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Explicit, additive receipt-table migration in the CMS environment.

No CMS/IDE table is dropped or altered. Not invoked by service startup.
"""
import argparse
import json
from sqlalchemy import inspect, text
from cms.db import OlympiadIDEReceipt, engine


def migrate(bind, apply=False):
    table = OlympiadIDEReceipt.__table__
    with bind.begin() as connection:
        # Serialize simultaneous installers; this is not a contest admission lock.
        connection.execute(text("SELECT pg_advisory_xact_lock(183529765, 1)"))
        inspector = inspect(connection)
        exists = table.name in inspector.get_table_names()
        if exists:
            columns = {item["name"] for item in inspector.get_columns(table.name)}
            unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints(table.name)}
            expected_unique = {("installation_id", "participation_id", "intent_id"), ("submission_id",), ("external_id",)}
            if columns != set(table.columns.keys()) or not expected_unique.issubset(unique):
                raise RuntimeError("Existing receipt table has an unexpected schema; refusing automatic changes")
        elif apply:
            table.create(bind=connection, checkfirst=True)
        return {"schemaVersion": 1, "table": table.name,
                "action": "already_present" if exists else "created" if apply else "would_create",
                "destructive": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Describe changes (the default)")
    modes.add_argument("--apply", action="store_true", help="Create the receipt table and its constraints")
    args = parser.parse_args()
    print(json.dumps(migrate(engine, apply=args.apply), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
