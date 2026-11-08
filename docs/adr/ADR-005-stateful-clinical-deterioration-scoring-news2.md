# ADR-005: Stateful Clinical Deterioration Scoring (Royal College of Physicians NEWS2 & qSOFA)

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Principal Forward-Deployed Data Engineer, Clinical Informatics Lead
- **Refs:** Royal College of Physicians National Early Warning Score (NEWS2), Sepsis-3 qSOFA Criteria

---

## 1. Context

A core mission of real-time clinical telemetry ingestion is identifying acute patient deterioration (particularly sepsis and acute respiratory failure) before cardiac arrest or multi-organ failure occurs. Ad-hoc single-vital threshold alerts produce high false-positive alarm fatigue in ICUs and general wards.

## 2. Decision

We implement the standardized **Royal College of Physicians NEWS2 (National Early Warning Score 2)** and **Sepsis-3 qSOFA (Quick Sequential Organ Failure Assessment)** algorithms in `ClinicalDeteriorationScorer` (`src/healthcare_lakehouse/scoring/clinical_deterioration.py`):

1. **NEWS2 Composite Scoring (`0..20` points):** Aggregates weighted sub-scores (`0..3`) across 7 physiological parameters:
   - Respiratory rate (`9279-1`), arterial oxygen saturation (`2708-6`), supplemental oxygen (`3150-0`), systolic blood pressure (`8480-6`), heart rate (`8867-4`), core body temperature (`8310-5`), and ACVPU level of consciousness (`67775-7`).
2. **qSOFA Scoring (`0..3` points):** Evaluates respiratory rate `>= 22 /min`, systolic BP `<= 100 mmHg`, and altered mentation (`ACVPU != "A"`).
3. **Clinical Risk Stratification & Sepsis Flagging:**
   - Classifies patients into `LOW`, `LOW_MEDIUM` (any single parameter scoring `3`), `MEDIUM` (`NEWS2 5..6`), and `HIGH` (`NEWS2 >= 7` or `qSOFA >= 2`).
   - Flags `sepsis_suspected = True` when `qSOFA >= 2` or (`NEWS2 >= 5` with serum lactate `>= 2.0 mmol/L`).

## 3. Consequences

- **Positive:** Clinically validated, interpretable risk alerts materialized in `< 2 ms` per bundle into `gold_patient_deterioration_alerts.parquet` with explicit `triggered_parameters` provenance.
- **Negative / Trade-offs:** Requires LOINC-normalized vital sign inputs from the Silver transformation layer.
