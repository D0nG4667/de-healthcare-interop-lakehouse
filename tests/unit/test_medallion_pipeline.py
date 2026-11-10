"""Unit tests for the Bronze -> Silver -> Gold Medallion Parquet Lakehouse pipeline."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq

from healthcare_lakehouse.config.settings import LakehouseSettings
from healthcare_lakehouse.lakehouse.medallion_pipeline import (
    BronzeIngestionPayload,
    MedallionLakehousePipeline,
)
from healthcare_lakehouse.models.fhir_resources import (
    FHIRBundle,
    FHIRHumanName,
    FHIRPatient,
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
    assert pipeline.verify_persisted_hipaa_tables() == ()

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


def test_medallion_pipeline_preserves_explicit_parquet_schemas_on_minimal_bundles(
    tmp_path: Path,
) -> None:
    """Verify 0-row tables and minimal Patient-only bundles preserve typed PyArrow schemas."""
    settings = LakehouseSettings(base_storage_path=tmp_path / "minimal_lakehouse")
    pipeline = MedallionLakehousePipeline(settings=settings)
    ts = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    minimal_pat = FHIRPatient(
        id="pat-minimal-1",
        identifiers=(),
        names=(FHIRHumanName(family="Minimal", given=("Case",)),),
        gender="unknown",
        birth_date=date(1985, 4, 10),
        addresses=(),
    )
    minimal_bundle = FHIRBundle(id="b-minimal", timestamp=ts, entries=(minimal_pat,))
    payload = BronzeIngestionPayload(
        source_system="MINIMAL_EHR",
        protocol="FHIR_JSON",
        message_type="Bundle",
        raw_payload=json.dumps(minimal_bundle.to_fhir_json_dict()),
    )

    metrics = pipeline.run_medallion_batch((payload,))
    assert metrics.silver_patients_written == 1
    assert metrics.silver_observations_written == 0
    assert metrics.silver_medications_written == 0

    # Even with 0 observations and 0 medications, Parquet files must have typed columns
    obs_schema = pq.read_schema(settings.silver_zone_dir / "silver_observations.parquet")
    med_schema = pq.read_schema(settings.silver_zone_dir / "silver_medications.parquet")
    assert "numeric_value" in obs_schema.names
    assert str(obs_schema.field("numeric_value").type) == "double"
    assert "rxnorm_code" in med_schema.names
    assert pipeline.verify_persisted_hipaa_tables() == ()
