"""Unit tests for Lakehouse, HIPAA Safe Harbor, and KMS configuration settings."""

from __future__ import annotations

from pathlib import Path

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
