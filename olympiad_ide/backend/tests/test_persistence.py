from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

from sqlalchemy import create_engine, select

from app.main import create_app
from app.models import FileNode, SynchronizationOperation, WorkspaceRevision
from conftest import APIClient


def document():
    folder_id, file_id = str(uuid4()), str(uuid4())
    now = "2026-10-20T00:00:00Z"
    return {"name": "Tests", "settings": {}, "editorState": {}, "nodes": {
        folder_id: {"id": folder_id, "type": "folder", "parentId": None, "name": "src", "createdAt": now, "updatedAt": now},
        file_id: {"id": file_id, "type": "file", "parentId": folder_id, "name": "main.cpp", "content": "int main() {}\n",
                  "language": "cpp", "documentRevision": 1, "createdAt": now, "updatedAt": now},
    }}


def operation(workspace_id, content, base=0):
    return {"workspaceId": workspace_id, "operationId": str(uuid4()), "baseRevision": base, "document": content}


def send(api, *operations):
    return api.post("/api/v1/sync/batches", json={"operations": list(operations)})


def test_workspace_crud_files_settings_and_revision(api):
    wid = str(uuid4())
    doc = document()
    created = api.post("/api/v1/workspaces", json={"id": wid, "document": doc})
    assert created.status_code == 201, created.text
    assert created.json()["revision"] == 1
    assert api.get("/api/v1/workspaces").json()[0]["id"] == wid
    retrieved = api.get(f"/api/v1/workspaces/{wid}").json()
    assert len(retrieved["document"]["nodes"]) == 2
    file_id = next(key for key, node in doc["nodes"].items() if node["type"] == "file")
    doc["nodes"][file_id]["content"] = "Unicode Ω你好  \n"
    doc["nodes"][file_id]["name"] = "renamed.cpp"
    doc["nodes"][file_id]["parentId"] = None
    doc["settings"] = {"fontSize": 18}
    response = send(api, operation(wid, doc, 1))
    assert response.status_code == 200, response.text
    assert response.json()["acknowledgements"][0]["revision"] == 2
    assert api.get(f"/api/v1/workspaces/{wid}/files").json()[file_id]["content"] == "Unicode Ω你好  \n"
    assert api.get(f"/api/v1/workspaces/{wid}/settings").json()["fontSize"] == 18
    assert api.request("DELETE", f"/api/v1/workspaces/{wid}", json={"baseRevision": 1}).status_code == 409
    assert api.request("DELETE", f"/api/v1/workspaces/{wid}", json={"baseRevision": 2}).status_code == 204
    assert api.get(f"/api/v1/workspaces/{wid}").status_code == 404


def test_session_and_workspace_isolation(api):
    wid = str(uuid4())
    op = operation(wid, document())
    assert send(api, op).status_code == 200
    other = APIClient(api.app)
    assert other.get(f"/api/v1/workspaces/{wid}").status_code == 401
    assert other.post("/api/v1/session").status_code == 200
    assert other.get(f"/api/v1/workspaces/{wid}").status_code == 404
    assert send(other, op).status_code == 404
    assert other.get(f"/api/v1/workspaces/{wid}/snapshots").status_code == 404
    assert api.cookies.get("olympiad_session") != other.cookies.get("olympiad_session")
    assert other.get("/api/v1/workspaces").json() == []


def test_empty_editor_group_roundtrips_null_active_file(api):
    wid = str(uuid4())
    doc = document()
    doc["editorState"] = {"groups": {
        "primary": {"id": "primary", "tabIds": [], "activeFileId": None},
        "secondary": {"id": "secondary", "tabIds": [], "activeFileId": None},
    }}
    assert send(api, operation(wid, doc)).status_code == 200
    fetched = api.get(f"/api/v1/workspaces/{wid}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["document"]["editorState"]["groups"]["secondary"]["activeFileId"] is None


def test_parent_validation_and_cycle_rejection(api):
    wid = str(uuid4())
    doc = document()
    fid = next(key for key, node in doc["nodes"].items() if node["type"] == "file")
    doc["nodes"][fid]["parentId"] = str(uuid4())
    assert send(api, operation(wid, doc)).status_code == 422
    doc = document()
    folder = next(key for key, node in doc["nodes"].items() if node["type"] == "folder")
    doc["nodes"][folder]["parentId"] = folder
    assert send(api, operation(wid, doc)).status_code == 422
    assert api.get(f"/api/v1/workspaces/{wid}").status_code == 404


def test_idempotent_replay_and_operation_id_reuse(api):
    wid = str(uuid4())
    op = operation(wid, document())
    first = send(api, op)
    assert first.status_code == 200, first.text
    assert send(api, op).json() == first.json()
    assert api.get(f"/api/v1/sync/status/{wid}").json()["revision"] == 1
    altered = deepcopy(op)
    altered["document"]["name"] = "changed payload"
    assert send(api, altered).status_code == 409
    with api.app.state.session_factory() as db:
        assert len(db.scalars(select(SynchronizationOperation)).all()) == 1
        assert len(db.scalars(select(WorkspaceRevision)).all()) == 1


def test_stale_text_rename_and_delete_conflict_preserves_server(api):
    wid = str(uuid4())
    doc = document()
    assert send(api, operation(wid, doc)).status_code == 200
    fid = next(key for key, node in doc["nodes"].items() if node["type"] == "file")
    latest = deepcopy(doc)
    latest["nodes"][fid]["content"] = "server text"
    assert send(api, operation(wid, latest, 1)).status_code == 200
    for mutation in ["text", "rename", "delete"]:
        stale = deepcopy(doc)
        if mutation == "text": stale["nodes"][fid]["content"] = "local text"
        if mutation == "rename": stale["nodes"][fid]["name"] = "other.cpp"
        if mutation == "delete": del stale["nodes"][fid]
        response = send(api, operation(wid, stale, 1))
        assert response.status_code == 409
        assert response.json()["error"]["server"]["document"]["nodes"][fid]["content"] == "server text"


def test_invalid_second_mutation_rolls_back_complete_batch(api):
    wid = str(uuid4())
    doc = document()
    assert send(api, operation(wid, doc)).status_code == 200
    updated = deepcopy(doc)
    updated["name"] = "must roll back"
    invalid = deepcopy(doc)
    fid = next(key for key, node in invalid["nodes"].items() if node["type"] == "file")
    invalid["nodes"][fid] = {key: value for key, value in invalid["nodes"][fid].items() if key not in ("content", "language")}
    invalid["nodes"][fid]["type"] = "folder"
    response = send(api, operation(wid, updated, 1), operation(wid, invalid, 2))
    assert response.status_code == 422, response.text
    current = api.get(f"/api/v1/workspaces/{wid}").json()
    assert current["revision"] == 1
    assert current["document"]["name"] == "Tests"


def test_soft_delete_snapshots_and_recovery(api):
    wid = str(uuid4())
    doc = document()
    assert send(api, operation(wid, doc)).status_code == 200
    fid = next(key for key, node in doc["nodes"].items() if node["type"] == "file")
    original = doc["nodes"].pop(fid)
    assert send(api, operation(wid, doc, 1)).status_code == 200
    snapshots = api.get(f"/api/v1/workspaces/{wid}/snapshots?fileId={fid}").json()
    assert snapshots[0]["content"] == original["content"]
    assert len(snapshots[0]["contentHash"]) == 64
    with api.app.state.session_factory() as db:
        assert db.get(FileNode, (fid, wid)).deleted_at is not None
    doc["nodes"][fid] = original
    assert send(api, operation(wid, doc, 2)).status_code == 200
    assert fid in api.get(f"/api/v1/workspaces/{wid}/files").json()


def test_data_and_session_survive_engine_and_app_restart(api):
    wid = str(uuid4())
    assert send(api, operation(wid, document())).status_code == 200
    url = api.app.state.engine.url
    api.app.state.engine.dispose()
    fresh_engine = create_engine(url)
    restarted = APIClient(create_app(fresh_engine))
    restarted.cookies = api.cookies
    assert restarted.get(f"/api/v1/workspaces/{wid}").json()["revision"] == 1
    fresh_engine.dispose()


def test_concurrent_postgres_writers_cannot_both_commit_same_revision(api):
    wid = str(uuid4())
    doc = document()
    assert send(api, operation(wid, doc)).status_code == 200
    clients = [APIClient(api.app), APIClient(api.app)]
    for client in clients: client.cookies.update(api.cookies)
    a, b = deepcopy(doc), deepcopy(doc)
    a["name"], b["name"] = "branch A", "branch B"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda args: send(args[0], operation(wid, args[1], 1)).status_code, zip(clients, [a, b])))
    assert sorted(results) == [200, 409]
    assert api.get(f"/api/v1/sync/status/{wid}").json()["revision"] == 2
