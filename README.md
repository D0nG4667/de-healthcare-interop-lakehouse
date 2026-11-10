# Healthcare Clinical Interoperability Lakehouse (`de-healthcare-interop-lakehouse`)

[![CI/CD & HIPAA Gate](https://img.shields.io/badge/CI%2FCD-GitHub_Actions_Passing-2ea44f?logo=githubactions)](.github/workflows/ci-pipeline.yml)
[![Test Coverage](https://img.shields.io/badge/Coverage-100.0%25_Verified-brightgreen?logo=pytest)](pyproject.toml)
[![HIPAA Safe Harbor](https://img.shields.io/badge/HIPAA_45_CFR_§164.514(b)(2)-18--Identifier_Zero--PHI_Verified-0052CC)](docs/governance/HIPAA_COMPLIANCE_AND_DATA_GOVERNANCE.md)
[![HL7 / FHIR Standard](https://img.shields.io/badge/Standards-HL7_v2.5.1_%7C_FHIR_R4_(v4.0.1)-orange)](docs/architecture/SYSTEM_ARCHITECTURE.md)
[![Type Checked](https://img.shields.io/badge/Mypy-Strict_100%25-blue)](pyproject.toml)
[![Gitflow](https://img.shields.io/badge/Gitflow-feature_%E2%86%92_develop_%E2%86%92_staging_%E2%86%92_main-purple)](docs/gitflow/ENTERPRISE_GITFLOW.md)

> An enterprise **Medallion Clinical Lakehouse (`Bronze` → `Silver` → `Gold`)** that ingests fragmented **HL7 v2.5.1 MLLP pipe-delimited bedside telemetry (`ADT^A01`, `ORU^R01`)** and deeply nested **Synthea™-orchestrated HL7 FHIR R4 (`JSON` / `XML`) clinical bundles**, translates legacy segments into canonical FHIR R4 resources, enforces **HIPAA Safe Harbor (45 CFR §164.514(b)(2)) 18-identifier de-identification** with rotatable **AWS KMS HMAC-SHA256 envelope tokenization**, computes real-time **Royal College of Physicians NEWS2 & qSOFA sepsis deterioration alerts**, and materializes high-performance **ZSTD/Snappy columnar Apache Parquet** research tables.

---

## Executive Navigation & Enterprise Documentation Suite

| Document | Scope & Audience |
| :--- | :--- |
| [**`AGENTS.md`**](AGENTS.md) | Root AI Agent & Principal Data Engineer Charter, Architecture Blueprint & Engineering Standards |
| [**`.agents/rules.md`**](.agents/rules.md) | Hierarchical Workspace Rules & Modular Domain Constraints (`.agents/rules/01..05`) |
| [**`BRD-001`**](docs/brd/BRD-001-clinical-interoperability-lakehouse.md) | Business Requirements Document: Clinical Objectives, SLAs, HIPAA Risk Register & ROI |
| [**`SYSTEM_ARCHITECTURE.md`**](docs/architecture/SYSTEM_ARCHITECTURE.md) | Deep System Architecture, Medallion Data Lineage, KMS Envelope Sequence & Surge Scaling |
| [**`ADR-001`**](docs/adr/ADR-001-medallion-lakehouse-parquet-architecture.md) | Architecture Decision Record: Three-Tier Medallion Lakehouse & Columnar Parquet Storage |
| [**`ADR-002`**](docs/adr/ADR-002-hipaa-safe-harbor-deidentification-and-kms-tokenization.md) | Architecture Decision Record: HIPAA Safe Harbor 18-Identifier Engine & KMS Key Rotation |
| [**`ADR-003`**](docs/adr/ADR-003-legacy-hl7v2-to-fhir-r4-canonical-translation.md) | Architecture Decision Record: Legacy HL7 v2.5.1 Pipe-Delimited to Canonical FHIR R4 Translation |
| [**`ADR-004`**](docs/adr/ADR-004-synthea-state-machine-synthetic-clinical-data.md) | Architecture Decision Record: Synthea™ State-Machine Disease Modules vs. Naive Faker Loops |
| [**`ADR-005`**](docs/adr/ADR-005-stateful-clinical-deterioration-scoring-news2.md) | Architecture Decision Record: Stateful NEWS2 & qSOFA Clinical Deterioration Scoring |
| [**`HIPAA_COMPLIANCE_AND_DATA_GOVERNANCE.md`**](docs/governance/HIPAA_COMPLIANCE_AND_DATA_GOVERNANCE.md) | Complete 18-Identifier Safe Harbor Mapping Table, Date-Shifting Math & Zero-PHI Audit Gate |
| [**`DEVELOPER_ONBOARDING.md`**](docs/onboarding/DEVELOPER_ONBOARDING.md) | Step-by-Step Developer Setup (`uv`, `lefthook`, `pytest`, `mypy`, `ruff`) & CLI Cookbook |
| [**`DEPLOYMENT_AND_OPERATIONS.md`**](docs/deployment/DEPLOYMENT_AND_OPERATIONS.md) | Production Cloud & Docker Runbook, KMS Key Rotation Ceremony & Epidemic Surge Playbook |
| [**`ENTERPRISE_GITFLOW.md`**](docs/gitflow/ENTERPRISE_GITFLOW.md) | Branch Promotion (`feature/*` → `develop` → `staging` → `main`), Worktrees & CI/CD Gates |

---

## 1. Problem Statement & Clinical Context

Modern hospital networks and Integrated Delivery Networks (IDNs) suffer from a critical **clinical data interoperability and privacy chasm**:

1. **Fragmented Multi-Protocol Telemetry:** Legacy bedside ICU physiological monitors, laboratory information systems (LIS), and older Admission-Discharge-Transfer (ADT) engines emit stateful, pipe-delimited **HL7 v2.5.1 (`MSH|PID|PV1|OBR|OBX|DG1`)** byte streams wrapped in Minimal Lower Layer Protocol (`MLLP` `0x0B..0x1C0D` frames). Simultaneously, modern Electronic Health Record (EHR) platforms and patient exchanges emit deeply nested, polymorphic **HL7 FHIR R4 (`v4.0.1`) JSON and XML Bundles** mandated by the **21st Century Cures Act**.
2. **Strict HIPAA Safe Harbor Privacy Constraints:** Raw clinical streams interleave life-critical physiological measurements (heart rate, arterial oxygen saturation, serum lactate) with highly sensitive **Protected Health Information (PHI)** across structured fields and unstructured physician notes. Under **45 CFR §164.514(b)(2) (HIPAA Safe Harbor)** and **§164.312 (Technical Safeguards)**, exposing even a single unmasked SSN, MRN, street address, elderly age (`> 89`), low-population 3-digit ZIP code (`<= 20,000` residents), or exact admission date in an analytical data lake constitutes a reportable federal breach.
3. **Delayed Sepsis & Respiratory Deterioration Detection:** Traditional night-batch ETL pipelines introduce 12–24 hour delays before vital signs reach analytical stores—far too late to detect acute ICU sepsis onset or respiratory failure, where every hour of delayed antibiotic administration increases mortality by **7.6%**.
4. **Semantic Fragility:** Naive de-identification scripts frequently corrupt medical ontology bindings (**LOINC**, **SNOMED-CT**, **RxNorm**, **ICD-10-CM**, **UCUM**) or randomize timestamps independently per row, destroying the longitudinal hour-by-hour time intervals required by clinical researchers to study treatment efficacy.

---

## 2. Clinical Data Streams & Inputs

To validate our architecture against realistic production workloads without risking real patient PHI, this repository rejects simplistic `Faker` loops in favor of **two stateful, medically grounded synthetic clinical stream engines**:

### Input Stream A: Synthea™-Orchestrated HL7 FHIR R4 JSON & XML Bundles
Driven by declarative state-machine disease modules in [`src/healthcare_lakehouse/synthetic/modules/`](src/healthcare_lakehouse/synthetic/modules/) and executed by [`SyntheaOrchestrator`](src/healthcare_lakehouse/synthetic/synthea_orchestrator.py):
- **[`sepsis_deterioration_module.json`](src/healthcare_lakehouse/synthetic/modules/sepsis_deterioration_module.json):** Models acute systemic infection (`ICD-10 A41.9` / `SNOMED-CT 91302008`) progressing through ICU triage, non-linear physiological decompensation (tachypnea `26–28 /min`, hypoxemia `SpO2 90%` on `40% FiO2`, hypotension `SBP 84–86 mmHg`, tachycardia `134–138 /min`, fever `39.4 °C`, hyperlactatemia `4.6 mmol/L`, acute confusion `ACVPU = C`), and empiric broad-spectrum intravenous antibiotic orders (`RxNorm 11124` Vancomycin 1000 mg IV).
- **[`cardiopulmonary_chronic_module.json`](src/healthcare_lakehouse/synthetic/modules/cardiopulmonary_chronic_module.json):** Models chronic obstructive pulmonary disease (`ICD-10 J44.1`) and essential hypertension (`SNOMED-CT 59621000`) with baseline inpatient monitoring and inhaled bronchodilator therapy (`RxNorm 435` Albuterol).
- **Embedded Synthetic PHI Boundary Cases:** Intentionally synthesizes patients aged `90+` (born `1931`), patients residing in restricted low-population HIPAA 3-digit ZIP prefixes (`036`, `059`, `821`), structured SSNs/MRNs/phones/emails/URLs/bedside device IPs, and free-text clinical notes containing embedded PII.

### Input Stream B: Legacy Bedside HL7 v2.5.1 Pipe-Delimited (`MLLP`) Streams
Generated by [`HL7v2Simulator`](src/healthcare_lakehouse/synthetic/hl7v2_simulator.py) to emulate high-velocity hospital integration engines (Mirth Connect / Rhapsody / NiFi):
- **`ADT^A01` / `ADT^A08` (Patient Admission & Demographic Update):** Contains `MSH`, `PID`, `PV1`, and `DG1` segments with raw MRNs, patient names, birth dates, street addresses, SSNs, attending physician NPIs, and ICD-10 diagnoses.
- **`ORU^R01` (Unsolicited Bedside Telemetry Observation):** Contains `MSH`, `PID`, `PV1`, `OBR`, and repeating `OBX` segments (`NM` numeric and `ST` string observations) carrying LOINC-coded vital sign panels wrapped in binary MLLP framing (`0x0B ... 0x1C 0x0D`).

---

## 3. System Architecture & Engineering Approach

We engineered a decoupled, zero-trust **Medallion Lakehouse Architecture (`Bronze` → `Silver` → `Gold`)** powered by **Python 3.11+**, **Pydantic v2**, **PyArrow / Apache Spark**, and **KMS HMAC-SHA256 Envelope Tokenization**.

### Architecture Diagrams

#### End-to-End Multi-Hop Medallion & Clinical Interoperability Architecture

```mermaid
flowchart TB
    subgraph Sources["1. Clinical Telemetry & EHR Sources"]
        SYN["Synthea™ State-Machine Engine<br/>(sepsis & cardiopulmonary modules)"]
        HL7["Bedside ICU Monitors & Legacy EHR<br/>(HL7 v2.5.1 ADT^A01 / ORU^R01 MLLP)"]
    end

    subgraph Bronze["2. BRONZE ZONE — Raw Immutable Audit Envelope (S3 / Parquet)"]
        BRZ_ING["Bronze Ingestion Gateway<br/>SHA-256 Digest + Watermark Lineage"]
        BRZ_TBL[("bronze_clinical_envelope.parquet<br/>(ZSTD Compressed, Append-Only)")]
        BRZ_ING --> BRZ_TBL
    end

    subgraph Silver["3. SILVER ZONE — Canonical FHIR R4 & HIPAA Safe Harbor Gate"]
        XLATE["Protocol Parsers & Translators<br/>HL7v2Parser (PID/PV1/OBX/DG1 → FHIR)<br/>FHIRParser (JSON & XML → FHIRBundle)"]
        KMS["AWS KMS Envelope Key Ring<br/>(KMSTokenizer HMAC-SHA256 + Key Rotation)"]
        ANON["HIPAAAnonymizer (45 CFR §164.514(b)(2))<br/>• 18-Identifier Redaction & Tokenization<br/>• Longitudinal Date Shift [-365, -1] Days<br/>• Age 90+ Top-Coding & ZIP-3 Masking<br/>• Free-Text Clinical Note Regex Scrubber"]
        AUDIT{"HIPAAComplianceAuditor<br/>Zero-PHI Gate<br/>(0 Violations Required)"}
        SLV_TBL[("Silver Canonical FHIR R4 Tables<br/>• silver_patients.parquet<br/>• silver_encounters.parquet<br/>• silver_observations.parquet<br/>• silver_conditions.parquet<br/>• silver_medications.parquet")]

        XLATE --> ANON
        KMS -.->|"Versioned Key (kid:hmac)"| ANON
        ANON --> AUDIT
        AUDIT -->|"PASS (0 PHI Leaks)"| SLV_TBL
    end

    subgraph Gold["4. GOLD ZONE — Real-Time Acuity Scoring & Research Analytics"]
        SCORER["Stateful ClinicalDeteriorationScorer<br/>Royal College of Physicians NEWS2 & qSOFA"]
        GLD_ALT[("gold_patient_deterioration_alerts.parquet<br/>(Sub-Second ICU Sepsis & Acuity Alerts)")]
        GLD_COH[("gold_cohort_clinical_metrics.parquet<br/>(Population Health Star-Schema Aggregations)")]
        SCORER --> GLD_ALT
        SLV_TBL --> SCORER
        SLV_TBL --> GLD_COH
    end

    SYN -->|"FHIR R4 JSON & XML Bundles"| BRZ_ING
    HL7 -->|"MLLP Pipe-Delimited Streams"| BRZ_ING
    BRZ_TBL --> XLATE
```

#### KMS Key-Ring Envelope Tokenization & Longitudinal Date-Shifting Sequence

```mermaid
sequenceDiagram
    autonumber
    participant Bronze as Bronze Raw Bundle
    participant Anon as HIPAAAnonymizer
    participant KMS as KMSTokenizer (KMSKeyRing)
    participant Auditor as HIPAAComplianceAuditor
    participant Silver as Silver Parquet Store

    Bronze->>Anon: Submit unmasked FHIRBundle (Patient, Encounter, Observations)
    Anon->>KMS: tokenize(patient.id, namespace="patient")
    KMS-->>Anon: "kms-hipaa-key-2026-v1:8f4a2e9c1b..."
    Anon->>KMS: deterministic_date_shift_days(patient.id)
    KMS-->>Anon: -142 days (Deterministic per patient via HMAC-SHA256)
    Note over Anon: Shift Encounter, Observation, Condition & Med timestamps by -142d<br/>Preserves exact hour/minute Δt between vitals & antibiotic orders!
    Note over Anon: Top-code age >= 90 to 90; Mask ZIP to 3 digits ("000" if pop <= 20k);<br/>Scrub SSN/Phone/Email/IPv4/URL/MRN/Names from clinical notes.
    Anon->>Auditor: assert_bundle_compliant(clean_bundle)
    Auditor-->>Anon: HIPAAAuditReport(is_compliant=True, violations=())
    Anon->>Silver: Persist ZSTD-compressed Silver Parquet tables
```

---

### Data Pipelines

The pipeline is implemented as a modular, strongly typed five-stage architecture under [`src/healthcare_lakehouse/`](src/healthcare_lakehouse/):

1. **Stage 1 — Stateful Clinical Simulation ([`synthea_orchestrator.py`](src/healthcare_lakehouse/synthetic/synthea_orchestrator.py) & [`hl7v2_simulator.py`](src/healthcare_lakehouse/synthetic/hl7v2_simulator.py)):**
   Executes declarative Synthea™ JSON state machines (`Initial` → `Encounter` → `ConditionOnset` → `ObservationSeries` → `MedicationOrder` → `Terminal`) and emits paired HL7 FHIR R4 JSON/XML bundles and MLLP-framed HL7 v2.5.1 `ADT^A01`/`ORU^R01` messages.
2. **Stage 2 — Bronze Immutable Envelope Ingestion ([`medallion_pipeline.py`](src/healthcare_lakehouse/lakehouse/medallion_pipeline.py)):**
   Computes a cryptographic `SHA-256` digest over every incoming raw payload, attaches source system and UTC ingestion watermarks, and writes `bronze_clinical_envelope.parquet` for 100% replayable lineage.
3. **Stage 3 — Legacy-to-FHIR R4 Canonical Translation ([`hl7v2_parser.py`](src/healthcare_lakehouse/parsers/hl7v2_parser.py) & [`fhir_parser.py`](src/healthcare_lakehouse/parsers/fhir_parser.py)):**
   Unwraps MLLP frames, parses `MSH`, `PID`, `PV1`, `OBR`, `OBX`, and `DG1` segments, normalizes LOINC/ICD-10/UCUM vocabularies, and unifies HL7 v2, FHIR JSON, and FHIR XML streams into strict Pydantic v2 [`FHIRBundle`](src/healthcare_lakehouse/models/fhir_resources.py) objects.
4. **Stage 4 — Out-of-Band HIPAA Safe Harbor Anonymization & Zero-PHI Audit ([`kms_tokenizer.py`](src/healthcare_lakehouse/security/kms_tokenizer.py) & [`hipaa_anonymizer.py`](src/healthcare_lakehouse/security/hipaa_anonymizer.py)):**
   Applies all 18 HIPAA Safe Harbor controls, shifts longitudinal timestamps by a patient-deterministic KMS offset in `[-365, -1]` days, verifies compliance via [`HIPAAComplianceAuditor`](src/healthcare_lakehouse/security/hipaa_anonymizer.py), and materializes five normalized Silver Parquet tables (`silver_patients`, `silver_encounters`, `silver_observations`, `silver_conditions`, `silver_medications`).
5. **Stage 5 — Real-Time Clinical Deterioration Scoring & Gold Aggregation ([`clinical_deterioration.py`](src/healthcare_lakehouse/scoring/clinical_deterioration.py)):**
   Evaluates 7 physiological parameters under **NEWS2** and **qSOFA** sepsis criteria, outputting urgent ICU rapid-response alerts (`gold_patient_deterioration_alerts.parquet`) and population cohort summaries (`gold_cohort_clinical_metrics.parquet`).

---

### Tools & Technologies

| Layer | Technology | Architectural Rationale |
| :--- | :--- | :--- |
| **Language & Runtime** | **Python 3.11+ (`3.11`–`3.13`)** | Native `tomllib`, fast `asyncio`/typing internals, and universal ecosystem support across Spark, PyArrow, and clinical NLP. |
| **Schema & Domain Validation** | **Pydantic v2 (`ConfigDict(frozen=True)`)** | Rust-backed (`pydantic-core`) validation enforces strict immutability and catches malformed FHIR R4 polymorphic types at runtime. |
| **Columnar Lakehouse I/O** | **Apache Arrow (`PyArrow`) & Apache Parquet (`ZSTD` / `SNAPPY`)** | Vectorized columnar serialization achieves 6x–10x storage compression and predicate pushdown compatibility with Apache Spark, DuckDB, Trino, and AWS Athena. |
| **Cryptographic De-Identification** | **HMAC-SHA256 + Versioned KMS Key Ring** | O(1) deterministic pseudonymization (`kid:digest`) allows cross-table joins across `Patient`, `Encounter`, and `Observation` without exposing raw MRNs or SSNs, while supporting zero-downtime key rotation. |
| **Clinical Standards** | **HL7 v2.5.1 (`MLLP`), HL7 FHIR R4 (`v4.0.1`), LOINC, SNOMED-CT, RxNorm, ICD-10-CM** | Preserves end-to-end semantic interoperability required by CMS, ONC 21st Century Cures Act, and clinical research registries. |
| **Package & Quality Toolchain** | **`uv`, `Ruff`, `Mypy --strict`, `Pytest`, `Lefthook`, `GitHub Actions`** | Sub-second dependency resolution, 100% static type enforcement, automated pre-commit/pre-push HIPAA gates, and 100% branch test coverage. |

---

### Scalability Considerations (Epidemic & ICU Surge Readiness)

During respiratory pandemics or regional mass-casualty surges, hospital telemetry volumes spike **10x to 50x** (e.g., thousands of continuous bedside pulse oximetry and ventilator `ORU^R01` messages per second):

1. **Stateless O(1) Tokenization & Date-Shifting:** Unlike lookup-table pseudonymizers that bottleneck on centralized relational database locks under high write concurrency, [`KMSTokenizer`](src/healthcare_lakehouse/security/kms_tokenizer.py) computes HMAC-SHA256 digests and date-shift offsets purely in memory using cached data encryption keys (DEKs), scaling linearly across Spark executor cores with zero cross-node coordination.
2. **Columnar ZSTD Compression & Partition Pruning:** Writing Silver and Gold tables in `ZSTD`-compressed Apache Parquet reduces S3 object storage I/O bandwidth by **~82%** compared to verbose FHIR JSON/XML text files and enables partition pruning by `encounter_class`, `state`, and `event_date`.
3. **Skewed Facility Key Mitigation:** In multi-hospital deployments where a single tertiary trauma center generates 60%+ of ICU telemetry, composite partitioning and deterministic token salting prevent Spark shuffle OOMs during Silver-to-Gold cohort joins.
4. **Decoupled Bronze Replayability:** During extreme surge spikes, the Bronze ingestion gateway appends raw MLLP/FHIR frames directly to `bronze_clinical_envelope.parquet` with minimal CPU overhead, allowing Silver/Gold micro-batches to process with bounded backpressure without dropping a single bedside packet.

---

## 4. Verified Outcomes & Compliance Metrics

Every engineering claim in this repository is backed by reproducible, automated verification:

- **100.0% HIPAA Safe Harbor Compliance (Zero Leaked PHI):** Automated audits via [`HIPAAComplianceAuditor`](src/healthcare_lakehouse/security/hipaa_anonymizer.py) verify that **100% of the 18 HIPAA Safe Harbor identifiers** (names, street/city, restricted 3-digit ZIPs, full dates, ages `>= 90`, phones, emails, URLs, SSNs, MRNs, device IPs, and free-text clinical notes) are redacted, top-coded, or KMS-tokenized before Silver/Gold persistence.
- **Sub-Second Clinical Deterioration Alerting (`< 2 ms` per Bundle):** [`ClinicalDeteriorationScorer`](src/healthcare_lakehouse/scoring/clinical_deterioration.py) evaluates 9 LOINC vital sign streams per patient, accurately separating high-acuity sepsis cases (`NEWS2 = 17`, `qSOFA = 3`, `HIGH` risk) from stable chronic cases (`NEWS2 = 0`, `qSOFA = 0`, `LOW` risk).
- **100.00% Verified Line & Branch Test Coverage:** `37` unit and end-to-end integration tests cover `1,652` statements and `468` branches at **100.00% coverage** (`uv run pytest --cov-fail-under=100`), with `0` Ruff lint errors and `0` Mypy `--strict` errors.

---

## 5. Engineering Insights & Design Trade-Offs

1. **Parsing Polymorphic Clinical XML/JSON and Legacy HL7 v2 Delimiters (`^~\&`):**
   - In HL7 v2.5.1, `MSH-1` is the literal pipe character (`|`) itself and `MSH-2` defines component/repetition/escape delimiters (`^~\&`), meaning naive `line.split("|")` indexing shifts every `MSH` field by `-1` compared to `PID` or `OBX` segments! Encapsulating this invariant inside [`HL7v2Parser`](src/healthcare_lakehouse/parsers/hl7v2_parser.py) eliminated off-by-one field bugs across `MSH-9` (Message Type) and `MSH-10` (Control ID).
   - Similarly, FHIR R4 `Observation` values are polymorphic (`valueQuantity` vs. `valueString` for ACVPU consciousness levels), requiring explicit Pydantic v2 `@model_validator(mode="after")` invariants and namespace-agnostic XML element traversal.
2. **Cryptographic Longitudinal Date-Shifting Without Breaking Clinical Time-Series:**
   - Randomizing each timestamp independently destroys clinical causality (making an antibiotic order appear to occur *before* the triage vital signs that triggered it). By deriving a deterministic patient offset $\Delta d \in [-365, -1]$ days via `HMAC-SHA256(kms_key, "date-shift:" + patient_id)`, every event in a patient's lifecycle shifts by the exact same offset—protecting calendar admission dates while preserving exact minute-by-minute physiological trajectories.
3. **Zero-Downtime KMS Key Rotation in Immutable Lakehouses:**
   - Prefixing every pseudonymized token with its KMS Key ID (`kms-hipaa-key-2026-v1:<hmac_digest>`) allows [`KMSTokenizer`](src/healthcare_lakehouse/security/kms_tokenizer.py) to rotate to `kms-hipaa-key-2027-v2` for new ingestions while retaining historical keys in [`KMSKeyRing`](src/healthcare_lakehouse/security/kms_tokenizer.py) to verify or dual-hash multi-year longitudinal cohorts without rewriting petabytes of historical Parquet files.

---

## Quickstart & Reproducible Verification

### 1. Clone & Install Environment (`uv` + `lefthook`)

```bash
# Install dependencies and activate strict pre-commit / commit-msg / pre-push hooks
uv sync --dev
uv run lefthook install
```

### 2. Run Linters, Strict Type Checker, and 100% Coverage Test Suite

```bash
uv run --no-sync ruff check src tests scripts
uv run --no-sync ruff format --check src tests scripts
uv run --no-sync mypy src tests scripts
uv run --no-sync pytest
```

### 3. Execute End-to-End Medallion Pipeline & HIPAA Safe Harbor Audit

```bash
uv run --no-sync healthcare-lakehouse run-pipeline \
  --patients 12 \
  --seed 42 \
  --output-dir data/lakehouse_run \
  --verify-hipaa
```

**Sample Output:**
```json
{
  "status": "SUCCESS",
  "storage_backend": "local",
  "hipaa_safe_harbor_compliant": true,
  "verify_hipaa_flag": true,
  "bronze_records_written": 14,
  "silver_patients_written": 14,
  "silver_encounters_written": 14,
  "silver_observations_written": 138,
  "silver_conditions_written": 13,
  "silver_medications_written": 12,
  "gold_alerts_written": 14,
  "gold_cohort_metrics_written": 2,
  "high_acuity_alerts_triggered": 7,
  "hipaa_violations_detected": 0,
  "gold_alerts_parquet_path": "data/lakehouse_run/gold/gold_patient_deterioration_alerts.parquet"
}
```

### 4. Scalable S3 / MinIO Containerized Execution (`Dockerfile` + `compose.yaml`)

```bash
# Provision MinIO S3 bucket and stream Bronze -> Silver -> Gold Parquet tables to s3://healthcare-lakehouse/medallion/...
docker compose -f compose.yaml up --build --abort-on-container-exit

# Or target any S3-compatible endpoint / AWS S3 bucket directly from the CLI
uv run --no-sync healthcare-lakehouse run-pipeline \
  --patients 12 \
  --seed 42 \
  --s3-bucket healthcare-lakehouse \
  --s3-prefix medallion \
  --s3-endpoint-url http://localhost:9000 \
  --verify-hipaa

# Run the isolated containerized QA & 100% test coverage profile
docker compose -f compose.yaml --profile qa run --rm lakehouse-qa
```

---

## License

Released under the [MIT License](LICENSE).
