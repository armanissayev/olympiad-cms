# SPDX-License-Identifier: AGPL-3.0-or-later
"""Native CMS Admin authentication/permission/contest membership for code history."""
import unittest
from contextlib import contextmanager
from datetime import datetime
import json
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory

import jwt
from cms import config
from cms.db import Admin, OlympiadIDEReceipt
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
        app=tornado_wsgi.WSGIApplication([(r'/contest/([0-9]+)/ide-history',IDEHistoryHandler),(r'/contest/([0-9]+)/ide-history/api/(sessions|files|files/[0-9]+/(?:timeline|replay))',IDEHistoryDataHandler)],cookie_secret=hex_to_bin(config.secret_key),xsrf_cookies=True,login_url='/login')
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

    def test_disabled_ordinary_admin_import_does_not_require_optional_pyjwt(self):
        script = """import importlib.abc,sys
class NoJWT(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='jwt' or fullname.startswith('jwt.'):
   raise ModuleNotFoundError('Optional PyJWT deliberately unavailable')
sys.meta_path.insert(0,NoJWT())
import cms.server.admin.handlers
print('optional_admin_import_ok')
"""
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr[-3000:]);self.assertIn('optional_admin_import_ok',result.stdout)


    def submitted_source(self, participation=None, task=None, linked=True):
        participation = participation or self.participation
        submission = self.add_submission(task=task or self.task, participation=participation,
                                         timestamp=datetime(2026, 11, 5, 12, 0), language='C++17 / g++')
        source = self.add_file(submission=submission, filename='main.%l')
        self.session.flush()
        receipt = None
        if linked:
            receipt = OlympiadIDEReceipt(installation_id='history-test-installation', intent_id=str(uuid4()),
                participation=participation, submission=submission, request_digest='a'*64,
                external_id='history-test-'+uuid4().hex,
                identity_scope={'installationId':'history-test-installation', 'userId':str(participation.user_id),
                    'contestId':str(participation.contest_id), 'participationId':str(participation.id)},
                source_manifest=[{'filename':'main.%l', 'sourceFilename':'solution.cpp', 'fileId':str(uuid4()), 'sha256':'b'*64, 'size':25}],
                correlation={'workspaceId':str(uuid4()), 'snapshotId':str(uuid4()),
                    'telemetry':{'sessionId':str(uuid4()), 'sequence':24}},
                received_at=datetime(2026,11,5,12,0))
            self.session.add(receipt)
        self.session.commit()
        return source, receipt

    def file_api(self, source=None, operation=None, extra=''):
        suffix = '/api/files'
        if source is not None: suffix += '/'+str(source.id)+'/'+operation
        return suffix+'?userId='+str(self.user.id)+'&taskId='+str(self.task.id)+extra

    @contextmanager
    def private_history_transport(self):
        from contextlib import ExitStack
        with TemporaryDirectory(prefix='cms-admin-key-') as folder, ExitStack() as stack:
            key=Path(folder)/'assertion.key';key.write_bytes(b'unit-only-administrator-key-32-bytes');key.chmod(0o600)
            client=MagicMock();client.__enter__.return_value=client
            response=MagicMock();response.__enter__.return_value=response;response.status_code=200
            response.iter_content.return_value=[b'{"available":true,"points":[]}'];client.get.return_value=response
            for name,value in [('olympiad_ide_enabled',True), ('olympiad_ide_installation_id','history-test-installation'),
                               ('olympiad_ide_signing_key_file',str(key)), ('olympiad_ide_runtime_url','http://127.0.0.1:8801')]:
                stack.enter_context(patch.object(config,name,value))
            stack.enter_context(patch('cms.server.admin.handlers.idehistory.requests.Session',return_value=client))
            yield client,key

    def test_submitted_file_listing_requires_admin_and_does_not_call_runtime(self):
        source,_=self.submitted_source()
        self.assertEqual(self.get(self.file_api()).status_code,302)
        self.client.set_cookie('localhost','participant_login','ordinary-participant-cookie')
        self.assertEqual(self.get(self.file_api()).status_code,302)
        self.login(self.reader)
        self.assertEqual(self.get(self.file_api()).status_code,403)
        self.assertEqual(self.get(self.file_api(source,'timeline')).status_code,403)
        self.login(self.admin)
        with self.private_history_transport() as (transport,_):
            response=self.get(self.file_api())
            self.assertEqual(response.status_code,200)
            rows=json.loads(response.data)['files'];self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['fileId'],str(source.id));self.assertEqual(rows[0]['sourceFilename'],'solution.cpp')
            self.assertEqual(rows[0]['filename'],'main.%l');self.assertTrue(rows[0]['hasHistory'])
            self.assertEqual(response.headers['Cache-Control'],'no-store');transport.get.assert_not_called()

    def test_file_listing_uses_actual_scoped_submissions_and_includes_cws_without_guessing(self):
        ide,_=self.submitted_source()
        cws,_=self.submitted_source(linked=False)
        other=self.add_user();other_part=self.add_participation(contest=self.contest,user=other)
        self.session.commit();alien,_=self.submitted_source(participation=other_part)
        second_task=self.add_task(contest=self.contest);self.session.commit()
        wrong_task,_=self.submitted_source(task=second_task)
        self.login(self.admin)
        with self.private_history_transport() as (transport,_):
            response=self.get(self.file_api());rows=json.loads(response.data)['files']
            self.assertEqual({row['fileId'] for row in rows},{str(ide.id),str(cws.id)})
            missing=next(row for row in rows if row['fileId']==str(cws.id))
            self.assertFalse(missing['hasHistory']);self.assertIn('outside Olympiad IDE',missing['reason'])
            for source in (alien,wrong_task):
                self.assertEqual(self.get(self.file_api(source,'timeline')).status_code,404)
                self.assertEqual(self.get(self.file_api(source,'replay','&sessionId='+str(uuid4()))).status_code,404)
            transport.get.assert_not_called()

    def test_file_history_query_is_built_from_receipt_and_bound_to_exact_signed_request(self):
        from urllib.parse import urlsplit,parse_qs
        source,receipt=self.submitted_source();self.login(self.admin)
        with self.private_history_transport() as (transport,key):
            response=self.get(self.file_api(source,'timeline','&intervalSeconds=10&workspaceId='+str(uuid4())+'&fileId='+str(uuid4())+'&captureSequence=999999&sha256='+'f'*64))
            self.assertEqual(response.status_code,200)
            args,kwargs=transport.get.call_args;url=urlsplit(args[0]);query=parse_qs(url.query)
            self.assertEqual(url.path,'/api/v1/admin/telemetry/file-timeline')
            self.assertEqual(query,{'workspaceId':[receipt.correlation['workspaceId']], 'fileId':[receipt.source_manifest[0]['fileId']],
                'captureSessionId':[receipt.correlation['telemetry']['sessionId']], 'captureSequence':['24'], 'sha256':['b'*64],
                'submittedAt':['2026-11-05T12:00:00.000000Z'], 'intervalSeconds':['10']})
            claims=jwt.decode(kwargs['headers']['Authorization'][7:],key.read_bytes(),algorithms=['HS256'],audience='olympiad-ide-admin-history')
            import hashlib
            self.assertEqual(claims['path'],url.path);self.assertEqual(claims['query_sha256'],hashlib.sha256(url.query.encode('ascii')).hexdigest())
            self.assertEqual(claims['targetUser'],str(self.user.id));self.assertEqual(claims['task'],str(self.task.id))

    def test_file_replay_keeps_receipt_capture_scope_and_checks_selected_position(self):
        from urllib.parse import urlsplit,parse_qs
        source,receipt=self.submitted_source();self.login(self.admin)
        session=receipt.correlation['telemetry']['sessionId']
        with self.private_history_transport() as (transport,_):
            result=self.get(self.file_api(source,'replay','&sessionId='+session+'&through=11'))
            self.assertEqual(result.status_code,200)
            parsed=urlsplit(transport.get.call_args[0][0]);query=parse_qs(parsed.query)
            self.assertEqual(parsed.path,'/api/v1/admin/telemetry/file-replay')
            self.assertEqual(query['sessionId'],[session]);self.assertEqual(query['through'],['11'])
            self.assertEqual(query['captureSequence'],['24']);self.assertEqual(query['sha256'],['b'*64])
            transport.get.reset_mock()
            for extra in ('&sessionId=not-a-session','&sessionId='+session+'&through=-1', '&sessionId='+session+'&through=1000001'):
                self.assertEqual(self.get(self.file_api(source,'replay',extra)).status_code,400)
            transport.get.assert_not_called()

    def test_missing_malformed_or_foreign_receipt_is_unavailable_without_runtime_access(self):
        source,receipt=self.submitted_source();self.login(self.admin)
        original_manifest=receipt.source_manifest;original_scope=receipt.identity_scope;original_correlation=receipt.correlation
        invalid=[('source_manifest',[]),('source_manifest',[{**original_manifest[0],'filename':'different.%l'}]),
                 ('source_manifest',[original_manifest[0],original_manifest[0]]),('source_manifest',[{**original_manifest[0],'sha256':'invalid'}]),
                 ('source_manifest',[{**original_manifest[0],'fileId':'invalid'}]),('source_manifest',[{**original_manifest[0],'sourceFilename':'../untrusted.cpp'}]),
                 ('identity_scope',{**original_scope,'userId':'999999'}),('correlation',{**original_correlation,'telemetry':None}),
                 ('correlation',{**original_correlation,'workspaceId':str(uuid4()).upper()}),
                 ('correlation',{**original_correlation,'telemetry':{'sessionId':str(uuid4()),'sequence':1000001}})]
        with self.private_history_transport() as (transport,_):
            for field,value in invalid:
                setattr(receipt,field,value);self.session.commit()
                listing=self.get(self.file_api());row=json.loads(listing.data)['files'][0]
                self.assertFalse(row['hasHistory'],(field,value));self.assertTrue(row['reason'])
                result=self.get(self.file_api(source,'timeline'));self.assertEqual(result.status_code,409,(field,value))
                self.assertEqual(json.loads(result.data)['error']['code'],'history_unavailable')
                receipt.source_manifest=original_manifest;receipt.identity_scope=original_scope;receipt.correlation=original_correlation;self.session.commit()
            transport.get.assert_not_called()

    def test_invalid_interval_and_cursor_are_rejected_before_transport(self):
        source,_=self.submitted_source();self.login(self.admin)
        with self.private_history_transport() as (transport,_):
            for interval in ('0','2','60','bad'):
                self.assertEqual(self.get(self.file_api(source,'timeline','&intervalSeconds='+interval)).status_code,400)
            for cursor in ('0','-1','bad'):
                self.assertEqual(self.get(self.file_api(extra='&beforeSubmission='+cursor)).status_code,400)
            transport.get.assert_not_called()

    def test_submitted_file_pagination_has_stable_exclusive_submission_cursor(self):
        sources=[]
        for _ in range(52):
            source,_=self.submitted_source(linked=False);sources.append(source)
        self.login(self.admin)
        with self.private_history_transport() as (transport,_):
            first=json.loads(self.get(self.file_api()).data)
            self.assertEqual(len(first['files']),50);self.assertIsNotNone(first['nextBeforeSubmission'])
            second=json.loads(self.get(self.file_api(extra='&beforeSubmission='+first['nextBeforeSubmission'])).data)
            self.assertEqual(len(second['files']),2);self.assertIsNone(second['nextBeforeSubmission'])
            identifiers=[row['fileId'] for row in first['files']+second['files']]
            self.assertEqual(len(set(identifiers)),52);self.assertEqual(set(identifiers),{str(source.id) for source in sources})
            transport.get.assert_not_called()
