import hashlib
import json
import time
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import select

from app.cms_identity import CMSSettings, AssertionError, principal_id, validate_assertion
from app.cms_identity_models import CMSPrincipal, CMSWorkspaceBinding
from app.main import create_app
from app.models import DevelopmentIdentity
from conftest import APIClient

KEY = b"test-only-cms-assertion-key-32-bytes-long"
INSTALLATION = "898dbca3-c879-4f7a-b0c3-49830c9e1c28"


def token(path="/api/v1/session", method="POST", body=b"", query=b"", user="1", contest="2", participation="3", task="4", **updates):
    now = int(time.time())
    claims = {"iss": INSTALLATION, "aud": "olympiad-ide-runtime", "sub": user,
              "contest": contest, "participation": participation, "task": task,
              "principal": principal_id(INSTALLATION, user, contest, participation),
              "scope": "runtime", "iat": now, "nbf": now, "exp": now + 30, "jti": str(uuid4()),
              "method": method, "path": path, "query_sha256": hashlib.sha256(query).hexdigest(),
              "body_sha256": hashlib.sha256(body).hexdigest()}
    claims.update(updates)
    return jwt.encode(claims, KEY, algorithm="HS256")


@pytest.mark.parametrize("updates", [{"aud": "wrong"}, {"iss": str(uuid4())}, {"scope": "admin"},
    {"principal": str(uuid4())}, {"exp": int(time.time()) - 60}, {"exp": int(time.time()) + 3600},
    {"sub": "not-a-cms-id"}, {"task": "0"}, {"method": "GET"}, {"path": "/api/v1/other"},
    {"body_sha256": "0" * 64}, {"query_sha256": "0" * 64}, {"jti": "invalid"}])
def test_assertions_reject_wrong_scope_request_and_expiry(updates):
    with pytest.raises(AssertionError):
        validate_assertion(token(**updates), CMSSettings(INSTALLATION, KEY), "POST", "/api/v1/session", b"", b"")


def test_principal_is_stable_and_separated_by_installation_user_contest_participation():
    values = [INSTALLATION, "1", "2", "3"]
    original = principal_id(*values)
    assert original == principal_id(*values)
    for index in range(4):
        changed = values.copy(); changed[index] += "x"
        assert original != principal_id(*changed)


@pytest.fixture
def cms_api(api, monkeypatch, tmp_path):
    # api fixture supplies an independently migrated disposable schema, plus a
    # legacy development identity which must survive and must not be adopted.
    key = tmp_path / "assertion.key"; key.write_bytes(KEY); key.chmod(0o600)
    monkeypatch.setenv("IDE_AUTH_MODE", "cms")
    monkeypatch.setenv("CMS_INSTALLATION_ID", INSTALLATION)
    monkeypatch.setenv("CMS_ASSERTION_KEY_FILE", str(key))
    app = create_app(api.app.state.engine)
    return APIClient(app)


def call(client, method, path, body=None, **identity):
    raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
    assertion = token(path, method, raw, **identity)
    return client.request(method, path, content=raw, headers={"Authorization": "Bearer " + assertion, "Content-Type": "application/json"})


def test_cms_mode_never_establishes_development_cookie_or_accepts_forged_headers(cms_api):
    for headers in ({}, {"X-Olympiad-Principal": str(uuid4())}, {"Authorization": "Bearer forged"}):
        response = cms_api.post("/api/v1/session", headers=headers)
        assert response.status_code == 401
        assert "set-cookie" not in response.headers
    assert cms_api.get("/api/v1/telemetry/policy").status_code == 401
    assert cms_api.get("/health/live").status_code == 200
    assert cms_api.get("/health/ready").status_code == 200


def test_assertion_is_one_use_and_mapping_is_stable(cms_api):
    assertion = token()
    headers = {"Authorization": "Bearer " + assertion}
    first = cms_api.post("/api/v1/session", headers=headers)
    assert first.status_code == 200
    assert "set-cookie" not in first.headers
    assert cms_api.post("/api/v1/session", headers=headers).status_code == 401
    retry = call(cms_api, "POST", "/api/v1/session")
    assert retry.json()["identityId"] == first.json()["identityId"]
    different = call(cms_api, "POST", "/api/v1/session", user="2")
    assert different.json()["identityId"] != first.json()["identityId"]
    with cms_api.app.state.session_factory() as db:
        assert len(list(db.scalars(select(CMSPrincipal)))) == 2
        assert len(list(db.scalars(select(DevelopmentIdentity)))) == 3  # old identity retained


def test_request_body_and_query_are_bound(cms_api):
    headers = {"Authorization": "Bearer " + token(body=b'{}')}
    assert cms_api.post("/api/v1/session", content=b'{"other":1}', headers=headers).status_code == 401
    headers = {"Authorization": "Bearer " + token()}
    assert cms_api.post("/api/v1/session?other=1", headers=headers).status_code == 401


def test_workspace_reservation_cannot_cross_task_or_participant(cms_api):
    workspace = str(uuid4())
    # Deliberately invalid document causes admission to fail after the scope
    # reservation; retry remains bound to the original participant/task.
    response = call(cms_api, "POST", "/api/v1/workspaces", {"id": workspace})
    assert response.status_code == 422
    with cms_api.app.state.session_factory() as db:
        binding = db.get(CMSWorkspaceBinding, workspace)
        assert binding.task_id == "4"
    for identity in ({"task": "5"}, {"user": "2"}, {"contest": "3"}):
        response = call(cms_api, "POST", "/api/v1/workspaces", {"id": workspace}, **identity)
        assert response.status_code == 404


def test_cms_mode_invalid_configuration_fails_closed(api, monkeypatch):
    monkeypatch.setenv("IDE_AUTH_MODE", "cms")
    monkeypatch.setenv("CMS_INSTALLATION_ID", "not-a-uuid")
    with pytest.raises(ValueError):
        create_app(api.app.state.engine)


def test_concurrent_assertion_replay_allows_only_one_request(cms_api):
    from concurrent.futures import ThreadPoolExecutor
    assertion = token()
    def request(_):
        return APIClient(cms_api.app).post("/api/v1/session", headers={"Authorization": "Bearer " + assertion}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(request, range(2)))
    assert results == [200, 401]


def test_workspace_quota_is_bounded_and_does_not_change_identity(cms_api, monkeypatch):
    monkeypatch.setenv("CMS_MAX_WORKSPACES", "1")
    assert call(cms_api, "POST", "/api/v1/workspaces", {"id": str(uuid4())}).status_code == 422
    response = call(cms_api, "POST", "/api/v1/workspaces", {"id": str(uuid4())})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "workspace_quota"
    assert call(cms_api, "POST", "/api/v1/session").status_code == 200
