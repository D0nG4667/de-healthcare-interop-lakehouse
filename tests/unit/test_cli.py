"""Unit tests for the Healthcare Interoperability Lakehouse CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthcare_lakehouse.cli import main


def test_cli_run_pipeline_executes_and_prints_json_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify the CLI run-pipeline subcommand executes end-to-end and outputs JSON metrics."""
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
