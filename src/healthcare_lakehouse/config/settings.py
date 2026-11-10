"""Immutable configuration settings for the Healthcare Interoperability Lakehouse."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import pyarrow.fs as pafs
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
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = Field(default=None, repr=False)
    s3_allow_bucket_creation: bool = False
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

    @classmethod
    def from_env(
        cls,
        *,
        base_storage_path: Path | None = None,
        s3_bucket: str | None = None,
        s3_prefix: str | None = None,
        s3_endpoint_url: str | None = None,
    ) -> LakehouseSettings:
        """Build LakehouseSettings from LAKEHOUSE_* environment variables and CLI overrides."""
        env_val: Any = os.getenv("LAKEHOUSE_ENV", "local")
        compression_val: Any = os.getenv("LAKEHOUSE_PARQUET_COMPRESSION", "ZSTD")
        allow_create_raw = os.getenv("LAKEHOUSE_S3_ALLOW_BUCKET_CREATION", "false").strip().lower()
        resolved_bucket = (
            s3_bucket if s3_bucket is not None else (os.getenv("LAKEHOUSE_S3_BUCKET") or None)
        )
        resolved_prefix = (
            s3_prefix if s3_prefix is not None else os.getenv("LAKEHOUSE_S3_PREFIX", "")
        )
        resolved_endpoint = (
            s3_endpoint_url
            if s3_endpoint_url is not None
            else (os.getenv("LAKEHOUSE_S3_ENDPOINT_URL") or None)
        )
        return cls(
            environment=env_val,
            base_storage_path=(
                base_storage_path if base_storage_path is not None else Path("data")
            ),
            s3_bucket=resolved_bucket,
            s3_prefix=resolved_prefix,
            s3_endpoint_url=resolved_endpoint,
            s3_region=os.getenv("LAKEHOUSE_S3_REGION", "us-east-1"),
            s3_access_key=os.getenv("LAKEHOUSE_S3_ACCESS_KEY") or None,
            s3_secret_key=os.getenv("LAKEHOUSE_S3_SECRET_KEY") or None,
            s3_allow_bucket_creation=allow_create_raw in {"1", "true", "yes"},
            kms_active_key_id=os.getenv("LAKEHOUSE_KMS_KEY_ID", "kms-hipaa-key-2026-v1"),
            parquet_compression=compression_val,
        )

    @property
    def is_s3_storage(self) -> bool:
        """Return True when S3 / MinIO object storage is configured."""
        return bool(self.s3_bucket and self.s3_bucket.strip())

    @property
    def storage_backend(self) -> Literal["local", "s3"]:
        """Active storage backend identifier ('local' or 's3')."""
        return "s3" if self.is_s3_storage else "local"

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

    def zone_object_prefix(self, zone: Literal["bronze", "silver", "gold"]) -> str:
        """Return the S3 'bucket[/prefix]/zone' key prefix for a Medallion zone."""
        bucket = (self.s3_bucket or "").strip("/")
        prefix = self.s3_prefix.strip("/")
        return f"{bucket}/{prefix}/{zone}" if prefix else f"{bucket}/{zone}"

    def table_storage_target(
        self,
        zone: Literal["bronze", "silver", "gold"],
        filename: str,
    ) -> str:
        """Return the Arrow FileSystem target path/key for a Medallion Parquet table."""
        if self.is_s3_storage:
            return f"{self.zone_object_prefix(zone)}/{filename}"
        return str(self.base_storage_path / zone / filename)

    def table_uri(
        self,
        zone: Literal["bronze", "silver", "gold"],
        filename: str,
    ) -> str:
        """Return the canonical URI ('s3://...' or local filesystem path) for a table."""
        if self.is_s3_storage:
            return f"s3://{self.table_storage_target(zone, filename)}"
        return str(self.base_storage_path / zone / filename)

    def build_arrow_filesystem(self) -> pafs.FileSystem:
        """Construct the PyArrow FileSystem (LocalFileSystem or S3FileSystem for MinIO/AWS)."""
        if not self.is_s3_storage:
            return pafs.LocalFileSystem()

        scheme = "https"
        endpoint_override: str | None = None
        if self.s3_endpoint_url:
            raw_ep = self.s3_endpoint_url.strip()
            if raw_ep.startswith(("http://", "https://")):
                parsed = urlparse(raw_ep)
                scheme = parsed.scheme
                endpoint_override = parsed.netloc
            else:
                endpoint_override = raw_ep

        return pafs.S3FileSystem(
            access_key=self.s3_access_key,
            secret_key=self.s3_secret_key,
            region=self.s3_region,
            scheme=scheme,
            endpoint_override=endpoint_override,
            allow_bucket_creation=self.s3_allow_bucket_creation,
            check_directory_existence_before_creation=True,
        )

    def ensure_directories(self) -> None:
        """Materialize Bronze, Silver, and Gold directories on the local filesystem."""
        self.bronze_zone_dir.mkdir(parents=True, exist_ok=True)
        self.silver_zone_dir.mkdir(parents=True, exist_ok=True)
        self.gold_zone_dir.mkdir(parents=True, exist_ok=True)
