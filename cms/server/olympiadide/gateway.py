"""Bounded authenticated private transport; CMS policy stays in this service."""
import hashlib
import json
import re
import time
from urllib.parse import parse_qsl
from uuid import uuid4

import jwt
import requests
from gevent.lock import BoundedSemaphore
from gevent import Timeout

from cms import config
from cms.db import Task
from .base import IDEAPIHandler


UUID_PATH = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# Each entry is a method set, exact suffix expression and allowed query keys.
ROUTES = [
    ({"POST"}, r"session", set()),
    ({"GET", "POST"}, r"workspaces", set()),
    ({"GET", "PATCH", "DELETE"}, r"workspaces/" + UUID_PATH, set()),
    ({"GET"}, r"workspaces/" + UUID_PATH + r"/(files|settings|executions)", set()),
    ({"GET"}, r"workspaces/" + UUID_PATH + r"/snapshots", {"fileId"}),
    ({"GET", "POST"}, r"workspaces/" + UUID_PATH + r"/execution-resources", set()),
    ({"POST"}, r"sync/batches", set()),
    ({"GET"}, r"sync/status/" + UUID_PATH, set()),
    ({"GET"}, r"telemetry/policy", set()),
    ({"POST"}, r"telemetry/(sessions|batches)", set()),
    ({"POST"}, r"telemetry/batches/" + UUID_PATH + r"/chunks", set()),
    ({"POST"}, r"telemetry/sessions/" + UUID_PATH + r"/close", set()),
    ({"GET"}, r"telemetry/sessions/" + UUID_PATH + r"/status", set()),
    ({"GET"}, r"telemetry/sessions/" + UUID_PATH + r"/(events|checkpoints)", {"after", "pageSize"}),
    ({"POST"}, r"executions", set()),
    ({"GET"}, r"executions/" + UUID_PATH, set()),
    ({"POST"}, r"executions/" + UUID_PATH + r"/cancel", set()),
    ({"GET"}, r"executions/" + UUID_PATH + r"/events", {"after"}),
    ({"GET"}, r"execution-capacity", set()),
]


def allowed_request(method, suffix, query):
    if len(query) > 2048:
        return False
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
    except ValueError:
        return False
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        return False
    return any(method in methods and re.fullmatch(pattern, suffix) is not None and set(keys) <= allowed
               for methods, pattern, allowed in ROUTES)


def assertion(identity, method, path, query, body, key):
    now = int(time.time())
    claims = {"iss": identity["installationId"], "aud": "olympiad-ide-runtime", "sub": str(identity["userId"]),
              "contest": str(identity["contestId"]), "participation": str(identity["participationId"]),
              "principal": identity["principalId"], "task": identity["taskId"], "scope": "runtime", "iat": now, "nbf": now, "exp": now + 30,
              "jti": str(uuid4()), "method": method, "path": path,
              "query_sha256": hashlib.sha256(query.encode("ascii")).hexdigest(), "body_sha256": hashlib.sha256(body).hexdigest()}
    return jwt.encode(claims, key, algorithm="HS256")


class RuntimeGateway(IDEAPIHandler):
    def get(self, suffix):
        self.forward(suffix)

    def post(self, suffix):
        self.forward(suffix)

    def patch(self, suffix):
        self.forward(suffix)

    def delete(self, suffix):
        self.forward(suffix)

    def forward(self, suffix):
        method, query, body = self.request.method, self.request.query, self.request.body
        if not allowed_request(method, suffix, query):
            self.set_status(404)
            self.finish({"error": {"code": "runtime_route_unavailable", "message": "Runtime route unavailable"}})
            return
        if len(body) > config.olympiad_ide_max_body_bytes:
            self.set_status(413)
            self.finish({"error": {"code": "too_large", "message": "Request exceeds body limit"}})
            return
        task_id = self.request.headers.get("X-Olympiad-Task", "")
        if not task_id.isascii() or not task_id.isdigit() or len(task_id) > 12:
            self.set_status(403)
            self.finish({"error": {"code": "task_required", "message": "Select an authorized CMS task"}})
            return
        task_id = str(int(task_id))
        task = self.sql_session.query(Task).filter(Task.id == int(task_id), Task.contest_id == self.contest.id).first()
        if task is None or not (self.r_params["actual_phase"] in (0, 3) or self.current_user.unrestricted):
            self.set_status(403)
            self.finish({"error": {"code": "task_unavailable", "message": "Task is not currently available"}})
            return
        if method == "POST" and suffix == "executions":
            from .admission import task_capability
            supported, _reason = task_capability(task)
            parameters = task.active_dataset.task_type_parameters if task.active_dataset else None
            if not supported or not parameters or parameters[1] != ["", ""]:
                self.set_status(422)
                self.finish({"error": {"code": "custom_run_unsupported", "message": "Use CMS for this task's grader or I/O mode; custom Run supports standalone stdin/stdout Batch tasks."}})
                return
        identity = dict(self.ide_identity)
        identity["taskId"] = task_id
        # No CMS database transaction/connection waits on the private runtime.
        self.sql_session.close()
        if not hasattr(self.service, "ide_runtime_slots"):
            self.service.ide_runtime_slots = BoundedSemaphore(config.olympiad_ide_max_runtime_requests)
        slots = self.service.ide_runtime_slots
        if not slots.acquire(blocking=False):
            self.set_status(503)
            self.set_header("Retry-After", "2")
            self.finish({"error": {"code": "runtime_busy", "message": "Background storage is busy; retry shortly"}})
            return
        try:
            # Key rotation requires a coordinated native/private-runtime restart.
            with open(config.olympiad_ide_signing_key_file, "rb") as stream:
                key = stream.read(4097)
            path = "/api/v1/" + suffix
            signed = assertion(identity, method, path, query, body, key)
            url = config.olympiad_ide_runtime_url.rstrip("/") + path + ("?" + query if query else "")
            with Timeout(config.olympiad_ide_request_timeout), requests.Session() as client:
                client.trust_env = False
                with client.request(method, url, data=body, headers={"Authorization": "Bearer " + signed, "Content-Type": "application/json", "Accept": "application/json"},
                                    timeout=(2, config.olympiad_ide_request_timeout), allow_redirects=False, stream=True) as response:
                    if 300 <= response.status_code < 400:
                        raise ValueError("Private runtime redirect rejected")
                    payload = bytearray()
                    for chunk in response.iter_content(65536):
                        payload.extend(chunk)
                        if len(payload) > config.olympiad_ide_max_response_bytes:
                            raise ValueError("Private runtime response exceeds limit")
                    if response.status_code != 204:
                        json.loads(payload)
                    self.set_status(response.status_code)
                    self.set_header("Content-Type", "application/json")
                    self.set_header("Cache-Control", "no-store")
                    self.finish(bytes(payload))
        except (requests.RequestException, ValueError, OSError, UnicodeError, Timeout):
            self.set_status(503)
            self.finish({"error": {"code": "runtime_unavailable", "message": "IDE storage or custom execution is temporarily unavailable"}})
        finally:
            slots.release()


HANDLERS = [(r"/ide/api/runtime/v1/(.*)", RuntimeGateway)]
