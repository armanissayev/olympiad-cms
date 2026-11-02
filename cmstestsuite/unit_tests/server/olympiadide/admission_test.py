# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real PostgreSQL transaction/policy tests; no participant program execution."""
import copy
import hashlib
import tempfile
import json
import subprocess
import sys
import time
from pathlib import Path
import unittest
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import patch, Mock

from cmstestsuite.unit_tests.databasemixin import DatabaseMixin
from cms import config
from cms.db import (OlympiadIDEReceipt, Participation, Session, Submission, Task,
                    engine)
from cms.db.filecacher import FileCacher
from cms.server.contest.submission import UnacceptableSubmission
from cms.server.contest.submission.policy import accept_contest_submission
from cms.server.olympiadide.admission import (
    IntentError, admit_intent, find_receipt, notify_after_commit, prepare_intent,
    receipt_view, task_capability)
from cms.server.olympiadide.migrate import migrate
from cms.service.esoperations import ESOperation, get_submissions_operations


class TestIDEAdmission(DatabaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 11, 2, 10, 0, 0)
        self.installation = str(uuid4())
        self.contest = self.add_contest(
            start=self.now-timedelta(hours=1), stop=self.now+timedelta(hours=1),
            languages=["C++17 / g++", "C++20 / g++", "Python 3 / CPython"])
        self.participation = self.add_participation(contest=self.contest)
        self.task = self.add_task(contest=self.contest, submission_format=["main.%l"])
        self.dataset = self.add_dataset(task=self.task, task_type="Batch",
            task_type_parameters=["alone", ["", ""], "diff"], score_type="Sum",
            score_type_parameters=1)
        self.task.active_dataset = self.dataset
        self.session.flush()
        self.directory = tempfile.TemporaryDirectory(prefix="cms-ide-admission-")
        self.addCleanup(self.directory.cleanup)
        self.cacher = FileCacher(path=self.directory.name)
        self.addCleanup(self.session.close)
        for name, value in (("submit_local_copy", False), ("secret_key", "12"*16)):
            patcher = patch.object(config, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        self.body = {"schemaVersion": 1, "intentId": str(uuid4()), "taskId": self.task.id,
            "language": "C++17 / g++", "snapshotId": str(uuid4()), "workspaceId": str(uuid4()),
            "telemetry": {"sessionId": str(uuid4()), "sequence": 17},
            "files": [{"filename": "main.%l", "sourceFilename": "solution.cpp",
                       "fileId": str(uuid4()), "content": "// café\r\nint main(){return 0;}\n"}]}

    def admit(self, body=None, timestamp=None):
        return admit_intent(self.session, self.cacher, self.installation,
            self.participation, self.task, timestamp or self.now,
            prepare_intent(body or self.body))

    def count(self):
        return self.session.query(Submission).filter_by(participation_id=self.participation.id).count()

    def test_exact_bytes_cms_file_storage_and_atomic_receipt(self):
        receipt, created = self.admit()
        self.assertTrue(created)
        self.session.commit()
        raw = self.body["files"][0]["content"].encode("utf-8")
        self.assertEqual(self.cacher.get_file_content(receipt.submission.files["main.%l"].digest), raw)
        self.assertEqual(receipt.source_manifest[0]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt.received_at, self.now)
        self.assertEqual(receipt.submission.participation_id, self.participation.id)
        self.assertEqual(receipt.submission.language, "C++17 / g++")
        self.assertEqual(receipt_view(receipt)["state"], "admitted")
        self.assertEqual(receipt.correlation["telemetry"], self.body["telemetry"])

    def test_python_admission_uses_actual_cms_identifier(self):
        self.body["language"] = "Python 3 / CPython"
        self.body["files"][0].update(sourceFilename="solution.py", content="print('5')\n")
        receipt, _ = self.admit()
        self.assertEqual(receipt.submission.language, "Python 3 / CPython")

    def test_duplicate_receipt_and_lost_response_after_deadline(self):
        receipt, _ = self.admit(); original = receipt_view(receipt)
        self.session.commit(); self.session.expire_all()
        again, created = self.admit(timestamp=self.contest.stop+timedelta(hours=1))
        self.assertFalse(created)
        self.assertEqual(receipt_view(again), original)
        self.assertEqual(self.count(), 1)

    def test_changed_body_reuse_is_rejected(self):
        self.admit(); self.session.commit()
        changed = copy.deepcopy(self.body); changed["files"][0]["content"] += "// later edit"
        with self.assertRaises(IntentError) as raised:
            self.admit(changed)
        self.assertEqual(raised.exception.code, "intent_reused")
        self.assertEqual(self.count(), 1)

    def test_same_source_new_intent_is_a_distinct_submission(self):
        first, _ = self.admit(); self.session.commit()
        other = copy.deepcopy(self.body); other["intentId"] = str(uuid4())
        second, _ = self.admit(other)
        self.assertNotEqual(first.submission_id, second.submission_id)
        self.assertEqual(self.count(), 2)

    def test_unadmitted_intent_cannot_reserve_old_deadline(self):
        with self.assertRaises(UnacceptableSubmission):
            self.admit(timestamp=self.contest.stop+timedelta(microseconds=1))
        self.assertEqual(self.count(), 0)

    def test_extra_time_and_inclusive_deadline(self):
        self.participation.extra_time = timedelta(minutes=10)
        receipt, _ = self.admit(timestamp=self.contest.stop+timedelta(minutes=10))
        self.assertTrue(receipt.submission.official)

    def test_analysis_is_unofficial_and_unrestricted_matches_cws(self):
        self.contest.analysis_enabled = True
        self.contest.analysis_start = self.contest.stop + timedelta(hours=1)
        self.contest.analysis_stop = self.contest.stop + timedelta(hours=2)
        receipt, _ = self.admit(timestamp=self.contest.analysis_start)
        self.assertFalse(receipt.submission.official)
        self.participation.unrestricted = True
        other = copy.deepcopy(self.body); other["intentId"] = str(uuid4())
        second, _ = self.admit(other, self.contest.start-timedelta(hours=1))
        self.assertFalse(second.submission.official)

    def test_receipt_is_bound_to_participation_and_installation(self):
        self.admit()
        other = self.add_participation(contest=self.contest); self.session.flush()
        self.assertIsNone(find_receipt(self.session, self.installation, other, self.body["intentId"]))
        self.assertIsNone(find_receipt(self.session, str(uuid4()), self.participation, self.body["intentId"]))

    def test_cross_contest_task_is_rejected(self):
        other = self.add_task(contest=self.add_contest(), submission_format=["main.%l"])
        self.session.flush()
        with self.assertRaises(IntentError):
            admit_intent(self.session, self.cacher, self.installation, self.participation,
                other, self.now, prepare_intent(self.body))
        self.assertEqual(self.count(), 0)

    def test_invalid_language_file_extension_and_disabled_java(self):
        for language, name in (("cpp17", "a.cpp"), ("Java / JDK", "Main.java"),
                               ("C++17 / g++", "a.py")):
            body = copy.deepcopy(self.body); body["language"] = language
            body["files"][0]["sourceFilename"] = name
            with self.assertRaises(UnacceptableSubmission):
                self.admit(body)
        self.assertEqual(self.count(), 0)

    def test_exact_mapping_and_unsupported_modes(self):
        wrong = copy.deepcopy(self.body); wrong["files"][0]["filename"] = "notes.%l"
        with self.assertRaises(IntentError): self.admit(wrong)
        for kind, parameters in (("Communication", []), ("OutputOnly", []),
                                 ("Batch", ["grader", ["", ""], "diff"])):
            self.dataset.task_type, self.dataset.task_type_parameters = kind, parameters
            self.assertFalse(task_capability(self.task)[0])
            with self.assertRaises(IntentError): self.admit()
        self.assertEqual(self.count(), 0)

    def test_file_io_official_batch_does_not_claim_custom_run_support(self):
        self.dataset.task_type_parameters = ["alone", ["input.txt", "output.txt"], "diff"]
        self.assertTrue(task_capability(self.task)[0])
        self.assertTrue(self.admit()[1])

    def test_rollback_before_commit_has_no_submission_or_receipt(self):
        self.session.commit()
        pid, tid = self.participation.id, self.task.id
        self.admit(); self.session.rollback()
        self.assertEqual(self.count(), 0)
        self.assertIsNone(find_receipt(self.session, self.installation, self.participation, self.body["intentId"]))
        self.assertTrue(self.admit()[1])

    def test_commit_before_failed_notification_is_found_by_existing_sweeper(self):
        receipt, _ = self.admit(); self.session.commit()
        submission_id = receipt.submission_id
        rpc = Mock(); rpc.new_submission.side_effect = RuntimeError("RPC disconnected")
        notify_after_commit(rpc, submission_id)
        operations = get_submissions_operations(self.session, self.contest.id)
        self.assertTrue(any(op.object_id == submission_id and op.type_ == ESOperation.COMPILATION for op, _, _ in operations))
        self.assertEqual(self.admit()[0].submission_id, submission_id)

    def _concurrent(self, cws=False, same_intent=False):
        self.contest.max_submission_number = 1
        self.session.commit()
        pid, tid, installation, now = self.participation.id, self.task.id, self.installation, self.now
        bodies = [copy.deepcopy(self.body), copy.deepcopy(self.body)]
        if not same_intent: bodies[1]["intentId"] = str(uuid4())
        processes = []
        root = Path(self.directory.name)
        start = root / "start"
        try:
            for index in range(2):
                request = {"participationId": pid, "taskId": tid, "installation": installation,
                    "body": bodies[index], "storage": str(root / "files"),
                    "ready": str(root / ("ready" + str(index))), "start": str(start),
                    "timestamp": now.isoformat(), "cws": cws and index == 0}
                path = root / ("request" + str(index) + ".json")
                path.write_text(json.dumps(request))
                processes.append(subprocess.Popen([sys.executable,
                    str(Path(__file__).with_name("concurrent_client.py")), str(path)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            deadline = time.monotonic() + 10
            while not all((root / ("ready" + str(index))).exists() for index in range(2)):
                if time.monotonic() >= deadline or any(process.poll() is not None for process in processes):
                    self.fail("Concurrent admission client failed before start barrier")
                time.sleep(0.01)
            start.touch()
            results = []
            for process in processes:
                output, errors = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, errors)
                results.append(json.loads(output.splitlines()[-1]))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=5)
        self.session.expire_all()
        self.assertEqual(self.count(), 1)
        return results

    def test_concurrent_same_intent_returns_one_submission(self):
        results = self._concurrent(same_intent=True)
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sorted(result[1] for result in results), [False, True])

    def test_concurrent_ide_shards_cannot_bypass_quota(self):
        results = self._concurrent()
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_simultaneous_cws_and_ide_share_quota_lock(self):
        results = self._concurrent(cws=True)
        self.assertEqual(sum(result is not None for result in results), 1)


class TestIntentValidation(unittest.TestCase):
    def body(self):
        return {"schemaVersion": 1, "intentId": str(uuid4()), "taskId": 1,
            "language": "C++17 / g++", "snapshotId": str(uuid4()), "workspaceId": str(uuid4()),
            "telemetry": None, "files": [{"filename": "main.%l", "sourceFilename": "a.cpp",
                "fileId": str(uuid4()), "content": "int main(){}"}]}

    def test_no_client_identity_timestamp_or_extra_source_fields(self):
        for key in ("userId", "ownerId", "timestamp", "participationId"):
            body = self.body(); body[key] = "untrusted"
            with self.assertRaises(IntentError): prepare_intent(body)

    def test_unpaired_surrogate_not_silently_replaced(self):
        body = self.body(); body["files"][0]["content"] = "\ud800"
        with self.assertRaises(IntentError) as error: prepare_intent(body)
        self.assertEqual(error.exception.code, "invalid_encoding")

    def test_paths_and_duplicate_mappings_rejected(self):
        for name in ("../a.cpp", "/tmp/a.cpp", "a\\b.cpp", "a\x00.cpp"):
            body = self.body(); body["files"][0]["sourceFilename"] = name
            with self.assertRaises(IntentError): prepare_intent(body)
        body = self.body(); body["files"].append(copy.deepcopy(body["files"][0]))
        with self.assertRaises(IntentError): prepare_intent(body)


class TestReceiptMigration(DatabaseMixin, unittest.TestCase):
    def test_targeted_additive_dry_run_and_repeat_preserve_existing_data(self):
        contest = self.add_contest(description="preserve me")
        self.session.commit(); contest_id = contest.id
        self.session.close()
        OlympiadIDEReceipt.__table__.drop(bind=engine)
        self.assertEqual(migrate(engine)["action"], "would_create")
        self.assertEqual(migrate(engine, apply=True)["action"], "created")
        self.assertEqual(migrate(engine, apply=True)["action"], "already_present")
        self.assertEqual(self.session.query(type(contest)).get(contest_id).description, "preserve me")
        self.session.close()

    def test_disabled_cws_admission_does_not_need_receipt_table(self):
        now = datetime(2026, 11, 2, 12)
        contest = self.add_contest(start=now-timedelta(hours=1), stop=now+timedelta(hours=1),
                                  languages=["Python 3 / CPython"])
        participation = self.add_participation(contest=contest)
        task = self.add_task(contest=contest, submission_format=["main.%l"])
        dataset = self.add_dataset(task=task, task_type="Batch",
                                  task_type_parameters=["alone", ["", ""], "diff"])
        task.active_dataset = dataset
        self.session.commit()
        OlympiadIDEReceipt.__table__.drop(bind=engine)
        try:
            from cms.server.olympiadide.admission import HTTPFile
            with tempfile.TemporaryDirectory(prefix="cms-disabled-source-") as directory:
                with patch.object(config, "submit_local_copy", False):
                    submission = accept_contest_submission(self.session, FileCacher(path=directory),
                        participation, task, now, {"main.%l": [HTTPFile("main.py", b"print(1)\n")]},
                        "Python 3 / CPython")
                    self.session.commit()
                    self.assertEqual(submission.language, "Python 3 / CPython")
        finally:
            self.session.close()
            migrate(engine, apply=True)

    def test_v44_dump_update_adds_optional_receipt_relationship(self):
        from cmscontrib.updaters.update_45 import Updater
        data = {"_version": 44, "0": {"_class": "Submission", "language": "Python 3 / CPython"}}
        output = Updater(data).run()
        self.assertEqual(output["0"]["olympiad_ide_receipts"], [])
        self.assertEqual(output["0"]["language"], "Python 3 / CPython")
