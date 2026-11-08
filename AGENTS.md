# AGENTS.md — Healthcare Clinical Interoperability Lakehouse

> **Enterprise Agentic Engineering Charter & System Blueprint**  
> **Project:** `de-healthcare-interop-lakehouse` (HL7 v2 / FHIR R4 Clinical Interoperability Medallion Lakehouse)  
> **Role:** Principal / Forward-Deployed Enterprise Data Engineer  
> **Compliance Standard:** HIPAA Privacy & Security Rules (45 CFR §164.514(b)(2) Safe Harbor & §164.312 Technical Safeguards), HL7 v2.5.1, HL7 FHIR R4 (v4.0.1)

---

## 1. Executive Mission & Five-Part Portfolio Storytelling Mandate

All documentation, architectural artifacts, and code implementations in this repository strictly align with the five-part enterprise portfolio storytelling structure:

1. **THE PROBLEM:**  
   Healthcare provider networks, bedside ICU monitors, and legacy Electronic Health Record (EHR) systems emit clinical telemetry in fragmented, real-time **HL7 v2** pipe-delimited (`MSH|PID|PV1|OBR|OBX|DG1`) MLLP streams and deeply nested **HL7 FHIR R4** JSON/XML bundles. These heterogeneous streams must be ingested, structurally normalized, de-identified under strict **HIPAA Safe Harbor (18 PHI identifiers)** privacy controls, scored in real time for acute patient deterioration, and persisted for downstream clinical research without breaking medical ontology semantics (**LOINC**, **SNOMED-CT**, **RxNorm**, **ICD-10-CM**).
2. **THE DATA / INPUTS:**  
   - **Synthea™ Patient Lifecycle Streams:** Standards-compliant HL7 FHIR R4 `Bundle` payloads (`Patient`, `Encounter`, `Observation`, `Condition`, `MedicationRequest`) orchestrated via custom Synthea™ state-machine disease modules (`sepsis_deterioration_module.json` and `cardiopulmonary_chronic_module.json`).
   - **Legacy Bedside HL7 v2.5.1 Streams:** High-velocity pipe-delimited `ADT^A01` (Admit), `ADT^A03` (Discharge), `ADT^A08` (Update), and `ORU^R01` (Unsolicited Observation) messages containing raw clinical vitals and unmasked patient demographics.
3. **YOUR APPROACH:**  
   A decoupled, multi-hop **Medallion Lakehouse Architecture** (`Bronze` -> `Silver` -> `Gold`) backed by **PyArrow / Apache Spark** and **S3-compatible columnar Parquet storage**:
   - **Bronze Zone (Raw Immutable Envelope):** Captures raw HL7 v2 and FHIR R4 payloads with cryptographic SHA-256 payload digests, ingestion watermarks, and source lineage metadata.
   - **Silver Zone (Canonical FHIR R4 & HIPAA Safe Harbor Gate):** Translates legacy HL7 v2 segments into canonical FHIR R4 structures, validates schemas via strict **Pydantic v2** models, and executes out-of-band **HIPAA Safe Harbor 18-identifier de-identification** using **AWS KMS envelope encryption & deterministic HMAC-SHA256 tokenization**, patient-consistent longitudinal date-shifting (`[-365, -1]` days), age top-coding (`>= 90` mapped to `90`), 3-digit ZIP code truncation with small-population (`000`) masking, and free-text PHI regex scrubbing.
   - **Gold Zone (Clinical Research & Real-Time Telemetry Alerts):** Computes stateful **NEWS2 (National Early Warning Score 2)** and **qSOFA (Quick Sequential Organ Failure Assessment)** deterioration scores for sub-second clinical alerting, and materializes ZSTD/Snappy-compressed columnar Parquet analytical tables for population health cohorts.
4. **THE OUTCOME:**  
   - **100% HIPAA Safe Harbor Compliance:** Automated Zero-PHI audit gates verify `0` leaked identifiers across all Silver and Gold records.
   - **Sub-Second Telemetry Alerting:** Stateful vital-sign evaluation flags high-acuity sepsis/respiratory deterioration in `< 5 ms` per clinical bundle.
   - **100% Verified Test Coverage:** Comprehensive unit, compliance, and end-to-end integration test suite enforced via `pytest --cov-fail-under=100`, `mypy --strict`, `ruff`, `lefthook`, and GitHub Actions CI/CD.
5. **WHAT YOU LEARNED:**  
   - Navigating deeply nested polymorphic FHIR R4 JSON/XML extensions and HL7 v2 delimiter escaping (`^~\&`) without losing clinical context.
   - Designing **cryptographic longitudinal date-shifting** so every timestamp for a given patient shifts by a deterministic, KMS-derived offset—protecting admission/birth dates while preserving exact hour/minute intervals between ICU vital sign observations and medication administrations.
   - Managing **KMS key-ring rotation** via versioned key IDs (`kid`) so historical pseudonymized tokens can be migrated or dual-hashed during key rotation windows without breaking multi-year patient cohort joins.

---

## 2. The Four Recruiter Anchors & Candidate Superpowers

### Four Recruiter Anchors
1. **Architecture Diagrams:** Multi-hop Mermaid system architecture, Medallion data lineage, KMS envelope encryption sequence diagrams, and Gitflow topology in [`README.md`](file:///c:/Users/hp/Desktop/gab/Data%20Engineering/alx-portfolio-de/de-healthcare-interop-lakehouse/README.md) and [`docs/architecture/SYSTEM_ARCHITECTURE.md`](file:///c:/Users/hp/Desktop/gab/Data%20Engineering/alx-portfolio-de/de-healthcare-interop-lakehouse/docs/architecture/SYSTEM_ARCHITECTURE.md).
2. **Data Pipelines:** End-to-end deterministic pipelines covering Synthea™ lifecycle synthesis, HL7 v2 MLLP parsing, FHIR R4 normalization, HIPAA Safe Harbor de-identification, NEWS2/qSOFA scoring, and PyArrow/Spark Parquet persistence.
3. **Tools & Technologies:** Explicit architectural rationale and trade-off analysis (ADR-001 through ADR-005) for Python 3.11+, Pydantic v2, PyArrow/Parquet, Apache Spark, KMS HMAC-SHA256, `uv`, Ruff, Mypy, Pytest, Lefthook, and GitHub Actions.
4. **Scalability Considerations:** Epidemic/pandemic surge architecture (10x–50x ICU telemetry spikes), dynamic partition pruning (`resource_type` / `event_date`), salted join keys for high-volume facilities, and streaming backpressure controls.

### Four Candidate Pillars / Superpowers
- **Strong Real-World Problem Framing:** Grounded in 45 CFR §164.514(b)(2) HIPAA Safe Harbor, HL7 FHIR R4 interoperability mandates (21st Century Cures Act), and ICU sepsis early warning (NEWS2/qSOFA).
- **System Design & Architecture:** Zero-trust boundary separation between raw PHI landing zones and research-ready analytical zones.
- **Technical Communication:** Complete enterprise documentation suite (`BRD`, `ADR-001..005`, `SYSTEM_ARCHITECTURE`, `DEVELOPER_ONBOARDING`, `DEPLOYMENT_AND_OPERATIONS`, `HIPAA_COMPLIANCE_AND_DATA_GOVERNANCE`, `ENTERPRISE_GITFLOW`).
- **Scalability & Performance Thinking:** Vectorized columnar I/O, O(1) deterministic HMAC tokenization, and memory-bounded streaming parsers.

---

## 3. Repository Structure & Module Boundaries

```text
de-healthcare-interop-lakehouse/
├── AGENTS.md                                      # Root AI Agent & Principal Engineer Charter
├── README.md                                      # 5-Part Portfolio Blueprint & Quickstart
├── pyproject.toml                                 # uv package config, Ruff, Mypy, Pytest (100% cov)
├── lefthook.yml                                   # Enterprise Git hooks (pre-commit, commit-msg, pre-push)
├── Makefile                                       # Developer automation targets
├── Dockerfile                                     # Multi-stage BuildKit container image (builder, qa, runtime)
├── .dockerignore                                  # BuildKit context & PHI artifact exclusion rules
├── compose.yaml                                   # Canonical Docker Compose Spec stack (MinIO S3 + Pipeline + QA)
├── .agents/
│   ├── rules.md                                   # Master workspace rules index
│   └── rules/                                     # Modular domain rules (Architecture, HIPAA, Gitflow, TDD)
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md                   # Mandatory HIPAA Safe Harbor 18-Identifier PR Checklist
│   └── workflows/
│       └── ci-pipeline.yml                        # Enterprise CI/CD pipeline (Format, Lint, Mypy, HIPAA Audit, 100% Test Cov)
├── docs/
│   ├── brd/BRD-001-clinical-interoperability-lakehouse.md
│   ├── architecture/SYSTEM_ARCHITECTURE.md
│   ├── adr/
│   │   ├── ADR-001-medallion-lakehouse-parquet-architecture.md
│   │   ├── ADR-002-hipaa-safe-harbor-deidentification-and-kms-tokenization.md
│   │   ├── ADR-003-legacy-hl7v2-to-fhir-r4-canonical-translation.md
│   │   ├── ADR-004-synthea-state-machine-synthetic-clinical-data.md
│   │   └── ADR-005-stateful-clinical-deterioration-scoring-news2.md
│   ├── onboarding/DEVELOPER_ONBOARDING.md
│   ├── deployment/DEPLOYMENT_AND_OPERATIONS.md
│   ├── governance/HIPAA_COMPLIANCE_AND_DATA_GOVERNANCE.md
│   └── gitflow/ENTERPRISE_GITFLOW.md
├── src/
│   └── healthcare_lakehouse/
│       ├── __init__.py
│       ├── config/
│       │   └── settings.py                        # Immutable Lakehouse, HIPAA, and KMS configurations
│       ├── models/
│       │   └── fhir_resources.py                  # Strict Pydantic v2 FHIR R4 & Medallion models
│       ├── synthetic/
│       │   ├── modules/
│       │   │   ├── sepsis_deterioration_module.json
│       │   │   └── cardiopulmonary_chronic_module.json
│       │   ├── synthea_orchestrator.py            # Synthea™ state-machine lifecycle & FHIR Bundle engine
│       │   └── hl7v2_simulator.py                 # HL7 v2.5.1 pipe-delimited ADT/ORU stream simulator
│       ├── parsers/
│       │   ├── hl7v2_parser.py                    # HL7 v2 segment parser & canonical FHIR R4 translator
│       │   └── fhir_parser.py                     # Hierarchical FHIR R4 JSON/XML parser & flattener
│       ├── security/
│       │   ├── kms_tokenizer.py                   # KMS key-ring envelope encryption & HMAC-SHA256 tokenizer
│       │   └── hipaa_anonymizer.py                # 18-identifier HIPAA Safe Harbor engine & compliance auditor
│       ├── scoring/
│       │   └── clinical_deterioration.py          # Stateful NEWS2 & qSOFA clinical acuity scoring engine
│       ├── lakehouse/
│       │   └── medallion_pipeline.py              # Bronze -> Silver -> Gold Parquet Medallion orchestrator
│       └── cli.py                                 # CLI entrypoint for simulation, pipeline, and HIPAA audit
└── tests/
    ├── unit/                                      # Comprehensive unit test suite (100% coverage)
    └── integration/                               # End-to-end Medallion & HIPAA compliance verification
```

---

## 4. Mandatory Engineering Standards for Agents & Contributors

1. **Test-Driven Development (TDD) & 100% Coverage:**
   - Write failing tests first (`RED`), implement minimal clean code (`GREEN`), and refactor (`REFACTOR`).
   - Every module under `src/healthcare_lakehouse/` MUST maintain **100% line and branch test coverage** (`uv run pytest --cov=src/healthcare_lakehouse --cov-branch --cov-fail-under=100`).
2. **Elegant Static Typing & Documentation:**
   - Every function, method, and class MUST have complete Python 3.11+ type annotations (`mypy --strict` zero errors) and Google-style docstrings.
3. **Synthetic Clinical Data Realism (No Basic Faker Loops):**
   - Never use naive random string loops to mock clinical data. Always use [`synthea_orchestrator.py`](file:///c:/Users/hp/Desktop/gab/Data%20Engineering/alx-portfolio-de/de-healthcare-interop-lakehouse/src/healthcare_lakehouse/synthetic/synthea_orchestrator.py) with state-machine disease modules (`sepsis_deterioration_module.json`, `cardiopulmonary_chronic_module.json`) and [`hl7v2_simulator.py`](file:///c:/Users/hp/Desktop/gab/Data%20Engineering/alx-portfolio-de/de-healthcare-interop-lakehouse/src/healthcare_lakehouse/synthetic/hl7v2_simulator.py) to preserve longitudinal physiological realism.
4. **Enterprise Gitflow & Commit Hygiene:**
   - **Branches:** `feature/<scope>` -> `develop` -> `staging` -> `main`.
   - **Prohibition:** Direct commits to `main` are strictly forbidden and blocked by `lefthook`.
   - **Commit Format:** Conventional Commits (`feat(scope): ...`, `fix(scope): ...`, `docs(scope): ...`, `test(scope): ...`, `chore(scope): ...`, `ci(scope): ...`) with clear subject lines (`<= 72` chars) and structured body bullets explaining *what* and *why*.
