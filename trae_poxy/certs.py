"""
@Project: AI Poxy Tools
@File: certs.py
@Description: X.509 certificate generation — Root CA and per-host leaf certificates with SAN.
@Author: 颖馨瑶 (Ying Xinyao)
@Contact: admin@loserrc.com | QQ: 1129414920
@Date: 2026-02-25
@Version: v1.2.2
@Copyright: (c) 2026 Ying Xinyao. All rights reserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class CertPaths:
    ca_cert: Path
    ca_key: Path
    certs_dir: Path
    hosts: list[str]


def _write_pem(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _build_ca() -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Trae-Poxy"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Trae-Poxy Local CA"),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return cert, key


def _build_leaf(
    ca_cert: x509.Certificate, ca_key: rsa.RSAPrivateKey, host: str
) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Trae-Poxy"),
            x509.NameAttribute(NameOID.COMMON_NAME, host),
        ]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return cert, key


def _leaf_paths(certs_dir: Path, host: str) -> tuple[Path, Path]:
    certs_dir.mkdir(parents=True, exist_ok=True)
    return certs_dir / f"{host}.pem", certs_dir / f"{host}.key"


def ensure_certs(paths: CertPaths) -> None:
    if paths.ca_cert.exists() and paths.ca_key.exists():
        ca_cert = x509.load_pem_x509_certificate(paths.ca_cert.read_bytes())
        ca_key = serialization.load_pem_private_key(
            paths.ca_key.read_bytes(), password=None
        )
    else:
        ca_cert, ca_key = _build_ca()
        _write_pem(paths.ca_cert, ca_cert.public_bytes(serialization.Encoding.PEM))
        _write_pem(
            paths.ca_key,
            ca_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ),
        )

    for host in paths.hosts:
        leaf_cert_path, leaf_key_path = _leaf_paths(paths.certs_dir, host)
        if leaf_cert_path.exists() and leaf_key_path.exists():
            continue
        leaf_cert, leaf_key = _build_leaf(ca_cert, ca_key, host)
        _write_pem(
            leaf_cert_path, leaf_cert.public_bytes(serialization.Encoding.PEM)
        )
        _write_pem(
            leaf_key_path,
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ),
        )


def get_leaf_paths(certs_dir: Path, host: str) -> tuple[Path, Path]:
    return _leaf_paths(certs_dir, host)
