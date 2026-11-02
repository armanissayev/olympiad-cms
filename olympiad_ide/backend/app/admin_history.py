"""Read-only, CMS administrator-authorized access to uploaded recording prefixes."""
import copy
import hashlib
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, Query, Request
from sqlalchemy import delete, select, func, or_

from .cms_identity import AssertionError, principal_id
from .cms_identity_models import CMSAssertionNonce, CMSPrincipal, CMSWorkspaceBinding
from .service import APIError
from .models import utcnow
from .telemetry import Fault, TelemetryResponse, apply_event, digest, validate_tree
from .telemetry_models import TelemetryCheckpoint, TelemetryEvent, TelemetrySession
from .telemetry_schema import DOCUMENT_TYPES

UUID_PATH = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ADMIN_PREFIX = '/api/v1/admin/telemetry/'


def validate_admin_assertion(token, settings, method, path, query, body):
    """Separate audience/scope; participant assertions cannot grant administrator access."""
    required = ['iss', 'aud', 'sub', 'targetUser', 'contest', 'participation', 'task', 'principal',
                'scope', 'iat', 'nbf', 'exp', 'jti', 'method', 'path', 'query_sha256', 'body_sha256']
    try:
        if method != 'GET' or body or not (path == ADMIN_PREFIX + 'sessions' or
                re.fullmatch(ADMIN_PREFIX + 'sessions/' + UUID_PATH + '/replay', path)):
            raise ValueError('Read-only route required')
        claims = jwt.decode(token, settings.key, algorithms=['HS256'], audience='olympiad-ide-admin-history',
                            issuer=settings.installation, options={'require': required}, leeway=2)
        if claims['scope'] != 'admin-history': raise ValueError('Invalid scope')
        for name in ('iat', 'nbf', 'exp'):
            if type(claims[name]) is not int: raise ValueError('Invalid time')
        if not 0 < claims['exp'] - claims['iat'] <= 30 or claims['nbf'] != claims['iat']:
            raise ValueError('Invalid lifetime')
        for name in ('sub', 'targetUser', 'contest', 'participation', 'task'):
            value = claims[name]
            if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 0 < int(value) or len(value) > 128:
                raise ValueError('Invalid CMS identity')
        if str(UUID(claims['jti'])) != claims['jti']: raise ValueError('Invalid nonce')
        expected = principal_id(settings.installation, claims['targetUser'], claims['contest'], claims['participation'])
        if claims['principal'] != expected: raise ValueError('Invalid participant mapping')
        if claims['method'] != method or claims['path'] != path: raise ValueError('Wrong route')
        if claims['query_sha256'] != hashlib.sha256(query).hexdigest() or claims['body_sha256'] != hashlib.sha256(body).hexdigest():
            raise ValueError('Wrong request')
        return claims
    except (jwt.PyJWTError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise AssertionError('Invalid administrator history assertion') from error


def consume_admin_assertion(factory, settings, claims):
    # The existing one-use nonce store is shared, but no admin is created as a participant.
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.execute(delete(CMSAssertionNonce).where(CMSAssertionNonce.expires_at < now - timedelta(seconds=60)))
        db.add(CMSAssertionNonce(id=claims['jti'], expires_at=datetime.fromtimestamp(claims['exp'], timezone.utc)))
        try:
            db.commit()
        except Exception as error:
            db.rollback()
            from sqlalchemy.exc import IntegrityError
            if isinstance(error, IntegrityError): raise AssertionError('Administrator assertion consumed') from error
            raise
    return {'administratorId': claims['sub'], 'installationId': settings.installation,
            'principalId': claims['principal'], 'userId': claims['targetUser'],
            'contestId': claims['contest'], 'participationId': claims['participation'], 'taskId': claims['task']}


def administrator(request):
    value = getattr(request.state, 'cms_admin_history', None)
    if request.app.state.auth_mode != 'cms' or not value:
        raise APIError(403, 'administrator_required', 'CMS administrator access required')
    return value


def scoped_sessions(db, scope):
    return select(TelemetrySession).join(CMSWorkspaceBinding, CMSWorkspaceBinding.workspace_id == TelemetrySession.workspace_id).join(
        CMSPrincipal, CMSPrincipal.id == CMSWorkspaceBinding.principal_id).where(
        TelemetrySession.owner_id == scope['principalId'], TelemetrySession.expires_at > utcnow(), CMSWorkspaceBinding.principal_id == scope['principalId'],
        CMSWorkspaceBinding.task_id == scope['taskId'], CMSPrincipal.installation_id == scope['installationId'],
        CMSPrincipal.user_id == scope['userId'], CMSPrincipal.contest_id == scope['contestId'],
        CMSPrincipal.participation_id == scope['participationId'])


def session_info(row):
    return {'id': row.id, 'workspaceId': row.workspace_id, 'startedAt': row.started_at,
            'completedAt': row.completed_at, 'lastSequence': row.last_contiguous_sequence,
            'lastOffsetMs': row.last_monotonic_offset, 'integrity': row.integrity,
            'gaps': row.detected_gaps, 'status': row.status, 'expiresAt': row.expires_at}


def replay_frame(db, session, through):
    """Start at a verified retained checkpoint and never invent a missing event."""
    requested = min(through, session.last_contiguous_sequence)
    notices = []
    checkpoint = None
    candidates = db.scalars(select(TelemetryCheckpoint).where(TelemetryCheckpoint.session_id == session.id,
        TelemetryCheckpoint.sequence <= requested).order_by(TelemetryCheckpoint.sequence.desc(), TelemetryCheckpoint.id).limit(100))
    for candidate in candidates:
        try:
            validate_tree(candidate.document_state)
            if digest(candidate.document_state) != candidate.state_hash or candidate.envelope.get('nodes') != candidate.document_state:
                raise ValueError('Checkpoint hash/content mismatch')
            checkpoint = candidate
            break
        except (Fault, ValueError, TypeError, KeyError):
            notices.append('Rejected inconsistent checkpoint at event ' + str(candidate.sequence))
    if checkpoint is None:
        return {'available': False, 'nodes': {}, 'sequence': 0, 'requestedSequence': requested,
                'checkpointSequence': None, 'event': None, 'activeFileId': None,
                'notices': notices + ['No verified uploaded checkpoint is available.']}
    nodes, sequence, event = copy.deepcopy(checkpoint.document_state), checkpoint.sequence, None
    prefix_count = db.scalar(select(func.count()).select_from(TelemetryEvent).where(
        TelemetryEvent.session_id == session.id, TelemetryEvent.sequence <= checkpoint.sequence))
    earlier_gap = prefix_count != checkpoint.sequence
    if earlier_gap: notices.append('Earlier events are missing; this independent verified checkpoint does not reconstruct the gap.')
    active_unknown = earlier_gap or bool(session.detected_gaps) or session.integrity != 'Complete'
    active = None if active_unknown else db.scalar(select(TelemetryEvent).where(TelemetryEvent.session_id == session.id,
        TelemetryEvent.sequence <= checkpoint.sequence, TelemetryEvent.event_type.in_(['ACTIVE_FILE_CHANGED', 'TAB_SWITCHED'])).order_by(TelemetryEvent.sequence.desc()).limit(1))
    active_file = active.file_id if active else None
    if checkpoint.sequence:
        event = db.scalar(select(TelemetryEvent).where(TelemetryEvent.session_id == session.id, TelemetryEvent.sequence == checkpoint.sequence))
    available = True
    between = [TelemetryEvent.session_id == session.id, TelemetryEvent.sequence > checkpoint.sequence, TelemetryEvent.sequence <= requested]
    recorded = db.scalar(select(func.count()).select_from(TelemetryEvent).where(*between))
    if recorded != requested - checkpoint.sequence:
        notices.append('Missing event ' + str(checkpoint.sequence + 1) + ' or a later event; only the verified checkpoint is shown. Missing edits are not invented.')
        available = False
    else:
        # Count audits sequence continuity without loading a million keyboard/cursor envelopes.
        # Only source/active-file changes and the selected event are needed for reconstruction.
        source_types = set(DOCUMENT_TYPES) | {'WORKSPACE_RECONCILED', 'FILE_CREATED', 'FOLDER_CREATED',
            'FILE_RENAMED', 'FOLDER_RENAMED', 'FILE_MOVED', 'FOLDER_MOVED', 'FILE_DELETED', 'FOLDER_DELETED'}
        relevant = source_types | {'ACTIVE_FILE_CHANGED', 'TAB_SWITCHED'}
        rows = list(db.scalars(select(TelemetryEvent).where(*between, or_(TelemetryEvent.event_type.in_(relevant),
            TelemetryEvent.sequence == requested)).order_by(TelemetryEvent.sequence).limit(5001)))
        if len(rows) > 5000:
            notices.append('Replay segment exceeds the bounded review window; choose a later verified checkpoint.')
            available = False
        else:
            for row in rows:
                try:
                    if row.event_type in source_types: nodes = apply_event(nodes, row.envelope)
                except (Fault, ValueError, KeyError, TypeError) as error:
                    notices.append('Cannot verify event ' + str(row.sequence) + ': ' + str(error) + '; showing only the verified checkpoint.')
                    nodes, sequence = copy.deepcopy(checkpoint.document_state), checkpoint.sequence
                    event = db.scalar(select(TelemetryEvent).where(TelemetryEvent.session_id == session.id, TelemetryEvent.sequence == checkpoint.sequence))
                    active_file = active.file_id if active and active.file_id in nodes else None
                    available = False; break
                if row.event_type in ('ACTIVE_FILE_CHANGED', 'TAB_SWITCHED'): active_file = row.file_id
                event = row
            if available: sequence = requested
    if session.integrity != 'Complete' or session.detected_gaps:
        notices.append('Recording reports ' + session.integrity + '; only retained, uploaded data is shown.')
    if through > session.last_contiguous_sequence: notices.append('Requested event has not been uploaded.')
    if active_file not in nodes: active_file = None
    return {'available': available, 'nodes': nodes, 'sequence': sequence, 'requestedSequence': requested,
            'checkpointSequence': checkpoint.sequence, 'activeFileId': active_file,
            'event': event.envelope if event else None, 'notices': notices}


def install_admin_history_routes(app, db_session):
    @app.get(ADMIN_PREFIX + 'sessions', response_class=TelemetryResponse)
    def sessions(request: Request, pageSize: int = Query(100, ge=1, le=200), before: str | None = None, db=Depends(db_session)):
        scope = administrator(request)
        query = scoped_sessions(db, scope)
        if before:
            try: cursor_id = str(UUID(before))
            except ValueError: raise APIError(422, 'invalid_cursor', 'Invalid recording cursor')
            cursor = db.scalar(query.where(TelemetrySession.id == cursor_id))
            if cursor is None: raise APIError(422, 'invalid_cursor', 'Invalid recording cursor')
            query = query.where((TelemetrySession.started_at < cursor.started_at) |
                               ((TelemetrySession.started_at == cursor.started_at) & (TelemetrySession.id < cursor.id)))
        rows = list(db.scalars(query.order_by(TelemetrySession.started_at.desc(), TelemetrySession.id.desc()).limit(pageSize + 1)))
        return {'sessions': [session_info(row) for row in rows[:pageSize]],
                'nextBefore': rows[pageSize - 1].id if len(rows) > pageSize else None,
                'notice': 'Only uploaded recordings are available. Browser-only or expired recordings cannot be recovered here.'}

    @app.get(ADMIN_PREFIX + 'sessions/{session_id}/replay', response_class=TelemetryResponse)
    def replay(session_id: UUID, request: Request, through: int = Query(0, ge=0, le=1_000_000), db=Depends(db_session)):
        scope = administrator(request)
        session = db.scalar(scoped_sessions(db, scope).where(TelemetrySession.id == str(session_id)))
        if session is None: raise APIError(404, 'recording_unavailable', 'Recording not found')
        return {'session': session_info(session), **replay_frame(db, session, through)}
