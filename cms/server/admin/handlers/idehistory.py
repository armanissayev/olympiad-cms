# SPDX-License-Identifier: AGPL-3.0-or-later
"""Private CMS Admin history viewer; participant cookies never authorize this route."""
import hashlib
import json
import os
import stat
import time
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import requests
from gevent import Timeout
from gevent.lock import BoundedSemaphore
try:
    import tornado4.web as tornado_web
except ImportError:
    import tornado.web as tornado_web

from cms import config
from cms.db import Contest, Participation, Task, User
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
        query = {}
        try:
            if suffix == 'sessions':
                before = self.get_argument('before', None)
                if before: query['before'] = str(UUID(before))
                query['pageSize'] = '100'
            else:
                through = int(self.get_argument('through', '0'))
                if not 0 <= through <= 1000000: raise ValueError()
                query['through'] = str(through)
        except (ValueError, TypeError):
            raise tornado_web.HTTPError(400, 'Invalid recording position')
        query = urlencode(query)
        path = '/api/v1/admin/telemetry/' + suffix
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
