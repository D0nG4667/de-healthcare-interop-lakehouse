"""Immutable configuration settings for the Healthcare Interoperability Lakehouse."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HIPAA_RESTRICTED_ZIP3_PREFIXES: frozenset[str] = frozenset(
    {
        "036",
        "059",
        "063",
        "102",
        "203",
        "556",
        "692",
        "790",
        "821",
        "823",
        "830",
        "831",
        "878",
        "879",
        "884",
        "890",
        "893",
    }
)


class LakehouseSettings(BaseModel):
    """Configuration contract governing Medallion paths, HIPAA Safe Harbor, and KMS keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: Literal["local", "development", "staging", "production"] = "local"
    base_storage_path: Path = Field(default_factory=lambda: Path("data"))
    kms_active_key_id: str = "kms-hipaa-key-2026-v1"
    hipaa_safe_harbor_max_age: int = 89
    hipaa_restricted_zip3_prefixes: frozenset[str] = HIPAA_RESTRICTED_ZIP3_PREFIXES
    parquet_compression: Literal["SNAPPY", "ZSTD", "GZIP"] = "ZSTD"

    @field_validator("hipaa_safe_harbor_max_age")
    @classmethod
    def _validate_hipaa_max_age(cls, value: int) -> int:
        if value > 89 or value < 1:
            raise ValueError(
                "HIPAA Safe Harbor (45 CFR 164.514(b)(2)) requires top-coding ages above 89."
            )
        return value

    @property
    def bronze_zone_dir(self) -> Path:
        """Directory storing immutable raw clinical ingestion envelopes."""
        return self.base_storage_path / "bronze"

    @property
    def silver_zone_dir(self) -> Path:
        """Directory storing canonical, HIPAA de-identified FHIR R4 Parquet tables."""
        return self.base_storage_path / "silver"

    @property
    def gold_zone_dir(self) -> Path:
        """Directory storing clinical research cohorts and NEWS2/qSOFA alert tables."""
        return self.base_storage_path / "gold"

    def ensure_directories(self) -> None:
        """Materialize Bronze, Silver, and Gold directories on the target filesystem."""
        self.bronze_zone_dir.mkdir(parents=True, exist_ok=True)
        self.silver_zone_dir.mkdir(parents=True, exist_ok=True)
        self.gold_zone_dir.mkdir(parents=True, exist_ok=True)
