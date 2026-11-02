# SPDX-License-Identifier: AGPL-3.0-or-later

"""Ingress bounds and explicitly trusted client-address handling."""
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.wrappers import Response


class IngressBoundary:
    def __init__(self, app, settings):
        self.app = app
        self.trusted = set(settings.olympiad_ide_trusted_proxy_addresses)
        self.hops = settings.olympiad_ide_num_proxies
        self.proxied = ProxyFix(app, x_for=self.hops, x_proto=self.hops, x_host=0, x_port=0, x_prefix=0) if self.hops else app
        self.max_body = settings.olympiad_ide_max_body_bytes

    def __call__(self, environ, start_response):
        try:
            size = int(environ.get("CONTENT_LENGTH") or 0)
            if size < 0:
                raise ValueError()
        except ValueError:
            return Response("Invalid content length", status=400)(environ, start_response)
        if size > self.max_body:
            return Response("Request too large", status=413)(environ, start_response)
        if environ.get("HTTP_TRANSFER_ENCODING"):
            return Response("A bounded Content-Length is required", status=411)(environ, start_response)
        peer = environ.get("REMOTE_ADDR")
        if peer in self.trusted and self.hops:
            return self.proxied(environ, start_response)
        # An untrusted direct client cannot manufacture its CMS IP/protocol.
        for name in ("HTTP_X_FORWARDED_FOR", "HTTP_X_FORWARDED_PROTO", "HTTP_X_FORWARDED_HOST", "HTTP_X_FORWARDED_PORT", "HTTP_FORWARDED"):
            environ.pop(name, None)
        return self.app(environ, start_response)
