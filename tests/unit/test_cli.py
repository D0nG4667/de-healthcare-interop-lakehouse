"""Unit tests for the Healthcare Interoperability Lakehouse CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from healthcare_lakehouse.cli import main
from healthcare_lakehouse.security.hipaa_anonymizer import HIPAAComplianceError


def test_cli_run_pipeline_executes_and_verifies_persisted_hipaa_tables(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify CLI run-pipeline executes end-to-end and audits persisted Parquet files."""
    out_dir = tmp_path / "cli_out"
    exit_code = main(
        [
            "run-pipeline",
            "--patients",
            "4",
            "--seed",
            "42",
            "--output-dir",
            str(out_dir),
            "--verify-hipaa",
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["status"] == "SUCCESS"
    assert report["hipaa_safe_harbor_compliant"] is True
    assert report["hipaa_violations_detected"] == 0
    assert report["silver_patients_written"] >= 4
    assert (out_dir / "gold" / "gold_patient_deterioration_alerts.parquet").is_file()

    # Also verify run without --verify-hipaa succeeds cleanly
    out_dir_no_flag = tmp_path / "cli_no_flag"
    assert (
        main(
            [
                "run-pipeline",
                "--patients",
                "2",
                "--seed",
                "42",
                "--output-dir",
                str(out_dir_no_flag),
            ]
        )
        == 0
    )
    _ = capsys.readouterr()


def test_cli_verify_hipaa_detects_tampered_parquet_phi_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify --verify-hipaa raises HIPAAComplianceError if persisted Parquet contains PHI."""
    from healthcare_lakehouse.lakehouse.medallion_pipeline import (
        MedallionLakehousePipeline,
        PipelineExecutionMetrics,
    )

    original_run = MedallionLakehousePipeline.simulate_and_run

    def tampered_run(
        self: MedallionLakehousePipeline,
        patient_count: int = 8,
        seed: int = 42,
    ) -> PipelineExecutionMetrics:
        metrics = original_run(self, patient_count=patient_count, seed=seed)
        tampered_table = pa.Table.from_pylist(
            [
                {
                    "patient_token": "raw-unmasked-id",
                    "mrn_token": "MRN-99999",
                    "gender": "male",
                    "birth_year": 1980,
                    "age_years": 46,
                    "state": "MA",
                    "postal_code_zip3": "021",
                    "scrubbed_clinical_note": "Leaked SSN 123-45-6789",
                }
            ]
        )
        pq.write_table(tampered_table, metrics.silver_patients_parquet_path)
        return metrics

    monkeypatch.setattr(MedallionLakehousePipeline, "simulate_and_run", tampered_run)
    with pytest.raises(HIPAAComplianceError, match="Persisted Parquet HIPAA audit failed"):
        main(
            [
                "run-pipeline",
                "--patients",
                "2",
                "--seed",
                "42",
                "--output-dir",
                str(tmp_path / "tampered"),
                "--verify-hipaa",
            ]
        )
