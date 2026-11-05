# SPDX-License-Identifier: AGPL-3.0-or-later
"""CMS Admin history review bound to actual submitted files and native receipts."""
import hashlib
import json
import os
import re
import stat
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import requests
from gevent import Timeout
from gevent.lock import BoundedSemaphore
from sqlalchemy.orm import joinedload
try:
    import tornado4.web as tornado_web
except ImportError:
    import tornado.web as tornado_web

from cms import config
from cms.db import Contest, File, Participation, Submission, Task, User
from .base import BaseHandler, require_permission


def history_assertion(admin_id, contest_id, participation, task_id, method, path, query, key):
    import jwt  # Optional IDE dependency; disabled ordinary Admin startup must not require it.
    now = int(time.time())
    installation = config.olympiad_ide_installation_id
    mapping = json.dumps([installation, str(participation.user_id), str(contest_id), str(participation.id)], separators=(",", ":"), ensure_ascii=True)
    claims = {"iss": installation, "aud": "olympiad-ide-admin-history", "scope": "admin-history",
              "sub": str(admin_id), "targetUser": str(participation.user_id), "contest": str(contest_id),
              "participation": str(participation.id), "task": str(task_id), "principal": str(uuid5(NAMESPACE_URL, mapping)),
              "iat": now, "nbf": now, "exp": now + 30, "jti": str(uuid4()), "method": method, "path": path,
              "query_sha256": hashlib.sha256(query.encode('ascii')).hexdigest(), "body_sha256": hashlib.sha256(b'').hexdigest()}
    return jwt.encode(claims, key, algorithm='HS256')


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Canonical UUID required')
    return value


def _iso_time(value):
    if not isinstance(value, datetime):
        raise ValueError('Timestamp required')
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec='microseconds') + 'Z'


def receipt_boundary(file, participation, installation):
    """Read the exact immutable receipt; never guess a recording from filename or time."""
    submission = file.submission
    receipts = submission.olympiad_ide_receipts
    unavailable = 'This file was submitted outside Olympiad IDE; no submitted-file recording link is available.'
    if len(receipts) != 1:
        return None, unavailable
    receipt = receipts[0]
    try:
        scope = {'installationId': installation, 'userId': str(participation.user_id),
                 'contestId': str(participation.contest_id), 'participationId': str(participation.id)}
        if (receipt.installation_id != installation or receipt.participation_id != participation.id
                or receipt.submission_id != submission.id or submission.participation_id != participation.id
                or receipt.identity_scope != scope):
            raise ValueError('Receipt scope mismatch')
        correlation = receipt.correlation
        if not isinstance(correlation, dict) or set(correlation) != {'workspaceId', 'snapshotId', 'telemetry'}:
            raise ValueError('Invalid capture correlation')
        workspace = _uuid(correlation['workspaceId'])
        _uuid(correlation['snapshotId'])
        boundary = correlation['telemetry']
        if boundary is None:
            return None, 'The submitted file has no captured editing-history boundary.'
        if not isinstance(boundary, dict) or set(boundary) != {'sessionId', 'sequence'}:
            raise ValueError('Invalid telemetry boundary')
        capture_session = _uuid(boundary['sessionId'])
        sequence = boundary['sequence']
        if type(sequence) is not int or not 0 <= sequence <= 1_000_000:
            raise ValueError('Unsupported capture position')
        manifest = receipt.source_manifest
        if not isinstance(manifest, list) or not 1 <= len(manifest) <= 100:
            raise ValueError('Invalid source manifest')
        matches = [item for item in manifest if isinstance(item, dict) and item.get('filename') == str(file.filename)]
        if len(matches) != 1:
            raise ValueError('Exact submitted-file mapping unavailable')
        selected = matches[0]
        if set(selected) != {'filename', 'sourceFilename', 'fileId', 'sha256', 'size'}:
            raise ValueError('Invalid source mapping')
        file_id = _uuid(selected['fileId'])
        for name in ('filename', 'sourceFilename'):
            text = selected[name]
            if (not isinstance(text, str) or not 1 <= len(text) <= 255 or text in ('.', '..')
                    or any(part in text for part in ('/', '\\', '\x00'))):
                raise ValueError('Invalid source name')
        if not isinstance(selected['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', selected['sha256']):
            raise ValueError('Invalid source hash')
        if type(selected['size']) is not int or not 0 <= selected['size'] <= 8_000_000:
            raise ValueError('Invalid source size')
        return {'workspaceId': workspace, 'fileId': file_id, 'captureSessionId': capture_session,
                'captureSequence': str(sequence), 'sha256': selected['sha256'],
                'submittedAt': _iso_time(receipt.received_at), 'sourceFilename': selected['sourceFilename']}, None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None, 'The stored submission has no valid recording link. Review its source in the normal CMS submission page.'


class IDEHistoryHandler(BaseHandler):
    @require_permission(BaseHandler.PERMISSION_ALL)
    def get(self, contest_id):
        self.contest = self.safe_get_item(Contest, contest_id)
        params = self.render_params()
        params['contest'] = self.contest
        params['history_users'] = self.sql_session.query(User).join(Participation).filter(Participation.contest_id == self.contest.id).order_by(User.username).all()
        params['history_tasks'] = self.sql_session.query(Task).filter(Task.contest_id == self.contest.id).order_by(Task.num).all()
        self.set_header('Cache-Control', 'no-store')
        self.render('ide_history.html', **params)


class IDEHistoryDataHandler(BaseHandler):
    def submitted_files(self, participation, task):
        try:
            before = self.get_argument('beforeSubmission', None)
            if before is not None:
                before = int(before)
                if before <= 0: raise ValueError()
        except (ValueError, TypeError):
            raise tornado_web.HTTPError(400, 'Invalid submission cursor')
        query = self.sql_session.query(Submission).filter(Submission.participation_id == participation.id,
            Submission.task_id == task.id).options(joinedload(Submission.files), joinedload(Submission.olympiad_ide_receipts))
        if before is not None: query = query.filter(Submission.id < before)
        submissions = query.order_by(Submission.id.desc()).limit(51).all()
        files, last_id, next_before, omitted = [], None, None, False
        for submission in submissions[:50]:
            sources = sorted(submission.files.values(), key=lambda source: (str(source.filename), source.id))
            # Preserve each ordinary submission as a whole page, so a multi-file receipt is not split/skipped.
            if len(files) + len(sources) > 200 and files:
                next_before = last_id
                break
            if len(sources) > 200:
                sources, omitted = sources[:200], True
            for source in sources:
                boundary, reason = receipt_boundary(source, participation, config.olympiad_ide_installation_id)
                files.append({'fileId': str(source.id), 'submissionId': str(submission.id),
                              'submittedAt': _iso_time(submission.timestamp), 'filename': str(source.filename),
                              'sourceFilename': boundary['sourceFilename'] if boundary else str(source.filename),
                              'language': submission.language, 'official': submission.official,
                              'hasHistory': boundary is not None, 'reason': reason})
            last_id = submission.id
        else:
            if len(submissions) > 50: next_before = last_id
        notice = 'Submitted files from CMS. Editing history is available only when a valid IDE capture link and uploaded recording are retained.'
        if omitted: notice += ' A submission exceeds the 200-file review limit; use its normal CMS submission page for the complete file list.'
        self.finish({'files': files, 'nextBeforeSubmission': str(next_before) if next_before is not None else None, 'notice': notice})

    @require_permission(BaseHandler.PERMISSION_ALL)
    def get(self, contest_id, suffix):
        self.set_header('Cache-Control', 'no-store')
        contest = self.safe_get_item(Contest, contest_id)
        try:
            user_id = int(self.get_argument('userId'))
            task_id = int(self.get_argument('taskId'))
        except (ValueError, TypeError, tornado_web.MissingArgumentError):
            raise tornado_web.HTTPError(400, 'Choose a participant and problem')
        participation = self.sql_session.query(Participation).filter(Participation.contest_id == contest.id, Participation.user_id == user_id).first()
        task = self.sql_session.query(Task).filter(Task.contest_id == contest.id, Task.id == task_id).first()
        if participation is None or task is None: raise tornado_web.HTTPError(404)
        if not config.olympiad_ide_enabled:
            self.set_status(503); self.finish({'error': {'message': 'Olympiad IDE history is unavailable'}}); return
        if suffix == 'files':
            self.submitted_files(participation, task)
            return
        query = {}
        runtime_suffix = suffix
        try:
            file_route = re.fullmatch(r'files/([0-9]+)/(timeline|replay)', suffix)
            if file_route:
                source = self.sql_session.query(File).join(Submission).filter(File.id == int(file_route.group(1)),
                    Submission.participation_id == participation.id, Submission.task_id == task.id).first()
                if source is None: raise tornado_web.HTTPError(404)
                boundary, reason = receipt_boundary(source, participation, config.olympiad_ide_installation_id)
                if boundary is None:
                    self.set_status(409); self.finish({'error': {'code': 'history_unavailable', 'message': reason}}); return
                query = {key: value for key, value in boundary.items() if key != 'sourceFilename'}
                operation = file_route.group(2)
                if operation == 'timeline':
                    interval = int(self.get_argument('intervalSeconds', '5'))
                    if interval not in (1, 5, 10, 30): raise ValueError()
                    query['intervalSeconds'] = str(interval)
                else:
                    query['sessionId'] = _uuid(self.get_argument('sessionId'))
                    through = int(self.get_argument('through', '0'))
                    if not 0 <= through <= 1_000_000: raise ValueError()
                    query['through'] = str(through)
                runtime_suffix = 'file-' + operation
            elif suffix == 'sessions':
                before = self.get_argument('before', None)
                if before: query['before'] = str(UUID(before))
                query['pageSize'] = '100'
            elif re.fullmatch(r'sessions/[0-9a-f-]{36}/replay', suffix):
                through = int(self.get_argument('through', '0'))
                if not 0 <= through <= 1_000_000: raise ValueError()
                query['through'] = str(through)
            else:
                raise tornado_web.HTTPError(404)
        except (ValueError, TypeError, tornado_web.MissingArgumentError):
            raise tornado_web.HTTPError(400, 'Invalid file history position')
        query = urlencode(query)
        path = '/api/v1/admin/telemetry/' + runtime_suffix
        admin_id = self.current_user.id
        # Release native CMS connections before private IDE storage I/O.
        signed_identity = (participation.user_id, participation.id)
        self.sql_session.close()
        if not hasattr(self.service, 'ide_admin_history_slots'):
            self.service.ide_admin_history_slots = BoundedSemaphore(4)
        slots = self.service.ide_admin_history_slots
        if not slots.acquire(blocking=False):
            self.set_status(503); self.finish({'error': {'message': 'History storage is busy; retry shortly'}}); return
        try:
            from types import SimpleNamespace
            from cms.server.olympiadide.configuration import _loopback
            origin = urlsplit(config.olympiad_ide_runtime_url)
            if (origin.scheme != 'http' or not _loopback(origin.hostname or '') or origin.username or origin.password
                    or origin.query or origin.fragment or origin.path not in ('', '/') or not origin.port
                    or not 1024 <= origin.port <= 65535):
                raise ValueError('Invalid private history origin')
            fd = os.open(config.olympiad_ide_signing_key_file, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
                    raise ValueError('Private assertion key required')
                key = stream.read(4097)
            if not 32 <= len(key) <= 4096: raise ValueError('Invalid assertion key')
            token = history_assertion(admin_id, contest.id, SimpleNamespace(user_id=signed_identity[0], id=signed_identity[1]), task_id, 'GET', path, query, key)
            url = config.olympiad_ide_runtime_url.rstrip('/') + path + '?' + query
            with Timeout(config.olympiad_ide_request_timeout), requests.Session() as client:
                client.trust_env = False
                with client.get(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'},
                                timeout=(2, config.olympiad_ide_request_timeout), allow_redirects=False, stream=True) as response:
                    if 300 <= response.status_code < 400: raise ValueError('Redirect rejected')
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > config.olympiad_ide_max_response_bytes: raise ValueError('History response exceeds limit')
                    json.loads(data)
                    self.set_status(response.status_code); self.set_header('Content-Type', 'application/json'); self.finish(bytes(data))
        except (requests.RequestException, ValueError, OSError, UnicodeError, ImportError, Timeout):
            self.set_status(503); self.finish({'error': {'message': 'History storage is temporarily unavailable'}})
        finally:
            slots.release()
