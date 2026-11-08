"""Unit tests for package metadata and version invariants."""

from __future__ import annotations

import healthcare_lakehouse


def test_package_version_is_semantic() -> None:
    """Verify the package exposes a valid semantic version string."""
    assert healthcare_lakehouse.__version__ == "1.0.0"
    assert "__version__" in healthcare_lakehouse.__all__
