# Contest Management System - http://cms-dev.github.io/
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Immutable official-submission intents admitted in the CMS transaction.

The browser's owner IDs and timestamps are not authority. All identities and
receipt times come from the authenticated native CMS request context. Callers
commit before invoking notification or returning an admitted response.
"""
import hashlib
import json
import logging
from collections import namedtuple
from uuid import UUID

from cms import config
from cms.db import OlympiadIDEReceipt
from cms.server.contest.submission.policy import (
    accept_contest_submission, lock_submission_participation)
from cmscommon.crypto import encrypt_number

logger = logging.getLogger(__name__)
HTTPFile = namedtuple("HTTPFile", ["filename", "body"])


class IntentError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def uuid_string(value, label):
    try:
        if not isinstance(value, str):
            raise ValueError()
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise IntentError(422, "invalid_intent", "%s must be a UUID" % label)


def _text(value, label, limit):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise IntentError(422, "invalid_intent", "Invalid %s" % label)
    return value


def prepare_intent(body):
    """Validate and hash bounded UTF-8 source outside the admission lock."""
    fields = {"schemaVersion", "intentId", "taskId", "language", "files",
              "snapshotId", "workspaceId", "telemetry"}
    if not isinstance(body, dict) or set(body) - fields or fields - {"telemetry"} - set(body):
        raise IntentError(422, "invalid_intent", "Unexpected or missing intent fields")
    if type(body["schemaVersion"]) is not int or body["schemaVersion"] != 1:
        raise IntentError(422, "unsupported_schema", "Only schemaVersion 1 is supported")
    if type(body["taskId"]) is not int or body["taskId"] <= 0:
        raise IntentError(422, "invalid_task", "taskId must be a positive CMS task identifier")
    value = {"schemaVersion": 1, "taskId": body["taskId"],
             "language": _text(body["language"], "CMS language", 120)}
    for name in ("intentId", "snapshotId", "workspaceId"):
        value[name] = uuid_string(body[name], name)
    telemetry = body.get("telemetry")
    if telemetry is not None:
        if not isinstance(telemetry, dict) or set(telemetry) != {"sessionId", "sequence"}:
            raise IntentError(422, "invalid_correlation", "Invalid telemetry boundary")
        sequence = telemetry["sequence"]
        if type(sequence) is not int or not 0 <= sequence <= 9007199254740991:
            raise IntentError(422, "invalid_correlation", "Invalid telemetry sequence")
        telemetry = {"sessionId": uuid_string(telemetry["sessionId"], "sessionId"), "sequence": sequence}
    value["telemetry"] = telemetry
    if not isinstance(body["files"], list) or not 1 <= len(body["files"]) <= 100:
        raise IntentError(422, "invalid_files", "Select between 1 and 100 source files")
    files, manifest, total = {}, [], 0
    normalized = []
    for file in body["files"]:
        if not isinstance(file, dict) or set(file) != {"filename", "sourceFilename", "fileId", "content"}:
            raise IntentError(422, "invalid_files", "Invalid source file fields")
        filename = _text(file["filename"], "CMS filename", 255)
        source_filename = _text(file["sourceFilename"], "source filename", 255)
        if any("/" in name or "\\" in name or "\x00" in name or name in (".", "..") for name in (filename, source_filename)):
            raise IntentError(422, "invalid_files", "Source filenames must be basenames")
        if filename in files:
            raise IntentError(422, "invalid_files", "Two sources map to the same CMS filename")
        if not isinstance(file["content"], str):
            raise IntentError(422, "invalid_files", "Source content must be UTF-8 text")
        try:
            raw = file["content"].encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise IntentError(422, "invalid_encoding", "Source contains an unpaired UTF-16 surrogate; correct it before submitting")
        if len(raw) > config.max_submission_length:
            raise IntentError(413, "source_too_large", "Source exceeds the CMS per-file byte limit")
        total += len(raw)
        if total > 8_000_000:
            raise IntentError(413, "source_too_large", "Submission exceeds the total byte limit")
        file_id = uuid_string(file["fileId"], "fileId")
        files[filename] = [HTTPFile(source_filename, raw)]
        manifest.append({"filename": filename, "sourceFilename": source_filename,
                         "fileId": file_id, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
        normalized.append({"filename": filename, "sourceFilename": source_filename,
                           "fileId": file_id, "content": file["content"]})
    value["files"] = sorted(normalized, key=lambda file: file["filename"])
    return value, files, sorted(manifest, key=lambda file: file["filename"])


def task_capability(task):
    dataset = task.active_dataset
    if dataset is None or dataset.task_type != "Batch":
        return False, "Use the standard CMS participant page for this task type."
    parameters = dataset.task_type_parameters
    if not isinstance(parameters, (list, tuple)) or len(parameters) != 3 or parameters[0] != "alone":
        return False, "Grader-based Batch submissions use the standard CMS participant page."
    if len(task.submission_format) != 1 or not task.submission_format[0].endswith(".%l"):
        return False, "This submission format uses the standard CMS participant page."
    return True, "Standalone Batch source submission through CMS."


def identity_scope(installation_id, participation):
    return {"installationId": installation_id, "userId": str(participation.user_id),
            "contestId": str(participation.contest_id), "participationId": str(participation.id)}


def find_receipt(sql_session, installation_id, participation, intent_id):
    return sql_session.query(OlympiadIDEReceipt).filter(
        OlympiadIDEReceipt.installation_id == installation_id,
        OlympiadIDEReceipt.participation_id == participation.id,
        OlympiadIDEReceipt.intent_id == uuid_string(intent_id, "intentId")).one_or_none()


def admit_intent(sql_session, file_cacher, installation_id, participation, task,
                 timestamp, prepared):
    """Return (receipt, created); caller owns commit/rollback, never RPC here.

    Same-scope receipts are checked before the current phase/capability rules,
    so acknowledged-but-lost submissions remain recoverable after the deadline.
    New intents always face the current server request timestamp and CMS policy.
    """
    body, files, manifest = prepared
    if task.id != body["taskId"] or task.contest_id != participation.contest_id:
        raise IntentError(404, "task_not_found", "Task not found")
    scope = identity_scope(installation_id, participation)
    canonical = json.dumps({"scope": scope, "intent": body}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True).encode("ascii")
    fingerprint = hashlib.sha256(canonical).hexdigest()
    lock_submission_participation(sql_session, participation)
    receipt = find_receipt(sql_session, installation_id, participation, body["intentId"])
    if receipt is not None:
        if receipt.request_digest != fingerprint:
            raise IntentError(409, "intent_reused", "This intent already refers to a different immutable submission")
        return receipt, False
    supported, reason = task_capability(task)
    if not supported:
        raise IntentError(422, "unsupported_task", reason)
    if set(files) != set(task.submission_format):
        raise IntentError(422, "invalid_files", "Select exactly the files required by the CMS task")
    submission = accept_contest_submission(
        sql_session, file_cacher, participation, task, timestamp, files, body["language"])
    sql_session.flush()
    receipt = OlympiadIDEReceipt(
        installation_id=installation_id, intent_id=body["intentId"],
        participation=participation, submission=submission,
        request_digest=fingerprint, external_id=encrypt_number(submission.id, config.secret_key),
        identity_scope=scope, source_manifest=manifest,
        correlation={"workspaceId": body["workspaceId"], "snapshotId": body["snapshotId"],
                     "telemetry": body["telemetry"]}, received_at=timestamp)
    sql_session.add(receipt)
    sql_session.flush()
    return receipt, True


def iso_time(timestamp):
    return timestamp.isoformat(timespec="microseconds") + "Z"


def receipt_view(receipt):
    submission = receipt.submission
    return {"schemaVersion": 1, "state": "admitted", "intentId": receipt.intent_id,
            "submissionId": receipt.external_id, "receivedAt": iso_time(receipt.received_at),
            "official": submission.official, "taskId": submission.task_id,
            "language": submission.language, "files": receipt.source_manifest,
            "requestDigest": receipt.request_digest, **receipt.correlation}


def notify_after_commit(evaluation_service, submission_id):
    """Best-effort hint; EvaluationService's durable 117s sweeper is recovery.

    Only call after a successful DB commit. A notification failure must not turn
    a committed admission into a rejection or trigger a second submission.
    """
    try:
        evaluation_service.new_submission(submission_id=submission_id)
    except Exception:
        logger.exception("IDE admission %s committed; evaluation notification failed; CMS sweeper will recover", submission_id)
