"""Simulated AWS KMS key-ring envelope encryption and HMAC-SHA256 pseudonymizer."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

DEFAULT_KEY_ID: str = "kms-hipaa-key-2026-v1"
DEFAULT_DEV_SECRET_ENV: str = "LAKEHOUSE_KMS_MASTER_SECRET"


@dataclass(frozen=True, slots=True)
class KMSKeyRing:
    """Immutable KMS key ring supporting active signing and historical key verification."""

    active_key_id: str
    keys: dict[str, bytes]

    def __post_init__(self) -> None:
        if self.active_key_id not in self.keys:
            raise ValueError(f"active_key_id {self.active_key_id!r} not found in KMSKeyRing keys.")


class KMSTokenizer:
    """Deterministic HMAC-SHA256 tokenizer backed by a rotatable KMS key ring."""

    def __init__(self, key_ring: KMSKeyRing) -> None:
        self._key_ring = key_ring

    @classmethod
    def from_default_dev_keyring(cls, active_key_id: str = DEFAULT_KEY_ID) -> KMSTokenizer:
        """Create a deterministic KMS tokenizer from environment or ephemeral test salt."""
        secret_text = os.environ.get(
            DEFAULT_DEV_SECRET_ENV,
            "hipaa-safe-harbor-ephemeral-dev-kms-envelope-key-2026",
        )
        ring = KMSKeyRing(
            active_key_id=active_key_id,
            keys={active_key_id: secret_text.encode("utf-8")},
        )
        return cls(key_ring=ring)

    @property
    def active_key_id(self) -> str:
        """Return the active KMS key identifier used to sign new tokens."""
        return self._key_ring.active_key_id

    def tokenize(self, value: str, namespace: str = "patient") -> str:
        """Pseudonymize a clinical identifier into a versioned HMAC-SHA256 token."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Identifier value to tokenize cannot be empty.")

        secret = self._key_ring.keys[self._key_ring.active_key_id]
        digest = self._compute_digest(secret=secret, namespace=namespace, value=cleaned)
        return f"{self._key_ring.active_key_id}:{digest}"

    def verify_token(self, value: str, token: str, namespace: str = "patient") -> bool:
        """Verify a versioned token against active or rotated keys in constant time."""
        if ":" not in token:
            return False
        key_id, provided_digest = token.split(":", maxsplit=1)
        secret = self._key_ring.keys.get(key_id)
        if secret is None:
            return False
        expected_digest = self._compute_digest(
            secret=secret,
            namespace=namespace,
            value=value.strip(),
        )
        return hmac.compare_digest(provided_digest, expected_digest)

    def deterministic_date_shift_days(self, patient_id: str) -> int:
        """Compute a patient-consistent longitudinal date shift in [-365, -1] days."""
        secret = self._key_ring.keys[self._key_ring.active_key_id]
        raw_bytes = hmac.new(
            secret,
            f"date-shift:{patient_id.strip()}".encode(),
            hashlib.sha256,
        ).digest()
        offset_magnitude = (int.from_bytes(raw_bytes[:4], byteorder="big") % 365) + 1
        return -offset_magnitude

    def rotate_key(self, new_key_id: str, new_secret: bytes) -> KMSTokenizer:
        """Return a new KMSTokenizer with new_key_id active while preserving old keys."""
        merged_keys = dict(self._key_ring.keys)
        merged_keys[new_key_id] = new_secret
        return KMSTokenizer(key_ring=KMSKeyRing(active_key_id=new_key_id, keys=merged_keys))

    @staticmethod
    def _compute_digest(secret: bytes, namespace: str, value: str) -> str:
        payload = f"{namespace}:{value}".encode()
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()[:24]
