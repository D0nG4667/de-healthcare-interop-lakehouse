# ADR-004: Synthea™ State-Machine Clinical Lifecycle Simulation vs. Naive Faker Loops

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Principal Forward-Deployed Data Engineer
- **Refs:** `AGENTS.md`, `.agents/rules/05-synthetic-clinical-data.md`

---

## 1. Context

Testing a healthcare clinical lakehouse with basic random `Faker` loops fails to validate distributed clinical pipelines because stateless random generators produce physiologically impossible combinations (e.g., normal heart rate during septic shock, observations occurring before admission, invalid LOINC/RxNorm codes, or broken foreign keys between `Observation`, `Encounter`, and `Patient`).

## 2. Decision

We implement declarative **Synthea™-compatible JSON State-Machine Disease Modules** (`sepsis_deterioration_module.json` and `cardiopulmonary_chronic_module.json`) orchestrated by `SyntheaOrchestrator` alongside `HL7v2Simulator`:

- Each patient traverses a directed state graph (`Initial` → `Encounter` → `ConditionOnset` → `ObservationSeries` → `MedicationOrder` → `Post_Resuscitation_Check` → `Terminal`) with realistic temporal delays (`delay_minutes`) and correlated physiological trajectories.
- Every clinical measurement is bound to authentic **LOINC** (`9279-1`, `2708-6`, `3150-0`, `8480-6`, `8462-4`, `8867-4`, `8310-5`, `2524-7`, `67775-7`), **SNOMED-CT**, **ICD-10-CM** (`A41.9`, `J44.1`), and **RxNorm** (`11124`, `435`) codes.
- Cohort synthesis deterministically injects HIPAA Safe Harbor edge cases (patients aged `90+`, restricted 3-digit ZIP codes `036`/`059`/`821`, and free-text notes containing synthetic SSNs/IPs/emails/URLs).

## 3. Consequences

- **Positive:** 100% deterministic, reproducible clinical cohorts with zero real patient PII, full relational integrity, and realistic physiological signal separation for NEWS2/qSOFA validation.
- **Negative / Trade-offs:** Higher initial engineering investment to author state-machine JSON modules compared to flat random loops.
