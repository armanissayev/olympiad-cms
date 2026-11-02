# SPDX-License-Identifier: AGPL-3.0-or-later

"""Safety guards for opt-in fault injection into owned disposable databases."""
from contextlib import contextmanager


def validate_outage_urls(cms_url, runtime_url):
    """Reject non-disposable, remote or shared targets before any SQL mutation."""
    from sqlalchemy.engine.url import make_url
    urls = [make_url(str(value)) for value in (cms_url, runtime_url)]
    for url in urls:
        if (url.get_backend_name() != "postgresql" or url.host not in ("127.0.0.1", "::1")
                or not url.port or not url.database or not url.database.endswith("fortesting")
                or not url.username or url.query):
            raise ValueError("Database outage targets must be explicit disposable loopback PostgreSQL databases ending fortesting")
    if urls[0].database == urls[1].database:
        raise ValueError("CMS and runtime outage targets must be separate databases")
    if (urls[0].host, urls[0].port, urls[0].username) != (urls[1].host, urls[1].port, urls[1].username):
        raise ValueError("Outage targets must use the same isolated cluster and owner")
    return urls


@contextmanager
def database_unavailable(url):
    """Temporarily disable only one validated fixture database; always reenable."""
    import psycopg2
    from psycopg2 import sql
    admin = psycopg2.connect(dbname="postgres", host=url.host, port=url.port,
                            user=url.username, password=url.password, connect_timeout=3)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute("SELECT datallowconn, datistemplate, pg_get_userbyid(datdba) = current_user FROM pg_database WHERE datname = %s", (url.database,))
            if cursor.fetchone() != (True, False, True):
                raise ValueError("Outage target must be an available non-template database owned by the fixture role")
            identifier = sql.Identifier(url.database)
            cursor.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS false").format(identifier))
            try:
                cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (url.database,))
                yield
            finally:
                cursor.execute(sql.SQL("ALTER DATABASE {} ALLOW_CONNECTIONS true").format(identifier))
    finally:
        admin.close()
