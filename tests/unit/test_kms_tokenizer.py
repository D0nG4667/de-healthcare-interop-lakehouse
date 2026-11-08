"""Unit tests for the AWS KMS envelope key-ring and HMAC-SHA256 tokenizer."""

from __future__ import annotations

import pytest

from healthcare_lakehouse.security.kms_tokenizer import KMSKeyRing, KMSTokenizer


def test_kms_tokenizer_deterministic_hmac_and_verification() -> None:
    """Verify deterministic tokenization, namespace isolation, and token verification."""
    tokenizer = KMSTokenizer.from_default_dev_keyring()
    assert tokenizer.active_key_id == "kms-hipaa-key-2026-v1"
    tok1 = tokenizer.tokenize("pat-0001", namespace="patient")
    tok2 = tokenizer.tokenize("pat-0001", namespace="patient")
    tok_enc = tokenizer.tokenize("pat-0001", namespace="encounter")

    assert tok1 == tok2
    assert tok1 != tok_enc
    assert tok1.startswith("kms-hipaa-key-2026-v1:")
    assert tokenizer.verify_token("pat-0001", tok1, namespace="patient") is True
    assert tokenizer.verify_token("pat-9999", tok1, namespace="patient") is False
    assert tokenizer.verify_token("pat-0001", "malformed_token", namespace="patient") is False
    assert (
        tokenizer.verify_token("pat-0001", "unknown-key-id:abcdef1234", namespace="patient")
        is False
    )


def test_kms_tokenizer_key_rotation_preserves_historical_verification() -> None:
    """Verify rotating KMS keys issues v2 tokens while still verifying historical v1 tokens."""
    v1_tokenizer = KMSTokenizer.from_default_dev_keyring()
    v1_token = v1_tokenizer.tokenize("MRN-2026001", namespace="mrn")

    v2_tokenizer = v1_tokenizer.rotate_key(
        new_key_id="kms-hipaa-key-2027-v2",
        new_secret=b"enterprise-rotated-secret-key-2027-v2-bytes",
    )
    v2_token = v2_tokenizer.tokenize("MRN-2026001", namespace="mrn")

    assert v2_token.startswith("kms-hipaa-key-2027-v2:")
    assert v1_token != v2_token
    # Historical v1 token must still verify under the rotated keyring
    assert v2_tokenizer.verify_token("MRN-2026001", v1_token, namespace="mrn") is True
    assert v2_tokenizer.verify_token("MRN-2026001", v2_token, namespace="mrn") is True


def test_kms_tokenizer_deterministic_date_shift_and_keyring_validation() -> None:
    """Verify patient date shift offset is deterministic in [-365, -1] and keyring validates."""
    tokenizer = KMSTokenizer.from_default_dev_keyring()
    shift_a1 = tokenizer.deterministic_date_shift_days("pat-0001")
    shift_a2 = tokenizer.deterministic_date_shift_days("pat-0001")
    assert shift_a1 == shift_a2
    assert -365 <= shift_a1 <= -1

    with pytest.raises(ValueError, match="active_key_id 'missing' not found"):
        KMSKeyRing(active_key_id="missing", keys={"k1": b"secret"})

    with pytest.raises(ValueError, match="cannot be empty"):
        tokenizer.tokenize("   ")
