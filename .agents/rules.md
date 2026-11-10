# Workspace Rules — Healthcare Clinical Interoperability Lakehouse (`de-healthcare-interop-lakehouse`)

This file defines the authoritative workspace rules for all AI coding agents and engineers working inside `de-healthcare-interop-lakehouse`. It is complemented by modular domain rule files in `.agents/rules/`.

---

## 1. Core Architectural & Domain Rules

1. **Medallion Zone Separation (`Bronze` -> `Silver` -> `Gold`):**
   - **Bronze Zone:** Stores raw, immutable HL7 v2 pipe-delimited messages and HL7 FHIR R4 Bundles wrapped in an audit envelope (`record_id`, `source_protocol`, `ingested_at`, `payload_sha256`, `raw_payload`). Never mutate Bronze payloads in place.
   - **Silver Zone:** Stores canonical, validated, and **HIPAA Safe Harbor de-identified** clinical entities (`Patient`, `Encounter`, `Observation`, `Condition`, `MedicationRequest`). No unmasked Protected Health Information (PHI) may ever enter Silver or Gold zones.
   - **Gold Zone:** Stores analytical star-schema Parquet tables, longitudinal patient cohort summaries, and real-time clinical deterioration alerts (**NEWS2** and **qSOFA**).
2. **Clinical Vocabulary Preservation:**
   - Never strip or corrupt standard clinical terminology codes (**LOINC**, **SNOMED-CT**, **RxNorm**, **ICD-10-CM**, **UCUM** units) during de-identification or flattening.

---

## 2. HIPAA Safe Harbor (45 CFR §164.514(b)(2)) Mandatory Controls

1. **18-Identifier De-Identification Gate:**
   - Every Silver and Gold record MUST pass through `HIPAAAnonymizer` and be verified by `HIPAAComplianceAuditor` with zero violations before persistence.
2. **Cryptographic Tokenization & Key Rotation:**
   - Direct identifiers (Patient ID, MRN, SSN, Encounter ID) MUST be pseudonymized using deterministic **HMAC-SHA256** backed by versioned KMS keys (`KMSTokenizer`), prefixed with the active key version ID (`v1:<hmac_hex>`).
3. **Patient-Consistent Longitudinal Date Shifting:**
   - Dates (birth date, admission/discharge timestamps, observation effective dates) MUST be shifted by a deterministic patient-specific offset in `[-365, -1]` days derived from the patient's KMS token so exact inter-event clinical intervals (hours/minutes between observations) remain 100% intact.
4. **Age Top-Coding & ZIP-3 Masking:**
   - Patients aged `>= 90` years MUST have their age top-coded to `90` and birth year masked accordingly.
   - Postal codes MUST be truncated to the first 3 digits (`ZIP-3`), or replaced with `"000"` if the 3-digit prefix belongs to the HIPAA restricted low-population (`<= 20,000` residents) prefix list (`036`, `059`, `063`, `102`, `203`, `556`, `692`, `790`, `821`, `823`, `830`, `831`, `878`, `879`, `884`, `890`, `893`).

---

## 3. Code Quality, Typing, and 100% Test Coverage

1. **Elegant Type Annotations:**
   - All functions, methods, generators, and class attributes MUST include explicit Python 3.11+ type annotations (`from __future__ import annotations`).
   - `uv run mypy src tests --strict` MUST pass with zero errors.
2. **Strict Test-Driven Development (TDD) & 100% Coverage:**
   - Write failing unit/integration tests before production code.
   - `uv run pytest --cov=src/healthcare_lakehouse --cov-branch --cov-fail-under=100` MUST pass at **100.0% coverage**.
3. **Formatting & Linting:**
   - `uv run ruff check src tests` and `uv run ruff format --check src tests` MUST pass cleanly.

---

## 4. Enterprise Gitflow & CI/CD Governance

1. **Branch Hierarchy:**
   - `feature/<topic>` -> `develop` -> `staging` -> `main`.
   - Never commit directly to `main`. Always branch from `develop` and merge via `--no-ff`.
2. **Conventional Commits:**
   - Format: `<type>(<scope>): <imperative summary>` (`<= 72` chars) followed by a detailed body.
   - Allowed types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `security`, `ci`, `chore`, `build`.
3. **Lefthook & CI Gates:**
   - Keep `lefthook.yml` and `.github/workflows/ci-pipeline.yml` synchronized across linting, typing, security, and 100% coverage gates.

---

## 5. Modular Rule References

- [01-architecture-and-medallion.md](./rules/01-architecture-and-medallion.md)
- [02-hipaa-compliance-and-security.md](./rules/02-hipaa-compliance-and-security.md)
- [03-gitflow-and-ci-cd.md](./rules/03-gitflow-and-ci-cd.md)
- [04-testing-and-type-safety.md](./rules/04-testing-and-type-safety.md)
- [05-synthetic-clinical-data.md](./rules/05-synthetic-clinical-data.md)
