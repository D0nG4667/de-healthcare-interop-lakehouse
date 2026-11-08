# Developer Onboarding Guide — `de-healthcare-interop-lakehouse`

Welcome to the **Healthcare Clinical Interoperability Lakehouse** engineering team! This guide walks you through environment setup, local development workflows, Test-Driven Development (TDD), Lefthook Git hooks, and HIPAA Safe Harbor compliance checks in under 10 minutes.

---

## 1. Prerequisites

- **Python:** `>= 3.11` (`3.11`, `3.12`, or `3.13`)
- **Package Manager:** [`uv`](https://docs.astral.sh/uv/) (`>= 0.5.0`)
- **Git:** `>= 2.38` (with Git worktree support)
- **Optional (Containerized Stack):** Docker & Docker Compose v2

---

## 2. Step-by-Step Local Setup

### Step 1: Clone the Repository & Checkout `develop`
```bash
git clone git@github.com:D0nG4667/de-healthcare-interop-lakehouse.git
cd de-healthcare-interop-lakehouse
git checkout develop
```

### Step 2: Sync Virtual Environment & Install Lefthook Git Hooks
```bash
uv sync --dev
uv run lefthook install
```
This installs `pydantic`, `pyarrow`, `pytest`, `pytest-cov`, `ruff`, `mypy`, and `lefthook`, and registers three automated Git hooks:
- **`pre-commit`:** Blocks direct commits to `main`, blocks staging of raw `.csv`/`.hl7`/`.mllp`/`.fhir.json`/`.pem`/`.key` artifacts, and runs `ruff check`, `ruff format --check`, and `mypy --strict`.
- **`commit-msg`:** Enforces Conventional Commits (`feat(scope): ...`, `fix(scope): ...`, etc.).
- **`pre-push`:** Runs `uv run pytest` with the **100.0% line and branch coverage gate**.

---

## 3. Daily Engineering Commands

| Task | Command |
| :--- | :--- |
| **Run Full Test Suite (100% Coverage Gate)** | `uv run --no-sync pytest` |
| **Run Strict Static Type Analysis** | `uv run --no-sync mypy src tests scripts` |
| **Run Linter & Code Formatter** | `uv run --no-sync ruff check src tests scripts && uv run --no-sync ruff format --check src tests scripts` |
| **Run End-to-End Medallion Pipeline CLI** | `uv run --no-sync healthcare-lakehouse run-pipeline --patients 12 --seed 42 --output-dir data/local_run --verify-hipaa` |
| **Execute Pre-Commit Hooks Manually** | `uv run --no-sync lefthook run pre-commit` |

---

## 4. Module Walkthrough for New Engineers

1. **Start at [`src/healthcare_lakehouse/models/fhir_resources.py`](../../src/healthcare_lakehouse/models/fhir_resources.py):** Understand the immutable Pydantic v2 domain models for `FHIRBundle`, `FHIRPatient`, `FHIREncounter`, `FHIRObservation`, `FHIRCondition`, and `FHIRMedicationRequest`.
2. **Explore [`src/healthcare_lakehouse/synthetic/`](../../src/healthcare_lakehouse/synthetic/):** Inspect `modules/sepsis_deterioration_module.json` and `synthea_orchestrator.py` to see how patient lifecycles and HL7 v2.5.1 MLLP messages (`hl7v2_simulator.py`) are synthesized.
3. **Trace Protocol Translation in [`src/healthcare_lakehouse/parsers/`](../../src/healthcare_lakehouse/parsers/):** Review how `hl7v2_parser.py` maps legacy `PID`/`PV1`/`OBX`/`DG1` segments into canonical FHIR R4 bundles.
4. **Verify HIPAA Safe Harbor De-Identification in [`src/healthcare_lakehouse/security/`](../../src/healthcare_lakehouse/security/):** Inspect `kms_tokenizer.py` and `hipaa_anonymizer.py` to see how all 18 PHI identifiers are masked/tokenized and verified by `HIPAAComplianceAuditor`.
5. **Review Medallion Orchestration & Scoring:** Examine `scoring/clinical_deterioration.py` (NEWS2 & qSOFA) and `lakehouse/medallion_pipeline.py` (Bronze/Silver/Gold PyArrow Parquet writers).
