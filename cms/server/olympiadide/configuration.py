# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fail-closed startup validation for the optional native service."""
import ipaddress
from pathlib import Path
import stat
from urllib.parse import urlsplit
from uuid import UUID

from cms import ConfigError, ServiceCoord


def _loopback(value):
    try:
        return value == "localhost" or ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def validate_configuration(settings, shard, contest_id):
    if settings.olympiad_ide_enabled is not True:
        raise ConfigError("Olympiad IDE is disabled")
    if settings.secret_key == settings.secret_key_default:
        raise ConfigError("Olympiad IDE requires a non-default CMS secret_key")
    if type(contest_id) is not int or contest_id <= 0:
        raise ConfigError("Olympiad IDE requires one explicit contest (-c ID); ALL is unsupported")
    if type(shard) is not int or shard < 0:
        raise ConfigError("Olympiad IDE shard must be a nonnegative integer")
    try:
        if str(UUID(settings.olympiad_ide_installation_id)) != settings.olympiad_ide_installation_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ConfigError("olympiad_ide_installation_id must be a stable installation UUID")
    addresses = settings.olympiad_ide_listen_address
    ports = settings.olympiad_ide_listen_port
    if not isinstance(addresses, list) or not isinstance(ports, list) or len(addresses) != len(ports):
        raise ConfigError("Olympiad IDE HTTP address/port lists must have equal length")
    if shard >= len(ports):
        raise ConfigError("Olympiad IDE HTTP shard address/port is missing")
    if any(not _loopback(a) for a in addresses):
        raise ConfigError("Olympiad IDE HTTP listeners must be loopback; expose only through HTTPS ingress")
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in ports) or len(set(ports)) != len(ports):
        raise ConfigError("Olympiad IDE HTTP ports must be distinct unprivileged ports")
    coordinates = settings.async_config.core_services
    rpc_bindings = set()
    for index in range(len(ports)):
        rpc = coordinates.get(ServiceCoord("OlympiadIDEService", index))
        if rpc is None or not _loopback(rpc.ip):
            raise ConfigError("Each Olympiad IDE shard needs a loopback core_services RPC address")
        if (rpc.ip, rpc.port) in rpc_bindings:
            raise ConfigError("Olympiad IDE RPC shard addresses must be distinct")
        rpc_bindings.add((rpc.ip, rpc.port))
        if rpc.port in ports:
            raise ConfigError("Olympiad IDE RPC and HTTP ports must differ")
    runtime = urlsplit(settings.olympiad_ide_runtime_url)
    if runtime.scheme != "http" or not _loopback(runtime.hostname or "") or runtime.username or runtime.password or runtime.query or runtime.fragment or runtime.path not in ("", "/"):
        raise ConfigError("Olympiad IDE private runtime must be a loopback HTTP origin without credentials or path")
    try:
        if runtime.port is None or not 1024 <= runtime.port <= 65535:
            raise ValueError()
    except ValueError:
        raise ConfigError("Olympiad IDE private runtime needs an explicit unprivileged port")
    if runtime.port in ports:
        raise ConfigError("Olympiad IDE private runtime and HTTP ports must differ")
    key_path = Path(settings.olympiad_ide_signing_key_file)
    try:
        metadata = key_path.stat()
        if key_path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077 or not 32 <= metadata.st_size <= 4096:
            raise ValueError()
        with key_path.open("rb") as secret:
            if len(secret.read(4097).strip()) < 32:
                raise ValueError()
    except (OSError, ValueError):
        raise ConfigError("Olympiad IDE signing key must be a readable private file containing at least 32 bytes")
    for name, lower, upper in (
        ("request_timeout", 1, 30), ("max_body_bytes", 100_000, 16_000_000),
        ("max_response_bytes", 100_000, 32_000_000), ("max_runtime_requests", 1, 64),
        ("max_http_connections", 2, 1024), ("num_proxies", 0, 4),
        ("restart_limit", 1, 20), ("restart_window", 60, 3600),
    ):
        value = getattr(settings, "olympiad_ide_" + name)
        if type(value) is not int or not lower <= value <= upper:
            raise ConfigError("Invalid olympiad_ide_" + name)
    if settings.olympiad_ide_max_runtime_requests >= settings.olympiad_ide_max_http_connections:
        raise ConfigError("Reserve HTTP capacity for native CMS operations beyond the runtime pool")
    if not isinstance(settings.olympiad_ide_trusted_proxy_addresses, list):
        raise ConfigError("Trusted proxy addresses must be a list")
    try:
        for value in settings.olympiad_ide_trusted_proxy_addresses:
            ipaddress.ip_address(value)
    except (ValueError, TypeError):
        raise ConfigError("Trusted proxy addresses must be literal IP addresses")
    if settings.olympiad_ide_num_proxies and not settings.olympiad_ide_trusted_proxy_addresses:
        raise ConfigError("Forwarded addresses require explicitly trusted proxy addresses")
    cws = settings.olympiad_ide_cws_base_path
    if not isinstance(cws, str) or not cws.startswith("/") or cws.startswith("//") or any(x in cws for x in ("?", "#", "\\", "..")):
        raise ConfigError("CWS fallback must be a same-origin absolute path")
    assets = Path(settings.olympiad_ide_assets_path or Path(__file__).with_name("static"))
    if not (assets / "index.html").is_file():
        raise ConfigError("Olympiad IDE frontend assets missing; run the opt-in production build/install")
    return addresses[shard], ports[shard], str(assets.resolve())
