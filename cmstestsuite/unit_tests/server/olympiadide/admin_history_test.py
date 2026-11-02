# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native CMS Admin authentication/permission/contest membership for code history."""
import unittest
import json
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory

import jwt
from cms import config
from cms.db import Admin
from cms.io.web_service import tornado_wsgi
from cms.server.admin.authentication import AWSAuthMiddleware, JSONSecureCookie
from cms.server.admin.handlers.idehistory import IDEHistoryHandler, IDEHistoryDataHandler, history_assertion
from cms.server.admin.jinja2_toolbox import AWS_ENVIRONMENT
from cmscommon.binary import hex_to_bin
from cmscommon.datetime import make_timestamp
from cmstestsuite.unit_tests.databasemixin import DatabaseMixin
from werkzeug.test import Client
from werkzeug.wrappers import Response


class TestAdminCodeHistory(DatabaseMixin,unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.contest=self.add_contest();self.user=self.add_user();self.participation=self.add_participation(contest=self.contest,user=self.user)
        self.task=self.add_task(contest=self.contest)
        self.admin=Admin(name='History admin',username='history-admin-'+uuid4().hex[:12],authentication='plaintext:unused',permission_all=True)
        self.reader=Admin(name='Read-only admin',username='history-reader-'+uuid4().hex[:12],authentication='plaintext:unused',permission_all=False)
        self.session.add_all([self.admin,self.reader]);self.session.commit()
        app=tornado_wsgi.WSGIApplication([(r'/contest/([0-9]+)/ide-history',IDEHistoryHandler),(r'/contest/([0-9]+)/ide-history/api/(sessions)',IDEHistoryDataHandler)],cookie_secret=hex_to_bin(config.secret_key),xsrf_cookies=True,login_url='/login')
        auth=AWSAuthMiddleware(app)
        app.service=SimpleNamespace(jinja2_environment=AWS_ENVIRONMENT,auth_handler=auth)
        self.client=Client(auth,Response)

    def login(self,admin):
        value=JSONSecureCookie({'id':admin.id,'ip':'127.0.0.1','timestamp':make_timestamp()},secret_key=hex_to_bin(config.secret_key))
        self.client.set_cookie('localhost','awslogin',value.serialize().decode('ascii'))

    def get(self,suffix=''):
        return self.client.get('/contest/'+str(self.contest.id)+'/ide-history'+suffix,environ_overrides={'REMOTE_ADDR':'127.0.0.1'})

    def test_anonymous_and_read_only_admin_cannot_read_history(self):
        self.assertEqual(self.get().status_code,302)
        self.login(self.reader)
        self.assertEqual(self.get().status_code,403)
        self.assertEqual(self.get('/api/sessions?userId='+str(self.user.id)+'&taskId='+str(self.task.id)).status_code,403)

    def test_full_admin_gets_selectors_readonly_source_and_sidebar_entry(self):
        self.login(self.admin)
        with patch.object(config,'olympiad_ide_enabled',True):response=self.get()
        self.assertEqual(response.status_code,200)
        body=response.data.decode();self.assertIn('Participant code history',body)
        self.assertIn('aria-label="History participant"',body);self.assertIn(self.user.username,body)
        self.assertIn('aria-label="Historical source" readonly',body);self.assertIn('>Code history</a>',body)
        self.assertNotIn('Recording Locally',body)

    def test_other_contest_user_or_problem_is_rejected_before_transport(self):
        self.login(self.admin)
        other=self.add_user();self.session.commit()
        self.assertEqual(self.get('/api/sessions?userId='+str(other.id)+'&taskId='+str(self.task.id)).status_code,404)
        self.assertEqual(self.get('/api/sessions?userId='+str(self.user.id)+'&taskId=999999').status_code,404)

    def test_native_history_assertion_has_separate_admin_scope_and_target(self):
        key=b'unit-only-administrator-key-32-bytes'
        with patch.object(config,'olympiad_ide_installation_id','898dbca3-c879-4f7a-b0c3-49830c9e1c28'):
            signed=history_assertion(self.admin.id,self.contest.id,self.participation,self.task.id,'GET','/api/v1/admin/telemetry/sessions','pageSize=100',key)
        claims=jwt.decode(signed,key,algorithms=['HS256'],audience='olympiad-ide-admin-history')
        self.assertEqual(claims['scope'],'admin-history');self.assertEqual(claims['sub'],str(self.admin.id));self.assertEqual(claims['targetUser'],str(self.user.id))
        self.assertEqual(claims['contest'],str(self.contest.id));self.assertEqual(claims['participation'],str(self.participation.id));self.assertEqual(claims['task'],str(self.task.id))

    def test_proxy_is_private_bounded_and_signs_checked_target(self):
        self.login(self.admin)
        client=MagicMock();client.__enter__.return_value=client
        response=MagicMock();response.__enter__.return_value=response;response.status_code=200
        response.iter_content.return_value=[b'{"sessions":[]}'];client.get.return_value=response
        with TemporaryDirectory(prefix='cms-admin-key-') as folder:
            key=Path(folder)/'assertion.key';key.write_bytes(b'unit-only-administrator-key-32-bytes');key.chmod(0o600)
            with patch.object(config,'olympiad_ide_enabled',True), patch.object(config,'olympiad_ide_installation_id','898dbca3-c879-4f7a-b0c3-49830c9e1c28'), patch.object(config,'olympiad_ide_signing_key_file',str(key)), patch.object(config,'olympiad_ide_runtime_url','http://127.0.0.1:8801'), patch('cms.server.admin.handlers.idehistory.requests.Session',return_value=client):
                result=self.get('/api/sessions?userId='+str(self.user.id)+'&taskId='+str(self.task.id))
            self.assertEqual(result.status_code,200);self.assertEqual(json.loads(result.data),{'sessions':[]})
            args,kwargs=client.get.call_args
            self.assertEqual(args[0],'http://127.0.0.1:8801/api/v1/admin/telemetry/sessions?pageSize=100')
            claims=jwt.decode(kwargs['headers']['Authorization'][7:],key.read_bytes(),algorithms=['HS256'],audience='olympiad-ide-admin-history')
            self.assertEqual(claims['targetUser'],str(self.user.id));self.assertEqual(claims['task'],str(self.task.id));self.assertFalse(client.trust_env)
            self.assertFalse(kwargs['allow_redirects']);self.assertTrue(kwargs['stream'])
        with patch.object(config,'olympiad_ide_enabled',True),patch.object(config,'olympiad_ide_runtime_url','http://untrusted.example:8801'),patch('cms.server.admin.handlers.idehistory.requests.Session') as transport:
            self.assertEqual(self.get('/api/sessions?userId='+str(self.user.id)+'&taskId='+str(self.task.id)).status_code,503)
            transport.assert_not_called()
