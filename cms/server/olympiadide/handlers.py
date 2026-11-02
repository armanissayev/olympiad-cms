# Contest Management System - http://cms-dev.github.io/
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Native participant official submission, receipt and feedback routes."""
import json
import logging
from urllib.parse import quote

try:
    import tornado4.web as tornado_web
except ImportError:
    import tornado.web as tornado_web
from sqlalchemy.orm import joinedload

from cms import config
from cms.db import OlympiadIDEReceipt, Submission, Task
from cms.server.contest.submission import UnacceptableSubmission
from cms.server.contest.submission.policy import check_submission_phase
from cmscommon.crypto import decrypt_number, encrypt_number
from .base import IDEAPIHandler
from .admission import (IntentError, admit_intent, find_receipt, iso_time,
                        notify_after_commit, prepare_intent, receipt_view)
from .feedback import participant_feedback
from cms.server.contest.submission.feedback import submission_status

logger = logging.getLogger(__name__)


def _error(handler, error):
    handler.sql_session.rollback()
    if isinstance(error, IntentError):
        status, code, message = error.status, error.code, error.message
    else:
        status, code, message = 422, "admission_rejected", error.formatted_text
    handler.write_json({"schemaVersion": 1, "state": "rejected",
                        "error": {"code": code, "message": message}}, status)


class OfficialHandler(IDEAPIHandler):
    def selected_task(self, task_id):
        try:
            value = int(task_id)
        except (TypeError, ValueError):
            raise IntentError(422, "invalid_task", "A CMS task identifier is required")
        task = self.sql_session.query(Task).filter(
            Task.id == value, Task.contest_id == self.contest.id).one_or_none()
        if task is None:
            raise IntentError(404, "task_not_found", "Task not found")
        return task

    def cws_url(self, task):
        return config.olympiad_ide_cws_base_path.rstrip("/") + "/tasks/" + quote(task.name, safe="") + "/submissions"


class OfficialSubmissionsHandler(OfficialHandler):
    @property
    def refresh_cookie(self):
        # Match the manual CWS Submit action without extending idle sessions
        # through background history/status polling.
        return self.request.method == "POST"

    def post(self):
        try:
            if len(self.request.body) > min(config.olympiad_ide_max_body_bytes, 9_000_000):
                raise IntentError(413, "request_too_large", "Submission request exceeds the byte limit")
            if self.request.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                raise IntentError(415, "json_required", "Submit a versioned JSON intent")
            try:
                body = json.loads(self.request.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise IntentError(422, "invalid_json", "Malformed submission intent")
            prepared = prepare_intent(body)
            task = self.selected_task(prepared[0]["taskId"])
            receipt, created = admit_intent(
                self.sql_session, self.service.file_cacher,
                self.principal()["installationId"], self.current_user, task,
                self.timestamp, prepared)
            # Materialize a bounded immutable response before releasing ORM state.
            response = receipt_view(receipt)
            submission_id = receipt.submission_id
            self.sql_session.commit()
        except (IntentError, UnacceptableSubmission) as error:
            _error(self, error)
            return
        # A DB exception before/at commit goes to the generic safe 500 handler;
        # it is an unknown outcome, never an invented successful receipt.
        if created:
            notify_after_commit(self.service.evaluation_service, submission_id)
        self.write_json(response, 201 if created else 200)

    def get(self):
        try:
            task = self.selected_task(self.get_argument("taskId", None))
            phase = check_submission_phase(self.current_user, task, self.timestamp)
            offset = int(self.get_argument("offset", "0"))
            if not 0 <= offset <= 100_000:
                raise ValueError()
        except ValueError:
            _error(self, IntentError(422, "invalid_offset", "Invalid history offset"))
            return
        except (IntentError, UnacceptableSubmission) as error:
            _error(self, error)
            return
        query = self.sql_session.query(Submission).filter(
            Submission.participation_id == self.current_user.id,
            Submission.task_id == task.id)
        total = query.count()
        submissions = query.options(joinedload(Submission.olympiad_ide_receipts)).order_by(
            Submission.timestamp.desc(), Submission.id.desc()).offset(offset).limit(30).all()
        result = []
        for submission in submissions:
            receipt = next((item for item in submission.olympiad_ide_receipts
                            if item.installation_id == self.principal()["installationId"]), None)
            result.append({
                "submissionId": receipt.external_id if receipt else encrypt_number(submission.id, config.secret_key),
                "intentId": receipt.intent_id if receipt else None,
                "correlation": receipt.correlation if receipt else None,
                "receivedAt": iso_time(submission.timestamp), "official": submission.official,
                "language": submission.language, "cwsUrl": self.cws_url(task),
                "status": submission_status(self.sql_session, submission, phase, self.translation),
            })
        self.write_json({"schemaVersion": 1, "submissions": result, "total": total,
                         "nextOffset": offset + len(result) if offset + len(result) < total else None})


class OfficialReceiptHandler(OfficialHandler):
    def get(self, intent_id):
        try:
            receipt = find_receipt(self.sql_session, self.principal()["installationId"],
                                   self.current_user, intent_id)
            if receipt is None:
                raise IntentError(404, "intent_not_found", "No committed receipt exists for this intent")
            self.write_json(receipt_view(receipt))
        except IntentError as error:
            _error(self, error)


class OfficialStatusHandler(OfficialHandler):
    def get(self, external_id):
        try:
            if len(external_id) > 128:
                raise ValueError()
            # A logical CMS dump import may remap database primary keys. The
            # stored opaque receipt identifier remains attached to its actual
            # Submission relationship, rather than decrypting an obsolete ID.
            receipt = self.sql_session.query(OlympiadIDEReceipt).filter(
                OlympiadIDEReceipt.external_id == external_id,
                OlympiadIDEReceipt.installation_id == self.principal()["installationId"],
                OlympiadIDEReceipt.participation_id == self.current_user.id).one_or_none()
            submission_id = receipt.submission_id if receipt else decrypt_number(external_id, config.secret_key)
            task = self.selected_task(self.get_argument("taskId", None))
            phase = check_submission_phase(self.current_user, task, self.timestamp)
            submission = self.sql_session.query(Submission).filter(
                Submission.id == submission_id,
                Submission.participation_id == self.current_user.id,
                Submission.task_id == task.id).one_or_none()
            if submission is None:
                raise IntentError(404, "submission_not_found", "Submission not found")
            self.write_json({"schemaVersion": 1, "submissionId": external_id,
                             "status": participant_feedback(self.sql_session, submission, phase, self.translation),
                             "cwsUrl": self.cws_url(task)})
        except (ValueError, TypeError):
            _error(self, IntentError(404, "submission_not_found", "Submission not found"))
        except (IntentError, UnacceptableSubmission) as error:
            _error(self, error)


HANDLERS = [
    (r"/ide/api/submissions", OfficialSubmissionsHandler),
    (r"/ide/api/submissions/status/([A-Za-z0-9_.-]+)", OfficialStatusHandler),
    (r"/ide/api/submissions/([0-9A-Fa-f-]{36})", OfficialReceiptHandler),
]
