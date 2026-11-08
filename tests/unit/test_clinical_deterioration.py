"""Unit tests for the stateful NEWS2 and qSOFA clinical deterioration scoring engine."""

from __future__ import annotations

from datetime import UTC, datetime

from healthcare_lakehouse.scoring.clinical_deterioration import (
    ClinicalDeteriorationScorer,
    VitalSignSnapshot,
)
from healthcare_lakehouse.security.hipaa_anonymizer import HIPAAAnonymizer
from healthcare_lakehouse.synthetic.synthea_orchestrator import SyntheaOrchestrator


def test_clinical_deterioration_scorer_evaluates_sepsis_and_stable_bundles() -> None:
    """Verify NEWS2 and qSOFA scoring on critical sepsis vs stable cardiopulmonary bundles."""
    orchestrator = SyntheaOrchestrator(seed=42)
    anonymizer = HIPAAAnonymizer()
    scorer = ClinicalDeteriorationScorer()

    critical_bundle = anonymizer.anonymize_bundle(
        orchestrator.simulate_patient_lifecycle(
            patient_index=0,
            module_name="sepsis_deterioration",
            force_critical_trajectory=True,
        )
    )
    critical_alert = scorer.evaluate_bundle(critical_bundle)
    assert critical_alert.risk_level == "HIGH"
    assert critical_alert.sepsis_suspected is True
    assert critical_alert.news2_score >= 7
    assert critical_alert.qsofa_score >= 2
    assert len(critical_alert.triggered_parameters) >= 4

    stable_bundle = anonymizer.anonymize_bundle(
        orchestrator.simulate_patient_lifecycle(
            patient_index=1,
            module_name="cardiopulmonary_chronic",
            force_critical_trajectory=False,
        )
    )
    stable_alert = scorer.evaluate_bundle(stable_bundle)
    assert stable_alert.risk_level == "LOW"
    assert stable_alert.sepsis_suspected is False
    assert stable_alert.news2_score <= 4
    assert stable_alert.qsofa_score == 0


def test_clinical_deterioration_scorer_news2_physiological_bands() -> None:
    """Verify all NEWS2 parameter scoring thresholds and LOW/LOW_MEDIUM/MEDIUM/HIGH tiers."""
    scorer = ClinicalDeteriorationScorer()
    ts = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    # 1. Extreme low values (bradypnea <=8, hypoxia <=91, SBP <=90, HR <=40, Temp <=35.0)
    extreme_low = VitalSignSnapshot(
        respiratory_rate=7.0,
        spo2_percent=89.0,
        inhaled_o2_percent=28.0,
        systolic_bp=85.0,
        heart_rate=38.0,
        temperature_celsius=34.8,
        lactate_mmol_l=3.2,
        acvpu_consciousness="V",
    )
    alert_low_extremes = scorer.score_snapshot(
        snapshot=extreme_low,
        patient_token="kms:p1",
        encounter_token="kms:e1",
        evaluated_at=ts,
    )
    assert alert_low_extremes.risk_level == "HIGH"
    assert alert_low_extremes.news2_score == 20

    # 2. Mildly abnormal bands (RR 9-11, SpO2 92-93, SBP 91-100, HR 41-50, Temp 35.1-36.0)
    medium_vitals = VitalSignSnapshot(
        respiratory_rate=10.0,
        spo2_percent=92.0,
        inhaled_o2_percent=21.0,
        systolic_bp=95.0,
        heart_rate=45.0,
        temperature_celsius=35.5,
        lactate_mmol_l=1.2,
        acvpu_consciousness="A",
    )
    alert_medium = scorer.score_snapshot(
        snapshot=medium_vitals,
        patient_token="kms:p2",
        encounter_token="kms:e2",
        evaluated_at=ts,
    )
    assert alert_medium.news2_score == 7
    assert alert_medium.risk_level == "HIGH"

    # 3. Score 5-6 MEDIUM tier (RR 22, SpO2 94, SBP 105, HR 95, Temp 38.5 => score 6)
    tier_medium = VitalSignSnapshot(
        respiratory_rate=22.0,
        spo2_percent=94.0,
        inhaled_o2_percent=21.0,
        systolic_bp=105.0,
        heart_rate=95.0,
        temperature_celsius=38.5,
        lactate_mmol_l=1.4,
        acvpu_consciousness="A",
    )
    alert_tier_med = scorer.score_snapshot(
        snapshot=tier_medium,
        patient_token="kms:p3",
        encounter_token="kms:e3",
        evaluated_at=ts,
    )
    assert alert_tier_med.news2_score == 6
    assert alert_tier_med.risk_level == "MEDIUM"

    # 4. Single parameter red score (score 3 on SBP >= 220, all others 0 -> LOW_MEDIUM)
    single_red = VitalSignSnapshot(
        respiratory_rate=15.0,
        spo2_percent=98.0,
        inhaled_o2_percent=21.0,
        systolic_bp=225.0,
        heart_rate=115.0,  # +2 -> total 5 or with HR 75 -> total 3 (LOW_MEDIUM)
        temperature_celsius=37.0,
        lactate_mmol_l=1.0,
        acvpu_consciousness="A",
    )
    alert_single_red = scorer.score_snapshot(
        snapshot=single_red.model_copy(update={"heart_rate": 75.0}),
        patient_token="kms:p4",
        encounter_token="kms:e4",
        evaluated_at=ts,
    )
    assert alert_single_red.news2_score == 3
    assert alert_single_red.risk_level == "LOW_MEDIUM"

    # Test HR 111-130 (+2) band
    alert_hr_band = scorer.score_snapshot(
        snapshot=single_red,
        patient_token="kms:p5",
        encounter_token="kms:e5",
        evaluated_at=ts,
    )
    assert alert_hr_band.news2_score == 5
