"""Owner-scoped telemetry ingestion and UTF-16 replay, independent of workspace synchronization."""
import copy
import hashlib
import json
import os
import re
from datetime import timedelta
from uuid import UUID
from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from .models import DevelopmentIdentity, utcnow
from .service import APIError, owned_workspace
from .telemetry_models import TelemetryBatch, TelemetryCheckpoint, TelemetryEvent, TelemetrySession
from .telemetry_schema import Batch, Chunk, Close, DOCUMENT_TYPES, SessionCreate


def limit(name, default):
    return max(1, int(os.getenv('TELEMETRY_' + name, default)))


def canonical(value):
    def numbers(item):
        if isinstance(item, float) and item.is_integer(): return int(item)
        if isinstance(item, dict): return {k: numbers(v) for k, v in item.items()}
        if isinstance(item, list): return [numbers(v) for v in item]
        return item
    return json.dumps(numbers(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class TelemetryResponse(JSONResponse):
    def render(self, content):
        # JSON can preserve lone UTF-16 code units; UTF-8 encoding the raw surrogate cannot.
        return json.dumps(content, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')


class Fault(Exception):
    def __init__(self, state, message):
        self.state, self.message = state, message


def invalid(message): raise Fault('Invalid Event', message)


def validate_tree(nodes):
    for key, node in nodes.items():
        if key != node['id'] or '/' in node['name'] or '\\' in node['name'] or node['name'] in ('.', '..'):
            invalid('Invalid node identity/name')
        if node['type'] == 'file' and (not isinstance(node['content'], str) or node['revision'] < 1): invalid('Invalid file')
        if node['type'] == 'folder' and (node['content'] is not None or node['revision'] != 0): invalid('Invalid folder')
        seen = {key}
        parent = node['parentId']
        while parent:
            if parent in seen or nodes.get(parent, {}).get('type') != 'folder': invalid('Invalid tree/cycle')
            seen.add(parent)
            parent = nodes[parent]['parentId']


def utf16(text): return text.encode('utf-16-le', errors='surrogatepass')


def position_offset(text, line, column):
    lines = re.split('(\r\n|\r|\n)', text)
    actual = lines[::2]
    if line > len(actual) or column - 1 > len(utf16(actual[line - 1])) // 2: invalid('Invalid source range')
    return len(utf16(''.join(lines[:2 * (line - 1)]))) // 2 + column - 1


def apply_event(previous, event):
    nodes = dict(previous)
    kind, payload, file_id = event['eventType'], event['payload'], event['fileId']
    node = nodes.get(file_id)
    if kind in DOCUMENT_TYPES:
        if not node or node['type'] != 'file': invalid('Unknown document identity')
        if payload['beforeRevision'] != node['revision'] or payload['afterRevision'] != node['revision'] + 1:
            raise Fault('Revision Mismatch', 'Document revision discontinuity')
        before = node['content']
        data, boundary = utf16(before), len(utf16(before)) // 2
        for _, change in sorted(enumerate(payload['changes']), key=lambda item: (-item[1]['offset'], item[0])):
            offset, length = change['offset'], change['deletedLength']
            if offset < 0 or length < 0 or offset + length > boundary: invalid('Invalid/overlapping UTF-16 offsets')
            r = change['range']
            if position_offset(before, r['startLineNumber'], r['startColumn']) != offset or position_offset(before, r['endLineNumber'], r['endColumn']) != offset + length: invalid('Range/offset mismatch')
            data = data[:2 * offset] + utf16(change['insertedText']) + data[2 * (offset + length):]
            boundary = offset
        text = data.decode('utf-16-le', errors='surrogatepass')
        text = re.sub(r'\r\n|\r|\n', lambda _: payload['eol'], text)
        if len(utf16(text)) // 2 > 2_000_000: invalid('Resulting document exceeds file limit')
        nodes[file_id] = {**node, 'content': text, 'revision': payload['afterRevision']}
    elif kind == 'WORKSPACE_RECONCILED':
        nodes = copy.deepcopy(payload['nodes'])
    elif kind in ('FILE_CREATED', 'FOLDER_CREATED'):
        if node or file_id != payload['node']['id'] or payload['node']['type'] != ('file' if kind == 'FILE_CREATED' else 'folder'): invalid('Invalid created identity/type')
        nodes[file_id] = payload['node']
    elif kind.startswith(('FILE_', 'FOLDER_')) and kind.endswith(('_RENAMED', '_MOVED', '_DELETED')):
        if not node or node['type'] != ('file' if kind.startswith('FILE_') else 'folder'): invalid('Unknown structural identity/type')
        if kind.endswith('_RENAMED'): nodes[file_id] = {**node, 'name': payload['name']}
        elif kind.endswith('_MOVED'): nodes[file_id] = {**node, 'parentId': payload['parentId']}
        else:
            if file_id not in payload['deletedIds'] or len(set(payload['deletedIds'])) != len(payload['deletedIds']): invalid('Invalid deleted subtree')
            for key in payload['deletedIds']:
                if key not in nodes: invalid('Unknown deleted identity')
                # Every removed identity must actually descend from this root.
                p = key
                while p and p != file_id: p = previous[p]['parentId']
                if not p: invalid('Unrelated identity in deleted subtree')
                del nodes[key]
    elif file_id and not node: invalid('Unknown event identity')
    elif kind in ('KEY_DOWN', 'KEY_UP', 'PASTE', 'COMPOSITION_START', 'COMPOSITION_END') and not node: invalid('Editor input requires a file')
    if len(nodes) > 5000: invalid('Workspace node limit exceeded')
    validate_tree(nodes)
    return nodes


def owned_session(db, session_id, owner_id, lock=False):
    query = select(TelemetrySession).where(TelemetrySession.id == str(session_id), TelemetrySession.owner_id == owner_id)
    found = db.scalar(query.with_for_update() if lock else query)
    if not found: raise APIError(404, 'session_not_found', 'Telemetry session not found')
    return found


def lock_owner(db, owner_id):
    # All telemetry writers use owner -> session lock order, making storage quotas atomic across tabs.
    # NO KEY UPDATE still serializes telemetry writers but permits Phase 2's FK KEY SHARE locks.
    # FOR UPDATE here would invert Phase 2's workspace -> owner-FK lock order and cause deadlocks.
    db.scalar(select(DevelopmentIdentity).where(DevelopmentIdentity.id == owner_id).with_for_update(key_share=True))


def replay_at(db, session, through):
    initial = db.scalar(select(TelemetryCheckpoint).where(TelemetryCheckpoint.session_id == session.id, TelemetryCheckpoint.sequence == 0).order_by(TelemetryCheckpoint.created_at).limit(1))
    nodes, sequence = copy.deepcopy(initial.document_state), 0
    for event in db.scalars(select(TelemetryEvent).where(TelemetryEvent.session_id == session.id, TelemetryEvent.sequence <= through).order_by(TelemetryEvent.sequence)):
        sequence += 1
        if event.sequence != sequence: raise Fault('Missing Events', f'Expected {sequence}')
        nodes = apply_event(nodes, event.envelope)
    if sequence != through: raise Fault('Missing Events', f'History ends at {sequence}')
    return nodes


def acknowledgement(batch):
    return {'batchId': batch.id, 'sessionId': batch.session_id, 'lastSequence': batch.last_sequence, 'digest': batch.payload_digest}


def ingest(db, owner, raw):
    body = Batch.model_validate(raw)
    payload = {key: value for key, value in raw.items() if key != 'digest'}
    if len(canonical(payload)) > limit('MAX_BATCH_BYTES', 8_000_000): raise APIError(413, 'batch_too_large', 'Invalid Event: batch exceeds assembly limit')
    if digest(payload) != body.digest: raise APIError(422, 'digest_mismatch', 'Invalid Event: batch digest mismatch')
    lock_owner(db, owner.id)
    session = owned_session(db, body.sessionId, owner.id, True)
    batch = db.get(TelemetryBatch, str(body.id))
    if batch and (batch.session_id != session.id or batch.payload_digest != body.digest): raise APIError(409, 'batch_reused', 'Invalid Event: batch identity reused')
    if batch and batch.acknowledgement_state == 'committed': return acknowledgement(batch)
    if session.storage_bytes + len(canonical(payload)) > limit('MAX_SESSION_BYTES', 100_000_000): raise APIError(413, 'storage_limit', 'Session storage limit exceeded; recording must remain local')
    owner_bytes = db.scalar(select(func.coalesce(func.sum(TelemetrySession.storage_bytes), 0)).where(TelemetrySession.owner_id == owner.id))
    if owner_bytes + len(canonical(payload)) > limit('MAX_OWNER_BYTES', 1_000_000_000): raise APIError(413, 'owner_storage_limit', 'Telemetry owner storage limit reached; data remains local')
    try:
        with db.begin_nested():
            state, sequence, clock = session.replay_state, session.last_contiguous_sequence, session.last_monotonic_offset
            checkpoint_sequences = {cp.sequence for cp in body.checkpoints}
            states = {sequence: state}
            seen = set()
            for raw_event, event in zip(raw['events'], body.events):
                if str(event.sessionId) != session.id or str(event.workspaceId) != session.workspace_id: invalid('Event session/workspace mismatch')
                if str(event.eventId) in seen: invalid('Duplicate event in batch')
                seen.add(str(event.eventId))
                if len(canonical(raw_event)) > limit('MAX_EVENT_BYTES', 4_000_000): invalid('Event exceeds size limit')
                duplicate = db.get(TelemetryEvent, str(event.eventId))
                if duplicate:
                    if duplicate.session_id != session.id or canonical(duplicate.envelope) != canonical(raw_event): invalid('Event ID reused')
                    continue
                if event.sequence != sequence + 1: raise Fault('Missing Events', f'Expected sequence {sequence + 1}, received {event.sequence}')
                if event.sequence > limit('MAX_SESSION_EVENTS', 1_000_000): invalid('Session event limit exceeded')
                if event.monotonicOffsetMs < clock: invalid('Monotonic clock regressed; reload requires a new session')
                if event.eventType in DOCUMENT_TYPES and event.payload.inputEventId:
                    key_event = db.get(TelemetryEvent, str(event.payload.inputEventId))
                    if not key_event or key_event.session_id != session.id or key_event.file_id != raw_event['fileId'] or key_event.event_type != 'KEY_DOWN' or key_event.sequence >= event.sequence:
                        invalid('Invalid keyboard correlation')
                if event.eventType == 'PASTE' and event.payload.transactionId:
                    transaction = db.scalar(select(TelemetryEvent).where(TelemetryEvent.session_id == session.id,
                        TelemetryEvent.file_id == raw_event['fileId'], TelemetryEvent.event_type.in_(DOCUMENT_TYPES),
                        TelemetryEvent.payload['transactionId'].as_string() == str(event.payload.transactionId)).limit(1))
                    if not transaction or transaction.sequence >= event.sequence: invalid('Invalid paste correlation')
                state = apply_event(state, raw_event)
                sequence, clock = event.sequence, event.monotonicOffsetMs
                if sequence in checkpoint_sequences: states[sequence] = state
                db.add(TelemetryEvent(event_id=str(event.eventId), session_id=session.id, sequence=sequence,
                    file_id=str(event.fileId) if event.fileId else None, event_type=event.eventType, schema_version=1,
                    client_timestamp=event.clientTimestamp, monotonic_offset=clock, payload=raw_event['payload'], envelope=raw_event))
                if event.eventType == 'SESSION_ENDED':
                    session.status = 'interrupted' if event.payload.interrupted else 'completed'
                    session.completed_at = utcnow()
                    if event.payload.interrupted: session.integrity = 'Recording Interrupted'
            db.flush()
            for raw_checkpoint, checkpoint in zip(raw['checkpoints'], body.checkpoints):
                if str(checkpoint.sessionId) != session.id or checkpoint.sequence > sequence: invalid('Checkpoint boundary outside committed prefix')
                existing = db.get(TelemetryCheckpoint, str(checkpoint.id))
                if existing:
                    if canonical(existing.envelope) != canonical(raw_checkpoint): invalid('Checkpoint ID reused')
                    continue
                expected = states.get(checkpoint.sequence)
                if expected is None: expected = replay_at(db, session, checkpoint.sequence)
                if digest(raw_checkpoint['nodes']) != checkpoint.stateHash or digest(expected) != checkpoint.stateHash: raise Fault('Checkpoint Mismatch', f'Checkpoint mismatch at {checkpoint.sequence}')
                db.add(TelemetryCheckpoint(id=str(checkpoint.id), session_id=session.id, sequence=checkpoint.sequence,
                    workspace_revision=checkpoint.workspaceRevision, document_state=raw_checkpoint['nodes'], state_hash=checkpoint.stateHash, envelope=raw_checkpoint))
            session.replay_state, session.last_contiguous_sequence, session.last_monotonic_offset = state, sequence, clock
            session.storage_bytes += len(canonical(payload))
            if session.integrity != 'Recording Interrupted': session.integrity = 'Complete'
            if not batch:
                batch = TelemetryBatch(id=str(body.id), session_id=session.id, payload_digest=body.digest)
                db.add(batch)
            batch.first_sequence = body.events[0].sequence if body.events else sequence
            batch.last_sequence, batch.acknowledgement_state, batch.chunks, batch.staged_bytes = sequence, 'committed', {}, 0
        db.commit()  # The acknowledgement is not returned before this commit.
        return acknowledgement(batch)
    except Fault as fault:
        was_missing = session.integrity == 'Missing Events'
        session.integrity = fault.state
        if fault.state == 'Missing Events' and not was_missing: session.detected_gaps += 1
        db.commit()  # Only diagnostic state survives the rolled-back event/savepoint transaction.
        raise APIError(409, 'telemetry_integrity', fault.state + ': ' + fault.message)


def install_routes(app, db_session, identity):
    @app.get('/api/v1/telemetry/policy')
    def policy():
        return {'retentionDays': limit('RETENTION_DAYS', 30), 'developmentDefault': 'TELEMETRY_RETENTION_DAYS' not in os.environ,
                'maxBatchBytes': limit('MAX_BATCH_BYTES', 8_000_000), 'maxEventBytes': limit('MAX_EVENT_BYTES', 4_000_000)}

    @app.post('/api/v1/telemetry/sessions', status_code=201)
    async def create_session(body: SessionCreate, request: Request, owner=Depends(identity), db: Session = Depends(db_session)):
        lock_owner(db, owner.id)
        owned_workspace(db, str(body.workspaceId), owner.id)
        raw = await request.json()
        size = len(canonical(raw))
        if size > limit('MAX_BATCH_BYTES', 8_000_000): raise APIError(413, 'initial_too_large', 'Initial checkpoint exceeds limit')
        existing = db.get(TelemetrySession, str(body.id))
        if existing:
            existing = owned_session(db, body.id, owner.id)
            if existing.workspace_id != str(body.workspaceId):
                raise APIError(409, 'session_reused', 'Telemetry session belongs to another workspace')
            initial = db.get(TelemetryCheckpoint, str(body.initial.id))
            if not initial or canonical(initial.envelope) != canonical(raw['initial']): raise APIError(409, 'session_reused', 'Session identity reused')
            return {'id': existing.id, 'lastSequence': existing.last_contiguous_sequence}
        count, size_total = db.execute(select(func.count(), func.coalesce(func.sum(TelemetrySession.storage_bytes), 0)).where(TelemetrySession.owner_id == owner.id)).one()
        if count >= limit('MAX_OWNER_SESSIONS', 200) or size_total + size > limit('MAX_OWNER_BYTES', 1_000_000_000): raise APIError(413, 'owner_storage_limit', 'Telemetry storage limit reached')
        if body.initial.sessionId != body.id or body.initial.sequence != 0: raise APIError(422, 'invalid_initial', 'Initial checkpoint boundary must be zero')
        try: validate_tree(raw['initial']['nodes'])
        except Fault as fault: raise APIError(422, 'invalid_initial', fault.state + ': ' + fault.message)
        if digest(raw['initial']['nodes']) != body.initial.stateHash: raise APIError(422, 'checkpoint_mismatch', 'Checkpoint Mismatch: initial hash')
        db.add(TelemetrySession(id=str(body.id), workspace_id=str(body.workspaceId), owner_id=owner.id, started_at=body.startedAt,
            replay_state=raw['initial']['nodes'], storage_bytes=size, expires_at=utcnow() + timedelta(days=limit('RETENTION_DAYS', 30))))
        db.flush()
        db.add(TelemetryCheckpoint(id=str(body.initial.id), session_id=str(body.id), sequence=0, workspace_revision=body.initial.workspaceRevision,
            document_state=raw['initial']['nodes'], state_hash=body.initial.stateHash, envelope=raw['initial']))
        db.commit()
        return {'id': str(body.id), 'lastSequence': 0}

    @app.post('/api/v1/telemetry/batches')
    async def batch(body: Batch, request: Request, owner=Depends(identity), db: Session = Depends(db_session)):
        return ingest(db, owner, await request.json())

    @app.post('/api/v1/telemetry/batches/{batch_id}/chunks')
    def chunk(batch_id: UUID, body: Chunk, owner=Depends(identity), db: Session = Depends(db_session)):
        lock_owner(db, owner.id)
        session = owned_session(db, body.sessionId, owner.id, True)
        if body.index >= body.total: raise APIError(422, 'invalid_chunk', 'Invalid chunk index')
        staged = db.get(TelemetryBatch, str(batch_id))
        if staged and (staged.session_id != session.id or staged.payload_digest != body.digest): raise APIError(409, 'batch_reused', 'Batch identity reused')
        if staged and staged.acknowledgement_state == 'committed': return {'acknowledgement': acknowledgement(staged)}
        if not staged:
            staging_count = db.scalar(select(func.count()).select_from(TelemetryBatch).where(TelemetryBatch.session_id == session.id, TelemetryBatch.acknowledgement_state == 'staging'))
            if staging_count >= 2: raise APIError(413, 'staging_limit', 'Too many staged batches')
            staged = TelemetryBatch(id=str(batch_id), session_id=session.id, payload_digest=body.digest, chunk_count=body.total, chunks={}, staged_bytes=0)
            db.add(staged)
        if staged.chunk_count != body.total: raise APIError(409, 'chunk_reused', 'Chunk count changed')
        chunks = dict(staged.chunks)
        previous = chunks.get(str(body.index))
        if previous is not None and previous != body.data: raise APIError(409, 'chunk_reused', 'Chunk content changed')
        size = staged.staged_bytes + (len(body.data) if previous is None else 0)
        if size > limit('MAX_BATCH_BYTES', 8_000_000) or size + session.storage_bytes > limit('MAX_SESSION_BYTES', 100_000_000): raise APIError(413, 'staging_limit', 'Staged bytes exceed storage limit')
        chunks[str(body.index)] = body.data
        staged.chunks, staged.staged_bytes = chunks, size
        if len(chunks) == body.total:
            try: raw = json.loads(''.join(chunks[str(i)] for i in range(body.total)))
            except (ValueError, KeyError): raise APIError(422, 'invalid_chunk', 'Invalid assembled JSON')
            if raw.get('id') != str(batch_id) or raw.get('sessionId') != session.id: raise APIError(422, 'invalid_chunk', 'Assembled identity mismatch')
            raw['digest'] = body.digest
            try: result = ingest(db, owner, raw)
            except ValidationError as error: raise APIError(422, 'invalid_event', 'Invalid Event: ' + str(error))
            return {'acknowledgement': result}
        db.commit()
        return {'acknowledgement': None}

    @app.post('/api/v1/telemetry/sessions/{session_id}/close')
    def close(session_id: UUID, body: Close, owner=Depends(identity), db: Session = Depends(db_session)):
        session = owned_session(db, session_id, owner.id, True)
        if body.lastSequence != session.last_contiguous_sequence: raise APIError(409, 'missing_events', 'Missing Events: cannot close ahead of committed prefix')
        if body.integrity != 'Complete': session.integrity = body.integrity
        if body.completedAt: session.completed_at = utcnow()
        session.status = 'interrupted' if session.integrity != 'Complete' else 'completed'
        db.commit()
        return {'status': session.status}

    @app.get('/api/v1/telemetry/sessions/{session_id}/status')
    def status(session_id: UUID, owner=Depends(identity), db: Session = Depends(db_session)):
        session = owned_session(db, session_id, owner.id)
        checkpoint = db.scalar(select(func.max(TelemetryCheckpoint.sequence)).where(TelemetryCheckpoint.session_id == session.id))
        return {'sessionId': session.id, 'lastSequence': session.last_contiguous_sequence, 'integrity': session.integrity,
                'gaps': session.detected_gaps, 'lastCheckpoint': checkpoint, 'status': session.status, 'expiresAt': session.expires_at}

    @app.get('/api/v1/telemetry/sessions/{session_id}/events', response_class=TelemetryResponse)
    def events(session_id: UUID, after: int = Query(0, ge=0), pageSize: int = Query(100, ge=1, le=500), owner=Depends(identity), db: Session = Depends(db_session)):
        session = owned_session(db, session_id, owner.id)
        rows = list(db.scalars(select(TelemetryEvent).where(TelemetryEvent.session_id == session.id, TelemetryEvent.sequence > after).order_by(TelemetryEvent.sequence).limit(pageSize + 1)))
        return {'events': [{**row.envelope, 'serverTimestamp': row.server_timestamp} for row in rows[:pageSize]], 'nextAfter': rows[pageSize - 1].sequence if len(rows) > pageSize else None}

    @app.get('/api/v1/telemetry/sessions/{session_id}/checkpoints', response_class=TelemetryResponse)
    def checkpoints(session_id: UUID, after: str | None = None, pageSize: int = Query(20, ge=1, le=100), owner=Depends(identity), db: Session = Depends(db_session)):
        session = owned_session(db, session_id, owner.id)
        query = select(TelemetryCheckpoint).where(TelemetryCheckpoint.session_id == session.id)
        if after:
            cursor = db.get(TelemetryCheckpoint, after)
            if not cursor or cursor.session_id != session.id: raise APIError(422, 'invalid_cursor', 'Invalid checkpoint cursor')
            query = query.where((TelemetryCheckpoint.sequence > cursor.sequence) | ((TelemetryCheckpoint.sequence == cursor.sequence) & (TelemetryCheckpoint.id > cursor.id)))
        rows = list(db.scalars(query.order_by(TelemetryCheckpoint.sequence, TelemetryCheckpoint.id).limit(pageSize + 1)))
        return {'checkpoints': [{**row.envelope, 'serverTimestamp': row.created_at} for row in rows[:pageSize]], 'nextAfter': rows[pageSize - 1].id if len(rows) > pageSize else None}


def delete_expired(db, now=None):
    """Explicit maintenance entry point; server FK cascades delete events/checkpoints/staging/receipts."""
    result = db.execute(delete(TelemetrySession).where(TelemetrySession.expires_at <= (now or utcnow())))
    db.commit()
    return result.rowcount
