# SPDX-License-Identifier: AGPL-3.0-or-later

"""Native context/auth integration against disposable real PostgreSQL."""
import ipaddress
import json
from datetime import timedelta
from types import SimpleNamespace
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cmstestsuite.unit_tests.databasemixin import DatabaseMixin
from cms import config
from cms.io.web_service import tornado_wsgi
from cms.locale import get_translations
from cms.server.contest.authentication import validate_login
from cms.server.olympiadide.base import IDEAPIHandler
from cms.server.olympiadide.context import ContextHandler
from cms.server.olympiadide.server import LiveHandler, ReadyHandler
from cms.server.olympiadide.handlers import OfficialSubmissionsHandler
from cmscommon.binary import hex_to_bin
from cmscommon.crypto import build_password
from cmscommon.datetime import make_datetime
from tornado.web import create_signed_value
from werkzeug.test import Client
from werkzeug.wrappers import Response


class ProtectedProbe(IDEAPIHandler):
    def get(self):
        self.write_json({'identity': self.ide_identity})

    post = get


class ContextTest(DatabaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        now = make_datetime()
        self.contest = self.add_contest(start=now-timedelta(hours=1), stop=now+timedelta(hours=1),
                                        allow_password_authentication=True, languages=['C++17 / g++', 'Python 3 / CPython'])
        self.user = self.add_user(password=build_password('local-test-password'))
        self.participation = self.add_participation(user=self.user, contest=self.contest)
        self.task = self.add_task(contest=self.contest, submission_format=['main.%l'])
        self.dataset = self.add_dataset(task=self.task, task_type='Batch', task_type_parameters=['alone', ['', ''], 'diff'],
                                        score_type='Sum', score_type_parameters=100)
        self.task.active_dataset = self.dataset
        self.session.commit()
        self.assets = TemporaryDirectory()
        self.addCleanup(self.assets.cleanup)
        Path(self.assets.name, 'index.html').write_text('<html></html>')
        self.service = SimpleNamespace(contest_id=self.contest.id, translations=get_translations(), assets_path=self.assets.name)
        self.app = tornado_wsgi.WSGIApplication([(r'/ide/api/context', ContextHandler), (r'/ide/api/probe', ProtectedProbe), (r'/ide/health/live', LiveHandler), (r'/ide/health/ready', ReadyHandler), (r'/ide/api/submissions', OfficialSubmissionsHandler)],
                                                cookie_secret=hex_to_bin(config.secret_key), xsrf_cookies=True)
        self.app.service = self.service
        self.client = Client(self.app, Response)
        self.patch = patch.object(config, 'olympiad_ide_installation_id', '68a65c90-95da-4930-ae83-b209dd0656c9')
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def request(self, path='/ide/api/context', **kwargs):
        return self.client.get(path, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}, **kwargs)

    def login(self, timestamp=None):
        _, cookie = validate_login(self.session, self.contest, timestamp or make_datetime(), self.user.username,
                                    'local-test-password', ipaddress.ip_address('127.0.0.1'))
        self.assertIsNotNone(cookie)
        name = self.contest.name + '_login'
        signed = create_signed_value(hex_to_bin(config.secret_key), name, cookie)
        self.client.set_cookie('localhost', name, signed.decode('ascii'))

    def test_context_reuses_cms_login_and_discloses_only_authorized_task_metadata(self):
        self.assertEqual(self.request().status_code, 401)
        self.login()
        response = self.request()
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['identity']['participationId'], str(self.participation.id))
        self.assertEqual(data['actualPhase'], 0)
        self.assertEqual(data['contest']['id'], self.contest.id)
        self.assertEqual(data['executionProfileMap']['python3']['cmsLanguage'], 'Python 3 / CPython')
        self.assertFalse(data['executionProfileMap']['java17']['enabled'])
        self.assertEqual([t['id'] for t in data['tasks']], [self.task.id])
        self.assertEqual(data['tasks'][0]['submissionFormat'], ['main.%l'])
        self.assertTrue(data['tasks'][0]['supported'])
        self.assertEqual({l['id'] for l in data['tasks'][0]['languages']}, set(self.contest.languages))
        self.assertNotIn('password', response.data.decode())
        self.assertNotIn('managers', response.data.decode())
        self.assertEqual(response.headers['Cache-Control'], 'no-store, private')

    def test_unsupported_task_type_keeps_context_available_with_cws_fallback(self):
        self.login()
        self.dataset.task_type = 'UnavailableCustomPlugin'
        self.session.commit()
        response = self.request()
        self.assertEqual(response.status_code, 200)
        task = json.loads(response.data)['tasks'][0]
        self.assertFalse(task['supported'])
        self.assertFalse(task['customRunSupported'])
        self.assertEqual(task['languages'], [])
        self.assertIn('/tasks/', task['statementUrl'])

    def test_expired_or_revoked_cms_cookie_cannot_become_development_identity(self):
        self.login(make_datetime()-timedelta(seconds=config.cookie_duration+1))
        self.assertEqual(self.request().status_code, 401)
        self.login()
        self.user.password = build_password('changed')
        self.session.commit()
        self.assertEqual(self.request().status_code, 401)

    def test_removed_hidden_or_ip_restricted_participation_is_rechecked(self):
        self.login()
        self.contest.ip_restriction = True
        self.participation.ip = [ipaddress.ip_network('192.0.2.0/24')]
        self.session.commit()
        self.assertEqual(self.request().status_code, 401)
        self.contest.ip_restriction = False
        self.participation.hidden = True
        self.contest.block_hidden_participations = True
        self.session.commit()
        self.login_cookie_for_current_state()
        self.assertEqual(self.request().status_code, 401)

    def login_cookie_for_current_state(self):
        # Reapply the same signed CMS cookie; no new authorization is granted.
        from cmscommon.datetime import make_timestamp
        raw = json.dumps([self.user.username, self.user.password, make_timestamp(make_datetime())]).encode()
        name = self.contest.name + '_login'
        self.client.set_cookie('localhost', name, create_signed_value(hex_to_bin(config.secret_key), name, raw).decode())

    def test_precontest_tasks_hidden_and_per_participant_extra_time_preserved(self):
        self.login()
        now = make_datetime()
        self.contest.start = now+timedelta(hours=1)
        self.contest.stop = now+timedelta(hours=2)
        self.session.commit()
        data = json.loads(self.request().data)
        self.assertEqual(data['actualPhase'], -2)
        self.assertEqual(data['tasks'], [])
        self.contest.start = now-timedelta(hours=2)
        self.contest.stop = now-timedelta(minutes=1)
        self.participation.extra_time = timedelta(minutes=5)
        self.session.commit()
        self.assertEqual(json.loads(self.request().data)['actualPhase'], 0)

    def test_cms_ip_autologin_is_supported_without_new_cookie_authority(self):
        self.contest.ip_autologin = True
        self.participation.ip = [ipaddress.ip_network('127.0.0.1/32')]
        self.session.commit()
        self.assertEqual(self.request().status_code, 200)

    def test_manual_submission_refreshes_cookie_but_background_context_does_not(self):
        self.login()
        response = self.request()
        data = json.loads(response.data)
        cookie_name = self.contest.name + '_login='
        self.assertFalse(any(cookie_name in value for value in response.headers.getlist('Set-Cookie')))
        response = self.client.post('/ide/api/submissions', data='{}', content_type='application/json',
                                    headers={'X-XSRFToken': data['csrfToken'], 'X-Olympiad-Principal': data['identity']['principalId']},
                                    environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        self.assertEqual(response.status_code, 422)
        self.assertTrue(any(cookie_name in value for value in response.headers.getlist('Set-Cookie')))

    def test_readiness_requires_receipt_migration_while_liveness_is_independent(self):
        self.assertEqual(self.request('/ide/health/ready').status_code, 200)
        self.session.execute('ALTER TABLE olympiad_ide_receipts RENAME TO missing_ide_receipts')
        self.session.commit()
        try:
            self.assertEqual(self.request('/ide/health/ready').status_code, 503)
            self.assertEqual(self.request('/ide/health/live').status_code, 200)
        finally:
            self.session.execute('ALTER TABLE missing_ide_receipts RENAME TO olympiad_ide_receipts')
            self.session.commit()

    def test_protected_request_needs_expected_identity_and_cms_xsrf(self):
        self.login()
        data = json.loads(self.request().data)
        self.assertEqual(self.request('/ide/api/probe').status_code, 409)
        headers = {'X-Olympiad-Principal': data['identity']['principalId']}
        self.assertEqual(self.request('/ide/api/probe', headers=headers).status_code, 200)
        self.assertEqual(self.client.post('/ide/api/probe', headers=headers, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).status_code, 403)
        headers['X-XSRFToken'] = data['csrfToken']
        self.assertEqual(self.client.post('/ide/api/probe', headers=headers, environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).status_code, 200)


if __name__ == '__main__':
    unittest.main()
