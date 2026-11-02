"""Durable execution control plane. This module never launches participant processes."""
import os
from datetime import timedelta, timezone
from uuid import uuid4
from sqlalchemy import func, select, text
from .models import DevelopmentIdentity, utcnow
from .service import APIError, owned_workspace
from .telemetry import canonical, digest
from .execution_models import ExecutionEvent, ExecutionJob, ExecutionResource, ExecutionResourceReceipt, ExecutionSnapshot, ExecutionWorker
from .execution_schema import JobEvent, JobResult, JobView, TERMINAL

ACTIVE = {'PREPARING', 'COMPILING', 'RUNNING'}
TRANSITIONS = {'QUEUED': {'PREPARING', 'CANCELLED', 'INFRASTRUCTURE_ERROR'}, 'PREPARING': {'COMPILING', 'RUNNING', 'CANCELLED', 'INFRASTRUCTURE_ERROR'},
    'COMPILING': {'RUNNING', 'COMPILATION_ERROR', 'CANCELLED', 'INFRASTRUCTURE_ERROR', 'OUTPUT_LIMIT_EXCEEDED'},
    'RUNNING': TERMINAL}


def setting(name, default): return max(1, int(os.getenv('EXECUTION_' + name, str(default))))


def limits_for(language):
    return {'cpuSeconds': setting('CPU_SECONDS', 2), 'wallSeconds': setting('WALL_SECONDS', 5),
        'memoryKiB': setting('JAVA_MEMORY_MIB', 512) * 1024 if language == 'java17' else setting('MEMORY_MIB', 256) * 1024,
        'outputBytes': min(1_048_576, setting('OUTPUT_BYTES', 1_048_576)), 'compileWallSeconds': setting('COMPILE_SECONDS', 30),
        'compileMemoryKiB': setting('COMPILE_MEMORY_MIB', 1024) * 1024, 'maxProcesses': 64 if language == 'java17' else 1}


def emit(db, job, event_type, **payload):
    event = JobEvent(sequence=job.last_sequence + 1, timestamp=utcnow().isoformat(), eventType=event_type, **payload)
    # Signalled processes have no exit code. Keep required nullable fields in
    # nested case results so both REST event validation and SSE replay work.
    value = event.model_dump(mode='json')
    job.last_sequence += 1
    db.add(ExecutionEvent(id=str(uuid4()), job_id=job.id, sequence=job.last_sequence, payload=value))


def transition(db, job, status):
    if status not in TRANSITIONS.get(job.status, set()): raise APIError(409, 'invalid_transition', f'Illegal execution transition {job.status} -> {status}')
    job.status = status
    if status == 'PREPARING': job.started_at = utcnow()
    if status in TERMINAL: job.completed_at = utcnow(); job.lease_expiration = None
    emit(db, job, 'STATUS', status=status)


def owned_job(db, job_id, owner_id, lock=False):
    query = select(ExecutionJob).where(ExecutionJob.id == str(job_id), ExecutionJob.owner_id == owner_id)
    job = db.scalar(query.with_for_update() if lock else query)
    if not job: raise APIError(404, 'execution_not_found', 'Execution not found')
    return job


def job_view(db, job):
    snapshot = db.get(ExecutionSnapshot, job.snapshot_id)
    iso = lambda value: value.astimezone(timezone.utc).isoformat() if value else None
    return JobView(id=job.id, workspaceId=job.workspace_id, snapshotId=snapshot.id, sourceHash=snapshot.source_hash,
        sourceManifest=[{'id': f['id'], 'path': f['path']} for f in snapshot.files],
        configuration=snapshot.configuration, status=job.status, createdAt=iso(job.created_at),
        startedAt=iso(job.started_at), completedAt=iso(job.completed_at),
        cancelRequested=job.cancel_requested, lastSequence=job.last_sequence, result=job.result, tests=job.tests)


def submit(db, owner_id, body, require_worker=False):
    # Compatible with Phase 2 owner foreign keys; serializes admission and idempotency for this owner.
    db.scalar(select(DevelopmentIdentity).where(DevelopmentIdentity.id == owner_id).with_for_update(key_share=True))
    owned_workspace(db, str(body.workspaceId), owner_id)
    payload = body.model_dump(mode='json')
    request_digest = digest(payload)
    existing = db.get(ExecutionJob, str(body.id))
    if existing:
        if existing.owner_id != owner_id: raise APIError(404, 'execution_not_found', 'Execution not found')
        if existing.request_digest != request_digest: raise APIError(409, 'idempotency_reused', 'Submission ID reused with different input')
        return existing
    if require_worker and not db.scalar(select(ExecutionWorker.id).where(
            ExecutionWorker.last_seen > utcnow() - timedelta(seconds=15), ExecutionWorker.capacity > 0).limit(1)):
        raise APIError(503, 'worker_unavailable', 'Custom Run is unavailable until an approved Linux worker is connected; official CMS Submit remains independent')
    queued = db.scalar(select(func.count()).select_from(ExecutionJob).where(ExecutionJob.owner_id == owner_id, ExecutionJob.status == 'QUEUED'))
    if queued >= setting('MAX_QUEUED_PER_OWNER', 3): raise APIError(429, 'queue_full', 'Your execution queue is full')
    total = db.scalar(select(func.count()).select_from(ExecutionJob).where(ExecutionJob.owner_id == owner_id, ExecutionJob.created_at > utcnow() - timedelta(hours=1)))
    if total >= setting('MAX_SUBMISSIONS_PER_HOUR', 100): raise APIError(429, 'submission_limit', 'Hourly submission limit reached')
    files = sorted(payload['files'], key=lambda f: f['id'])
    if digest({'files': files, 'configuration': payload['configuration']}) != body.sourceHash:
        raise APIError(422, 'source_hash_mismatch', 'Source snapshot hash mismatch')
    snapshot = ExecutionSnapshot(id=str(uuid4()), workspace_id=str(body.workspaceId), source_hash=body.sourceHash, files=files, configuration=payload['configuration'])
    db.add(snapshot); db.flush()
    job = ExecutionJob(id=str(body.id), owner_id=owner_id, workspace_id=str(body.workspaceId), snapshot_id=snapshot.id,
        request_digest=request_digest, tests=payload['tests'], limits=limits_for(body.configuration.language), status='QUEUED', last_sequence=0, output_bytes=0, cancel_requested=False)
    db.add(job); db.flush(); emit(db, job, 'STATUS', status='QUEUED')
    return job


def resource_view(resource):
    return {'workspaceId': resource.workspace_id, 'id': resource.id, 'revision': resource.revision, 'value': resource.value, 'deleted': resource.deleted}


def mutate_resource(db, owner_id, workspace_id, body):
    db.scalar(select(DevelopmentIdentity).where(DevelopmentIdentity.id == owner_id).with_for_update(key_share=True))
    owned_workspace(db, str(workspace_id), owner_id)
    fingerprint = digest({'workspaceId': str(workspace_id), **body.model_dump(mode='json')})
    receipt = db.get(ExecutionResourceReceipt, str(body.operationId))
    if receipt:
        if receipt.owner_id != owner_id: raise APIError(404, 'not_found', 'Operation not found')
        if receipt.digest != fingerprint: raise APIError(409, 'operation_reused', 'Resource operation ID reused')
        return receipt.response
    resource = db.get(ExecutionResource, str(body.value.id))
    if resource and resource.workspace_id != str(workspace_id): raise APIError(404, 'not_found', 'Resource not found')
    if body.baseRevision != (resource.revision if resource else 0):
        raise APIError(409, 'resource_conflict', 'Execution resource changed; both versions retained', server=resource_view(resource) if resource else None)
    if not resource:
        count = db.scalar(select(func.count()).select_from(ExecutionResource).where(ExecutionResource.workspace_id == str(workspace_id)))
        if count >= 200: raise APIError(413, 'resource_limit', 'Workspace resource limit reached')
        resource = ExecutionResource(id=str(body.value.id), workspace_id=str(workspace_id), kind=body.value.kind, revision=0)
        db.add(resource)
    if resource.kind != body.value.kind: raise APIError(422, 'kind_changed', 'Resource kind cannot change')
    resource.revision += 1; resource.value = body.value.model_dump(mode='json'); resource.deleted = body.deleted
    response = resource_view(resource)
    db.add(ExecutionResourceReceipt(id=str(body.operationId), owner_id=owner_id, digest=fingerprint, response=response))
    return response


def expire_leases(db):
    now = utcnow()
    stale = db.scalars(select(ExecutionJob).where(ExecutionJob.status.in_(ACTIVE), ExecutionJob.lease_expiration < now).with_for_update(skip_locked=True))
    for job in stale:
        status = 'CANCELLED' if job.cancel_requested else 'INFRASTRUCTURE_ERROR'
        transition(db, job, status)
        job.result = JobResult(status=status, compilationOutput='', toolchainVersion='unavailable', cases=[], error='Worker lease expired; execution outcome is unresolved. Submit a new run to retry.').model_dump(mode='json')
        job.lease_token = None
        emit(db, job, 'RESULT', status=status)
    for job in db.scalars(select(ExecutionJob).where(ExecutionJob.status == 'QUEUED', ExecutionJob.created_at < now - timedelta(seconds=setting('QUEUE_TIMEOUT_SECONDS', 600))).with_for_update(skip_locked=True)):
        transition(db, job, 'INFRASTRUCTURE_ERROR')
        job.result = JobResult(status='INFRASTRUCTURE_ERROR', compilationOutput='', toolchainVersion='unavailable', cases=[], error='Queue deadline exceeded; no worker became available').model_dump(mode='json')
        emit(db, job, 'RESULT', status=job.status)


def claim(db, worker_id, capacity):
    # Short global scheduler lock prevents simultaneous owner/capacity decisions, not execution concurrency.
    db.execute(text('SELECT pg_advisory_xact_lock(487391024)'))
    expire_leases(db)
    busy = db.scalar(select(func.count()).select_from(ExecutionJob).where(ExecutionJob.worker_id == worker_id, ExecutionJob.status.in_(ACTIVE)))
    if busy >= capacity: return None
    active_owners = set(db.scalars(select(ExecutionJob.owner_id).where(ExecutionJob.status.in_(ACTIVE))))
    query = select(ExecutionJob).where(ExecutionJob.status == 'QUEUED')
    if active_owners: query = query.where(ExecutionJob.owner_id.not_in(active_owners))
    job = db.scalar(query.order_by(ExecutionJob.created_at, ExecutionJob.id).with_for_update(skip_locked=True).limit(1))
    if not job: return None
    job.worker_id = worker_id; job.lease_token = str(uuid4()); job.lease_expiration = utcnow() + timedelta(seconds=15)
    transition(db, job, 'PREPARING')
    return job


def fenced_job(db, job_id, token):
    job = db.scalar(select(ExecutionJob).where(ExecutionJob.id == job_id).with_for_update())
    if not job or job.lease_token != token or job.status in TERMINAL or not job.lease_expiration or job.lease_expiration <= utcnow():
        raise APIError(409, 'lease_lost', 'Worker lease lost')
    return job


def finish(db, job, result):
    parsed = JobResult.model_validate(result)
    if parsed.status not in TERMINAL: raise APIError(422, 'invalid_result', 'Worker result is not terminal')
    test_ids = {t['id'] for t in job.tests}
    if len({str(c.testId) for c in parsed.cases}) != len(parsed.cases) or any(str(c.testId) not in test_ids for c in parsed.cases): raise APIError(422, 'invalid_result', 'Unknown/duplicate test result')
    if parsed.status == 'FINISHED' and (len(parsed.cases) != len(job.tests) or any(c.status != 'FINISHED' for c in parsed.cases)): raise APIError(422, 'invalid_result', 'Successful result must include every completed test')
    by_id = {t['id']: t for t in job.tests}
    for case in parsed.cases:
        test = by_id[str(case.testId)]
        case.expectedStdout = test['expectedStdout']; case.name = test['name']
        case.verdict = compare(case.status, case.stdout, case.expectedStdout)
    if job.cancel_requested: parsed.status = 'CANCELLED'
    transition(db, job, parsed.status)
    job.result = parsed.model_dump(mode='json'); job.lease_token = None
    emit(db, job, 'RESULT', status=parsed.status)


def compare(status, actual, expected):
    if status != 'FINISHED': return 'Not Executed'
    if expected is None: return 'Not Compared'
    return 'Accepted' if actual.replace('\r\n', '\n') == expected.replace('\r\n', '\n') else 'Wrong Answer'
