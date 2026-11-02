# SPDX-License-Identifier: AGPL-3.0-or-later

"""No-network tests for destructive smoke-test target selection and restoration."""
import unittest
from unittest.mock import patch

from psycopg2 import sql
from cmstestsuite.olympiadide_smoke_safety import database_unavailable, validate_outage_urls


class DatabaseOutageSafetyTest(unittest.TestCase):
    cms = "postgresql+psycopg2://fixture@127.0.0.1:55459/cmsfortesting"
    runtime = "postgresql+psycopg://fixture@127.0.0.1:55459/idefortesting"

    def test_only_distinct_disposable_databases_on_one_loopback_cluster_allowed(self):
        urls = validate_outage_urls(self.cms, self.runtime)
        self.assertEqual([url.database for url in urls], ["cmsfortesting", "idefortesting"])
        for invalid in (self.cms, self.runtime.replace("127.0.0.1", "example.org"),
                        self.runtime.replace("idefortesting", "production"),
                        self.runtime.replace("55459", "55460"),
                        self.runtime.replace("fixture@", "other@"),
                        self.runtime + "?host=example.org"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_outage_urls(self.cms, invalid)

    @patch("psycopg2.connect")
    def test_exception_restores_target_and_termination_is_database_scoped(self, connect):
        admin = connect.return_value
        cursor = admin.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (True, False, True)
        target = validate_outage_urls(self.cms, self.runtime)[0]
        with self.assertRaisesRegex(RuntimeError, "test interruption"):
            with database_unavailable(target):
                raise RuntimeError("test interruption")
        calls = cursor.execute.call_args_list
        alter = [call.args[0] for call in calls if isinstance(call.args[0], sql.Composed)]
        self.assertEqual(len(alter), 2)
        self.assertEqual(alter[0].seq, [sql.SQL("ALTER DATABASE "), sql.Identifier("cmsfortesting"), sql.SQL(" ALLOW_CONNECTIONS false")])
        self.assertEqual(alter[1].seq, [sql.SQL("ALTER DATABASE "), sql.Identifier("cmsfortesting"), sql.SQL(" ALLOW_CONNECTIONS true")])
        termination = [call for call in calls if isinstance(call.args[0], str) and "pg_terminate_backend" in call.args[0]]
        self.assertEqual(len(termination), 1)
        self.assertIn("WHERE datname = %s AND pid <> pg_backend_pid()", termination[0].args[0])
        self.assertEqual(termination[0].args[1], ("cmsfortesting",))
        admin.close.assert_called_once()

    @patch("psycopg2.connect")
    def test_unowned_or_already_disabled_database_is_never_altered(self, connect):
        target = validate_outage_urls(self.cms, self.runtime)[0]
        for state in (None, (False, False, True), (True, True, True), (True, False, False)):
            connect.reset_mock()
            cursor = connect.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = state
            with self.subTest(state=state), self.assertRaises(ValueError):
                with database_unavailable(target):
                    self.fail("unsafe target entered")
            self.assertFalse(any(isinstance(call.args[0], sql.Composed) for call in cursor.execute.call_args_list))
