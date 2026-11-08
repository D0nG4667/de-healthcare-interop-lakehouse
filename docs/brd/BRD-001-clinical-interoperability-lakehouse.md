# BRD-001: Business Requirements Document — Healthcare Clinical Interoperability Lakehouse

| Metadata | Details |
| :--- | :--- |
| **Document ID** | `BRD-001` |
| **Project Title** | Enterprise HL7 v2 / FHIR R4 Clinical Interoperability Medallion Lakehouse |
| **Version** | `1.0.0` |
| **Status** | `APPROVED / PRODUCTION-READY` |
| **Author** | Principal Forward-Deployed Data Engineer |
| **Regulatory Scope** | HIPAA Privacy Rule (45 CFR §164.514(b)(2) Safe Harbor), HIPAA Security Rule (45 CFR §164.312), ONC 21st Century Cures Act (HL7 FHIR R4 v4.0.1) |

---

## 1. Executive Summary & Business Problem

Integrated healthcare delivery networks (IDNs), intensive care units (ICUs), and clinical research institutions operate across heterogeneous legacy and modern health information systems. Bedside physiological monitors and legacy Admission-Discharge-Transfer (ADT) engines emit real-time **HL7 v2.5.1 pipe-delimited (`MLLP`)** messages, while modern Electronic Health Record (EHR) systems exchange **HL7 FHIR R4 (`JSON` / `XML`)** bundles.

Without a unified, privacy-preserving interoperability lakehouse:
1. **Delayed Clinical Intervention:** High-acuity physiological deterioration (sepsis, acute respiratory failure) is not scored consistently across legacy and modern feeds in sub-second time.
2. **HIPAA Compliance Liability:** Raw clinical payloads contain all **18 HIPAA Safe Harbor PHI identifiers** embedded in both structured segments (`PID`, `Patient`) and unstructured free-text clinical notes. Uncontrolled ingestion into analytics environments creates severe regulatory penalty exposure (\$100 to \$50,000+ per violation, up to \$1.5M+/year per category).
3. **Analytical Data Silos:** Clinical researchers cannot join legacy HL7 v2 bedside vitals with FHIR R4 medication orders and diagnoses in a high-performance columnar format without losing longitudinal temporal relationships.

---

## 2. Business Objectives & Success Metrics (KPIs)

| Objective ID | Business Objective | Target KPI / SLA | Verification Mechanism |
| :--- | :--- | :--- | :--- |
| **BO-01** | **Zero-PHI Analytical Leakage** | `0` unmasked HIPAA Safe Harbor identifiers in Silver/Gold zones (`100.0%` compliance) | Automated `HIPAAComplianceAuditor` gate on every bundle + CI/CD repository scan |
| **BO-02** | **Sub-Second Acuity Scoring** | `< 5 ms` per clinical bundle evaluation for **NEWS2** and **qSOFA** sepsis alerting | `ClinicalDeteriorationScorer` unit & integration benchmarks |
| **BO-03** | **Multi-Protocol Interoperability** | `100%` lossless normalization of `HL7 v2.5.1 (ADT/ORU)`, `FHIR R4 JSON`, and `FHIR R4 XML` | End-to-end Medallion integration test suite (`test_end_to_end_lakehouse.py`) |
| **BO-04** | **Longitudinal Research Integrity** | `100%` preservation of intra-patient hour/minute intervals across date-shifted records | Deterministic HMAC-SHA256 patient date-shift verification in `test_hipaa_anonymizer.py` |
| **BO-05** | **Engineering Reliability** | `100.0%` line and branch test coverage; `0` static typing or lint defects | Enforced via `lefthook` pre-push hooks and GitHub Actions CI matrix |

---

## 3. Stakeholder Register

| Stakeholder Group | Role & Interest | Key Deliverables Consumed |
| :--- | :--- | :--- |
| **Critical Care / ICU Clinicians** | Rapid identification of acute sepsis and respiratory deterioration | `gold_patient_deterioration_alerts.parquet` (NEWS2 & qSOFA risk tiers) |
| **Chief Information Security Officer (CISO) & Privacy Officer** | Enforcement of 45 CFR §164.514(b)(2) Safe Harbor & KMS encryption key rotation | `HIPAAAnonymizer`, `KMSTokenizer`, `HIPAAComplianceAuditor`, Audit Logs |
| **Clinical Research & Population Health Data Scientists** | Longitudinal cohort analysis preserving LOINC, SNOMED-CT, RxNorm, and ICD-10 semantics | Silver canonical FHIR Parquet tables & `gold_cohort_clinical_metrics.parquet` |
| **Data Engineering & Platform Operations** | Reliable, observable, schema-enforced Bronze/Silver/Gold pipelines | `MedallionLakehousePipeline`, CLI, Docker Compose stack, CI/CD pipelines |

---

## 4. Functional Requirements (FR)

- **FR-01 (Multi-Protocol Ingestion to Bronze):** The system SHALL ingest raw `HL7 v2.5.1` (including MLLP-framed bytes), `HL7 FHIR R4 JSON`, and `HL7 FHIR R4 XML` payloads into an immutable Bronze Parquet zone (`bronze_clinical_envelope.parquet`) with SHA-256 payload digests and UTC ingestion timestamps.
- **FR-02 (Legacy HL7 v2 to FHIR R4 Translation):** The system SHALL parse `MSH`, `PID`, `PV1`, `OBR`, `OBX`, and `DG1` segments and translate them into canonical `FHIRBundle` resources (`Patient`, `Encounter`, `Observation`, `Condition`).
- **FR-03 (HIPAA Safe Harbor 18-Identifier De-Identification):** The system SHALL strip, mask, or cryptographically tokenize all 18 PHI categories prior to Silver zone persistence, including:
  - Deterministic KMS HMAC-SHA256 tokenization of patient, MRN, encounter, observation, condition, medication, and practitioner IDs.
  - Patient-consistent longitudinal date shifting (`[-365, -1]` days) preserving exact elapsed time between clinical events.
  - Elderly age top-coding (`age >= 90` mapped to `90` with birth year capped accordingly).
  - Postal code truncation to 3 digits (`ZIP-3`) and masking to `"000"` for all 17 restricted low-population Census prefixes (`<= 20,000` residents).
  - Regex and entity scrubbing of SSNs, phones, emails, IPv4 addresses, URLs, MRNs, and names in free-text clinical notes.
- **FR-04 (Stateful Clinical Deterioration Scoring):** The system SHALL compute Royal College of Physicians **NEWS2** (`0..20`) and **qSOFA** (`0..3`) scores from LOINC-coded vital signs and classify acuity into `LOW`, `LOW_MEDIUM`, `MEDIUM`, and `HIGH` risk tiers with sepsis suspicion flags.
- **FR-05 (Realistic Synthetic Clinical Data Generation):** The system SHALL provide Synthea™-compatible JSON state-machine disease modules (`sepsis_deterioration_module.json`, `cardiopulmonary_chronic_module.json`) and an HL7 v2.5.1 stream simulator to validate pipelines without real patient PHI.

---

## 5. Non-Functional Requirements (NFR)

- **NFR-01 (Security & Key Rotation):** Cryptographic tokens MUST be prefixed with the KMS key identifier (`<kid>:<hmac>`) so key rotation does not invalidate historical tokens.
- **NFR-02 (Storage Efficiency):** All Bronze, Silver, and Gold tables MUST be stored in Apache Parquet with columnar compression (`ZSTD` or `SNAPPY`).
- **NFR-03 (Code Quality & Testability):** All production code MUST maintain `100.0%` line and branch test coverage (`pytest --cov-fail-under=100`) and pass `mypy --strict`.
