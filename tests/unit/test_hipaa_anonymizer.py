"""Unit tests for the HIPAA Safe Harbor 18-identifier de-identification engine and auditor."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from healthcare_lakehouse.models.fhir_resources import (
    FHIRAddress,
    FHIRBundle,
    FHIRHumanName,
    FHIRIdentifier,
    FHIRPatient,
)
from healthcare_lakehouse.security.hipaa_anonymizer import (
    HIPAAAnonymizer,
    HIPAAComplianceAuditor,
    HIPAAComplianceError,
)
from healthcare_lakehouse.synthetic.synthea_orchestrator import SyntheaOrchestrator


def test_hipaa_anonymizer_deidentifies_cohort_and_preserves_longitudinal_intervals() -> None:
    """Verify all 18 HIPAA Safe Harbor identifiers are masked and clinical deltas remain intact."""
    orchestrator = SyntheaOrchestrator(seed=42)
    raw_bundles = orchestrator.generate_cohort(patient_count=6)
    anonymizer = HIPAAAnonymizer()
    auditor = HIPAAComplianceAuditor()

    for raw_bundle in raw_bundles:
        # Raw bundle contains synthetic PHI and must fail the compliance audit before anonymization
        raw_report = auditor.audit_bundle(raw_bundle)
        assert raw_report.is_compliant is False
        assert len(raw_report.violations) > 0

        # Calculate exact time delta between encounter start and first observation before shift
        raw_enc_start = raw_bundle.encounters()[0].period_start
        raw_obs_time = raw_bundle.observations()[0].effective_datetime
        expected_delta = raw_obs_time - raw_enc_start

        clean_bundle = anonymizer.anonymize_bundle(raw_bundle)

        # Verify compliance audit passes with 0 violations on anonymized bundle
        clean_report = auditor.assert_bundle_compliant(clean_bundle)
        assert clean_report.is_compliant is True
        assert clean_report.violations == ()

        # Verify longitudinal interval between encounter and observation is 100% preserved
        clean_enc_start = clean_bundle.encounters()[0].period_start
        clean_obs_time = clean_bundle.observations()[0].effective_datetime
        assert (clean_obs_time - clean_enc_start) == expected_delta
        assert clean_enc_start != raw_enc_start

        # Verify relational foreign keys match tokenized patient and encounter IDs
        pat = clean_bundle.patients()[0]
        enc = clean_bundle.encounters()[0]
        assert enc.subject_id == pat.id
        for obs in clean_bundle.observations():
            assert obs.subject_id == pat.id
            assert obs.encounter_id == enc.id
        for cond in clean_bundle.conditions():
            assert cond.subject_id == pat.id
            assert cond.encounter_id == enc.id
        for med in clean_bundle.medication_requests():
            assert med.subject_id == pat.id
            assert med.encounter_id == enc.id


def test_hipaa_anonymizer_top_codes_90_plus_and_masks_short_or_restricted_zip() -> None:
    """Verify elderly age 90+ top-coding, short ZIPs, and auditor violation detection."""
    anonymizer = HIPAAAnonymizer()
    auditor = HIPAAComplianceAuditor()
    assert anonymizer.tokenizer.active_key_id == "kms-hipaa-key-2026-v1"
    assert anonymizer.scrub_free_text("No names here", sensitive_names=None) == "No names here"
    assert anonymizer.scrub_free_text("Initial J.", sensitive_names=["J", "Smith"]) == "Initial J."
    ts = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    elderly_patient = FHIRPatient(
        id="pat-elderly-95",
        identifiers=(FHIRIdentifier(system="http://hosp/mrn", value="MRN-999"),),
        names=(FHIRHumanName(family="Smith", given=("John",)),),
        gender="male",
        birth_date=date(1930, 5, 20),  # 96 years old in 2026
        addresses=(
            FHIRAddress(
                line=("123 Secret Ln",),
                city="TinyTown",
                state="WY",
                postal_code="82",  # Short malformed postal code -> "000"
            ),
        ),
        ssn="999-88-7777",
        device_ip="10.0.0.1",
        clinical_note="John Smith SSN 999-88-7777 IP 10.0.0.1 email a@b.com phone 617-555-1234",
    )
    bundle = FHIRBundle(id="b-elderly", timestamp=ts, entries=(elderly_patient,))
    clean = anonymizer.anonymize_bundle(bundle)
    clean_pat = clean.patients()[0]

    assert clean_pat.age_years == 90
    assert clean_pat.birth_date == date(1936, 1, 1)
    assert clean_pat.addresses[0].postal_code == "000"
    assert clean_pat.clinical_note is not None
    assert "999-88-7777" not in clean_pat.clinical_note
    assert "10.0.0.1" not in clean_pat.clinical_note
    assert "John" not in clean_pat.clinical_note
    assert auditor.assert_bundle_compliant(clean).is_compliant is True

    # Verify assert_bundle_compliant raises HIPAAComplianceError on unmasked bundle
    with pytest.raises(HIPAAComplianceError, match="HIPAA Safe Harbor audit failed"):
        auditor.assert_bundle_compliant(bundle)

    # Also test auditor catches restricted ZIP-3, age > 90, and leaked observation note
    leaked_patient = clean_pat.model_copy(
        update={
            "age_years": 94,
            "birth_date": date(1930, 5, 20),
            "clinical_note": None,
            "addresses": (
                FHIRAddress(
                    line=("REDACTED",),
                    city="REDACTED",
                    state="NH",
                    postal_code="036",
                ),
            ),
        }
    )
    leaked_bundle = FHIRBundle(id="b-leak", timestamp=ts, entries=(leaked_patient,))
    leaked_report = auditor.audit_bundle(leaked_bundle)
    assert leaked_report.is_compliant is False
    assert any("age_years" in v for v in leaked_report.violations)
    assert any("Restricted or unmasked postal_code" in v for v in leaked_report.violations)
