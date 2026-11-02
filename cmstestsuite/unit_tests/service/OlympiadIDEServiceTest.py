# SPDX-License-Identifier: AGPL-3.0-or-later

"""Native IDE configuration, lifecycle and identity boundaries (no sandbox execution)."""
from collections import defaultdict, deque
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest
from unittest.mock import Mock, patch

from werkzeug.test import Client
from werkzeug.wrappers import Response

from cms import Address, ConfigError, ServiceCoord, config
from cms.conf import Config
from cms.server.olympiadide.base import IDEAPIHandler, identity_for
from cms.server.olympiadide.configuration import validate_configuration
from cms.server.olympiadide.middleware import IngressBoundary
from cms.service.ResourceService import ProcessMatcher, ResourceService


class ConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        (directory / 'index.html').write_text('<html></html>')
        key = directory / 'assertion.key'
        key.write_text('test-key-only-' * 4)
        key.chmod(0o600)
        self.settings = SimpleNamespace(**vars(config))
        self.settings.olympiad_ide_enabled = True
        self.settings.olympiad_ide_installation_id = '68a65c90-95da-4930-ae83-b209dd0656c9'
        self.settings.secret_key = '12' * 16
        self.settings.olympiad_ide_signing_key_file = str(key)
        self.settings.olympiad_ide_assets_path = str(directory)
        self.settings.async_config = SimpleNamespace(core_services={
            ServiceCoord('OlympiadIDEService', 0): Address('127.0.0.1', 21991),
        })

    def test_enabled_shard_has_separate_private_http_and_rpc(self):
        address, port, assets = validate_configuration(self.settings, 0, 1)
        self.assertEqual(address, '127.0.0.1')
        self.assertEqual(port, 8891)
        self.assertTrue(Path(assets, 'index.html').is_file())

    def test_two_shards_use_separate_http_and_rpc_bindings(self):
        self.settings.olympiad_ide_listen_address = ['127.0.0.1', '127.0.0.1']
        self.settings.olympiad_ide_listen_port = [8891, 8892]
        self.settings.async_config.core_services[ServiceCoord('OlympiadIDEService', 1)] = Address('127.0.0.1', 21992)
        self.assertEqual(validate_configuration(self.settings, 1, 1)[1], 8892)
        self.settings.async_config.core_services[ServiceCoord('OlympiadIDEService', 1)] = Address('127.0.0.1', 21991)
        with self.assertRaises(ConfigError):
            validate_configuration(self.settings, 1, 1)

    def test_disabled_all_and_missing_shard_fail_closed(self):
        for contest, shard in [(None, 0), (1, 1), (-1, 0)]:
            with self.assertRaises(ConfigError):
                validate_configuration(self.settings, shard, contest)
        self.settings.olympiad_ide_enabled = False
        with self.assertRaises(ConfigError):
            validate_configuration(self.settings, 0, 1)

    def test_public_or_conflicting_bindings_and_ssrf_origins_rejected(self):
        for value in ['0.0.0.0', '192.0.2.1', '']:
            self.settings.olympiad_ide_listen_address = [value]
            with self.assertRaises(ConfigError):
                validate_configuration(self.settings, 0, 1)
        self.settings.olympiad_ide_listen_address = ['127.0.0.1']
        for value in ['http://example.test:8801', 'http://user:pass@127.0.0.1:8801', 'http://127.0.0.1:8801/path', 'http://127.0.0.1:8891']:
            self.settings.olympiad_ide_runtime_url = value
            with self.assertRaises(ConfigError):
                validate_configuration(self.settings, 0, 1)

    def test_public_secret_and_default_cms_signing_key_rejected(self):
        key = Path(self.settings.olympiad_ide_signing_key_file)
        key.chmod(0o644)
        with self.assertRaises(ConfigError):
            validate_configuration(self.settings, 0, 1)
        key.chmod(0o600)
        self.settings.secret_key = self.settings.secret_key_default
        with self.assertRaises(ConfigError):
            validate_configuration(self.settings, 0, 1)

    def test_runtime_pool_reserves_native_admission_capacity(self):
        self.settings.olympiad_ide_max_http_connections = 16
        with self.assertRaises(ConfigError):
            validate_configuration(self.settings, 0, 1)

    def test_disabled_service_is_not_discovered_by_checker_or_resources(self):
        path = Path(self.temp.name, 'cms.json')
        for enabled in (False, True):
            path.write_text(json.dumps({'core_services': {'OlympiadIDEService': [['127.0.0.1', 21991]]},
                                        'other_services': {}, 'olympiad_ide_enabled': enabled}))
            isolated = object.__new__(Config)
            isolated.async_config = SimpleNamespace(core_services={}, other_services={})
            self.assertTrue(isolated._load_unique(str(path)))
            self.assertEqual(bool(isolated.async_config.core_services), enabled)


class IdentityAndIngressTest(unittest.TestCase):
    def test_principal_survives_username_change_and_separates_contests(self):
        participation = SimpleNamespace(user_id=1, contest_id=2, id=3, username='before')
        first = identity_for(participation, 'installation')
        participation.username = 'after'
        self.assertEqual(identity_for(participation, 'installation'), first)
        participation.contest_id = 4
        self.assertNotEqual(identity_for(participation, 'installation')['principalId'], first['principalId'])
        self.assertNotEqual(identity_for(participation, 'other-installation')['principalId'], first['principalId'])

    def test_account_switch_or_missing_scope_rejected(self):
        target = SimpleNamespace(ide_identity={'principalId': 'old'}, request=SimpleNamespace(headers={}))
        with self.assertRaises(Exception) as caught:
            IDEAPIHandler.ensure_expected_principal(target)
        self.assertEqual(caught.exception.status_code, 409)
        target.request.headers['X-Olympiad-Principal'] = 'new'
        with self.assertRaises(Exception):
            IDEAPIHandler.ensure_expected_principal(target)
        target.request.headers['X-Olympiad-Principal'] = 'old'
        IDEAPIHandler.ensure_expected_principal(target)

    def client(self):
        settings = SimpleNamespace(olympiad_ide_trusted_proxy_addresses=['127.0.0.1'],
                                   olympiad_ide_num_proxies=1, olympiad_ide_max_body_bytes=100)
        def app(environ, start_response):
            return Response(json.dumps({'ip': environ['REMOTE_ADDR'], 'scheme': environ['wsgi.url_scheme'],
                                        'forwarded': environ.get('HTTP_X_FORWARDED_FOR')}), content_type='application/json')(environ, start_response)
        return Client(IngressBoundary(app, settings), Response)

    def test_forwarded_ip_only_from_explicit_trusted_peer(self):
        client = self.client()
        headers = {'X-Forwarded-For': '192.0.2.2', 'X-Forwarded-Proto': 'https'}
        response = client.get('/', headers=headers, environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
        self.assertEqual(json.loads(response.data)['ip'], '192.0.2.2')
        response = client.get('/', headers=headers, environ_overrides={'REMOTE_ADDR': '192.0.2.5'})
        value = json.loads(response.data)
        self.assertEqual(value['ip'], '192.0.2.5')
        self.assertEqual(value['scheme'], 'http')
        self.assertIsNone(value['forwarded'])

    def test_ingress_rejects_unbounded_or_oversize_body(self):
        self.assertEqual(self.client().post('/', data='x' * 101).status_code, 413)
        self.assertEqual(self.client().post('/', headers={'Transfer-Encoding': 'chunked'}).status_code, 411)


class LifecycleTest(unittest.TestCase):
    def service(self):
        service = object.__new__(ResourceService)
        coord = ServiceCoord('OlympiadIDEService', 0)
        service.contest_id = 7
        service.autorestart = True
        service._local_services = [coord]
        service._launched_processes = set()
        service._will_restart = {coord: True}
        service._procs = {coord: None}
        service._services_prev_cpu_times = {}
        service._ide_restart_attempts = defaultdict(deque)
        service._ide_next_restart = {}
        return service, coord

    def test_installed_launcher_recognized_with_shard_and_contest(self):
        with patch('cms.service.ResourceService.BIN_PATH', '/opt/cms/bin'):
            self.assertEqual(ProcessMatcher._is_interesting_command_line(
                ['/opt/cms/bin/python3', '/opt/cms/bin/cmsOlympiadIDEService', '2', '-c', '7']), ('OlympiadIDEService', 2))

    @patch('cms.service.ResourceService.subprocess.Popen')
    @patch('cms.service.ResourceService.ProcessMatcher.find', return_value=None)
    def test_restart_storm_is_bounded_and_can_be_explicitly_reenabled(self, find, popen):
        service, coord = self.service()
        popen.return_value.poll.return_value = 1
        with patch('cms.service.ResourceService.BIN_PATH', '/opt/cms/bin'):
            for now in (0, 5, 15, 35, 75, 135):
                with patch('cms.service.ResourceService.time.monotonic', return_value=now):
                    service._restart_services()
        self.assertEqual(popen.call_count, 5)
        self.assertEqual(popen.call_args[0][0], ['/opt/cms/bin/cmsOlympiadIDEService', '0', '-c', '7'])
        self.assertFalse(service._will_restart[coord])
        self.assertTrue(service.toggle_autorestart('OlympiadIDEService,0'))
        self.assertEqual(len(service._ide_restart_attempts[coord]), 0)

    def test_first_stop_waits_for_async_rpc_connection(self):
        service, _coord = self.service()
        remote = SimpleNamespace(connected=False, quit=Mock())
        remote.quit.return_value.get.return_value = None
        with patch.object(service, 'connect_to', return_value=remote), patch('cms.service.ResourceService.sleep', side_effect=lambda _: setattr(remote, 'connected', True)):
            service.kill_service('OlympiadIDEService,0')
        remote.quit.assert_called_once_with(reason='Asked by ResourceService')
        remote.quit.return_value.get.assert_called_once_with(timeout=5)

    def test_unavailable_stop_connection_is_bounded(self):
        service, _coord = self.service()
        remote = SimpleNamespace(connected=False, quit=Mock())
        with patch.object(service, 'connect_to', return_value=remote), patch('cms.service.ResourceService.time.monotonic', side_effect=[0,4]):
            self.assertFalse(service.kill_service('OlympiadIDEService,0'))
        remote.quit.assert_not_called()

    @patch('cms.service.ResourceService.subprocess.Popen')
    @patch('cms.service.ResourceService.ProcessMatcher.find')
    def test_duplicate_start_and_intentional_stop_prevent_spawn(self, find, popen):
        service, coord = self.service()
        find.return_value.is_running.return_value = True
        service._restart_services()
        popen.assert_not_called()
        service._will_restart[coord] = False
        service._procs[coord] = None
        find.return_value = None
        service._restart_services()
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
