import hashlib
import os
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .database import make_engine, session_factory
from .models import DevelopmentIdentity, RecoverySnapshot, Workspace, utcnow
from .schemas import (
    DeleteRequest, SyncAcknowledgement, SyncBatch, SyncOperation, SyncResponse,
    WorkspaceCreate, WorkspacePatch, WorkspaceResponse,
)
from .service import APIError, apply_operation, owned_workspace, workspace_response

COOKIE = "olympiad_session"


def create_app(engine=None) -> FastAPI:
    auth_mode = os.getenv("IDE_AUTH_MODE", "development")
    if auth_mode not in ("development", "cms"):
        raise ValueError("IDE_AUTH_MODE must be development or cms")
    app = FastAPI(title="Olympiad IDE API", version="0.2.0",
                  docs_url=None if auth_mode == "cms" else "/docs",
                  redoc_url=None if auth_mode == "cms" else "/redoc",
                  openapi_url=None if auth_mode == "cms" else "/openapi.json")
    app.state.engine = engine if engine is not None else make_engine()
    app.state.auth_mode = auth_mode
    app.state.session_factory = session_factory(app.state.engine)
    if auth_mode == "cms":
        from .cms_identity import CMSSettings, CMSIdentityMiddleware
        cms_settings = CMSSettings.from_environment()
        app.add_middleware(CMSIdentityMiddleware, settings=cms_settings, factory=app.state.session_factory)

    @app.exception_handler(APIError)
    async def api_error(_request, error):
        return JSONResponse(error.body, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, error):
        return JSONResponse({"error": {"code": "validation_error", "message": str(error)}}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def integrity_error(_request, _error):
        return JSONResponse({"error": {"code": "concurrent_mutation", "message": "Concurrent change; retry with current revision"}}, status_code=409)

    @app.middleware("http")
    async def request_boundary(request: Request, call_next):
        try:
            length = int(request.headers.get("content-length", "0"))
            if length < 0:
                raise ValueError()
        except ValueError:
            return JSONResponse({"error": {"code": "invalid_length", "message": "Invalid content length"}}, status_code=400)
        if length > 9_000_000:
            return JSONResponse({"error": {"code": "too_large", "message": "Request exceeds 9 MB"}}, status_code=413)
        origin = request.headers.get("origin")
        allowed = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080").split(",")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in allowed:
            return JSONResponse({"error": {"code": "origin_denied", "message": "Origin not allowed"}}, status_code=403)
        return await call_next(request)

    def db_session():
        with app.state.session_factory() as db:
            yield db

    def identity(request: Request, db: Session = Depends(db_session)) -> DevelopmentIdentity:
        if auth_mode == "cms":
            scope = getattr(request.state, "cms_identity", None)
            if not scope:
                raise APIError(401, "cms_session_required", "Authenticate through CMS")
            owner = db.get(DevelopmentIdentity, scope["principalId"])
            if owner is None:
                raise APIError(401, "cms_session_required", "Authenticate through CMS")
            return owner
        token = request.cookies.get(COOKIE)
        found = db.scalar(select(DevelopmentIdentity).where(
            DevelopmentIdentity.token_hash == hashlib.sha256((token or "").encode()).hexdigest(),
            DevelopmentIdentity.expires_at > utcnow(),
        ))
        if not found:
            raise APIError(401, "session_required", "Establish a development session first")
        return found

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready(db: Session = Depends(db_session)):
        try:
            db.execute(text("SELECT 1"))
            if auth_mode == "cms":
                from .cms_identity_models import CMSPrincipal, CMSWorkspaceBinding, CMSAssertionNonce
                for model in (CMSPrincipal, CMSWorkspaceBinding, CMSAssertionNonce):
                    db.execute(select(model).limit(1))
        except SQLAlchemyError:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready"}

    @app.get("/api/v1/health")
    def health(db: Session = Depends(db_session)):
        db.execute(text("SELECT 1"))
        return {"service": "olympiad-ide-api", "status": "ok", "version": "0.2.0"}

    @app.post("/api/v1/session")
    def establish_session(request: Request, response: Response, db: Session = Depends(db_session)):
        if auth_mode == "cms":
            scope = getattr(request.state, "cms_identity", None)
            if not scope:
                raise APIError(401, "cms_session_required", "Authenticate through CMS")
            return {"identityId": scope["principalId"], "identity": scope}
        token = request.cookies.get(COOKIE)
        if token:
            found = db.scalar(select(DevelopmentIdentity).where(
                DevelopmentIdentity.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                DevelopmentIdentity.expires_at > utcnow(),
            ))
            if found:
                return {"identityId": found.id}
        token = secrets.token_urlsafe(32)
        found = DevelopmentIdentity(id=str(uuid4()), token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                    expires_at=utcnow() + timedelta(days=30))
        db.add(found)
        db.commit()
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=30 * 86400,
                            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true", path="/api")
        return {"identityId": found.id}

    @app.get("/api/v1/workspaces", response_model=list[WorkspaceResponse])
    def list_workspaces(request: Request, owner=Depends(identity), db: Session = Depends(db_session)):
        query = select(Workspace).where(Workspace.owner_id == owner.id, Workspace.deleted_at.is_(None))
        if auth_mode == "cms":
            from .cms_identity_models import CMSWorkspaceBinding
            query = query.join(CMSWorkspaceBinding, CMSWorkspaceBinding.workspace_id == Workspace.id).where(
                CMSWorkspaceBinding.task_id == request.state.cms_identity["taskId"])
        return [workspace_response(db, w) for w in db.scalars(query)]

    @app.post("/api/v1/workspaces", response_model=WorkspaceResponse, status_code=201)
    def create_workspace(body: WorkspaceCreate, owner=Depends(identity), db: Session = Depends(db_session)):
        apply_operation(db, owner.id, SyncOperation(operationId=uuid4(), workspaceId=body.id,
                                                   baseRevision=0, document=body.document))
        result = workspace_response(db, owned_workspace(db, str(body.id), owner.id))
        db.commit()
        return result

    @app.get("/api/v1/workspaces/{workspace_id}", response_model=WorkspaceResponse)
    def get_workspace(workspace_id: UUID, owner=Depends(identity), db: Session = Depends(db_session)):
        return workspace_response(db, owned_workspace(db, str(workspace_id), owner.id))

    @app.patch("/api/v1/workspaces/{workspace_id}", response_model=WorkspaceResponse)
    def update_workspace(workspace_id: UUID, body: WorkspacePatch, owner=Depends(identity), db: Session = Depends(db_session)):
        owned_workspace(db, str(workspace_id), owner.id)
        apply_operation(db, owner.id, SyncOperation(operationId=body.operationId, workspaceId=workspace_id,
                                                   baseRevision=body.baseRevision, document=body.document))
        result = workspace_response(db, owned_workspace(db, str(workspace_id), owner.id))
        db.commit()
        return result

    @app.delete("/api/v1/workspaces/{workspace_id}", status_code=204)
    def delete_workspace(workspace_id: UUID, body: DeleteRequest, owner=Depends(identity), db: Session = Depends(db_session)):
        workspace = owned_workspace(db, str(workspace_id), owner.id, lock=True)
        if workspace.revision != body.baseRevision:
            raise APIError(409, "revision_conflict", "Workspace changed", server=workspace_response(db, workspace).model_dump(mode="json"))
        workspace.deleted_at = utcnow()
        workspace.revision += 1
        db.commit()
        return Response(status_code=204)

    @app.get("/api/v1/workspaces/{workspace_id}/files")
    def get_files(workspace_id: UUID, owner=Depends(identity), db: Session = Depends(db_session)):
        return workspace_response(db, owned_workspace(db, str(workspace_id), owner.id)).document.nodes

    @app.get("/api/v1/workspaces/{workspace_id}/settings")
    def get_settings(workspace_id: UUID, owner=Depends(identity), db: Session = Depends(db_session)):
        return workspace_response(db, owned_workspace(db, str(workspace_id), owner.id)).document.settings

    @app.post("/api/v1/sync/batches", response_model=SyncResponse)
    def synchronize(body: SyncBatch, owner=Depends(identity), db: Session = Depends(db_session)):
        if len({op.workspaceId for op in body.operations}) != 1:
            raise APIError(422, "invalid_batch", "A batch must belong to one workspace")
        acknowledgements = [SyncAcknowledgement(operationId=str(op.operationId),
                            revision=apply_operation(db, owner.id, op)) for op in body.operations]
        db.commit()
        return SyncResponse(acknowledgements=acknowledgements)

    @app.get("/api/v1/sync/status/{workspace_id}")
    def sync_status(workspace_id: UUID, owner=Depends(identity), db: Session = Depends(db_session)):
        workspace = owned_workspace(db, str(workspace_id), owner.id)
        return {"workspaceId": workspace.id, "revision": workspace.revision}

    @app.get("/api/v1/workspaces/{workspace_id}/snapshots")
    def snapshots(workspace_id: UUID, fileId: UUID | None = None, owner=Depends(identity), db: Session = Depends(db_session)):
        owned_workspace(db, str(workspace_id), owner.id)
        query = select(RecoverySnapshot).where(RecoverySnapshot.workspace_id == str(workspace_id))
        if fileId:
            query = query.where(RecoverySnapshot.file_id == str(fileId))
        records = db.scalars(query.order_by(RecoverySnapshot.created_at.desc()).limit(200))
        return [{"snapshotId": s.id, "fileId": s.file_id, "name": s.name, "content": s.content,
                 "contentHash": s.content_hash, "revision": s.revision, "reason": s.reason,
                 "createdAt": s.created_at} for s in records]

    from .admin_history import install_admin_history_routes
    install_admin_history_routes(app, db_session)
    from .telemetry import install_routes
    install_routes(app, db_session, identity)
    from .execution_api import install_execution_routes
    install_execution_routes(app, db_session, identity)
    from .debug_api import install_debug_routes
    install_debug_routes(app, db_session, identity)
    return app


app = create_app()
