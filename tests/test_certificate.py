"""Tests for the portable, signed trust certificate (issue + offline verify)."""
from __future__ import annotations

import copy

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import certificate as cert_mod
from app.audit import run_audit
from app.certificate import issue_certificate, verify_certificate
from app.main import app
from app.schemas import AuditRequest

client = TestClient(app)

_METRICS_NOT_TRUSTWORTHY = {"metrics": {"in_sample": 0.99, "holdout": 0.74}}
_TRUSTWORTHY_BODY = {
    "split": {
        "train_ts": list(range(0, 40)),
        "test_ts": list(range(40, 60)),
        "train_groups": [f"e{i}" for i in range(40)],
        "test_groups": [f"e{i + 100}" for i in range(20)],
    },
    "predictions": {
        "predicted": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.15,
                      0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 0.05, 0.5],
        "outcomes": [0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 1],
    },
}


def test_round_trip_via_http():
    r = client.post("/audit", json=_METRICS_NOT_TRUSTWORTHY)
    assert r.status_code == 200
    body = r.json()
    cert = body["certificate"]
    assert cert is not None

    v = client.post("/verify", json=cert)
    assert v.status_code == 200
    vbody = v.json()
    assert vbody["valid"] is True
    assert vbody["claim"] == cert["claim"]


def test_tamper_verdict_invalidates_signature():
    r = client.post("/audit", json=_METRICS_NOT_TRUSTWORTHY)
    cert = r.json()["certificate"]
    tampered = copy.deepcopy(cert)
    tampered["claim"]["verdict"] = "TRUSTWORTHY"
    tampered["claim"]["trust_score"] = 100

    v = client.post("/verify", json=tampered)
    assert v.status_code == 200
    vbody = v.json()
    assert vbody["valid"] is False
    assert "tamper" in vbody["reason"].lower() or "signature" in vbody["reason"].lower()


def test_structurally_broken_claim_is_200_valid_false():
    # A certificate whose `claim` is not an object is a normal answer
    # (valid: false), not a 400 — matches the SKILL.md contract.
    for broken in ("not-a-claim", None, 123, ["a"]):
        v = client.post("/verify", json={"claim": broken, "signature": "ab",
                                          "algorithm": "Ed25519", "public_key": "cd"})
        assert v.status_code == 200, broken
        assert v.json()["valid"] is False, broken


def test_forged_signer_is_rejected():
    r = client.post("/audit", json=_METRICS_NOT_TRUSTWORTHY)
    cert = r.json()["certificate"]

    other_key = Ed25519PrivateKey.generate()
    other_public_hex = other_key.public_key().public_bytes_raw().hex()
    forged_signature = other_key.sign(cert_mod.canonical(cert["claim"])).hex()

    forged = copy.deepcopy(cert)
    forged["public_key"] = other_public_hex
    forged["signature"] = forged_signature

    v = client.post("/verify", json=forged)
    assert v.status_code == 200
    vbody = v.json()
    assert vbody["valid"] is False
    assert "unknown signer" in vbody["reason"].lower()


def test_determinism_same_input_same_digest_and_content_id():
    r1 = client.post("/audit", json=_METRICS_NOT_TRUSTWORTHY)
    r2 = client.post("/audit", json=_METRICS_NOT_TRUSTWORTHY)
    c1 = r1.json()["certificate"]
    c2 = r2.json()["certificate"]
    assert c1["claim"]["input_sha256"] == c2["claim"]["input_sha256"]
    assert c1["content_id"] == c2["content_id"]


def test_certificate_claim_matches_response_not_trustworthy():
    r = client.post("/audit", json=_METRICS_NOT_TRUSTWORTHY)
    body = r.json()
    assert body["verdict"] == "NOT_TRUSTWORTHY"
    assert body["trust_score"] == 40
    cert = body["certificate"]
    assert cert["claim"]["verdict"] == body["verdict"]
    assert cert["claim"]["trust_score"] == body["trust_score"]


def test_certificate_claim_matches_response_trustworthy():
    r = client.post("/audit", json=_TRUSTWORTHY_BODY)
    body = r.json()
    cert = body["certificate"]
    assert cert["claim"]["verdict"] == body["verdict"]
    assert cert["claim"]["trust_score"] == body["trust_score"]


def test_unit_issue_and_verify_directly():
    req = AuditRequest(**_METRICS_NOT_TRUSTWORTHY)
    resp = run_audit(req)
    cert = issue_certificate(req, resp)
    result = verify_certificate(cert)
    assert result["valid"] is True
    assert result["reason"]
    assert result["claim"]["verdict"] == resp.verdict


def test_unit_verify_empty_dict_never_raises():
    result = verify_certificate({})
    assert result["valid"] is False
    assert isinstance(result["reason"], str) and result["reason"]
    assert result["claim"] is None


def test_unit_verify_non_dict_never_raises():
    assert verify_certificate(None)["valid"] is False
    assert verify_certificate("not a cert")["valid"] is False
    assert verify_certificate(123)["valid"] is False
