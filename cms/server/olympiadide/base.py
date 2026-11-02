# SPDX-License-Identifier: AGPL-3.0-or-later

"""CMS participant authentication and stable IDE scope boundary."""
import json
import logging
from uuid import NAMESPACE_URL, uuid5

try:
    import tornado4.web as tornado_web
except ImportError:
    import tornado.web as tornado_web

from cms import config
from cms.server.contest.handlers.contest import ContestHandler

logger = logging.getLogger(__name__)


def identity_for(participation, installation_id):
    scope = [str(installation_id), str(participation.user_id),
             str(participation.contest_id), str(participation.id)]
    principal = str(uuid5(NAMESPACE_URL, json.dumps(scope, separators=(",", ":"), ensure_ascii=True)))
    return dict(zip(("installationId", "userId", "contestId", "participationId"), scope), principalId=principal)


class IDEAPIHandler(ContestHandler):
    # Background persistence/telemetry/polling must not turn CMS's idle cookie
    # timeout into a permanently refreshed session.
    refresh_cookie = False
    requires_principal = True

    def prepare(self):
        super().prepare()
        self.set_header("Cache-Control", "no-store, private")
        self.set_header("X-Content-Type-Options", "nosniff")
        if self.contest is None:
            raise tornado_web.HTTPError(404, reason="contest_unavailable")
        if self.current_user is None:
            raise tornado_web.HTTPError(401, reason="authentication_required")
        self.ide_identity = identity_for(self.current_user, config.olympiad_ide_installation_id)
        if self.requires_principal:
            self.ensure_expected_principal()

    def principal(self):
        return self.ide_identity

    def ensure_expected_principal(self):
        if self.request.headers.get("X-Olympiad-Principal") != self.ide_identity["principalId"]:
            raise tornado_web.HTTPError(409, reason="identity_changed")

    def get_login_url(self):
        return config.olympiad_ide_cws_base_path

    def write_json(self, value, status=200):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=UTF-8")
        self.finish(json.dumps(value, ensure_ascii=True, separators=(",", ":")))

    def write_error(self, status_code, **kwargs):
        error = kwargs.get("exc_info", (None, None, None))[1]
        code = getattr(error, "reason", None) or "request_failed"
        if status_code >= 500:
            code = "service_unavailable"
            logger.error("IDE request failed (%s)", type(error).__name__)
        messages = {
            "authentication_required": "Sign in through CMS to resume server operations.",
            "identity_changed": "CMS identity changed; pending work remains bound to its original participant.",
            "service_unavailable": "The CMS operation is temporarily unavailable.",
        }
        self.set_header("Cache-Control", "no-store, private")
        self.write_json({"schemaVersion": 1, "error": {"code": code, "message": messages.get(code, "Request could not be completed.")},
                         "links": {"login": config.olympiad_ide_cws_base_path, "fallback": config.olympiad_ide_cws_base_path}}, status_code)
