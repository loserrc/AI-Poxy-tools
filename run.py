"""
@Project: AI Poxy Tools
@File: run.py
@Description: CLI entry point — init (certs/config), serve (proxy), and print-hosts commands.
@Author: 颖馨瑶 (Ying Xinyao)
@Contact: admin@loserrc.com | QQ: 1129414920
@Date: 2026-02-25
@Version: v1.2.2
@Copyright: (c) 2026 Ying Xinyao. All rights reserved.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from trae_poxy.certs import CertPaths, ensure_certs
from trae_poxy.config import load_config, save_default_config
from trae_poxy.server import run_server


def _build_cert_paths(config) -> CertPaths:
    return CertPaths(
        ca_cert=Path(config.ca_cert_path),
        ca_key=Path(config.ca_key_path),
        certs_dir=Path(config.certs_dir),
        hosts=config.intercept_hosts,
    )


def cmd_init() -> None:
    save_default_config()
    config = load_config()
    ensure_certs(_build_cert_paths(config))
    print("OK: config.json and certs are ready.")


def cmd_serve() -> None:
    config = load_config()
    ensure_certs(_build_cert_paths(config))
    handlers = [logging.StreamHandler()]
    if config.log_file:
        log_path = Path(config.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    run_server(config)


def cmd_print_hosts() -> None:
    config = load_config()
    for host in config.intercept_hosts:
        print(f"127.0.0.1 {host}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Poxy Tools local HTTPS rewriter.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Generate local CA and leaf certs.")
    sub.add_parser("serve", help="Start local HTTPS server.")
    sub.add_parser("print-hosts", help="Print hosts entry.")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init()
    elif args.command == "serve":
        cmd_serve()
    elif args.command == "print-hosts":
        cmd_print_hosts()


if __name__ == "__main__":
    main()
