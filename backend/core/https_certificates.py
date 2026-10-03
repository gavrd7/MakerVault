from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class CertificateError(RuntimeError):
    pass


def tls_root() -> Path:
    root = Path(os.getenv("MAKERVAULT_TLS_ROOT", "/app/tls"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def paths() -> dict[str, Path]:
    root = tls_root()
    return {
        "ca_cert": root / "local-ca.crt",
        "ca_key": root / "local-ca.key",
        "server_cert": Path(os.getenv("MAKERVAULT_TLS_CERT_FILE", str(root / "cert.pem"))),
        "server_key": Path(os.getenv("MAKERVAULT_TLS_KEY_FILE", str(root / "key.pem"))),
    }


def normalise_host(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise CertificateError("Host name or IP address is required.")
    if ":" in value and not value.startswith("["):
        # request.get_host() may include a port; IPv6 is intentionally not part
        # of the v1 local-certificate wizard.
        host, sep, port = value.rpartition(":")
        if sep and port.isdigit() and host:
            value = host
    if value.startswith("[") and "]" in value:
        raise CertificateError("IPv6 certificate generation is not supported by this wizard yet.")
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        if len(value) > 253 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
            raise CertificateError(f"Invalid host name: {value}")
        return value.lower()
    if ip.version != 4:
        raise CertificateError("IPv6 certificate generation is not supported by this wizard yet.")
    return str(ip)


def _san(hosts: list[str]) -> x509.SubjectAlternativeName:
    values = []
    for host in hosts:
        try:
            values.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            values.append(x509.DNSName(host))
    return x509.SubjectAlternativeName(values)


def _write_private(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    os.chmod(temp, 0o600)
    temp.replace(path)


def _write_public(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    os.chmod(temp, 0o644)
    temp.replace(path)


def _load_cert(path: Path) -> x509.Certificate | None:
    if not path.is_file():
        return None
    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except (ValueError, OSError):
        return None


def _cert_summary(cert: x509.Certificate | None) -> dict:
    if not cert:
        return {}
    sans = []
    try:
        extension = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        for item in extension.value:
            if isinstance(item, x509.DNSName):
                sans.append(item.value)
            elif isinstance(item, x509.IPAddress):
                sans.append(str(item.value))
    except x509.ExtensionNotFound:
        pass
    return {
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "sans": sans,
        "sha256_fingerprint": cert.fingerprint(hashes.SHA256()).hex(":"),
    }


def certificate_status(current_host: str = "") -> dict:
    p = paths()
    server = _load_cert(p["server_cert"])
    ca = _load_cert(p["ca_cert"])
    mode = os.getenv("MAKERVAULT_HTTPS_ENABLED", "auto").strip().lower() or "auto"
    https_port = int(os.getenv("MAKERVAULT_HTTPS_PORT", "8443"))
    host = ""
    try:
        host = normalise_host(current_host) if current_host else ""
    except CertificateError:
        host = ""
    private_host = False
    if host:
        try:
            private_host = ipaddress.ip_address(host).is_private
        except ValueError:
            private_host = host.endswith(".local") or "." not in host

    return {
        "mode": mode,
        "https_port": https_port,
        "current_host": host,
        "current_host_private": private_host,
        "server_certificate": _cert_summary(server),
        "local_ca": _cert_summary(ca),
        "local_ca_available": bool(ca and p["ca_key"].is_file()),
        "server_certificate_available": bool(server and p["server_key"].is_file()),
        "native_url": f"https://{host}:{https_port}" if host else "",
        "reverse_proxy_recommended": True,
        "public_acme": {
            "available_in_app": False,
            "reason": (
                "Public ACME issuance requires proof of control through public port 80/443 "
                "or a DNS provider. MakerVault does not grant the web process host/network "
                "control; use your reverse proxy/Certbot for public certificates."
            ),
        },
    }


def generate_local_certificate(hosts: list[str]) -> dict:
    clean = []
    for raw in hosts:
        host = normalise_host(raw)
        if host not in clean:
            clean.append(host)
    if "localhost" not in clean:
        clean.append("localhost")
    if "127.0.0.1" not in clean:
        clean.append("127.0.0.1")
    if len(clean) > 20:
        raise CertificateError("Too many certificate names; use at most 20.")

    p = paths()
    now = datetime.now(timezone.utc)
    ca_cert = _load_cert(p["ca_cert"])
    ca_key = None
    if ca_cert and p["ca_key"].is_file():
        try:
            ca_key = serialization.load_pem_private_key(p["ca_key"].read_bytes(), password=None)
        except (ValueError, OSError):
            raise CertificateError("The existing local CA key is unreadable. Restore it or remove the local CA files deliberately.")

    if not ca_cert or ca_key is None:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        ca_name = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MakerVault"),
            x509.NameAttribute(NameOID.COMMON_NAME, "MakerVault Local CA"),
        ])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name)
            .issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        _write_private(
            p["ca_key"],
            ca_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        )
        _write_public(p["ca_cert"], ca_cert.public_bytes(serialization.Encoding.PEM))

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MakerVault"),
        x509.NameAttribute(NameOID.COMMON_NAME, clean[0]),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=397))
        .add_extension(_san(clean), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    _write_private(
        p["server_key"],
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    _write_public(p["server_cert"], cert.public_bytes(serialization.Encoding.PEM))

    return {
        "hosts": clean,
        "server_certificate": _cert_summary(cert),
        "local_ca": _cert_summary(ca_cert),
    }
