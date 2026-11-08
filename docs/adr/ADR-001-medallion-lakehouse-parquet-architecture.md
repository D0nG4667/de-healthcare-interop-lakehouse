# ADR-001: Three-Tier Medallion Lakehouse & Columnar Apache Parquet Architecture

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Principal Forward-Deployed Data Engineer, Clinical Platform Architecture Board
- **Refs:** `BRD-001`, `SYSTEM_ARCHITECTURE.md`

---

## 1. Context

Healthcare clinical data arrives in heterogeneous wire formats: pipe-delimited HL7 v2.5.1 (`ADT^A01`, `ORU^R01`) streams and deeply nested HL7 FHIR R4 JSON/XML bundles. Storing raw clinical text files directly in an analytical warehouse exposes Protected Health Information (PHI) to unauthorized analysts, while stripping raw payloads upon ingestion destroys auditability and prevents re-parsing when clinical ontology mappings evolve.

## 2. Decision

We adopt a **Three-Tier Medallion Lakehouse Architecture (`Bronze` → `Silver` → `Gold`)** persisted in **Apache Parquet (`PyArrow`)** with `ZSTD` / `SNAPPY` columnar compression:

1. **Bronze Zone (`bronze_clinical_envelope.parquet`):** Append-only raw envelope storing unmodified HL7 v2 / FHIR payloads alongside SHA-256 digests and UTC ingestion watermarks inside a PHI-restricted security boundary.
2. **Silver Zone (`silver_*.parquet`):** Canonical, relational FHIR R4 entities (`Patient`, `Encounter`, `Observation`, `Condition`, `MedicationRequest`) that have passed the out-of-band **HIPAA Safe Harbor 18-identifier de-identification gate** and automated `HIPAAComplianceAuditor`.
3. **Gold Zone (`gold_*.parquet`):** Sub-second clinical deterioration alert tables (`NEWS2` / `qSOFA`) and aggregated population cohort tables ready for BI and clinical research.

## 3. Consequences

- **Positive:** Complete cryptographic lineage (`payload_sha256`), strict zero-PHI analytical isolation in Silver/Gold, and 6x–10x storage reduction via columnar Parquet compression.
- **Negative / Trade-offs:** Requires maintaining strict schema contracts between Bronze raw parsing and Silver tabular flattening, enforced via Pydantic v2 models (`src/healthcare_lakehouse/models/fhir_resources.py`).
