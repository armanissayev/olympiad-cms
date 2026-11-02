# Contest Management System - http://cms-dev.github.io/
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Add the optional IDE receipt relationship to version-44 model dumps."""

class Updater:
    def __init__(self, data):
        assert data["_version"] == 44
        self.objs = data

    def run(self):
        for key, obj in self.objs.items():
            if not key.startswith("_") and obj["_class"] == "Submission":
                obj.setdefault("olympiad_ide_receipts", [])
        return self.objs
