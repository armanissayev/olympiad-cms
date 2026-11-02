# SPDX-License-Identifier: AGPL-3.0-or-later
"""Actual CWS page rendering for the optional contest-scoped IDE entry."""
import ipaddress
from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote

from cms import config
from cms.io.web_service import tornado_wsgi
from cms.locale import get_translations
from cms.server.contest.authentication import validate_login
from cms.server.contest.handlers.main import MainHandler
from cms.server.contest.jinja2_toolbox import CWS_ENVIRONMENT
from cmscommon.binary import hex_to_bin
from cmscommon.crypto import build_password
from cmscommon.datetime import make_datetime
from cmstestsuite.unit_tests.databasemixin import DatabaseMixin
from tornado.web import create_signed_value
from werkzeug.test import Client
from werkzeug.wrappers import Response


class TestOverviewIDEEntry(DatabaseMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        now = make_datetime()
        self.contest = self.add_contest(start=now-timedelta(hours=1), stop=now+timedelta(hours=1),
                                        allow_password_authentication=True, languages=[])
        self.user = self.add_user(password=build_password('disposable-overview-test'))
        self.add_participation(user=self.user, contest=self.contest)
        self.session.commit()
        self.service = SimpleNamespace(contest_id=self.contest.id, translations=get_translations(),
                                       jinja2_environment=CWS_ENVIRONMENT)
        app = tornado_wsgi.WSGIApplication([(r'/', MainHandler)], cookie_secret=hex_to_bin(config.secret_key), xsrf_cookies=True)
        app.service = self.service
        self.client = Client(app, Response)

    def login(self):
        _, cookie = validate_login(self.session, self.contest, make_datetime(), self.user.username,
                                    'disposable-overview-test', ipaddress.ip_address('127.0.0.1'))
        name = self.contest.name + '_login'
        signed = create_signed_value(hex_to_bin(config.secret_key), name, cookie)
        self.client.set_cookie('localhost', name, signed.decode('ascii'))

    def get_page(self):
        return self.client.get('/', environ_overrides={'REMOTE_ADDR': '127.0.0.1'})

    def test_authenticated_enabled_contest_has_visible_ide_entry_before_general_information(self):
        self.login()
        with patch.object(config, 'olympiad_ide_enabled', True):
            response = self.get_page()
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertIn('aria-labelledby="olympiad-ide-entry-title"', html)
        self.assertIn('class="container ide-overview-layout"', html)
        self.assertIn('href="/ide/">Open Olympiad IDE</a>', html)
        self.assertLess(html.index('id="olympiad-ide-entry-title"'), html.index('General information'))

    def test_disabled_feature_leaves_normal_contest_page_without_ide_entry(self):
        self.login()
        with patch.object(config, 'olympiad_ide_enabled', False):
            response = self.get_page()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'General information', response.data)
        self.assertNotIn(b'Open Olympiad IDE', response.data)

    def test_signed_out_visitor_gets_normal_login_without_advertising_workspace(self):
        with patch.object(config, 'olympiad_ide_enabled', True):
            response = self.get_page()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Please log in', response.data)
        self.assertNotIn(b'Open Olympiad IDE', response.data)

    def test_multi_contest_page_does_not_link_to_another_single_contest_ide(self):
        self.service.contest_id = None
        app = tornado_wsgi.WSGIApplication([(r'/([^/]+)', MainHandler)], cookie_secret=hex_to_bin(config.secret_key), xsrf_cookies=True)
        app.service = self.service
        self.client = Client(app, Response)
        self.login()
        with patch.object(config, 'olympiad_ide_enabled', True):
            response = self.client.get('/'+quote(self.contest.name, safe=''), environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'General information', response.data)
        self.assertNotIn(b'Open Olympiad IDE', response.data)
