"""Bronze -> Silver -> Gold Medallion Parquet Lakehouse orchestrator."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict

from healthcare_lakehouse.config.settings import LakehouseSettings
from healthcare_lakehouse.models.fhir_resources import FHIRBundle
from healthcare_lakehouse.parsers.fhir_parser import FHIRParser
from healthcare_lakehouse.parsers.hl7v2_parser import HL7v2Parser
from healthcare_lakehouse.scoring.clinical_deterioration import (
    ClinicalDeteriorationAlert,
    ClinicalDeteriorationScorer,
)
from healthcare_lakehouse.security.hipaa_anonymizer import (
    HIPAAAnonymizer,
    HIPAAComplianceAuditor,
)
from healthcare_lakehouse.synthetic.hl7v2_simulator import HL7v2Simulator
from healthcare_lakehouse.synthetic.synthea_orchestrator import SyntheaOrchestrator

BRONZE_ENVELOPE_SCHEMA: pa.Schema = pa.schema(
    [
        ("envelope_id", pa.string()),
        ("source_system", pa.string()),
        ("protocol", pa.string()),
        ("message_type", pa.string()),
        ("ingested_at_utc", pa.string()),
        ("payload_sha256", pa.string()),
        ("raw_payload", pa.string()),
    ]
)

SILVER_PATIENTS_SCHEMA: pa.Schema = pa.schema(
    [
        ("patient_token", pa.string()),
        ("mrn_token", pa.string()),
        ("gender", pa.string()),
        ("birth_year", pa.int64()),
        ("age_years", pa.int64()),
        ("state", pa.string()),
        ("postal_code_zip3", pa.string()),
        ("scrubbed_clinical_note", pa.string()),
    ]
)

SILVER_ENCOUNTERS_SCHEMA: pa.Schema = pa.schema(
    [
        ("encounter_token", pa.string()),
        ("patient_token", pa.string()),
        ("status", pa.string()),
        ("encounter_class", pa.string()),
        ("facility_id", pa.string()),
        ("period_start_iso", pa.string()),
    ]
)

SILVER_OBSERVATIONS_SCHEMA: pa.Schema = pa.schema(
    [
        ("observation_token", pa.string()),
        ("patient_token", pa.string()),
        ("encounter_token", pa.string()),
        ("loinc_code", pa.string()),
        ("display", pa.string()),
        ("numeric_value", pa.float64()),
        ("string_value", pa.string()),
        ("unit", pa.string()),
        ("effective_datetime_iso", pa.string()),
    ]
)

SILVER_CONDITIONS_SCHEMA: pa.Schema = pa.schema(
    [
        ("condition_token", pa.string()),
        ("patient_token", pa.string()),
        ("encounter_token", pa.string()),
        ("code", pa.string()),
        ("display", pa.string()),
        ("onset_datetime_iso", pa.string()),
    ]
)

SILVER_MEDICATIONS_SCHEMA: pa.Schema = pa.schema(
    [
        ("medication_token", pa.string()),
        ("patient_token", pa.string()),
        ("encounter_token", pa.string()),
        ("rxnorm_code", pa.string()),
        ("display", pa.string()),
        ("dosage_text", pa.string()),
        ("authored_on_iso", pa.string()),
    ]
)

GOLD_ALERTS_SCHEMA: pa.Schema = pa.schema(
    [
        ("patient_token", pa.string()),
        ("encounter_token", pa.string()),
        ("evaluated_at_iso", pa.string()),
        ("news2_score", pa.int64()),
        ("qsofa_score", pa.int64()),
        ("risk_level", pa.string()),
        ("sepsis_suspected", pa.bool_()),
        ("recommended_response", pa.string()),
        ("triggered_parameters", pa.string()),
    ]
)

GOLD_COHORT_SCHEMA: pa.Schema = pa.schema(
    [
        ("gender", pa.string()),
        ("encounter_class", pa.string()),
        ("patient_count", pa.int64()),
        ("mean_news2_score", pa.float64()),
        ("max_news2_score", pa.int64()),
        ("suspected_sepsis_cases", pa.int64()),
    ]
)


class BronzeIngestionPayload(BaseModel):
    """Raw clinical payload entering the immutable Bronze landing zone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_system: str
    protocol: Literal["HL7V2", "FHIR_JSON", "FHIR_XML"]
    message_type: str
    raw_payload: str


class PipelineExecutionMetrics(BaseModel):
    """Operational telemetry and lineage metrics produced by a Medallion batch run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bronze_records_written: int
    silver_patients_written: int
    silver_encounters_written: int
    silver_observations_written: int
    silver_conditions_written: int
    silver_medications_written: int
    gold_alerts_written: int
    gold_cohort_metrics_written: int
    high_acuity_alerts_triggered: int
    hipaa_violations_detected: int
    bronze_parquet_path: Path
    silver_patients_parquet_path: Path
    gold_alerts_parquet_path: Path
    gold_cohort_parquet_path: Path


class MedallionLakehousePipeline:
    """Executes Bronze ingestion, Silver HIPAA de-identification, and Gold analytics."""

    def __init__(
        self,
        settings: LakehouseSettings | None = None,
        anonymizer: HIPAAAnonymizer | None = None,
        auditor: HIPAAComplianceAuditor | None = None,
        scorer: ClinicalDeteriorationScorer | None = None,
    ) -> None:
        self._settings = settings or LakehouseSettings()
        self._anonymizer = anonymizer or HIPAAAnonymizer(settings=self._settings)
        self._auditor = auditor or HIPAAComplianceAuditor()
        self._scorer = scorer or ClinicalDeteriorationScorer()
        self._fhir_parser = FHIRParser()
        self._hl7_parser = HL7v2Parser()

    def simulate_and_run(
        self,
        patient_count: int = 8,
        seed: int = 42,
    ) -> PipelineExecutionMetrics:
        """Synthesize a multi-protocol clinical cohort and execute the full Medallion pipeline."""
        orchestrator = SyntheaOrchestrator(seed=seed)
        hl7_sim = HL7v2Simulator()
        bundles = orchestrator.generate_cohort(patient_count=patient_count)

        payloads: list[BronzeIngestionPayload] = []
        for idx, bundle in enumerate(bundles):
            if idx % 3 == 1:
                payloads.append(
                    BronzeIngestionPayload(
                        source_system="SYNTHEA_XML_FEED",
                        protocol="FHIR_XML",
                        message_type="Bundle",
                        raw_payload=orchestrator.bundle_to_fhir_xml(bundle),
                    )
                )
            else:
                payloads.append(
                    BronzeIngestionPayload(
                        source_system="SYNTHEA_FHIR_GATEWAY",
                        protocol="FHIR_JSON",
                        message_type="Bundle",
                        raw_payload=json.dumps(bundle.to_fhir_json_dict()),
                    )
                )

        # Also append bedside HL7 v2.5.1 ORU^R01 and ADT^A01 telemetry streams
        hl7_bundles = orchestrator.generate_cohort(patient_count=2)
        payloads.append(
            BronzeIngestionPayload(
                source_system="ICU_MLLP_MONITOR",
                protocol="HL7V2",
                message_type="ORU^R01",
                raw_payload=hl7_sim.generate_oru_r01_from_bundle(hl7_bundles[0]),
            )
        )
        payloads.append(
            BronzeIngestionPayload(
                source_system="BEDSIDE_ADT_FEED",
                protocol="HL7V2",
                message_type="ADT^A01",
                raw_payload=hl7_sim.generate_adt_a01_from_bundle(hl7_bundles[1]),
            )
        )
        return self.run_medallion_batch(tuple(payloads))

    def run_medallion_batch(
        self,
        payloads: Sequence[BronzeIngestionPayload],
    ) -> PipelineExecutionMetrics:
        """Execute Bronze -> Silver -> Gold Medallion transitions and persist Parquet tables."""
        self._settings.ensure_directories()

        # 1. BRONZE ZONE: Immutable Raw Envelope with SHA-256 Lineage
        bronze_path = self._ingest_to_bronze(payloads)

        # 2. SILVER ZONE: Canonical FHIR R4 Normalization & HIPAA Safe Harbor Gate
        clean_bundles: list[FHIRBundle] = []
        total_violations = 0
        for item in payloads:
            if item.protocol == "FHIR_JSON":
                raw_bundle = self._fhir_parser.parse_json_bundle(item.raw_payload)
            elif item.protocol == "FHIR_XML":
                raw_bundle = self._fhir_parser.parse_xml_bundle(item.raw_payload)
            else:
                raw_bundle = self._hl7_parser.translate_to_fhir_bundle(item.raw_payload)

            clean_bundle = self._anonymizer.anonymize_bundle(raw_bundle)
            audit_report = self._auditor.assert_bundle_compliant(clean_bundle)
            total_violations += len(audit_report.violations)
            clean_bundles.append(clean_bundle)

        silver_counts, silver_patients_path = self._write_silver_tables(clean_bundles)

        # 3. GOLD ZONE: Stateful NEWS2/qSOFA Deterioration Alerts & Research Cohort Metrics
        alerts: list[ClinicalDeteriorationAlert] = [
            self._scorer.evaluate_bundle(b) for b in clean_bundles
        ]
        gold_alerts_path = self._write_gold_alerts(alerts)
        gold_cohort_path, cohort_rows_written = self._write_gold_cohort_metrics(
            clean_bundles, alerts
        )

        high_acuity_count = sum(1 for a in alerts if a.risk_level == "HIGH")

        return PipelineExecutionMetrics(
            bronze_records_written=len(payloads),
            silver_patients_written=silver_counts["patients"],
            silver_encounters_written=silver_counts["encounters"],
            silver_observations_written=silver_counts["observations"],
            silver_conditions_written=silver_counts["conditions"],
            silver_medications_written=silver_counts["medications"],
            gold_alerts_written=len(alerts),
            gold_cohort_metrics_written=cohort_rows_written,
            high_acuity_alerts_triggered=high_acuity_count,
            hipaa_violations_detected=total_violations,
            bronze_parquet_path=bronze_path,
            silver_patients_parquet_path=silver_patients_path,
            gold_alerts_parquet_path=gold_alerts_path,
            gold_cohort_parquet_path=gold_cohort_path,
        )

    def verify_persisted_hipaa_tables(self) -> tuple[str, ...]:
        """Scan persisted Silver and Gold Parquet files on disk for any PHI leak or bad token."""
        violations: list[str] = []
        silver_dir = self._settings.silver_zone_dir
        gold_dir = self._settings.gold_zone_dir

        table_checks: tuple[tuple[Path, tuple[str, ...], tuple[str, ...]], ...] = (
            (
                silver_dir / "silver_patients.parquet",
                ("patient_token", "mrn_token"),
                ("scrubbed_clinical_note",),
            ),
            (
                silver_dir / "silver_encounters.parquet",
                ("encounter_token", "patient_token"),
                (),
            ),
            (
                silver_dir / "silver_observations.parquet",
                ("observation_token", "patient_token", "encounter_token"),
                ("string_value",),
            ),
            (
                silver_dir / "silver_conditions.parquet",
                ("condition_token", "patient_token", "encounter_token"),
                (),
            ),
            (
                silver_dir / "silver_medications.parquet",
                ("medication_token", "patient_token", "encounter_token"),
                ("dosage_text",),
            ),
            (
                gold_dir / "gold_patient_deterioration_alerts.parquet",
                ("patient_token",),
                (),
            ),
        )

        for parquet_path, token_cols, text_cols in table_checks:
            rows = self.read_parquet_records(parquet_path)
            for row_idx, row in enumerate(rows):
                for tok_col in token_cols:
                    val = str(row.get(tok_col, ""))
                    if val != "UNKNOWN-PATIENT" and not HIPAAComplianceAuditor.is_valid_kms_token(
                        val
                    ):
                        violations.append(
                            f"{parquet_path.name}[{row_idx}].{tok_col} invalid token: {val!r}"
                        )
                for txt_col in text_cols:
                    txt_val = str(row.get(txt_col, ""))
                    if txt_val:
                        violations.extend(
                            HIPAAComplianceAuditor.scan_text_for_phi(
                                txt_val, f"{parquet_path.name}[{row_idx}].{txt_col}"
                            )
                        )
        return tuple(violations)

    def _ingest_to_bronze(self, payloads: Sequence[BronzeIngestionPayload]) -> Path:
        now_iso = datetime.now(tz=UTC).isoformat()
        rows: list[dict[str, Any]] = []
        for idx, item in enumerate(payloads, start=1):
            digest = hashlib.sha256(item.raw_payload.encode("utf-8")).hexdigest()
            rows.append(
                {
                    "envelope_id": f"brz-{idx:05d}-{digest[:10]}",
                    "source_system": item.source_system,
                    "protocol": item.protocol,
                    "message_type": item.message_type,
                    "ingested_at_utc": now_iso,
                    "payload_sha256": digest,
                    "raw_payload": item.raw_payload,
                }
            )
        path = self._settings.bronze_zone_dir / "bronze_clinical_envelope.parquet"
        self._write_parquet(rows, path, BRONZE_ENVELOPE_SCHEMA)
        return path

    def _write_silver_tables(
        self,
        bundles: Sequence[FHIRBundle],
    ) -> tuple[dict[str, int], Path]:
        patient_rows: list[dict[str, Any]] = []
        encounter_rows: list[dict[str, Any]] = []
        observation_rows: list[dict[str, Any]] = []
        condition_rows: list[dict[str, Any]] = []
        medication_rows: list[dict[str, Any]] = []

        for bundle in bundles:
            for pat in bundle.patients():
                addr = pat.addresses[0] if pat.addresses else None
                mrn_tok = pat.identifiers[0].value if pat.identifiers else pat.id
                patient_rows.append(
                    {
                        "patient_token": pat.id,
                        "mrn_token": mrn_tok,
                        "gender": pat.gender,
                        "birth_year": pat.birth_date.year,
                        "age_years": pat.age_years or 0,
                        "state": addr.state if addr is not None else "UNK",
                        "postal_code_zip3": addr.postal_code if addr is not None else "000",
                        "scrubbed_clinical_note": pat.clinical_note or "",
                    }
                )
            for enc in bundle.encounters():
                encounter_rows.append(
                    {
                        "encounter_token": enc.id,
                        "patient_token": enc.subject_id,
                        "status": enc.status,
                        "encounter_class": enc.class_code,
                        "facility_id": enc.facility_id,
                        "period_start_iso": enc.period_start.isoformat(),
                    }
                )
            for obs in bundle.observations():
                coding = obs.code.coding[0]
                observation_rows.append(
                    {
                        "observation_token": obs.id,
                        "patient_token": obs.subject_id,
                        "encounter_token": obs.encounter_id,
                        "loinc_code": coding.code,
                        "display": coding.display,
                        "numeric_value": (
                            obs.value_quantity.value if obs.value_quantity is not None else None
                        ),
                        "string_value": obs.value_string or "",
                        "unit": obs.value_quantity.unit if obs.value_quantity is not None else "",
                        "effective_datetime_iso": obs.effective_datetime.isoformat(),
                    }
                )
            for cond in bundle.conditions():
                coding = cond.code.coding[0]
                condition_rows.append(
                    {
                        "condition_token": cond.id,
                        "patient_token": cond.subject_id,
                        "encounter_token": cond.encounter_id,
                        "code": coding.code,
                        "display": coding.display,
                        "onset_datetime_iso": cond.onset_datetime.isoformat(),
                    }
                )
            for med in bundle.medication_requests():
                coding = med.medication_code.coding[0]
                medication_rows.append(
                    {
                        "medication_token": med.id,
                        "patient_token": med.subject_id,
                        "encounter_token": med.encounter_id,
                        "rxnorm_code": coding.code,
                        "display": coding.display,
                        "dosage_text": med.dosage_text,
                        "authored_on_iso": med.authored_on.isoformat(),
                    }
                )

        silver_dir = self._settings.silver_zone_dir
        patients_path = silver_dir / "silver_patients.parquet"
        self._write_parquet(patient_rows, patients_path, SILVER_PATIENTS_SCHEMA)
        self._write_parquet(
            encounter_rows, silver_dir / "silver_encounters.parquet", SILVER_ENCOUNTERS_SCHEMA
        )
        self._write_parquet(
            observation_rows,
            silver_dir / "silver_observations.parquet",
            SILVER_OBSERVATIONS_SCHEMA,
        )
        self._write_parquet(
            condition_rows, silver_dir / "silver_conditions.parquet", SILVER_CONDITIONS_SCHEMA
        )
        self._write_parquet(
            medication_rows, silver_dir / "silver_medications.parquet", SILVER_MEDICATIONS_SCHEMA
        )

        counts = {
            "patients": len(patient_rows),
            "encounters": len(encounter_rows),
            "observations": len(observation_rows),
            "conditions": len(condition_rows),
            "medications": len(medication_rows),
        }
        return counts, patients_path

    def _write_gold_alerts(self, alerts: Sequence[ClinicalDeteriorationAlert]) -> Path:
        rows: list[dict[str, Any]] = [
            {
                "patient_token": a.patient_token,
                "encounter_token": a.encounter_token,
                "evaluated_at_iso": a.evaluated_at.isoformat(),
                "news2_score": a.news2_score,
                "qsofa_score": a.qsofa_score,
                "risk_level": a.risk_level,
                "sepsis_suspected": a.sepsis_suspected,
                "recommended_response": a.recommended_response,
                "triggered_parameters": ",".join(a.triggered_parameters),
            }
            for a in alerts
        ]
        path = self._settings.gold_zone_dir / "gold_patient_deterioration_alerts.parquet"
        self._write_parquet(rows, path, GOLD_ALERTS_SCHEMA)
        return path

    def _write_gold_cohort_metrics(
        self,
        bundles: Sequence[FHIRBundle],
        alerts: Sequence[ClinicalDeteriorationAlert],
    ) -> tuple[Path, int]:
        grouped_scores: dict[tuple[str, str], list[int]] = defaultdict(list)
        grouped_sepsis: dict[tuple[str, str], int] = defaultdict(int)

        for bundle, alert in zip(bundles, alerts, strict=True):
            patients = bundle.patients()
            encounters = bundle.encounters()
            gender = patients[0].gender if patients else "unknown"
            enc_class = encounters[0].class_code if encounters else "AMB"
            key = (gender, enc_class)
            grouped_scores[key].append(alert.news2_score)
            if alert.sepsis_suspected:
                grouped_sepsis[key] += 1

        cohort_rows: list[dict[str, Any]] = []
        for (grp_gender, grp_class), scores in sorted(grouped_scores.items()):
            cohort_rows.append(
                {
                    "gender": grp_gender,
                    "encounter_class": grp_class,
                    "patient_count": len(scores),
                    "mean_news2_score": round(sum(scores) / len(scores), 2),
                    "max_news2_score": max(scores),
                    "suspected_sepsis_cases": grouped_sepsis[(grp_gender, grp_class)],
                }
            )

        path = self._settings.gold_zone_dir / "gold_cohort_clinical_metrics.parquet"
        self._write_parquet(cohort_rows, path, GOLD_COHORT_SCHEMA)
        return path, len(cohort_rows)

    def _write_parquet(
        self,
        rows: Sequence[dict[str, Any]],
        path: Path,
        schema: pa.Schema,
    ) -> None:
        table = pa.Table.from_pylist(list(rows), schema=schema)
        pq.write_table(table, path, compression=self._settings.parquet_compression)

    @staticmethod
    def read_parquet_records(path: Path) -> list[dict[str, Any]]:
        """Read a Parquet file from Bronze, Silver, or Gold storage into Python dicts."""
        table = pq.read_table(path)
        result: list[dict[str, Any]] = table.to_pylist()
        return result
