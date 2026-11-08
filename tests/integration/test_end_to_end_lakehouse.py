"""End-to-end integration tests for the Healthcare Clinical Interoperability Lakehouse."""

from __future__ import annotations

from pathlib import Path

from healthcare_lakehouse.config.settings import LakehouseSettings
from healthcare_lakehouse.lakehouse.medallion_pipeline import MedallionLakehousePipeline


def test_end_to_end_synthetic_simulation_to_gold_analytics(tmp_path: Path) -> None:
    """Verify full synthetic cohort simulation through Bronze, Silver, and Gold zones."""
    settings = LakehouseSettings(
        environment="staging",
        base_storage_path=tmp_path / "e2e_lakehouse",
        parquet_compression="SNAPPY",
    )
    pipeline = MedallionLakehousePipeline(settings=settings)
    metrics = pipeline.simulate_and_run(patient_count=6, seed=2026)

    assert metrics.bronze_records_written == 8  # 6 FHIR Bundles + 2 HL7v2 streams
    assert metrics.silver_patients_written == 8
    assert metrics.gold_alerts_written == 8
    assert metrics.hipaa_violations_detected == 0

    cohort_rows = pipeline.read_parquet_records(metrics.gold_cohort_parquet_path)
    assert len(cohort_rows) >= 2
    assert all("mean_news2_score" in row for row in cohort_rows)
