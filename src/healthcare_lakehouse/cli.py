"""Enterprise CLI entrypoint for the Healthcare Clinical Interoperability Lakehouse."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from healthcare_lakehouse.config.settings import LakehouseSettings
from healthcare_lakehouse.lakehouse.medallion_pipeline import MedallionLakehousePipeline


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for healthcare-lakehouse."""
    parser = argparse.ArgumentParser(
        prog="healthcare-lakehouse",
        description=(
            "Enterprise HL7 v2 / FHIR R4 Clinical Interoperability Medallion Lakehouse CLI"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_cmd = subparsers.add_parser(
        "run-pipeline",
        help="Synthesize clinical streams and execute the Bronze->Silver->Gold Medallion pipeline.",
    )
    run_cmd.add_argument(
        "--patients",
        type=int,
        default=8,
        help="Number of longitudinal Synthea patient lifecycles to synthesize.",
    )
    run_cmd.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Deterministic PRNG seed for reproducible clinical simulation.",
    )
    run_cmd.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="Base directory for Bronze, Silver, and Gold Parquet zones.",
    )
    run_cmd.add_argument(
        "--verify-hipaa",
        action="store_true",
        help="Enforce strict HIPAA Safe Harbor 18-identifier Zero-PHI audit verification.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute the CLI command and emit structured JSON operational telemetry."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    settings = LakehouseSettings(base_storage_path=Path(args.output_dir))
    pipeline = MedallionLakehousePipeline(settings=settings)
    metrics = pipeline.simulate_and_run(patient_count=int(args.patients), seed=int(args.seed))

    summary = {
        "status": "SUCCESS",
        "hipaa_safe_harbor_compliant": metrics.hipaa_violations_detected == 0,
        "verify_hipaa_flag": bool(args.verify_hipaa),
        "bronze_records_written": metrics.bronze_records_written,
        "silver_patients_written": metrics.silver_patients_written,
        "silver_encounters_written": metrics.silver_encounters_written,
        "silver_observations_written": metrics.silver_observations_written,
        "silver_conditions_written": metrics.silver_conditions_written,
        "silver_medications_written": metrics.silver_medications_written,
        "gold_alerts_written": metrics.gold_alerts_written,
        "gold_cohort_metrics_written": metrics.gold_cohort_metrics_written,
        "high_acuity_alerts_triggered": metrics.high_acuity_alerts_triggered,
        "hipaa_violations_detected": metrics.hipaa_violations_detected,
        "gold_alerts_parquet_path": str(metrics.gold_alerts_parquet_path),
    }
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
