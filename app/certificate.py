"""Portable, signed trust certificates for /audit responses.

Every /audit response carries an Ed25519-signed "certificate" — a compact,
tamper-evident claim about the verdict/trust_score/input that another agent
can carry around and verify OFFLINE (no re-audit, no shared secret) via
POST /verify. The signature proves the certificate is genuine (issued by
this service, over this exact claim) and untampered.

Key management
---------------
The signing key MUST be stable across restarts, or every certificate issued
before a redeploy stops verifying. So we never generate a random key at
startup: we derive an Ed25519 key deterministically from a fixed 32-byte
seed baked into this module (`_DEFAULT_SEED_HEX`, a DEMO key — replace it in
any real deployment), overridable via the `LEGIBRIGHT_SIGNING_SEED` env var
(64 hex chars = 32 bytes). Same seed in -> same key out, every process start.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .schemas import AuditRequest, AuditResponse

# Fixed demo seed — NOT a secret worth protecting in this hackathon build.
# Override with LEGIBRIGHT_SIGNING_SEED (64 hex chars) for a real deployment.
_DEFAULT_SEED_HEX = "4c656769627269676874547275737441756469744b657944656d6f5365656431"

_seed_hex = os.environ.get("LEGIBRIGHT_SIGNING_SEED", _DEFAULT_SEED_HEX)
_SEED = bytes.fromhex(_seed_hex)
_PRIVATE_KEY: Ed25519PrivateKey = Ed25519PrivateKey.from_private_bytes(_SEED)
_PUBLIC_KEY: Ed25519PublicKey = _PRIVATE_KEY.public_key()

_PUBLIC_KEY_BYTES = _PUBLIC_KEY.public_bytes_raw()
PUBLIC_KEY_HEX = _PUBLIC_KEY_BYTES.hex()
KEY_ID = hashlib.sha256(_PUBLIC_KEY_BYTES).hexdigest()[:16]

ALGORITHM = "Ed25519"


def canonical(obj: Any) -> bytes:
    """Deterministic JSON encoding used for both digesting and signing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def input_digest(req: AuditRequest) -> str:
    """sha256 hex of the canonical request body (what was actually audited)."""
    return hashlib.sha256(canonical(req.model_dump(exclude_none=True))).hexdigest()


def issue_certificate(req: AuditRequest, resp: AuditResponse) -> dict:
    """Build and sign a portable trust certificate for an audit response."""
    claim = {
        "schema": "legibright-trust-cert/1",
        "issuer": "legibright-trust-audit",
        "target": resp.target,
        "verdict": resp.verdict,
        "trust_score": resp.trust_score,
        "counts": resp.counts,
        "input_sha256": input_digest(req),
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    content_id = hashlib.sha256(canonical({
        "input_sha256": claim["input_sha256"],
        "verdict": claim["verdict"],
        "trust_score": claim["trust_score"],
    })).hexdigest()[:16]
    signature = _PRIVATE_KEY.sign(canonical(claim)).hex()
    return {
        "claim": claim,
        "content_id": content_id,
        "signature": signature,
        "algorithm": ALGORITHM,
        "public_key": PUBLIC_KEY_HEX,
        "key_id": KEY_ID,
    }


def verify_certificate(cert: dict) -> dict:
    """Verify a certificate offline, without re-running the audit.

    Defensive by design: never raises, never 500s. Any malformed / missing
    field or a wrong type results in {"valid": False, "reason": "..."}.
    """
    if not isinstance(cert, dict):
        return {"valid": False, "reason": "certificate must be a JSON object", "claim": None}

    claim = cert.get("claim")
    signature_hex = cert.get("signature")
    public_key_hex = cert.get("public_key")
    algorithm = cert.get("algorithm")

    if not isinstance(claim, dict):
        return {"valid": False, "reason": "missing or invalid 'claim' field", "claim": None}
    if not isinstance(signature_hex, str) or not signature_hex:
        return {"valid": False, "reason": "missing or invalid 'signature' field", "claim": None}
    if not isinstance(public_key_hex, str) or not public_key_hex:
        return {"valid": False, "reason": "missing or invalid 'public_key' field", "claim": None}
    if not isinstance(algorithm, str):
        return {"valid": False, "reason": "missing or invalid 'algorithm' field", "claim": None}

    if algorithm != ALGORITHM:
        return {"valid": False, "reason": "unsupported algorithm", "claim": None}

    if public_key_hex != PUBLIC_KEY_HEX:
        return {
            "valid": False,
            "reason": "unknown signer — not issued by this service",
            "claim": None,
        }

    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return {"valid": False, "reason": "signature is not valid hex", "claim": None}

    try:
        _PUBLIC_KEY.verify(signature, canonical(claim))
    except InvalidSignature:
        return {
            "valid": False,
            "reason": "signature does not match claim (tampered or corrupt)",
            "claim": None,
        }
    except Exception:
        return {"valid": False, "reason": "signature verification failed", "claim": None}

    return {"valid": True, "reason": "genuine, untampered Legibright certificate", "claim": claim}
