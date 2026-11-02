# SPDX-License-Identifier: AGPL-3.0-or-later
"""Real PostgreSQL recovery of an idle pooled CMS connection."""
import unittest
import psycopg2
from cmstestsuite.unit_tests.databasemixin import DatabaseMixin
from cms.db import engine


class TestIdleConnectionRecovery(DatabaseMixin, unittest.TestCase):
    def test_killed_idle_connection_is_replaced_before_request(self):
        with engine.connect() as connection:
            original_pid = connection.execute("SELECT pg_backend_pid()").scalar()
        arguments = engine.url.translate_connect_args(username="user", database="dbname")
        arguments.update(engine.url.query)
        control = psycopg2.connect(**arguments)
        control.autocommit = True
        try:
            with control.cursor() as cursor:
                cursor.execute("SELECT pg_terminate_backend(%s)", (original_pid,))
                self.assertTrue(cursor.fetchone()[0])
            # This is a fresh operation after checkout, not an automatic retry
            # of any transaction that was in flight when PostgreSQL went away.
            with engine.connect() as recovered:
                self.assertNotEqual(recovered.execute("SELECT pg_backend_pid()").scalar(), original_pid)
                self.assertEqual(recovered.execute("SELECT 42").scalar(), 42)
        finally:
            control.close()
            engine.dispose()
