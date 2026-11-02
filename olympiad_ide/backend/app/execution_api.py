import asyncio
import json
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from .models import utcnow
from .service import owned_workspace
from .execution_models import ExecutionEvent, ExecutionJob, ExecutionResource, ExecutionWorker
from .execution_schema import CapacityView, EventPage, ExecutionSubmit, JobView, ResourceMutation, ResourceView, TERMINAL
from .execution_service import expire_leases, job_view, mutate_resource, owned_job, resource_view, submit, transition


def install_execution_routes(app, db_session, identity):
    async def start_reaper():
        async def maintain():
            def tick():
                with app.state.session_factory() as session:
                    expire_leases(session); session.commit()
            while True:
                await asyncio.sleep(5)
                try: await asyncio.to_thread(tick)
                except Exception:
                    import logging
                    logging.getLogger('olympiad.execution').error('execution_maintenance_retry_required')
        app.state.execution_reaper = asyncio.create_task(maintain())
    async def stop_reaper():
        task = getattr(app.state, 'execution_reaper', None)
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    previous_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with previous_lifespan(application) as state:
            await start_reaper()
            try: yield state
            finally: await stop_reaper()
    app.router.lifespan_context = lifespan
    @app.post('/api/v1/executions', response_model=JobView, status_code=201)
    def create(body: ExecutionSubmit, owner=Depends(identity), db=Depends(db_session)):
        job = submit(db, owner.id, body, require_worker=app.state.auth_mode == "cms"); db.commit()
        return job_view(db, job)

    @app.get('/api/v1/workspaces/{workspace_id}/executions', response_model=list[JobView])
    def history(workspace_id: UUID, owner=Depends(identity), db=Depends(db_session)):
        owned_workspace(db, str(workspace_id), owner.id)
        expire_leases(db); db.commit()
        return [job_view(db, j) for j in db.scalars(select(ExecutionJob).where(ExecutionJob.workspace_id == str(workspace_id), ExecutionJob.owner_id == owner.id).order_by(ExecutionJob.created_at.desc()).limit(30))]

    @app.get('/api/v1/executions/{job_id}', response_model=JobView)
    def get(job_id: UUID, owner=Depends(identity), db=Depends(db_session)):
        owned_job(db, job_id, owner.id)
        expire_leases(db); db.commit()
        return job_view(db, owned_job(db, job_id, owner.id))

    @app.post('/api/v1/executions/{job_id}/cancel', response_model=JobView)
    def cancel(job_id: UUID, owner=Depends(identity), db=Depends(db_session)):
        job = owned_job(db, job_id, owner.id, True)
        if job.status not in TERMINAL:
            job.cancel_requested = True
            if job.status == 'QUEUED': transition(db, job, 'CANCELLED')
        db.commit()
        return job_view(db, job)

    @app.get('/api/v1/executions/{job_id}/events', response_model=EventPage)
    async def events(job_id: UUID, request: Request, after: int = Query(0, ge=0), stream: bool = False, owner=Depends(identity), db=Depends(db_session)):
        owned_job(db, job_id, owner.id)
        if not stream:
            rows = list(db.scalars(select(ExecutionEvent).where(ExecutionEvent.job_id == str(job_id), ExecutionEvent.sequence > after).order_by(ExecutionEvent.sequence).limit(200)))
            return {'events': [row.payload for row in rows], 'nextAfter': rows[-1].sequence if rows else after}
        cursor = max(after, int(request.headers.get('last-event-id', '0')) if request.headers.get('last-event-id', '').isdigit() else 0)
        owner_id = owner.id
        db.rollback()  # Release the dependency's checked-out connection before opening a long stream.
        async def generate():
            nonlocal cursor
            # Fresh short transactions, never keep a checked-out connection for a stream lifetime.
            for _ in range(30):
                if await request.is_disconnected(): return
                with app.state.session_factory() as session:
                    job = owned_job(session, job_id, owner_id)
                    rows = list(session.scalars(select(ExecutionEvent).where(ExecutionEvent.job_id == str(job_id), ExecutionEvent.sequence > cursor).order_by(ExecutionEvent.sequence).limit(200)))
                    done = job.status in TERMINAL
                    values = [row.payload for row in rows]
                for value in values:
                    cursor = value['sequence']
                    yield f'id: {cursor}\ndata: {json.dumps(value)}\n\n'
                if done and len(values) < 200: return
                yield ': heartbeat\n\n'
                await asyncio.sleep(0.5)
        return StreamingResponse(generate(), media_type='text/event-stream', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    @app.get('/api/v1/workspaces/{workspace_id}/execution-resources', response_model=list[ResourceView])
    def resources(workspace_id: UUID, owner=Depends(identity), db=Depends(db_session)):
        owned_workspace(db, str(workspace_id), owner.id)
        return [resource_view(r) for r in db.scalars(select(ExecutionResource).where(ExecutionResource.workspace_id == str(workspace_id)))]

    @app.post('/api/v1/workspaces/{workspace_id}/execution-resources', response_model=ResourceView)
    def change_resource(workspace_id: UUID, body: ResourceMutation, owner=Depends(identity), db=Depends(db_session)):
        result = mutate_resource(db, owner.id, workspace_id, body); db.commit(); return result

    @app.get('/api/v1/execution-capacity', response_model=CapacityView)
    def capacity(owner=Depends(identity), db=Depends(db_session)):
        from datetime import timedelta
        workers = list(db.scalars(select(ExecutionWorker).where(ExecutionWorker.last_seen > utcnow() - timedelta(seconds=15))))
        return {'workers': len(workers), 'capacity': sum(w.capacity for w in workers), 'queuedJobs': db.scalar(select(func.count()).select_from(ExecutionJob).where(ExecutionJob.status == 'QUEUED', ExecutionJob.owner_id == owner.id)),
            'activeJobs': db.scalar(select(func.count()).select_from(ExecutionJob).where(ExecutionJob.status.in_(['PREPARING', 'COMPILING', 'RUNNING']), ExecutionJob.owner_id == owner.id)),
            'failedJobs': db.scalar(select(func.count()).select_from(ExecutionJob).where(ExecutionJob.status.in_(TERMINAL - {'FINISHED', 'CANCELLED'}), ExecutionJob.owner_id == owner.id)),
            'cancellationCount': db.scalar(select(func.count()).select_from(ExecutionJob).where(ExecutionJob.cancel_requested.is_(True), ExecutionJob.owner_id == owner.id))}
