# SPDX-License-Identifier: AGPL-3.0-or-later
"""Receipt/source roundtrip through the pinned CMS logical dump mechanism."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from cmstestsuite.unit_tests.databasemixin import DatabaseMixin
from cms.db import OlympiadIDEReceipt
from cms.db.filecacher import FileCacher
from cmscommon.digest import bytes_digest
from cmscontrib.DumpExporter import DumpExporter
from cmscontrib.DumpImporter import DumpImporter


class TestIDEReceiptDump(DatabaseMixin, unittest.TestCase):
    def tearDown(self):
        self.session.close()
        super().tearDown()

    def test_receipt_source_and_relations_survive_cms_dump_import(self):
        contest = self.add_contest()
        participation = self.add_participation(contest=contest)
        task = self.add_task(contest=contest, submission_format=["main.%l"])
        dataset = self.add_dataset(task=task); task.active_dataset = dataset
        submission = self.add_submission(task, participation, language="Python 3 / CPython")
        source = b"print('preserve exact bytes')\r\n"
        digest = bytes_digest(source)
        self.add_fsobject(digest, source)
        self.add_file(submission=submission, filename="main.%l", digest=digest)
        self.session.flush()
        intent = str(uuid4()); installation = str(uuid4())
        manifest = [{"filename": "main.%l", "sourceFilename": "main.py", "fileId": str(uuid4()),
                     "size": len(source), "sha256": hashlib.sha256(source).hexdigest()}]
        scope = {"installationId": installation, "userId": str(participation.user_id),
                 "contestId": str(contest.id), "participationId": str(participation.id)}
        correlation = {"workspaceId": str(uuid4()), "snapshotId": str(uuid4()), "telemetry": None}
        receipt = OlympiadIDEReceipt(installation_id=installation, intent_id=intent,
            participation=participation, submission=submission, request_digest="ab"*32,
            external_id="immutable-opaque-reference", identity_scope=scope,
            source_manifest=manifest, correlation=correlation, received_at=datetime(2026,11,2,12))
        self.session.add(receipt); self.session.commit(); self.session.close()
        with tempfile.TemporaryDirectory(prefix="cms-receipt-dump-") as directory:
            target = str(Path(directory)/"dump")
            self.assertTrue(DumpExporter(None, target, dump_files=True, dump_model=True,
                skip_generated=False, skip_submissions=False, skip_user_tests=False,
                skip_users=False, skip_print_jobs=False).do_export())
            dump = json.loads((Path(target)/"contest.json").read_text())
            self.assertEqual(dump["_version"], 45)
            self.assertTrue(any(isinstance(value, dict) and value.get("_class") == "OlympiadIDEReceipt" for value in dump.values()))
            # Only the DatabaseMixin's disposable *fortesting database is cleared.
            self.delete_data()
            self.assertTrue(DumpImporter(False, target, load_files=True, load_model=True,
                skip_generated=False, skip_submissions=False, skip_user_tests=False,
                skip_users=False, skip_print_jobs=False).do_import())
        restored = self.session.query(OlympiadIDEReceipt).filter_by(intent_id=intent).one()
        self.assertEqual(restored.source_manifest, manifest)
        self.assertEqual(restored.identity_scope, scope)
        self.assertEqual(restored.correlation, correlation)
        self.assertEqual(restored.request_digest, "ab"*32)
        self.assertEqual(restored.external_id, "immutable-opaque-reference")
        self.assertEqual(restored.participation_id, restored.submission.participation_id)
        self.assertEqual(FileCacher().get_file_content(restored.submission.files["main.%l"].digest), source)
