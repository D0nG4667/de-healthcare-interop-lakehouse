"""Unit tests for the Synthea state-machine clinical lifecycle orchestrator."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from healthcare_lakehouse.models.fhir_resources import FHIRBundle, FHIRPatient
from healthcare_lakehouse.synthetic.synthea_orchestrator import (
    SyntheaModuleDefinition,
    SyntheaOrchestrator,
)


def test_synthea_orchestrator_loads_builtin_disease_modules() -> None:
    """Verify built-in sepsis and cardiopulmonary Synthea modules load and validate."""
    orchestrator = SyntheaOrchestrator(seed=42)
    modules = orchestrator.available_modules()
    assert "sepsis_deterioration" in modules
    assert "cardiopulmonary_chronic" in modules

    sepsis_mod = orchestrator.get_module("sepsis_deterioration")
    assert isinstance(sepsis_mod, SyntheaModuleDefinition)
    assert "Initial" in sepsis_mod.states
    assert "Terminal" in sepsis_mod.states


def test_synthea_orchestrator_synthesizes_longitudinal_sepsis_and_chronic_cohorts() -> None:
    """Verify cohort generation produces valid FHIR R4 Bundles with longitudinal vitals."""
    orchestrator = SyntheaOrchestrator(seed=101)
    bundles = orchestrator.generate_cohort(patient_count=6)
    assert len(bundles) == 6

    # Verify mix of sepsis deterioration, chronic cardiopulmonary, and elderly (90+) patients
    ages_in_2026 = [2026 - b.patients()[0].birth_date.year for b in bundles]
    assert any(age >= 90 for age in ages_in_2026)

    # Verify restricted ZIP-3 prefix coverage exists in generated cohort for HIPAA testing
    zip_prefixes = {b.patients()[0].addresses[0].postal_code[:3] for b in bundles}
    assert any(prefix in {"036", "059", "821"} for prefix in zip_prefixes)

    for bundle in bundles:
        patient = bundle.patients()[0]
        encounters = bundle.encounters()
        observations = bundle.observations()
        conditions = bundle.conditions()
        medications = bundle.medication_requests()

        assert len(encounters) >= 1
        assert len(observations) >= 7
        assert len(conditions) >= 1
        assert len(medications) >= 1

        # Verify relational integrity across patient, encounter, observations, and meds
        enc_ids = {e.id for e in encounters}
        for obs in observations:
            assert obs.subject_id == patient.id
            assert obs.encounter_id in enc_ids
        for cond in conditions:
            assert cond.subject_id == patient.id
            assert cond.encounter_id in enc_ids
        for med in medications:
            assert med.subject_id == patient.id
            assert med.encounter_id in enc_ids


def test_synthea_orchestrator_renders_fhir_xml_and_rejects_invalid_inputs() -> None:
    """Verify FHIR R4 XML serialization and error handling for unknown modules or counts."""
    orchestrator = SyntheaOrchestrator(seed=7)
    bundle = orchestrator.simulate_patient_lifecycle(
        patient_index=0,
        module_name="sepsis_deterioration",
        force_critical_trajectory=True,
    )
    xml_payload = orchestrator.bundle_to_fhir_xml(bundle)
    assert "<Bundle" in xml_payload
    assert "<Patient>" in xml_payload
    assert "<Observation>" in xml_payload

    # Also verify XML rendering when patient has no optional identifiers/names/addresses/extensions
    minimal_bundle = FHIRBundle(
        id="bundle-min-xml",
        timestamp=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        entries=(
            FHIRPatient(
                id="pat-xml-min",
                identifiers=(),
                names=(),
                gender="other",
                birth_date=date(1990, 5, 5),
            ),
        ),
    )
    min_xml = orchestrator.bundle_to_fhir_xml(minimal_bundle)
    assert "pat-xml-min" in min_xml

    stable_bundle = orchestrator.simulate_patient_lifecycle(
        patient_index=1,
        module_name="cardiopulmonary_chronic",
        force_critical_trajectory=False,
    )
    assert len(stable_bundle.observations()) >= 7

    with pytest.raises(ValueError, match="Unknown Synthea module"):
        orchestrator.get_module("non_existent_module")

    with pytest.raises(ValueError, match="patient_count must be >= 1"):
        orchestrator.generate_cohort(patient_count=0)
