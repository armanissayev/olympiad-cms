"""Authenticated, request-bound CMS assertions for the private ASGI runtime.

CMS checks session/participation on every gateway request. Assertions never reach
JavaScript. Consumed nonces commit independently of the requested operation, so
even failed requests cannot replay an assertion. Retry through CMS for a new one.
"""
import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import jwt
from sqlalchemy import delete, select, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .cms_identity_models import CMSAssertionNonce, CMSPrincipal, CMSWorkspaceBinding
from .models import DevelopmentIdentity, Workspace
from .telemetry_models import TelemetrySession
from .execution_models import ExecutionJob


def principal_id(installation, user, contest, participation):
    scope = json.dumps([installation, str(user), str(contest), str(participation)], separators=(",", ":"), ensure_ascii=True)
    return str(uuid5(NAMESPACE_URL, scope))


def read_key(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("CMS assertion key must be a private regular file (mode 0600 or 0400)")
        key = stream.read(4097)
    if not 32 <= len(key) <= 4096:
        raise ValueError("CMS assertion key must contain 32..4096 bytes")
    return key


@dataclass(frozen=True)
class CMSSettings:
    installation: str
    key: bytes
    max_body_bytes: int = 9_000_000

    @classmethod
    def from_environment(cls):
        installation = os.environ.get("CMS_INSTALLATION_ID", "")
        if str(UUID(installation)) != installation:
            raise ValueError("CMS_INSTALLATION_ID must be a canonical UUID")
        return cls(installation, read_key(os.environ["CMS_ASSERTION_KEY_FILE"]))


class AssertionError(Exception):
    pass


class ScopeError(Exception):
    def __init__(self, message, status=404, code="resource_unavailable"):
        self.status, self.code, self.message = status, code, message


def validate_assertion(token, settings, method, path, query, body):
    required = ["iss", "aud", "sub", "contest", "participation", "task", "principal", "scope", "iat", "nbf", "exp", "jti", "method", "path", "query_sha256", "body_sha256"]
    try:
        claims = jwt.decode(token, settings.key, algorithms=["HS256"], audience="olympiad-ide-runtime", issuer=settings.installation,
                            options={"require": required}, leeway=2)
        for name in ("iat", "nbf", "exp"):
            if type(claims[name]) is not int:
                raise ValueError("invalid time")
        if not 0 < claims["exp"] - claims["iat"] <= 30 or claims["nbf"] != claims["iat"]:
            raise ValueError("invalid lifetime")
        for name in ("sub", "contest", "participation", "task"):
            if not isinstance(claims[name], str) or not claims[name].isascii() or not claims[name].isdigit() or int(claims[name]) <= 0 or len(claims[name]) > 128:
                raise ValueError("invalid identity")
        if str(UUID(claims["jti"])) != claims["jti"]:
            raise ValueError("invalid nonce")
        principal = principal_id(settings.installation, claims["sub"], claims["contest"], claims["participation"])
        if claims["principal"] != principal or claims["scope"] != "runtime":
            raise ValueError("invalid scope")
        if claims["method"] != method or claims["path"] != path:
            raise ValueError("wrong request")
        if claims["query_sha256"] != hashlib.sha256(query).hexdigest() or claims["body_sha256"] != hashlib.sha256(body).hexdigest():
            raise ValueError("wrong content")
        return claims
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise AssertionError("Invalid CMS identity assertion") from error


def consume_assertion(factory, settings, claims, path, method, body):
    """Atomic one-use assertion plus deterministic principal creation (IDE DB only)."""
    now = datetime.now(timezone.utc)
    with factory() as db:
        try:
            db.execute(delete(CMSAssertionNonce).where(CMSAssertionNonce.expires_at < now - timedelta(seconds=60)))
            db.add(CMSAssertionNonce(id=claims["jti"], expires_at=datetime.fromtimestamp(claims["exp"], timezone.utc)))
            db.flush()
            # Retain existing ownership FKs; the backing owner has no usable
            # development bearer token and is never adopted by display name.
            db.execute(insert(DevelopmentIdentity).values(id=claims["principal"], token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
                       created_at=now, expires_at=now).on_conflict_do_nothing(index_elements=["id"]))
            db.execute(insert(CMSPrincipal).values(id=claims["principal"], installation_id=settings.installation,
                       user_id=claims["sub"], contest_id=claims["contest"], participation_id=claims["participation"]).on_conflict_do_nothing(index_elements=["id"]))
            principal = db.get(CMSPrincipal, claims["principal"])
            if (principal.installation_id, principal.user_id, principal.contest_id, principal.participation_id) != (
                    settings.installation, claims["sub"], claims["contest"], claims["participation"]):
                raise AssertionError("CMS principal mapping mismatch")
            db.commit()  # Consume once even when the requested operation fails.
            check_workspace_binding(db, claims, path, method, body)
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise AssertionError("CMS identity assertion was already consumed") from error
    return {"installationId": settings.installation, "userId": claims["sub"], "contestId": claims["contest"],
            "participationId": claims["participation"], "principalId": claims["principal"], "taskId": claims["task"]}


def check_workspace_binding(db, claims, path, method, body):
    payload = {}
    if body:
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise ScopeError("Invalid request body")
        if not isinstance(payload, dict):
            raise ScopeError("Invalid request body")
    suffix = path.removeprefix("/api/v1/")
    workspace = None
    create = False
    if suffix == "workspaces" and method == "POST":
        workspace, create = payload.get("id"), True
    elif suffix == "sync/batches":
        operations = payload.get("operations", [])
        if not isinstance(operations, list) or not operations or any(not isinstance(op, dict) for op in operations):
            raise ScopeError("Invalid workspace scope")
        if any(not isinstance(op.get("workspaceId"), str) for op in operations):
            raise ScopeError("Invalid workspace scope")
        workspaces = {op["workspaceId"] for op in operations}
        if len(workspaces) != 1:
            raise ScopeError("Invalid workspace scope")
        workspace, create = next(iter(workspaces)), True
    elif re.fullmatch(r"(?:workspaces|sync/status)/[0-9a-f-]+(?:/.*)?", suffix):
        workspace = suffix.split("/")[2 if suffix.startswith("sync/") else 1]
    elif suffix == "executions" and method == "POST" or suffix == "telemetry/sessions" and method == "POST":
        workspace = payload.get("workspaceId")
    elif suffix.startswith("executions/"):
        row = db.get(ExecutionJob, suffix.split("/")[1])
        if row is None or row.owner_id != claims["principal"]:
            raise ScopeError("Execution unavailable")
        workspace = row.workspace_id
    elif suffix.startswith("telemetry/") and suffix != "telemetry/policy":
        session_id = suffix.split("/")[2] if suffix.startswith("telemetry/sessions/") else payload.get("sessionId")
        if not isinstance(session_id, str):
            raise ScopeError("Telemetry unavailable")
        row = db.get(TelemetrySession, session_id)
        if row is None or row.owner_id != claims["principal"]:
            raise ScopeError("Telemetry unavailable")
        workspace = row.workspace_id
    if workspace is None:
        return
    try:
        workspace = str(UUID(workspace))
    except (ValueError, TypeError, AttributeError):
        raise ScopeError("Invalid workspace")
    binding = db.get(CMSWorkspaceBinding, workspace)
    if binding is None:
        if not create or db.get(Workspace, workspace) is not None:
            raise ScopeError("Workspace unavailable; legacy data needs explicit import")
        db.scalar(select(DevelopmentIdentity).where(DevelopmentIdentity.id == claims["principal"]).with_for_update(key_share=True))
        maximum = max(1, min(1000, int(os.environ.get("CMS_MAX_WORKSPACES", "100"))))
        count = db.scalar(select(func.count()).select_from(CMSWorkspaceBinding).where(CMSWorkspaceBinding.principal_id == claims["principal"]))
        if count >= maximum:
            raise ScopeError("CMS workspace storage quota reached; export or reuse an existing workspace", 429, "workspace_quota")
        db.execute(insert(CMSWorkspaceBinding).values(workspace_id=workspace, principal_id=claims["principal"], task_id=claims["task"])
                   .on_conflict_do_nothing(index_elements=["workspace_id"]))
        binding = db.get(CMSWorkspaceBinding, workspace)
    if binding.principal_id != claims["principal"] or binding.task_id != claims["task"]:
        raise ScopeError("Workspace scope changed")


class CMSIdentityMiddleware:
    def __init__(self, app, settings, factory):
        self.app, self.settings, self.factory = app, settings, factory

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or (scope["method"] == "GET" and scope["path"] in ("/health/live", "/health/ready")):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"")
        if not authorization.startswith(b"Bearer ") or len(authorization) > 8192:
            return await self.reject(scope, receive, send, 401, "cms_assertion_required", "CMS authentication required")
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.settings.max_body_bytes:
                return await self.reject(scope, receive, send, 413, "too_large", "Request exceeds body limit")
            if not message.get("more_body", False):
                break
        try:
            claims = validate_assertion(authorization[7:].decode("ascii"), self.settings, scope["method"], scope["path"], scope.get("query_string", b""), bytes(body))
            identity = await run_in_threadpool(consume_assertion, self.factory, self.settings, claims, scope["path"], scope["method"], bytes(body))
        except ScopeError as error:
            return await self.reject(scope, receive, send, error.status, error.code, error.message)
        except (AssertionError, UnicodeError):
            return await self.reject(scope, receive, send, 401, "cms_assertion_invalid", "CMS authentication required")
        except SQLAlchemyError:
            return await self.reject(scope, receive, send, 503, "identity_unavailable", "Identity storage temporarily unavailable")
        scope.setdefault("state", {})["cms_identity"] = identity
        delivered = False

        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay_body, send)

    @staticmethod
    async def reject(scope, receive, send, status, code, message):
        response = JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers={"Cache-Control": "no-store"})
        await response(scope, receive, send)
