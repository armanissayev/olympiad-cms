"""Read-only, CMS administrator-authorized access to uploaded recording prefixes."""
import copy
import json
from dataclasses import dataclass
import hashlib
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, Query, Request
from sqlalchemy import delete, select, func, or_
from sqlalchemy.orm import defer

from .cms_identity import AssertionError, principal_id
from .cms_identity_models import CMSAssertionNonce, CMSPrincipal, CMSWorkspaceBinding
from .service import APIError
from .models import utcnow
from .telemetry import Fault, TelemetryResponse, apply_event, digest, validate_tree
from .telemetry_models import TelemetryCheckpoint, TelemetryEvent, TelemetrySession
from .telemetry_schema import DOCUMENT_TYPES
from .history_analysis import group_file_events, THRESHOLDS, REVIEW_NOTICE

UUID_PATH = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ADMIN_PREFIX = '/api/v1/admin/telemetry/'


def validate_admin_assertion(token, settings, method, path, query, body):
    """Separate audience/scope; participant assertions cannot grant administrator access."""
    required = ['iss', 'aud', 'sub', 'targetUser', 'contest', 'participation', 'task', 'principal',
                'scope', 'iat', 'nbf', 'exp', 'jti', 'method', 'path', 'query_sha256', 'body_sha256']
    try:
        if method != 'GET' or body or not (path in {ADMIN_PREFIX + 'sessions', ADMIN_PREFIX + 'file-timeline', ADMIN_PREFIX + 'file-replay'} or
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
    return select(TelemetrySession).options(defer(TelemetrySession.replay_state)).join(CMSWorkspaceBinding, CMSWorkspaceBinding.workspace_id == TelemetrySession.workspace_id).join(
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
    with db.scalars(select(TelemetryCheckpoint).where(TelemetryCheckpoint.session_id == session.id,
        TelemetryCheckpoint.sequence <= requested).order_by(TelemetryCheckpoint.sequence.desc(), TelemetryCheckpoint.id).limit(100).execution_options(stream_results=True, yield_per=1)) as candidates:
        for candidate in candidates:
            try:
                if not isinstance(candidate.document_state, dict) or not isinstance(candidate.envelope, dict):
                    raise ValueError('Malformed checkpoint object')
                validate_tree(candidate.document_state)
                if digest(candidate.document_state) != candidate.state_hash or candidate.envelope.get('nodes') != candidate.document_state:
                    raise ValueError('Checkpoint hash/content mismatch')
                checkpoint = candidate
                break
            except (Fault, ValueError, TypeError, KeyError, AttributeError):
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
                except (Fault, ValueError, KeyError, TypeError, AttributeError) as error:
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


# Limits bound source payloads and reconstruction work independently of dense key streams.
MAX_HISTORY_PERIODS = 30
MAX_HISTORY_EVENTS = 10000
MAX_HISTORY_PAYLOAD_BYTES = 6_000_000


@dataclass(frozen=True)
class CapturedFile:
    workspace_id: str
    file_id: str
    session_id: str
    sequence: int
    expected_sha256: str
    submitted_at: datetime


def submitted_file_target(workspaceId: UUID, fileId: UUID, captureSessionId: UUID,
                          captureSequence: int = Query(..., ge=0, le=1_000_000),
                          sha256: str = Query(..., pattern=r'^[0-9a-f]{64}$'),
                          submittedAt: datetime = Query(...)):
    if submittedAt.tzinfo is None or submittedAt.utcoffset() is None:
        raise APIError(422, 'invalid_submission_boundary', 'Submission timestamp must include its timezone')
    return CapturedFile(str(workspaceId), str(fileId), str(captureSessionId), captureSequence,
                        sha256, submittedAt.astimezone(timezone.utc))


def capture_session(db, scope, target):
    row = db.scalar(scoped_sessions(db, scope).where(TelemetrySession.id == target.session_id,
                                                    TelemetrySession.workspace_id == target.workspace_id))
    if row is None:
        raise APIError(404, 'recording_unavailable', 'The submitted file recording has not been uploaded or is no longer retained')
    return row


def older_boundary(db, row, target):
    # A late event stops the prefix, not merely that one event. Never splice over a gap.
    first_late = db.scalar(select(func.min(TelemetryEvent.sequence)).where(
        TelemetryEvent.session_id == row.id, TelemetryEvent.server_timestamp > target.submitted_at))
    return min(row.last_contiguous_sequence, first_late - 1) if first_late is not None else row.last_contiguous_sequence


def file_session(db, scope, target, session_id):
    captured = capture_session(db, scope, target)
    if session_id == captured.id:
        return captured, min(target.sequence, captured.last_contiguous_sequence)
    row = db.scalar(scoped_sessions(db, scope).where(TelemetrySession.id == session_id,
        TelemetrySession.workspace_id == target.workspace_id,
        TelemetrySession.server_started_at <= captured.server_started_at,
        TelemetrySession.server_started_at <= target.submitted_at))
    if row is None:
        raise APIError(404, 'recording_unavailable', 'This editing period does not belong to the submitted file history')
    return row, older_boundary(db, row, target)


def source_hash(content):
    try:
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    except UnicodeEncodeError:
        return None


def one_file_frame(db, row, target, through):
    frame = replay_frame(db, row, through)
    node = frame['nodes'].get(target.file_id)
    node = node if isinstance(node, dict) and node.get('type') == 'file' and isinstance(node.get('content'), str) else None
    notices = list(frame['notices'])
    if node is None:
        notices.append('This file does not exist in the verified state at this position.')
    return {'fileId': target.file_id, 'content': node['content'] if node else None,
            'name': node['name'] if node else None, 'sequence': frame['sequence'],
            'requestedSequence': through, 'available': frame['available'] and node is not None,
            'sha256': source_hash(node['content']) if node else None,
            'session': session_info(row), 'notices': notices}


def file_correlation(db, captured, target):
    frame = one_file_frame(db, captured, target, target.sequence)
    complete = (frame['available'] and frame['sha256'] is not None and frame['sequence'] == target.sequence and not frame['notices']
                and captured.integrity == 'Complete' and not captured.detected_gaps)
    if not complete:
        state, detail = 'unavailable', 'The exact submission boundary cannot be fully verified from retained uploaded history. Missing edits are not invented.'
    elif frame['sha256'] == target.expected_sha256:
        state, detail = 'matched', 'Exact submitted-file bytes match the verified uploaded recording at the captured boundary. This does not prove authorship.'
    else:
        state, detail = 'mismatch', 'Recorded source at the captured boundary differs from the actual CMS submitted-file hash. Review the recording integrity; this is not a plagiarism verdict.'
    return {'state': state, 'expectedSha256': target.expected_sha256, 'actualSha256': frame['sha256'], 'detail': detail}


def file_timeline(db, scope, target, interval_seconds):
    captured = capture_session(db, scope, target)
    earlier = list(db.scalars(scoped_sessions(db, scope).where(
        TelemetrySession.workspace_id == target.workspace_id, TelemetrySession.id != captured.id,
        TelemetrySession.server_started_at <= captured.server_started_at,
        TelemetrySession.server_started_at <= target.submitted_at).order_by(
            TelemetrySession.server_started_at.desc(), TelemetrySession.id.desc()).limit(MAX_HISTORY_PERIODS + 1)))
    notices = [REVIEW_NOTICE,
        'Editing periods are separate recordings ordered by server registration; gaps and browser clock changes are not treated as continuous writing.',
        'Only the captured recording has an exact receipt boundary. Earlier recordings exclude events uploaded after submission; older offline uploads may be unavailable.']
    partial = len(earlier) > MAX_HISTORY_PERIODS
    if partial:
        notices.append(f'Only the newest {MAX_HISTORY_PERIODS} earlier retained editing periods are included.')
    periods, points, used_events, used_bytes = [], [], 0, 0
    display_order = {row.id: index for index, row in enumerate(list(reversed(earlier[:MAX_HISTORY_PERIODS])) + [captured])}
    # Spend the bounded analysis budget on the actual submitted period, then newest history.
    for row in [captured] + earlier[:MAX_HISTORY_PERIODS]:
        through = min(target.sequence, row.last_contiguous_sequence) if row.id == captured.id else older_boundary(db, row, target)
        if row.id != captured.id and through < row.last_contiguous_sequence:
            notices.append('Later-uploaded activity was excluded from an earlier editing period.')
            partial = True
        # Only file source/paste/copy cues are read, not dense key-up/cursor/focus streams.
        copy_key = (TelemetryEvent.event_type == 'KEY_DOWN') & TelemetryEvent.payload['key'].as_string().in_(['c', 'C']) & (
            (TelemetryEvent.payload['ctrl'].as_boolean() == True) | (TelemetryEvent.payload['meta'].as_boolean() == True))
        relevant = or_((TelemetryEvent.file_id == target.file_id) & or_(
            TelemetryEvent.event_type.in_(set(DOCUMENT_TYPES) | {'PASTE', 'FILE_CREATED'}), copy_key),
            TelemetryEvent.event_type == 'WORKSPACE_RECONCILED')
        query = select(TelemetryEvent.sequence, TelemetryEvent.event_type, TelemetryEvent.file_id,
                       TelemetryEvent.monotonic_offset, TelemetryEvent.client_timestamp, TelemetryEvent.payload).where(
            TelemetryEvent.session_id == row.id, TelemetryEvent.sequence <= through, relevant).order_by(
                TelemetryEvent.sequence).limit(max(1, MAX_HISTORY_EVENTS - used_events + 1)).execution_options(stream_results=True, yield_per=50)
        events, truncated = [], False
        with db.execute(query) as result:
            for event in result:
                used_events += 1
                size = len(json.dumps(event.payload, ensure_ascii=True))
                used_bytes += size
                if used_events > MAX_HISTORY_EVENTS or used_bytes > MAX_HISTORY_PAYLOAD_BYTES:
                    truncated = True
                    partial = True
                    break
                # A workspace restore is relevant only if it actually contains this file.
                if event.event_type == 'WORKSPACE_RECONCILED' and target.file_id not in event.payload.get('nodes', {}):
                    continue
                events.append({'sequence': event.sequence, 'eventType': event.event_type,
                               'fileId': event.file_id, 'monotonicOffsetMs': event.monotonic_offset,
                               'clientTimestamp': event.client_timestamp.isoformat(), 'payload': event.payload})
        if row.id != captured.id and not events:
            recorded_file = db.scalar(select(TelemetryCheckpoint.id).where(
                TelemetryCheckpoint.session_id == row.id, TelemetryCheckpoint.sequence <= through,
                TelemetryCheckpoint.document_state[target.file_id].is_not(None)).limit(1))
            if recorded_file is None:
                if truncated:
                    notices.append('The bounded file activity review was truncated; not all earlier intervals or markers are available.')
                    break
                continue
        prefix_count, last_offset = db.execute(select(func.count(), func.max(TelemetryEvent.monotonic_offset)).where(
            TelemetryEvent.session_id == row.id, TelemetryEvent.sequence <= through)).one()
        if prefix_count != through:
            notices.append('An editing period has missing stored events; its intervals and review markers are partial.')
            partial = True
        grouped = group_file_events(events, interval_seconds)
        label = 'Submitted editing period' if row.id == captured.id else 'Earlier editing period'
        period = {'sessionId': row.id, 'label': label, 'startedAt': row.started_at,
                  'through': through, 'initialSequence': 0, 'lastOffsetMs': max(0, last_offset or 0),
                  'integrity': row.integrity, 'gaps': row.detected_gaps}
        periods.append(period)
        initial = {'sequence': 0, 'offsetMs': 0, 'startOffsetMs': 0, 'endOffsetMs': 0,
                   'timestamp': row.started_at, 'kind': 'initial', 'label': 'Initial recorded state',
                   'inserted': 0, 'deleted': 0, 'editCount': 0, 'keyboardInputs': 0, 'markers': []}
        for point in [initial] + grouped:
            point.update(id=f'{row.id}:{point["sequence"]}:{point["kind"]}', sessionId=row.id)
            points.append(point)
        if truncated:
            notices.append('The bounded file activity review was truncated; not all earlier intervals or markers are available.')
            break
    # Always include the actual immutable capture boundary, even when analysis is truncated.
    capture_event = db.scalar(select(TelemetryEvent).where(TelemetryEvent.session_id == captured.id,
                                                          TelemetryEvent.sequence == min(target.sequence, captured.last_contiguous_sequence)))
    boundary = {'id': f'{captured.id}:{target.sequence}:submission', 'sessionId': captured.id,
                'sequence': target.sequence, 'offsetMs': capture_event.monotonic_offset if capture_event else 0,
                'timestamp': target.submitted_at,
                'kind': 'submission', 'label': 'Submitted version', 'inserted': 0, 'deleted': 0,
                'editCount': 0, 'keyboardInputs': 0, 'markers': []}
    points.append(boundary)
    if captured.id not in {period['sessionId'] for period in periods}:
        periods.append({'sessionId': captured.id, 'label': 'Submitted editing period', 'startedAt': captured.started_at,
                        'through': min(target.sequence, captured.last_contiguous_sequence), 'initialSequence': 0,
                        'lastOffsetMs': captured.last_monotonic_offset, 'integrity': captured.integrity, 'gaps': captured.detected_gaps})
    correlation = file_correlation(db, captured, target)
    if correlation['state'] != 'matched':
        notices.append(correlation['detail'])
        partial = partial or correlation['state'] == 'unavailable'
    if any(period['integrity'] != 'Complete' or period['gaps'] for period in periods):
        partial = True
        notices.append('One or more recordings report incomplete integrity. Markers cover retained activity only.')
    periods.sort(key=lambda period: display_order[period['sessionId']])
    points.sort(key=lambda point: (display_order[point['sessionId']], point['sequence'], {'initial': 0, 'editing': 1, 'submission': 2}[point['kind']]))
    return {'fileId': target.file_id, 'intervalSeconds': interval_seconds, 'periods': periods,
            'points': points, 'summary': {name: sum(point[name] for point in points) for name in ('editCount', 'inserted', 'deleted', 'keyboardInputs')} |
            {'markerCount': sum(len(point['markers']) for point in points), 'periodCount': len(periods)},
            'correlation': correlation, 'thresholds': THRESHOLDS, 'notices': list(dict.fromkeys(notices)), 'partial': partial}


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


    @app.get(ADMIN_PREFIX + 'file-timeline', response_class=TelemetryResponse)
    def submitted_file_timeline(request: Request, target=Depends(submitted_file_target),
                                intervalSeconds: int = Query(5), db=Depends(db_session)):
        scope = administrator(request)
        if intervalSeconds not in (1, 5, 10, 30):
            raise APIError(422, 'invalid_interval', 'Choose a 1, 5, 10 or 30 second editing interval')
        return file_timeline(db, scope, target, intervalSeconds)

    @app.get(ADMIN_PREFIX + 'file-replay', response_class=TelemetryResponse)
    def submitted_file_replay(request: Request, target=Depends(submitted_file_target),
                              sessionId: UUID = Query(...), through: int = Query(0, ge=0, le=1_000_000),
                              db=Depends(db_session)):
        scope = administrator(request)
        row, allowed = file_session(db, scope, target, str(sessionId))
        if through > allowed:
            if row.id == target.session_id and through <= target.sequence:
                return {'fileId': target.file_id, 'content': None, 'name': None, 'sequence': allowed,
                        'requestedSequence': through, 'available': False, 'sha256': None,
                        'session': session_info(row), 'notices': ['The captured editing prefix has not been uploaded. No later source is substituted.']}
            raise APIError(422, 'invalid_recording_position', 'Position is outside this submitted file history')
        return one_file_frame(db, row, target, through)
