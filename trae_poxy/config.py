from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "listen_host": "127.0.0.1",
    "listen_port": 8443,
    "default_upstream": "https://newapi.loserrc.com",
    "upstream_map": {},
    "verify_upstream_ssl": True,
    "upstream_ca_bundle": "",
    "ca_cert_path": "certs/ca.pem",
    "ca_key_path": "certs/ca.key",
    "certs_dir": "certs",
    "intercept_hosts": [
        "api.openai.com",
        "api.anthropic.com",
        "generativelanguage.googleapis.com",
    ],
    "path_rewrite_map": {
        "generativelanguage.googleapis.com": [
            ["/v1beta/openai/", "/v1/"]
        ]
    },
    "log_level": "INFO",
    "log_file": "logs/trae_poxy.log",
    "preserve_host": False,
    "log_request_body": False,
    "log_response_body": False,
    "normalize_models": True,
}


@dataclass(frozen=True)
class Config:
    listen_host: str
    listen_port: int
    default_upstream: str
    upstream_map: Dict[str, str]
    verify_upstream_ssl: bool
    upstream_ca_bundle: str
    ca_cert_path: str
    ca_key_path: str
    certs_dir: str
    intercept_hosts: list[str]
    path_rewrite_map: Dict[str, list[list[str]]]
    log_level: str
    log_file: str
    preserve_host: bool
    log_request_body: bool
    log_response_body: bool
    normalize_models: bool


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    merged["listen_port"] = int(merged["listen_port"])
    merged["verify_upstream_ssl"] = bool(merged["verify_upstream_ssl"])
    if "default_upstream" not in merged and "upstream_base" in merged:
        merged["default_upstream"] = merged["upstream_base"]
    merged["default_upstream"] = str(merged["default_upstream"]).rstrip("/")
    upstream_map = merged.get("upstream_map") or {}
    merged["upstream_map"] = {
        str(k).strip(): str(v).rstrip("/") for k, v in upstream_map.items()
    }
    merged["upstream_ca_bundle"] = str(merged.get("upstream_ca_bundle") or "")
    merged["ca_cert_path"] = str(merged["ca_cert_path"])
    merged["ca_key_path"] = str(merged["ca_key_path"])
    merged["certs_dir"] = str(merged["certs_dir"])
    intercept_hosts = merged.get("intercept_hosts") or []
    merged["intercept_hosts"] = [str(host).strip() for host in intercept_hosts if host]
    rewrite_map = merged.get("path_rewrite_map") or {}
    normalized_map: Dict[str, list[list[str]]] = {}
    for host, rules in rewrite_map.items():
        if not host or not isinstance(rules, list):
            continue
        normalized_rules: list[list[str]] = []
        for rule in rules:
            if not isinstance(rule, list) or len(rule) != 2:
                continue
            src, dst = str(rule[0]), str(rule[1])
            normalized_rules.append([src, dst])
        if normalized_rules:
            normalized_map[str(host).strip()] = normalized_rules
    merged["path_rewrite_map"] = normalized_map
    merged["log_level"] = str(merged["log_level"]).upper()
    merged["log_file"] = str(merged["log_file"]) if merged.get("log_file") else ""
    merged["preserve_host"] = bool(merged["preserve_host"])
    merged["log_request_body"] = bool(merged["log_request_body"])
    merged["log_response_body"] = bool(merged["log_response_body"])
    merged["normalize_models"] = bool(merged["normalize_models"])
    return merged


def load_config(path: Path | str = "config.json") -> Config:
    config_path = Path(path)
    data: Dict[str, Any] = {}
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    normalized = _normalize(data)
    return Config(**normalized)


def save_default_config(path: Path | str = "config.json") -> None:
    config_path = Path(path)
    if config_path.exists():
        return
    config_path.write_text(
        json.dumps(DEFAULT_CONFIG, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
