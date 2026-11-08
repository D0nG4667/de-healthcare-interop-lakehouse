"""Unit tests for strict Pydantic v2 HL7 FHIR R4 domain models."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from healthcare_lakehouse.models.fhir_resources import (
    FHIRAddress,
    FHIRBundle,
    FHIRCodeableConcept,
    FHIRCoding,
    FHIRCondition,
    FHIRContactPoint,
    FHIREncounter,
    FHIRHumanName,
    FHIRIdentifier,
    FHIRMedicationRequest,
    FHIRObservation,
    FHIRPatient,
    FHIRQuantity,
)


def _sample_patient() -> FHIRPatient:
    return FHIRPatient(
        id="pat-001",
        identifiers=(
            FHIRIdentifier(
                system="http://hospital.example.org/mrn",
                value="MRN-100200",
                type_code="MR",
            ),
        ),
        names=(FHIRHumanName(family="Rodriguez", given=("Elena", "Maria"), prefix=("Ms.",)),),
        telecom=(
            FHIRContactPoint(system="phone", value="617-555-0142", use="mobile"),
            FHIRContactPoint(system="email", value="elena.rodriguez@example.com", use="home"),
        ),
        gender="female",
        birth_date=date(1931, 4, 15),
        addresses=(
            FHIRAddress(
                line=("742 Huntington Ave", "Apt 4B"),
                city="Boston",
                state="MA",
                postal_code="02115-5001",
            ),
        ),
        ssn="123-45-6789",
        device_ip="192.168.10.45",
        clinical_note="Patient Elena Rodriguez (SSN 123-45-6789) admitted via ED.",
    )


def test_fhir_bundle_resource_accessors_and_roundtrip_serialization() -> None:
    """Verify FHIRBundle filters resource types and roundtrips standard FHIR R4 JSON."""
    patient = _sample_patient()
    ts = datetime(2026, 6, 15, 10, 30, tzinfo=UTC)
    encounter = FHIREncounter(
        id="enc-001",
        status="in-progress",
        class_code="ICU",
        subject_id=patient.id,
        period_start=ts,
        period_end=datetime(2026, 6, 16, 12, 0, tzinfo=UTC),
        reason_code=FHIRCodeableConcept(
            coding=(
                FHIRCoding(
                    system="http://snomed.info/sct",
                    code="91302008",
                    display="Sepsis",
                ),
            ),
            text="Sepsis",
        ),
        facility_id="FAC-BOS-01",
        attending_physician="Dr. Gregory House",
    )
    obs_numeric = FHIRObservation(
        id="obs-hr-001",
        subject_id=patient.id,
        encounter_id=encounter.id,
        effective_datetime=ts,
        code=FHIRCodeableConcept(
            coding=(
                FHIRCoding(
                    system="http://loinc.org",
                    code="8867-4",
                    display="Heart rate",
                ),
            ),
            text="Heart rate",
        ),
        value_quantity=FHIRQuantity(value=134.0, unit="/min", code="/min"),
        interpretation_code="H",
        note="Tachycardia noted by bedside monitor.",
    )
    obs_text = FHIRObservation(
        id="obs-acvpu-001",
        subject_id=patient.id,
        encounter_id=encounter.id,
        effective_datetime=ts,
        code=FHIRCodeableConcept(
            coding=(
                FHIRCoding(
                    system="http://loinc.org",
                    code="67775-7",
                    display="Level of responsiveness",
                ),
            ),
            text="ACVPU Consciousness",
        ),
        value_string="C",
    )
    condition = FHIRCondition(
        id="cond-001",
        subject_id=patient.id,
        encounter_id=encounter.id,
        onset_datetime=ts,
        code=FHIRCodeableConcept(
            coding=(
                FHIRCoding(
                    system="http://hl7.org/fhir/sid/icd-10-cm",
                    code="A41.9",
                    display="Sepsis, unspecified organism",
                ),
            ),
            text="Sepsis, unspecified organism",
        ),
    )
    medication = FHIRMedicationRequest(
        id="med-001",
        subject_id=patient.id,
        encounter_id=encounter.id,
        authored_on=ts,
        medication_code=FHIRCodeableConcept(
            coding=(
                FHIRCoding(
                    system="http://www.nlm.nih.gov/research/umls/rxnorm",
                    code="11124",
                    display="Vancomycin Injectable Solution",
                ),
            ),
            text="Vancomycin 1000 MG IV Q12H",
        ),
        dosage_text="1000 mg IV every 12 hours",
    )

    bundle = FHIRBundle(
        id="bundle-001",
        bundle_type="collection",
        timestamp=ts,
        entries=(patient, encounter, obs_numeric, obs_text, condition, medication),
    )

    assert len(bundle.patients()) == 1
    assert len(bundle.encounters()) == 1
    assert len(bundle.observations()) == 2
    assert len(bundle.conditions()) == 1
    assert len(bundle.medication_requests()) == 1

    fhir_json = bundle.to_fhir_json_dict()
    assert fhir_json["resourceType"] == "Bundle"
    assert len(fhir_json["entry"]) == 6
    # Inject a custom ignored extension to verify extension loop branch handling
    fhir_json["entry"][0]["resource"]["extension"].append(
        {"url": "http://example.org/fhir/ext/other", "valueString": "ignored"}
    )

    reconstructed = FHIRBundle.from_fhir_json_dict(fhir_json)
    assert reconstructed.id == bundle.id
    assert reconstructed.patients()[0].id == "pat-001"
    assert reconstructed.patients()[0].ssn == "123-45-6789"
    first_obs = reconstructed.observations()[0]
    assert first_obs.value_quantity is not None
    assert first_obs.value_quantity.value == 134.0
    assert reconstructed.observations()[1].value_string == "C"
    assert reconstructed.conditions()[0].code.coding[0].code == "A41.9"
    assert reconstructed.medication_requests()[0].medication_code.coding[0].code == "11124"

    # Also test minimal patient & encounter without optional fields
    minimal_patient = FHIRPatient(
        id="pat-min",
        identifiers=(),
        names=(),
        gender="unknown",
        birth_date=date(1980, 1, 1),
    )
    minimal_enc = FHIREncounter(
        id="enc-min",
        subject_id="pat-min",
        period_start=ts,
    )
    min_bundle = FHIRBundle(id="b-min", timestamp=ts, entries=(minimal_patient, minimal_enc))
    min_roundtrip = FHIRBundle.from_fhir_json_dict(min_bundle.to_fhir_json_dict())
    assert min_roundtrip.patients()[0].ssn is None
    assert min_roundtrip.encounters()[0].period_end is None


def test_fhir_observation_requires_quantity_or_string_value() -> None:
    """Verify FHIRObservation rejects observations missing both value_quantity and value_string."""
    with pytest.raises(ValidationError):
        FHIRObservation(
            id="obs-invalid",
            subject_id="pat-001",
            encounter_id="enc-001",
            effective_datetime=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
            code=FHIRCodeableConcept(
                coding=(FHIRCoding(system="http://loinc.org", code="8867-4", display="HR"),),
                text="HR",
            ),
        )


def test_fhir_bundle_from_json_rejects_invalid_bundle_or_unknown_resource() -> None:
    """Verify FHIRBundle.from_fhir_json_dict validates resourceType and entry schemas."""
    with pytest.raises(ValueError, match="Expected FHIR Bundle"):
        FHIRBundle.from_fhir_json_dict({"resourceType": "Patient", "id": "p1"})

    with pytest.raises(ValueError, match="Unsupported FHIR resourceType"):
        FHIRBundle.from_fhir_json_dict(
            {
                "resourceType": "Bundle",
                "id": "b-bad",
                "type": "collection",
                "timestamp": "2026-06-15T10:30:00+00:00",
                "entry": [{"resource": {"resourceType": "DiagnosticReport", "id": "dr1"}}],
            }
        )
