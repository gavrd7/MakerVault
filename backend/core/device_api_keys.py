"""Token primitives for future scoped MakerVault device/integration API keys.

This module deliberately does not authenticate Django requests or persist keys:
the database model, revocation policy and isolated bearer endpoints follow in
separate, testable changes. No existing session endpoint accepts these tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

TOKEN_PREFIX = "mvk"
SECRET_BYTES = 32
SCOPES = frozenset({
    "tags:read",
    "tags:write",
    "inventory:read",
    "spools:weight",
    "devices:status",
})
# A fixed-width public key identifier supports indexed lookup without storing
# recoverable credentials. It is not itself a credential.
_TOKEN_RE = re.compile(r"^mvk_([0-9a-f]{24})_([A-Za-z0-9_-]{43})$")


@dataclass(frozen=True)
class IssuedToken:
    plaintext: str
    identifier: str
    digest: str


def validate_scopes(scopes: object) -> tuple[str, ...]:
    """Reject unknown, empty, duplicate or malformed scope lists."""
    if not isinstance(scopes, (list, tuple)) or not scopes:
        raise ValueError("Choose at least one API scope.")
    if any(not isinstance(scope, str) for scope in scopes):
        raise ValueError("API scopes must be strings.")
    if len(set(scopes)) != len(scopes) or not set(scopes) <= SCOPES:
        raise ValueError("Duplicate or unsupported API scope.")
    return tuple(sorted(scopes))


def generate_token() -> IssuedToken:
    """Return secret once to caller; only identifier and digest may be stored."""
    identifier = secrets.token_hex(12)
    secret = secrets.token_urlsafe(SECRET_BYTES)
    token = f"{TOKEN_PREFIX}_{identifier}_{secret}"
    return IssuedToken(
        plaintext=token,
        identifier=identifier,
        digest=hashlib.sha256(token.encode("ascii")).hexdigest(),
    )


def parse_identifier(token: object) -> str | None:
    """Extract nonsecret lookup ID without validating the credential."""
    if not isinstance(token, str):
        return None
    match = _TOKEN_RE.fullmatch(token)
    return match.group(1) if match else None


def verify_token(token: object, expected_digest: str) -> bool:
    """Constant-time digest comparison; callers must first check key status."""
    if parse_identifier(token) is None:
        return False
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        return False
    candidate = hashlib.sha256(token.encode("ascii")).hexdigest()
    return hmac.compare_digest(candidate, expected_digest)
