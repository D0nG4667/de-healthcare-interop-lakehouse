"""Unit tests for the Bronze -> Silver -> Gold Medallion Parquet Lakehouse pipeline."""

from __future__ import annotations

from pathlib import Path

from healthcare_lakehouse.config.settings import LakehouseSettings
from healthcare_lakehouse.lakehouse.medallion_pipeline import (
    BronzeIngestionPayload,
    MedallionLakehousePipeline,
)
from healthcare_lakehouse.synthetic.hl7v2_simulator import HL7v2Simulator
from healthcare_lakehouse.synthetic.synthea_orchestrator import SyntheaOrchestrator


def test_medallion_pipeline_ingests_fhir_json_xml_and_hl7v2_to_gold_parquet(
    tmp_path: Path,
) -> None:
    """Verify Bronze, Silver, and Gold Parquet materialization across all 3 clinical protocols."""
    settings = LakehouseSettings(base_storage_path=tmp_path / "lakehouse")
    pipeline = MedallionLakehousePipeline(settings=settings)
    orchestrator = SyntheaOrchestrator(seed=42)
    hl7_sim = HL7v2Simulator()

    cohort = orchestrator.generate_cohort(patient_count=4)
    import json

    payloads = (
        BronzeIngestionPayload(
            source_system="SYNTHEA_EHR",
            protocol="FHIR_JSON",
            message_type="Bundle",
            raw_payload=json.dumps(cohort[0].to_fhir_json_dict()),
        ),
        BronzeIngestionPayload(
            source_system="SYNTHEA_XML_GATEWAY",
            protocol="FHIR_XML",
            message_type="Bundle",
            raw_payload=orchestrator.bundle_to_fhir_xml(cohort[1]),
        ),
        BronzeIngestionPayload(
            source_system="ICU_MLLP_GATEWAY",
            protocol="HL7V2",
            message_type="ORU^R01",
            raw_payload=hl7_sim.generate_oru_r01_from_bundle(cohort[2]),
        ),
        BronzeIngestionPayload(
            source_system="BEDSIDE_ADT",
            protocol="HL7V2",
            message_type="ADT^A01",
            raw_payload=hl7_sim.generate_adt_a01_from_bundle(cohort[3]),
        ),
    )

    metrics = pipeline.run_medallion_batch(payloads)
    assert metrics.bronze_records_written == 4
    assert metrics.silver_patients_written == 4
    assert metrics.silver_encounters_written == 4
    assert metrics.silver_observations_written > 0
    assert metrics.silver_conditions_written > 0
    assert metrics.silver_medications_written > 0
    assert metrics.gold_alerts_written == 4
    assert metrics.gold_cohort_metrics_written > 0
    assert metrics.high_acuity_alerts_triggered >= 1
    assert metrics.hipaa_violations_detected == 0

    # Verify Parquet files exist on disk and are readable via PyArrow
    bronze_rows = pipeline.read_parquet_records(metrics.bronze_parquet_path)
    silver_patients = pipeline.read_parquet_records(metrics.silver_patients_parquet_path)
    gold_alerts = pipeline.read_parquet_records(metrics.gold_alerts_parquet_path)

    assert len(bronze_rows) == 4
    assert len(silver_patients) == 4
    assert len(gold_alerts) == 4
    for pat_row in silver_patients:
        assert ":" in str(pat_row["patient_token"])
        assert pat_row["postal_code_zip3"] != "036"
        assert int(pat_row["age_years"]) <= 90
