# SPDX-License-Identifier: AGPL-3.0-or-later

"""Native CMS web/RPC service for the integrated Olympiad IDE."""
from pathlib import Path

from gevent.pool import Pool
try:
    import tornado4.web as tornado_web
except ImportError:
    import tornado.web as tornado_web

from cms import config, ServiceCoord
from cms.db import Contest, OlympiadIDEReceipt, SessionGen
from cms.io import WebService
from cms.locale import get_translations
from cms.server.contest.jinja2_toolbox import CWS_ENVIRONMENT
from cmscommon.binary import hex_to_bin
from .configuration import validate_configuration
from .context import ContextHandler
from .middleware import IngressBoundary


class LiveHandler(tornado_web.RequestHandler):
    def get(self):
        self.set_header("Cache-Control", "no-store")
        self.write({"schemaVersion": 1, "service": "OlympiadIDEService", "status": "alive"})


class ReadyHandler(tornado_web.RequestHandler):
    def get(self):
        self.set_header("Cache-Control", "no-store")
        try:
            with SessionGen() as session:
                ready = session.query(Contest.id).filter(Contest.id == self.application.service.contest_id).first() is not None
                session.query(OlympiadIDEReceipt.id).limit(1).all()
            ready = ready and Path(self.application.service.assets_path, "index.html").is_file()
        except Exception:
            ready = False
        self.set_status(200 if ready else 503)
        self.write({"schemaVersion": 1, "status": "ready" if ready else "unavailable", "cms": ready,
                    "runtime": "independent; check its private readiness endpoint"})


class RootHandler(tornado_web.RequestHandler):
    def get(self):
        self.redirect("/ide/", permanent=True)


class OlympiadIDEService(WebService):
    def __init__(self, shard, contest_id=None):
        address, port, assets = validate_configuration(config, shard, contest_id)
        self.contest_id = contest_id
        self.assets_path = assets
        self.translations = get_translations()
        self.jinja2_environment = CWS_ENVIRONMENT
        from .handlers import HANDLERS as submission_handlers
        from .gateway import HANDLERS as runtime_handlers
        handlers = [(r"/ide/health/live", LiveHandler), (r"/ide/health/ready", ReadyHandler),
                    (r"/ide/api/context", ContextHandler)] + submission_handlers + runtime_handlers + [
                        (r"/ide", RootHandler),
                        (r"/ide/(.*)", tornado_web.StaticFileHandler, {"path": assets, "default_filename": "index.html"}),
                    ]
        parameters = {"cookie_secret": hex_to_bin(config.secret_key), "debug": False,
                      "xsrf_cookies": True, "xsrf_cookie_kwargs": {"secure": True, "samesite": "Strict"},
                      "num_proxies_used": 0}
        super().__init__(port, handlers, parameters, shard=shard, listen_address=address)
        self.web_server.set_spawn(Pool(config.olympiad_ide_max_http_connections))
        self.wsgi_app = IngressBoundary(self.wsgi_app, config)
        self.evaluation_service = self.connect_to(ServiceCoord("EvaluationService", 0))
