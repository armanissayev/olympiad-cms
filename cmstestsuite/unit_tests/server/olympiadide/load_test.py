# SPDX-License-Identifier: AGPL-3.0-or-later
"""No network/DB tests for the opt-in disposable load harness."""
import copy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

MODULE = Path(__file__).resolve().parents[4] / 'olympiad_ide' / 'tools' / 'cms_load.py'
spec = importlib.util.spec_from_file_location('cms_load_under_test', MODULE)
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


class LoadValidationTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix='cms-load-validation-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.target = {'schemaVersion':1, 'disposable':True, 'targetId':str(uuid4()),
            'origin':'https://localhost:18443', 'contestId':1, 'contestName':'ide-load-unit', 'installationId':str(uuid4())}
        self.credentials = [{'username':'generated-user', 'password':'unit-only-value', 'taskId':1}]
        self.scenario = {'name':'context_read', 'participants':1, 'iterations':2, 'concurrency':1,
                         'ratePerSecond':5, 'rampSeconds':0, 'durationSeconds':5, 'timeoutSeconds':1}
        self.plan = {'schemaVersion':1, 'scenarios':[self.scenario]}
        self.options = SimpleNamespace(confirm_disposable=self.target['targetId'], allow_remote_disposable=False,
                                       allow_official_submissions=False, allow_custom_runs=False)

    def fixture(self, value):
        path = self.root/'request.json'
        path.write_text(json.dumps(value))
        return str(path)

    def test_validate_read_only_plan_has_no_network(self):
        with patch.object(load.requests, 'Session', side_effect=AssertionError('Network must not be used')):
            result = load.validate(self.target, self.credentials, self.plan, self.options)
        self.assertEqual(result['participants'], 1)
        self.assertEqual(result['maximumHttpRequests'], 9)

    def test_disposable_confirmation_scope_and_tls_required(self):
        for field, value in [('disposable',False), ('origin','http://localhost:18443'), ('origin','https://example.org'),
                             ('contestName','live-contest'), ('targetId',str(uuid4()))]:
            target = dict(self.target, **{field:value})
            with self.subTest(field=field, value=value), self.assertRaises(load.Invalid):
                load.validate(target, self.credentials, copy.deepcopy(self.plan), self.options)

    def test_limits_distinct_participants_and_request_budget(self):
        for field, value in [('participants',351), ('concurrency',2), ('ratePerSecond',1001),
                             ('durationSeconds',3601), ('timeoutSeconds',31), ('iterations',10001), ('rampSeconds',10)]:
            plan = copy.deepcopy(self.plan); plan['scenarios'][0][field] = value
            with self.subTest(field=field), self.assertRaises(load.Invalid):
                load.validate(self.target, self.credentials, plan, self.options)
        with self.assertRaises(load.Invalid):
            load.validate(self.target, self.credentials*2, self.plan, self.options)

    def test_official_and_execution_need_separate_explicit_optins(self):
        for scenario, path, option in [('official_submissions','/ide/api/submissions','allow_official_submissions'),
                                      ('custom_runs','/ide/api/runtime/v1/executions','allow_custom_runs')]:
            self.scenario.update(name=scenario, requestsFile=self.fixture({'schemaVersion':1,
                'steps':[{'method':'POST','path':path,'json':{},'expect':[201]}]}))
            with self.assertRaises(load.Invalid):
                load.validate(self.target, self.credentials, copy.deepcopy(self.plan), self.options)
            setattr(self.options, option, True)
            load.validate(self.target, self.credentials, copy.deepcopy(self.plan), self.options)

    def test_routes_reject_admin_external_traversal_and_wrong_category(self):
        for path in ['https://example.org/ide/api/context', '//example.org/', '/admin', '/ide/api/runtime/v1/../admin',
                     '/ide/api/runtime/v1/%2e%2e/admin', '/ide/api/runtime/v1/rpc']:
            with self.subTest(path=path), self.assertRaises(load.Invalid):
                load.category('POST', path)
        self.scenario.update(name='autosave', requestsFile=self.fixture({'schemaVersion':1,
            'steps':[{'method':'POST','path':'/ide/api/submissions'}]}))
        self.options.allow_official_submissions = True
        with self.assertRaises(load.Invalid):
            load.validate(self.target, self.credentials, self.plan, self.options)

    def test_external_credentials_private_mode_and_fixture_render_types(self):
        path = self.root/'credentials.json'; path.write_text(json.dumps(self.credentials)); path.chmod(0o644)
        with self.assertRaises(load.Invalid): load.read_json(path, private=True)
        path.chmod(0o600)
        self.assertEqual(load.read_json(path, private=True), self.credentials)
        rendered = load.render({'taskId':'{{taskId}}','content':'exact Ω\r\n','path':'/x/{{id}}'}, {'taskId':7,'id':'abc'})
        self.assertEqual(rendered, {'taskId':7,'content':'exact Ω\r\n','path':'/x/abc'})
        with self.assertRaises(load.Invalid): load.render('{{missing}}', {})

    def test_context_cannot_switch_identity_contest_or_task(self):
        actor = load.Actor(0, self.credentials[0], self.target)
        context = {'schemaVersion':1,'identity':{'installationId':self.target['installationId'],'contestId':'1','principalId':str(uuid4())},
            'contest':{'name':'ide-load-unit'},'user':{'username':'generated-user'},'csrfToken':'test-token','tasks':[{'id':1}]}
        actor.context_check(context)
        actor.context = None  # A fresh cookie jar must not reset the trusted principal.
        for update in ({'identity':dict(context['identity'],principalId=str(uuid4()))}, {'contest':{'name':'live'}}, {'tasks':[]}):
            with self.assertRaises(load.Invalid): actor.context_check(dict(context, **update))

    def test_statistics_do_not_invent_missing_server_metrics(self):
        measure = load.Measurements(self.scenario)
        measure.requests = [{'status':200,'ms':10,'bytes':7,'error':None,'officialUnknown':False},
                            {'status':None,'ms':30,'bytes':0,'error':'ReadTimeout','officialUnknown':True}]
        measure.operations = [{'ok':True,'ms':10},{'ok':False,'ms':30}]
        value = measure.report()
        self.assertEqual(value['httpLatencyMs']['p50'],20)
        self.assertEqual(value['failedOperations'],1)
        self.assertEqual(value['officialOutcomeUnknown'],1)
        for key in ('databaseConnections','queueAgeSeconds','storageGrowthBytes','serverCpuPercent','serverMemoryBytes'):
            self.assertIsNone(value[key])

    def test_validate_only_cli_writes_no_credentials_and_performs_no_http(self):
        paths = {}
        for name,value in [('target',self.target),('credentials',self.credentials),('plan',self.plan)]:
            paths[name] = self.root/(name+'.json'); paths[name].write_text(json.dumps(value)); paths[name].chmod(0o600)
        report = self.root/'report.json'
        arguments = [item for name,path in paths.items() for item in ('--'+name,str(path))]
        arguments += ['--report',str(report),'--confirm-disposable',self.target['targetId'],'--validate-only']
        with patch.object(load.requests, 'Session', side_effect=AssertionError('No network')):
            self.assertEqual(load.main(arguments),0)
        data = report.read_text()
        self.assertNotIn('unit-only-value', data)
        self.assertNotIn('generated-user', data)
        self.assertEqual(json.loads(data)['execution'],'validation_only')
        self.assertEqual(json.loads(data)['scenarios'],[])


if __name__ == '__main__':
    unittest.main()
