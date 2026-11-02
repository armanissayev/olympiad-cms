# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render real CWS submission rows when a participant has exhausted tokens."""
import ipaddress
from datetime import timedelta
from types import SimpleNamespace
import unittest
from uuid import uuid4

from cms import config, TOKEN_MODE_FINITE
from cms.io.web_service import tornado_wsgi
from cms.locale import get_translations
from cms.server.contest.authentication import validate_login
from cms.server.contest.handlers.tasksubmission import TaskSubmissionsHandler
from cms.server.contest.jinja2_toolbox import CWS_ENVIRONMENT
from cmscommon.binary import hex_to_bin
from cmscommon.crypto import build_password
from cmscommon.datetime import make_datetime
from cmstestsuite.unit_tests.databasemixin import DatabaseMixin
from tornado.web import create_signed_value
from werkzeug.test import Client
from werkzeug.wrappers import Response


class TestTaskSubmissionRendering(DatabaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        now = make_datetime()
        self.contest = self.add_contest(start=now-timedelta(hours=1), stop=now+timedelta(hours=2),
                                        allow_password_authentication=True, languages=[])
        self.user = self.add_user(password=build_password('disposable-submission-render'))
        self.participation = self.add_participation(user=self.user, contest=self.contest)
        self.task = self.add_task(contest=self.contest, name='sum'+uuid4().hex, token_mode=TOKEN_MODE_FINITE,
                                  token_gen_initial=0, token_gen_number=0,
                                  token_gen_interval=timedelta(hours=2))
        self.task.active_dataset = self.add_dataset(task=self.task, task_type='Batch',
            task_type_parameters=['alone', ['', ''], 'diff'], score_type='Sum', score_type_parameters=25)
        self.add_submission(task=self.task, participation=self.participation,
                             timestamp=now-timedelta(minutes=2), official=True)
        self.add_submission(task=self.task, participation=self.participation,
                             timestamp=now-timedelta(minutes=1), official=False)
        self.session.commit()
        service = SimpleNamespace(contest_id=self.contest.id, translations=get_translations(),
                                  jinja2_environment=CWS_ENVIRONMENT)
        app = tornado_wsgi.WSGIApplication([(r'/tasks/([^/]+)/submissions', TaskSubmissionsHandler)],
            cookie_secret=hex_to_bin(config.secret_key), xsrf_cookies=True)
        app.service = service
        self.client = Client(app, Response)
        _, cookie = validate_login(self.session, self.contest, make_datetime(), self.user.username,
                                    'disposable-submission-render', ipaddress.ip_address('127.0.0.1'))
        name = self.contest.name + '_login'
        signed = create_signed_value(hex_to_bin(config.secret_key), name, cookie)
        self.client.set_cookie('localhost', name, signed.decode('ascii'))

    def page(self):
        return self.client.get('/tasks/'+self.task.name+'/submissions', environ_overrides={'REMOTE_ADDR':'127.0.0.1'})

    def test_exhausted_tokens_render_both_official_and_unofficial_rows(self):
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Official submissions', response.data)
        self.assertIn(b'Unofficial submissions', response.data)
        self.assertEqual(response.data.count(b'No tokens'), 2)

    def test_future_generation_renders_wait_for_both_submission_kinds(self):
        self.task.token_gen_number = 1
        self.session.commit()
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.count(b'Wait...'), 2)

    def test_available_tokens_still_offer_play_action(self):
        self.task.token_gen_initial = 1
        self.session.commit()
        response = self.page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.count(b'>Play!</button>'), 2)
