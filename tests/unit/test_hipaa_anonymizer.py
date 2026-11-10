"""Unit tests for the HIPAA Safe Harbor 18-identifier de-identification engine and auditor."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from healthcare_lakehouse.config.settings import LakehouseSettings
from healthcare_lakehouse.models.fhir_resources import (
    FHIRAddress,
    FHIRBundle,
    FHIRCodeableConcept,
    FHIRCoding,
    FHIRCondition,
    FHIREncounter,
    FHIRHumanName,
    FHIRIdentifier,
    FHIRMedicationRequest,
    FHIRObservation,
    FHIRPatient,
)
from healthcare_lakehouse.parsers.hl7v2_parser import HL7v2Parser
from healthcare_lakehouse.security.hipaa_anonymizer import (
    HIPAAAnonymizer,
    HIPAAComplianceAuditor,
    HIPAAComplianceError,
)
from healthcare_lakehouse.security.kms_tokenizer import DEFAULT_DEV_SECRET_ENV
from healthcare_lakehouse.synthetic.hl7v2_simulator import HL7v2Simulator
from healthcare_lakehouse.synthetic.synthea_orchestrator import SyntheaOrchestrator


def test_hipaa_anonymizer_deidentifies_cohort_and_preserves_longitudinal_intervals() -> None:
    """Verify all 18 HIPAA Safe Harbor identifiers are masked and clinical deltas remain intact."""
    orchestrator = SyntheaOrchestrator(seed=42)
    raw_bundles = orchestrator.generate_cohort(patient_count=6)
    anonymizer = HIPAAAnonymizer()
    auditor = HIPAAComplianceAuditor()

    for raw_bundle in raw_bundles:
        raw_report = auditor.audit_bundle(raw_bundle)
        assert raw_report.is_compliant is False
        assert len(raw_report.violations) > 0

        raw_enc_start = raw_bundle.encounters()[0].period_start
        raw_obs_time = raw_bundle.observations()[0].effective_datetime
        expected_delta = raw_obs_time - raw_enc_start

        clean_bundle = anonymizer.anonymize_bundle(raw_bundle)

        clean_report = auditor.assert_bundle_compliant(clean_bundle)
        assert clean_report.is_compliant is True
        assert clean_report.violations == ()

        clean_enc_start = clean_bundle.encounters()[0].period_start
        clean_obs_time = clean_bundle.observations()[0].effective_datetime
        assert (clean_obs_time - clean_enc_start) == expected_delta
        assert clean_enc_start != raw_enc_start

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


def test_hipaa_anonymizer_links_cross_protocol_hl7v2_and_fhir_patients_by_mrn() -> None:
    """Verify the same patient arriving via FHIR R4 and HL7 v2 gets identical token & shift."""
    orchestrator = SyntheaOrchestrator(seed=42)
    fhir_bundle = orchestrator.simulate_patient_lifecycle(patient_index=0)
    hl7_raw = HL7v2Simulator().generate_oru_r01_from_bundle(fhir_bundle)
    hl7_bundle = HL7v2Parser().translate_to_fhir_bundle(hl7_raw)

    anonymizer = HIPAAAnonymizer()
    clean_fhir = anonymizer.anonymize_bundle(fhir_bundle)
    clean_hl7 = anonymizer.anonymize_bundle(hl7_bundle)

    assert clean_fhir.patients()[0].id == clean_hl7.patients()[0].id
    assert clean_fhir.encounters()[0].period_start == clean_hl7.encounters()[0].period_start


def test_hipaa_anonymizer_top_codes_90_plus_and_scrubs_obs_and_med_free_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify age 89/90+ anchoring, custom KMS key wiring, and full free-text scrubbing."""
    custom_settings = LakehouseSettings(kms_active_key_id="kms-custom-2026-v3")
    anonymizer = HIPAAAnonymizer(settings=custom_settings)
    auditor = HIPAAComplianceAuditor()
    assert anonymizer.tokenizer.active_key_id == "kms-custom-2026-v3"
    assert anonymizer.scrub_free_text("No names here", sensitive_names=None) == "No names here"
    assert anonymizer.scrub_free_text("Initial J.", sensitive_names=["J", "Smith"]) == "Initial J."

    monkeypatch.delenv(DEFAULT_DEV_SECRET_ENV, raising=False)
    with pytest.raises(ValueError, match=DEFAULT_DEV_SECRET_ENV):
        HIPAAAnonymizer(settings=LakehouseSettings(environment="production"))

    ts = datetime(2026, 2, 10, 12, 0, tzinfo=UTC)
    elderly_patient = FHIRPatient(
        id="pat-elderly-95",
        identifiers=(FHIRIdentifier(system="http://hosp/mrn", value="MRN-999"),),
        names=(FHIRHumanName(family="Smith", given=("John",)),),
        gender="male",
        birth_date=date(1930, 5, 20),
        addresses=(
            FHIRAddress(
                line=("123 Secret Ln",),
                city="TinyTown",
                state="WY",
                postal_code="82",
            ),
        ),
        ssn="999-88-7777",
        device_ip="10.0.0.1",
        clinical_note=(
            "John Smith SSN 999-88-7777 IP 10.0.0.1 IPv6 2001:0db8:85a3:0000:0000:8a2e:0370:7334 "
            "email a@b.com phone (617) 555-1234"
        ),
    )
    enc = FHIREncounter(
        id="enc-999",
        subject_id="pat-elderly-95",
        period_start=ts,
        attending_physician="Dr. Gregory House",
    )
    obs_narrative = FHIRObservation(
        id="obs-text-1",
        subject_id="pat-elderly-95",
        encounter_id="enc-999",
        effective_datetime=ts,
        code=FHIRCodeableConcept(
            coding=(FHIRCoding(system="http://loinc.org", code="8867-4", display="Heart rate"),),
            text="Heart rate",
        ),
        value_string="Narrative for John Smith with Dr. Gregory House call (617) 555-1234",
    )
    med = FHIRMedicationRequest(
        id="med-999",
        subject_id="pat-elderly-95",
        encounter_id="enc-999",
        authored_on=ts,
        medication_code=FHIRCodeableConcept(
            coding=(
                FHIRCoding(
                    system="http://www.nlm.nih.gov/research/umls/rxnorm",
                    code="11124",
                    display="Vancomycin",
                ),
            ),
            text="Vancomycin",
        ),
        dosage_text="Dispense to John Smith MRN-999 via 2001:0db8:85a3:0000:0000:8a2e:0370:7334",
    )
    bundle = FHIRBundle(
        id="b-elderly",
        timestamp=ts,
        entries=(elderly_patient, enc, obs_narrative, med),
    )
    clean = anonymizer.anonymize_bundle(bundle)
    clean_pat = clean.patients()[0]
    clean_obs = clean.observations()[0]
    clean_med = clean.medication_requests()[0]

    assert clean_pat.age_years == 90
    assert clean_pat.birth_date == date(clean.timestamp.year - 90, 1, 1)
    assert clean_pat.addresses[0].postal_code == "000"
    assert clean_pat.clinical_note is not None
    assert "(617) 555-1234" not in clean_pat.clinical_note
    assert "2001:0db8" not in clean_pat.clinical_note
    assert clean_obs.value_string is not None
    assert "John" not in clean_obs.value_string
    assert "House" not in clean_obs.value_string
    assert "(617) 555-1234" not in clean_obs.value_string
    assert "John" not in clean_med.dosage_text
    assert "MRN-999" not in clean_med.dosage_text
    assert "2001:0db8" not in clean_med.dosage_text
    assert auditor.assert_bundle_compliant(clean).is_compliant is True

    with pytest.raises(HIPAAComplianceError, match="HIPAA Safe Harbor audit failed"):
        auditor.assert_bundle_compliant(bundle)


def test_hipaa_auditor_catches_fake_colon_tokens_and_all_resource_violations() -> None:
    """Verify strict KMS token regex validation and PHI scanning across all 5 resource types."""
    auditor = HIPAAComplianceAuditor()
    ts = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

    # 89-year-old patient check: born 1936-12-20 at 2026-06-15 is 89 years old (not yet 90)
    anonymizer = HIPAAAnonymizer()
    pat_89 = FHIRPatient(
        id="pat-89",
        identifiers=(
            FHIRIdentifier(
                system="http://hl7.org/fhir/sid/us-ssn",
                value="999-00-1111",
                type_code="SS",
            ),
        ),
        names=(FHIRHumanName(family="Doe", given=("Jane",)),),
        gender="female",
        birth_date=date(1936, 12, 20),
        addresses=(),
    )
    enc_89 = FHIREncounter(
        id="enc-89",
        subject_id="pat-89",
        period_start=ts,
        attending_physician=None,
    )
    clean_89 = anonymizer.anonymize_bundle(
        FHIRBundle(id="b-89", timestamp=ts, entries=(pat_89, enc_89))
    )
    assert clean_89.patients()[0].age_years == 89
    assert clean_89.patients()[0].birth_date.year >= clean_89.timestamp.year - 89
    assert auditor.assert_bundle_compliant(clean_89).is_compliant is True

    # Forge a bundle using fake colon prefixes ("urn:uuid:...") and leaked text across resources
    forged_pat = FHIRPatient(
        id="urn:uuid:pat-1",
        identifiers=(FHIRIdentifier(system="http://hosp/mrn", value="MRN:12345"),),
        names=(FHIRHumanName(use="anonymous", family="REDACTED", given=("ANONYMIZED",)),),
        gender="female",
        birth_date=date(1930, 5, 20),
        age_years=94,
        addresses=(
            FHIRAddress(line=("REDACTED",), city="REDACTED", state="NH", postal_code="036"),
        ),
    )
    forged_enc = FHIREncounter(
        id="urn:uuid:enc-1",
        subject_id="urn:uuid:pat-1",
        period_start=ts,
        attending_physician="NPI:998877",
    )
    forged_obs = FHIRObservation(
        id="urn:uuid:obs-1",
        subject_id="urn:uuid:pat-1",
        encounter_id="urn:uuid:enc-1",
        effective_datetime=ts,
        code=FHIRCodeableConcept(
            coding=(FHIRCoding(system="http://loinc.org", code="8867-4", display="HR"),),
            text="HR",
        ),
        value_string="Call (617) 555-9999 or https://ehr.local/p/1",
        note="IPv6 2001:0db8:85a3:0000:0000:8a2e:0370:7334",
    )
    forged_cond = FHIRCondition(
        id="urn:uuid:cond-1",
        subject_id="urn:uuid:pat-1",
        encounter_id="urn:uuid:enc-1",
        onset_datetime=ts,
        code=FHIRCodeableConcept(
            coding=(
                FHIRCoding(
                    system="http://hl7.org/fhir/sid/icd-10-cm", code="A41.9", display="Sepsis"
                ),
            ),
            text="Sepsis",
        ),
    )
    forged_med = FHIRMedicationRequest(
        id="urn:uuid:med-1",
        subject_id="urn:uuid:pat-1",
        encounter_id="urn:uuid:enc-1",
        authored_on=ts,
        medication_code=FHIRCodeableConcept(
            coding=(FHIRCoding(system="http://rxnorm", code="11124", display="Vanco"),),
            text="Vanco",
        ),
        dosage_text="Patient SSN 123-45-6789 email leak@hosp.org IP 192.168.1.9 MRN-555",
    )
    forged_bundle = FHIRBundle(
        id="urn:uuid:bundle-1",
        timestamp=ts,
        entries=(forged_pat, forged_enc, forged_obs, forged_cond, forged_med),
    )
    report = auditor.audit_bundle(forged_bundle)
    assert report.is_compliant is False
    joined = "\n".join(report.violations)
    assert "Bundle.id" in joined
    assert "Patient.id" in joined
    assert "Patient.identifier" in joined
    assert "Encounter.id" in joined
    assert "Encounter.attending_physician" in joined
    assert "Observation.id" in joined
    assert "Condition.id" in joined
    assert "MedicationRequest.id" in joined
    assert "Observation(urn:uuid:obs-1).value_string" in joined
    assert "MedicationRequest(urn:uuid:med-1).dosage_text" in joined
