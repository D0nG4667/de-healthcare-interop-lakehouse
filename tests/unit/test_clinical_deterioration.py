"""Unit tests for the stateful NEWS2 and qSOFA clinical deterioration scoring engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from healthcare_lakehouse.models.fhir_resources import (
    FHIRBundle,
    FHIRCodeableConcept,
    FHIRCoding,
    FHIRObservation,
    FHIRQuantity,
)
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


def test_clinical_deterioration_ignores_non_acvpu_strings_and_sorts_chronologically() -> None:
    """Verify narrative string observations do not trigger ACVPU +3 and timestamps sort."""
    scorer = ClinicalDeteriorationScorer()
    t0 = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    t1 = t0 + timedelta(minutes=15)

    # Out-of-order observations: newer normal HR (t1) placed BEFORE older high HR (t0),
    # plus a qualitative string observation ("normal") on a non-ACVPU LOINC code,
    # and an invalid ACVPU string ("UNKNOWN") on 67775-7 that should normalize to "A".
    hr_concept = FHIRCodeableConcept(
        coding=(FHIRCoding(system="http://loinc.org", code="8867-4", display="Heart rate"),),
        text="Heart rate",
    )
    acvpu_concept = FHIRCodeableConcept(
        coding=(FHIRCoding(system="http://loinc.org", code="67775-7", display="ACVPU"),),
        text="ACVPU",
    )
    obs_newer_normal_hr = FHIRObservation(
        id="kms:obs-2",
        subject_id="kms:pat-1",
        encounter_id="kms:enc-1",
        effective_datetime=t1,
        code=hr_concept,
        value_quantity=FHIRQuantity(value=76.0, unit="/min", code="/min"),
    )
    obs_older_high_hr = FHIRObservation(
        id="kms:obs-1",
        subject_id="kms:pat-1",
        encounter_id="kms:enc-1",
        effective_datetime=t0,
        code=hr_concept,
        value_quantity=FHIRQuantity(value=135.0, unit="/min", code="/min"),
    )
    obs_qualitative_text = FHIRObservation(
        id="kms:obs-3",
        subject_id="kms:pat-1",
        encounter_id="kms:enc-1",
        effective_datetime=t1,
        code=hr_concept,
        value_string="normal sinus rhythm",
    )
    obs_invalid_acvpu = FHIRObservation(
        id="kms:obs-4",
        subject_id="kms:pat-1",
        encounter_id="kms:enc-1",
        effective_datetime=t0,
        code=acvpu_concept,
        value_string="unrecognized",
    )
    bundle = FHIRBundle(
        id="kms:bundle-1",
        timestamp=t0,
        entries=(
            obs_newer_normal_hr,
            obs_older_high_hr,
            obs_qualitative_text,
            obs_invalid_acvpu,
        ),
    )
    alert = scorer.evaluate_bundle(bundle)
    assert alert.patient_token == "kms:pat-1"
    assert alert.encounter_token == "kms:enc-1"
    assert alert.news2_score == 0
    assert alert.qsofa_score == 0
    assert alert.risk_level == "LOW"

    # Empty observation-less bundle fallback
    empty_alert = scorer.evaluate_bundle(FHIRBundle(id="kms:empty", timestamp=t0, entries=()))
    assert empty_alert.patient_token == "UNKNOWN-PATIENT"
    assert empty_alert.encounter_token == "UNKNOWN-ENCOUNTER"


def test_clinical_deterioration_scorer_news2_physiological_bands_and_rounding() -> None:
    """Verify all NEWS2 parameter bands, fractional vital rounding, and risk tiers."""
    scorer = ClinicalDeteriorationScorer()
    ts = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    # Fractional boundary check: HR 130.7 rounds to 131 (+3), RR 24.6 rounds to 25 (+3)
    fractional = VitalSignSnapshot(
        respiratory_rate=24.6,
        spo2_percent=91.4,
        inhaled_o2_percent=28.0,
        systolic_bp=90.4,
        heart_rate=130.7,
        temperature_celsius=35.04,
        lactate_mmol_l=3.2,
        acvpu_consciousness="V",
    )
    alert_fractional = scorer.score_snapshot(
        snapshot=fractional,
        patient_token="kms:p1",
        encounter_token="kms:e1",
        evaluated_at=ts,
    )
    assert alert_fractional.risk_level == "HIGH"
    assert alert_fractional.news2_score == 20

    # Mildly abnormal bands (RR 9-11, SpO2 92-93, SBP 91-100, HR 41-50, Temp 35.1-36.0)
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

    # Score 5-6 MEDIUM tier (RR 22, SpO2 94, SBP 105, HR 95, Temp 38.5 => score 6)
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

    # Single parameter red score (score 3 on SBP >= 220, all others 0 -> LOW_MEDIUM)
    single_red = VitalSignSnapshot(
        respiratory_rate=15.0,
        spo2_percent=98.0,
        inhaled_o2_percent=21.0,
        systolic_bp=225.0,
        heart_rate=115.0,
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

    alert_hr_band = scorer.score_snapshot(
        snapshot=single_red,
        patient_token="kms:p5",
        encounter_token="kms:e5",
        evaluated_at=ts,
    )
    assert alert_hr_band.news2_score == 5
