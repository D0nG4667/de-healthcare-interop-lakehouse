"""Unit tests for the HL7 v2.5.1 pipe-delimited parser and FHIR R4 canonical translator."""

from __future__ import annotations

import pytest

from healthcare_lakehouse.parsers.hl7v2_parser import HL7v2Parser
from healthcare_lakehouse.synthetic.hl7v2_simulator import HL7v2Simulator
from healthcare_lakehouse.synthetic.synthea_orchestrator import SyntheaOrchestrator


def test_hl7v2_parser_parses_adt_and_oru_into_canonical_fhir_bundles() -> None:
    """Verify HL7v2Parser translates ADT^A01, ORU^R01, and MLLP bytes into FHIRBundle."""
    orchestrator = SyntheaOrchestrator(seed=42)
    source_bundle = orchestrator.simulate_patient_lifecycle(
        patient_index=0,
        module_name="sepsis_deterioration",
        force_critical_trajectory=True,
    )
    simulator = HL7v2Simulator()
    parser = HL7v2Parser()

    adt_raw = simulator.generate_adt_a01_from_bundle(source_bundle)
    parsed_adt = parser.parse_message(adt_raw)
    assert parsed_adt.message_type == "ADT^A01"
    assert parsed_adt.sending_application == "BEDSIDE_EHR"
    assert parsed_adt.segments[0].field(99) == ""
    assert parsed_adt.segments[0].components(99) == ()

    adt_bundle = parser.translate_to_fhir_bundle(adt_raw)
    assert len(adt_bundle.patients()) == 1
    assert len(adt_bundle.encounters()) == 1
    assert len(adt_bundle.conditions()) == 1
    assert adt_bundle.patients()[0].ssn == source_bundle.patients()[0].ssn

    oru_raw = simulator.generate_oru_r01_from_bundle(source_bundle)
    mllp_bytes = simulator.wrap_mllp_frame(oru_raw)
    oru_bundle = parser.translate_to_fhir_bundle(mllp_bytes)
    assert len(oru_bundle.patients()) == 1
    assert len(oru_bundle.observations()) == len(source_bundle.observations())
    # Verify both numeric and string (ACVPU) OBX observations were translated
    assert any(o.value_quantity is not None for o in oru_bundle.observations())
    assert any(o.value_string == "C" for o in oru_bundle.observations())


def test_hl7v2_parser_handles_raw_bytes_and_rejects_malformed_messages() -> None:
    """Verify error handling for empty messages, missing MSH, or missing PID segments."""
    parser = HL7v2Parser()

    minimal_hl7 = (
        b"MSH|^~\\&|MON|FAC01|LAKE|MED|20260615103000||ADT^A08|MSG1|P|2.5.1\n"
        b"PID|1||MRN-99^^^HOSP^MR||Doe^Jane||19750101|O|||10 Main St^^Boston^MA^02115^US||"
    )
    bundle = parser.translate_to_fhir_bundle(minimal_hl7)
    assert bundle.patients()[0].gender == "other"
    assert bundle.patients()[0].ssn is None

    with pytest.raises(ValueError, match="Empty HL7 v2 message"):
        parser.parse_message("   \n  ")

    with pytest.raises(ValueError, match="must begin with an MSH segment"):
        parser.parse_message("PID|1||MRN-100||Smith^John")

    with pytest.raises(ValueError, match="missing required PID segment"):
        parser.translate_to_fhir_bundle(
            "MSH|^~\\&|MON|FAC01|LAKE|MED|20260615103000||ADT^A01|MSG1|P|2.5.1"
        )
