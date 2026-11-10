# Rule 01: Medallion Lakehouse & Clinical Interoperability Architecture

## Scope
Applies to all modules in `src/healthcare_lakehouse/models/`, `src/healthcare_lakehouse/parsers/`, `src/healthcare_lakehouse/scoring/`, and `src/healthcare_lakehouse/lakehouse/`.

## Architectural Principles

1. **Multi-Protocol Ingestion (`HL7 v2.5.1` & `HL7 FHIR R4`):**
   - Legacy bedside feeds (`ADT^A01`, `ADT^A03`, `ADT^A08`, `ORU^R01`) must be parsed deterministically from pipe-delimited segments (`MSH`, `PID`, `PV1`, `OBR`, `OBX`, `DG1`) and translated into canonical FHIR R4 `Bundle` structures before entering the Silver transformation stage.
   - Native FHIR R4 feeds (`JSON` and `XML`) must be parsed into the identical canonical domain models (`FHIRBundle`, `FHIRPatient`, `FHIREncounter`, `FHIRObservation`, `FHIRCondition`, `FHIRMedicationRequest`).

2. **Three-Tier Medallion Lakehouse Contracts:**
   - **Bronze Layer (`bronze_clinical_envelope.parquet`):**
     - Schema: `envelope_id`, `source_system`, `protocol` (`HL7V2` | `FHIR_JSON` | `FHIR_XML`), `message_type`, `ingested_at_utc`, `payload_sha256`, `raw_payload`.
     - Purpose: Immutable replayability, cryptographic audit trail, and schema-drift recovery.
   - **Silver Layer (`silver_patients.parquet`, `silver_encounters.parquet`, `silver_observations.parquet`, `silver_conditions.parquet`, `silver_medications.parquet`):**
     - Schema: Flattened, strongly typed, HIPAA Safe Harbor de-identified clinical tables with KMS HMAC-SHA256 pseudonymized foreign keys (`patient_token`, `encounter_token`) and shifted ISO-8601 timestamps.
   - **Gold Layer (`gold_patient_deterioration_alerts.parquet`, `gold_cohort_clinical_metrics.parquet`):**
     - Schema: Enriched clinical decision-support tables combining stateful **NEWS2** / **qSOFA** acuity scores, risk tiers (`LOW`, `LOW_MEDIUM`, `MEDIUM`, `HIGH`), sepsis flags, and aggregated cohort statistics.

3. **Columnar Storage Optimization:**
   - Persist all lakehouse tables as Apache Parquet via `pyarrow.parquet` (and compatible with `pyspark.sql.DataFrame.write.parquet`) using `SNAPPY` or `ZSTD` compression and explicit `pyarrow.Schema` definitions to prevent silent type drift.
