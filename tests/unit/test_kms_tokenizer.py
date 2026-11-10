"""Unit tests for the AWS KMS envelope key-ring and HMAC-SHA256 tokenizer."""

from __future__ import annotations

import pytest

from healthcare_lakehouse.security.kms_tokenizer import (
    DEFAULT_DEV_SECRET_ENV,
    KMSKeyRing,
    KMSTokenizer,
)


def test_kms_tokenizer_deterministic_hmac_and_verification() -> None:
    """Verify 128-bit deterministic tokenization, namespace isolation, and verification."""
    tokenizer = KMSTokenizer.from_default_dev_keyring()
    assert tokenizer.active_key_id == "kms-hipaa-key-2026-v1"
    tok1 = tokenizer.tokenize("pat-0001", namespace="patient")
    tok2 = tokenizer.tokenize("pat-0001", namespace="patient")
    tok_enc = tokenizer.tokenize("pat-0001", namespace="encounter")

    assert tok1 == tok2
    assert tok1 != tok_enc
    key_prefix, hex_digest = tok1.split(":", maxsplit=1)
    assert key_prefix == "kms-hipaa-key-2026-v1"
    assert len(hex_digest) == 32
    assert tokenizer.verify_token("pat-0001", tok1, namespace="patient") is True
    assert tokenizer.verify_token("pat-9999", tok1, namespace="patient") is False
    assert tokenizer.verify_token("pat-0001", "malformed_token", namespace="patient") is False
    assert (
        tokenizer.verify_token("pat-0001", "unknown-key-id:abcdef1234", namespace="patient")
        is False
    )


def test_kms_tokenizer_key_rotation_preserves_historical_verification_and_date_shift() -> None:
    """Verify key rotation issues v2 tokens while keeping v1 verification and stable date shifts."""
    v1_tokenizer = KMSTokenizer.from_default_dev_keyring()
    v1_token = v1_tokenizer.tokenize("MRN-2026001", namespace="mrn")
    v1_shift = v1_tokenizer.deterministic_date_shift_days("MRN-2026001")

    v2_tokenizer = v1_tokenizer.rotate_key(
        new_key_id="kms-hipaa-key-2027-v2",
        new_secret=b"enterprise-rotated-secret-key-2027-v2-bytes",
    )
    v2_token = v2_tokenizer.tokenize("MRN-2026001", namespace="mrn")
    v2_shift = v2_tokenizer.deterministic_date_shift_days("MRN-2026001")

    assert v2_token.startswith("kms-hipaa-key-2027-v2:")
    assert v1_token != v2_token
    assert v2_shift == v1_shift
    assert v2_tokenizer.verify_token("MRN-2026001", v1_token, namespace="mrn") is True
    assert v2_tokenizer.verify_token("MRN-2026001", v2_token, namespace="mrn") is True


def test_kms_tokenizer_keyring_validation_and_production_secret_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify keyring invariants and production requirement for LAKEHOUSE_KMS_MASTER_SECRET."""
    tokenizer = KMSTokenizer.from_default_dev_keyring()
    shift_a1 = tokenizer.deterministic_date_shift_days("pat-0001")
    shift_a2 = tokenizer.deterministic_date_shift_days("pat-0001")
    assert shift_a1 == shift_a2
    assert -365 <= shift_a1 <= -1

    with pytest.raises(ValueError, match="active_key_id 'missing' not found"):
        KMSKeyRing(active_key_id="missing", keys={"k1": b"secret"})

    with pytest.raises(ValueError, match="cohort_salt_key_id 'missing-salt' not found"):
        KMSKeyRing(
            active_key_id="k1",
            keys={"k1": b"secret"},
            cohort_salt_key_id="missing-salt",
        )

    with pytest.raises(ValueError, match="cannot be empty"):
        tokenizer.tokenize("   ")

    monkeypatch.delenv(DEFAULT_DEV_SECRET_ENV, raising=False)
    with pytest.raises(ValueError, match=DEFAULT_DEV_SECRET_ENV):
        KMSTokenizer.from_default_dev_keyring(require_env_secret=True)

    monkeypatch.setenv(DEFAULT_DEV_SECRET_ENV, "prod-kms-envelope-secret-key")
    prod_tok = KMSTokenizer.from_default_dev_keyring(
        active_key_id="kms-prod-v1",
        require_env_secret=True,
    )
    assert prod_tok.active_key_id == "kms-prod-v1"
