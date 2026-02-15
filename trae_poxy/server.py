from __future__ import annotations

import ssl
from pathlib import Path

from aiohttp import web

from .config import Config
from .certs import get_leaf_paths
from .proxy import create_app


def _build_ssl_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    return context


def run_server(config: Config) -> None:
    app = create_app(config)
    certs_dir = Path(config.certs_dir)
    default_host = config.intercept_hosts[0]
    default_cert, default_key = get_leaf_paths(certs_dir, default_host)
    ssl_context = _build_ssl_context(default_cert, default_key)
    host_contexts: dict[str, ssl.SSLContext] = {}
    for host in config.intercept_hosts:
        cert_path, key_path = get_leaf_paths(certs_dir, host)
        host_contexts[host] = _build_ssl_context(cert_path, key_path)

    def _sni_callback(sslobj: ssl.SSLObject, servername: str, _ctx: ssl.SSLContext) -> None:
        if not servername:
            return
        target = host_contexts.get(servername)
        if target:
            sslobj.context = target

    ssl_context.set_servername_callback(_sni_callback)
    web.run_app(
        app,
        host=config.listen_host,
        port=config.listen_port,
        ssl_context=ssl_context,
    )
