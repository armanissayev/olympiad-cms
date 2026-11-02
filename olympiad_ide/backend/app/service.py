import hashlib
import json
import os
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    FileNode, RecoverySnapshot, SynchronizationOperation, Workspace,
    WorkspaceRevision, WorkspaceSettings, utcnow,
)
from .schemas import SyncOperation, WorkspaceDocument, WorkspaceResponse


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str, **details):
        self.status = status
        self.body = {"error": {"code": code, "message": message, **details}}


def owned_workspace(db: Session, workspace_id: str, owner_id: str, *, lock=False) -> Workspace:
    query = select(Workspace).where(Workspace.id == workspace_id)
    if lock:
        query = query.with_for_update()
    workspace = db.scalar(query)
    if not workspace or workspace.owner_id != owner_id or workspace.deleted_at:
        raise APIError(404, "not_found", "Workspace not found")
    return workspace


def workspace_response(db: Session, workspace: Workspace) -> WorkspaceResponse:
    nodes = db.scalars(select(FileNode).where(
        FileNode.workspace_id == workspace.id, FileNode.deleted_at.is_(None),
    )).all()
    settings = db.get(WorkspaceSettings, workspace.id)
    return WorkspaceResponse(
        id=workspace.id, ownerId=workspace.owner_id, revision=workspace.revision,
        createdAt=workspace.created_at, updatedAt=workspace.updated_at,
        document=WorkspaceDocument(
            name=workspace.name, settings=settings.settings if settings else {},
            editorState=workspace.editor_state,
            nodes={node.id: {
                "id": node.id, "parentId": node.parent_id, "name": node.name, "type": node.type,
                "createdAt": node.created_at, "updatedAt": node.updated_at,
                **({"content": node.content, "language": node.language,
                    "documentRevision": node.document_revision} if node.type == "file" else {}),
            } for node in nodes},
        ),
    )


def snapshot(db: Session, node: FileNode, reason: str) -> None:
    if node.type != "file":
        return
    recent = db.scalars(select(RecoverySnapshot).where(
        RecoverySnapshot.workspace_id == node.workspace_id, RecoverySnapshot.file_id == node.id,
    ).order_by(RecoverySnapshot.created_at.desc(), RecoverySnapshot.id.desc())).all()
    digest = hashlib.sha256((node.content or "").encode()).hexdigest()
    if recent and recent[0].content_hash == digest and recent[0].name == node.name:
        return
    if reason == "periodic" and recent:
        previous = recent[0].created_at
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=utcnow().tzinfo)
        if utcnow() - previous < timedelta(seconds=int(os.getenv("SNAPSHOT_INTERVAL_SECONDS", "60"))):
            return
    db.add(RecoverySnapshot(
        id=str(uuid4()), workspace_id=node.workspace_id, file_id=node.id, name=node.name,
        content=node.content or "", content_hash=digest, revision=node.server_revision, reason=reason,
    ))
    for old in recent[max(0, int(os.getenv("SNAPSHOT_RETENTION", "20")) - 1):]:
        db.delete(old)


def apply_operation(db: Session, owner_id: str, operation: SyncOperation) -> int:
    workspace_id = str(operation.workspaceId)
    operation_id = str(operation.operationId)
    payload = operation.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    if workspace and (workspace.owner_id != owner_id or workspace.deleted_at):
        raise APIError(404, "not_found", "Workspace not found")
    prior = db.get(SynchronizationOperation, operation_id)
    if prior:
        if prior.owner_id != owner_id or prior.workspace_id != workspace_id or prior.payload_hash != digest:
            raise APIError(409, "operation_reuse", "Operation ID was reused with different content")
        return prior.result_revision
    if workspace is None:
        if operation.baseRevision != 0:
            raise APIError(404, "not_found", "Workspace not found")
        workspace = Workspace(id=workspace_id, owner_id=owner_id, name=operation.document.name, revision=0)
        db.add(workspace)
        db.flush()
    if workspace.revision != operation.baseRevision:
        raise APIError(409, "revision_conflict", "Workspace changed since the last acknowledged revision",
                       server=workspace_response(db, workspace).model_dump(mode="json"))

    revision = workspace.revision + 1
    workspace.name = operation.document.name
    workspace.editor_state = operation.document.editorState
    workspace.revision = revision
    workspace.updated_at = utcnow()
    existing = {n.id: n for n in db.scalars(select(FileNode).where(FileNode.workspace_id == workspace_id))}
    for key, node in existing.items():
        if key not in operation.document.nodes and node.deleted_at is None:
            snapshot(db, node, "before_delete")
            node.deleted_at = utcnow()
            node.server_revision = revision

    for key, incoming in operation.document.nodes.items():
        node = existing.get(key)
        if node and node.type != incoming.type:
            raise APIError(422, "invalid_mutation", "A node's type cannot change")
        parent_id = str(incoming.parentId) if incoming.parentId else None
        if node is None:
            node = FileNode(id=key, workspace_id=workspace_id, type=incoming.type,
                            name=incoming.name, server_revision=revision)
            db.add(node)
        elif node.name != incoming.name or node.parent_id != parent_id or node.deleted_at:
            snapshot(db, node, "before_structure")
        node.parent_id = parent_id
        node.name = incoming.name
        node.content = incoming.content
        node.language = incoming.language
        node.document_revision = incoming.documentRevision
        node.server_revision = revision
        node.created_at = incoming.createdAt
        node.updated_at = incoming.updatedAt
        node.deleted_at = None
        db.flush()
        snapshot(db, node, "initial" if key not in existing else "periodic")

    settings = db.get(WorkspaceSettings, workspace_id)
    if settings is None:
        settings = WorkspaceSettings(workspace_id=workspace_id)
        db.add(settings)
    settings.settings = operation.document.settings.model_dump(mode="json")
    settings.updated_at = utcnow()
    db.add(SynchronizationOperation(
        operation_id=operation_id, workspace_id=workspace_id, owner_id=owner_id,
        payload_hash=digest, base_revision=operation.baseRevision, result_revision=revision,
    ))
    db.add(WorkspaceRevision(
        id=str(uuid4()), workspace_id=workspace_id, revision=revision, operation_id=operation_id,
    ))
    db.flush()
    return revision
