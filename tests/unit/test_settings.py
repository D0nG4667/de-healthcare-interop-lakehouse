"""Unit tests for Lakehouse, HIPAA Safe Harbor, and KMS configuration settings."""

from __future__ import annotations

from pathlib import Path

import pyarrow.fs as pafs
import pytest
from pydantic import ValidationError

from healthcare_lakehouse.config.settings import (
    HIPAA_RESTRICTED_ZIP3_PREFIXES,
    LakehouseSettings,
)


def test_default_settings_creates_expected_zone_paths(tmp_path: Path) -> None:
    """Verify Bronze, Silver, and Gold directory properties resolve from base path."""
    settings = LakehouseSettings(base_storage_path=tmp_path)
    assert settings.environment == "local"
    assert settings.bronze_zone_dir == tmp_path / "bronze"
    assert settings.silver_zone_dir == tmp_path / "silver"
    assert settings.gold_zone_dir == tmp_path / "gold"
    assert settings.hipaa_safe_harbor_max_age == 89
    assert settings.parquet_compression == "ZSTD"
    assert "036" in settings.hipaa_restricted_zip3_prefixes
    assert len(HIPAA_RESTRICTED_ZIP3_PREFIXES) == 17


def test_settings_ensure_directories_creates_medallion_folders(tmp_path: Path) -> None:
    """Verify ensure_directories creates bronze, silver, and gold directories on disk."""
    base = tmp_path / "lakehouse_store"
    settings = LakehouseSettings(base_storage_path=base, environment="staging")
    settings.ensure_directories()
    assert settings.bronze_zone_dir.is_dir()
    assert settings.silver_zone_dir.is_dir()
    assert settings.gold_zone_dir.is_dir()


def test_settings_rejects_invalid_max_age_or_mutability(tmp_path: Path) -> None:
    """Verify HIPAA max age above 89 is rejected and settings are immutable."""
    valid_explicit = LakehouseSettings(
        base_storage_path=tmp_path,
        hipaa_safe_harbor_max_age=89,
    )
    assert valid_explicit.hipaa_safe_harbor_max_age == 89

    with pytest.raises(ValidationError):
        LakehouseSettings(base_storage_path=tmp_path, hipaa_safe_harbor_max_age=95)

    settings = LakehouseSettings(base_storage_path=tmp_path)
    with pytest.raises(ValidationError):
        setattr(settings, "environment", "production")  # noqa: B010


def test_settings_s3_minio_filesystem_and_env_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify S3/MinIO object targets, secret masking, Arrow filesystems, and from_env()."""
    local_settings = LakehouseSettings(base_storage_path=tmp_path)
    assert local_settings.is_s3_storage is False
    assert local_settings.storage_backend == "local"
    assert isinstance(local_settings.build_arrow_filesystem(), pafs.LocalFileSystem)
    assert local_settings.table_uri("gold", "alerts.parquet") == str(
        tmp_path / "gold" / "alerts.parquet"
    )

    minio_settings = LakehouseSettings(
        s3_bucket="healthcare-lakehouse",
        s3_prefix="/medallion/",
        s3_endpoint_url="http://minio-s3:9000",
        s3_access_key="lakehouse_admin",
        s3_secret_key="super-secret-minio-key",
        s3_allow_bucket_creation=True,
    )
    assert minio_settings.is_s3_storage is True
    assert minio_settings.storage_backend == "s3"
    assert "super-secret-minio-key" not in repr(minio_settings)
    assert minio_settings.zone_object_prefix("bronze") == "healthcare-lakehouse/medallion/bronze"
    assert (
        minio_settings.table_storage_target("silver", "silver_patients.parquet")
        == "healthcare-lakehouse/medallion/silver/silver_patients.parquet"
    )
    assert (
        minio_settings.table_uri("gold", "gold_alerts.parquet")
        == "s3://healthcare-lakehouse/medallion/gold/gold_alerts.parquet"
    )
    assert isinstance(minio_settings.build_arrow_filesystem(), pafs.S3FileSystem)

    # Also verify empty s3_prefix, https endpoint, bare host:port endpoint, and AWS default (None)
    root_bucket_settings = LakehouseSettings(
        s3_bucket="aws-prod-lakehouse",
        s3_prefix="",
        s3_endpoint_url=None,
    )
    assert root_bucket_settings.zone_object_prefix("gold") == "aws-prod-lakehouse/gold"
    assert isinstance(root_bucket_settings.build_arrow_filesystem(), pafs.S3FileSystem)

    https_s3 = LakehouseSettings(
        s3_bucket="b1",
        s3_endpoint_url="https://s3.us-east-1.amazonaws.com",
    )
    assert isinstance(https_s3.build_arrow_filesystem(), pafs.S3FileSystem)

    bare_host_s3 = LakehouseSettings(
        s3_bucket="b2",
        s3_endpoint_url="localhost:9000",
    )
    assert isinstance(bare_host_s3.build_arrow_filesystem(), pafs.S3FileSystem)

    # Verify LakehouseSettings.from_env(...) resolution and CLI override precedence
    monkeypatch.setenv("LAKEHOUSE_ENV", "staging")
    monkeypatch.setenv("LAKEHOUSE_S3_BUCKET", "env-bucket")
    monkeypatch.setenv("LAKEHOUSE_S3_PREFIX", "env-prefix")
    monkeypatch.setenv("LAKEHOUSE_S3_ENDPOINT_URL", "http://minio-s3:9000")
    monkeypatch.setenv("LAKEHOUSE_S3_REGION", "eu-west-1")
    monkeypatch.setenv("LAKEHOUSE_S3_ACCESS_KEY", "env-ak")
    monkeypatch.setenv("LAKEHOUSE_S3_SECRET_KEY", "env-sk")
    monkeypatch.setenv("LAKEHOUSE_S3_ALLOW_BUCKET_CREATION", "true")
    monkeypatch.setenv("LAKEHOUSE_KMS_KEY_ID", "kms-env-v2")
    monkeypatch.setenv("LAKEHOUSE_PARQUET_COMPRESSION", "SNAPPY")

    env_settings = LakehouseSettings.from_env(base_storage_path=tmp_path)
    assert env_settings.environment == "staging"
    assert env_settings.s3_bucket == "env-bucket"
    assert env_settings.s3_prefix == "env-prefix"
    assert env_settings.s3_endpoint_url == "http://minio-s3:9000"
    assert env_settings.s3_region == "eu-west-1"
    assert env_settings.s3_access_key == "env-ak"
    assert env_settings.s3_secret_key == "env-sk"
    assert env_settings.s3_allow_bucket_creation is True
    assert env_settings.kms_active_key_id == "kms-env-v2"
    assert env_settings.parquet_compression == "SNAPPY"

    override_settings = LakehouseSettings.from_env(
        s3_bucket="cli-bucket",
        s3_prefix="cli-prefix",
        s3_endpoint_url="http://127.0.0.1:9000",
    )
    assert override_settings.s3_bucket == "cli-bucket"
    assert override_settings.s3_prefix == "cli-prefix"
    assert override_settings.s3_endpoint_url == "http://127.0.0.1:9000"

    monkeypatch.setenv("LAKEHOUSE_ENV", "invalid-env")
    with pytest.raises(ValidationError):
        LakehouseSettings.from_env()
