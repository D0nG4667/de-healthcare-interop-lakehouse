"""Unit tests for the HL7 v2.5.1 pipe-delimited clinical stream simulator."""

from __future__ import annotations

import pytest

from healthcare_lakehouse.synthetic.hl7v2_simulator import HL7v2Simulator
from healthcare_lakehouse.synthetic.synthea_orchestrator import SyntheaOrchestrator


def test_hl7v2_simulator_emits_adt_and_oru_pipe_delimited_messages() -> None:
    """Verify HL7v2Simulator generates valid MSH, PID, PV1, OBR, OBX, and DG1 segments."""
    orchestrator = SyntheaOrchestrator(seed=42)
    bundle = orchestrator.simulate_patient_lifecycle(
        patient_index=0,
        module_name="sepsis_deterioration",
        force_critical_trajectory=True,
    )
    simulator = HL7v2Simulator()

    adt_msg = simulator.generate_adt_a01_from_bundle(bundle)
    assert adt_msg.startswith("MSH|^~\\&|BEDSIDE_EHR|")
    assert "|ADT^A01^ADT_A01|" in adt_msg
    assert "\nPID|1||" in adt_msg
    assert "\nPV1|1|" in adt_msg
    assert "\nDG1|1|" in adt_msg

    oru_msg = simulator.generate_oru_r01_from_bundle(bundle)
    assert oru_msg.startswith("MSH|^~\\&|ICU_TELEMETRY|")
    assert "|ORU^R01^ORU_R01|" in oru_msg
    assert "\nPID|1||" in oru_msg
    assert "\nOBR|1|" in oru_msg
    assert "\nOBX|1|NM|" in oru_msg

    # Verify MLLP framing wrapper
    mllp_bytes = simulator.wrap_mllp_frame(oru_msg)
    assert mllp_bytes.startswith(b"\x0b")
    assert mllp_bytes.endswith(b"\x1c\x0d")
    assert simulator.unwrap_mllp_frame(mllp_bytes) == oru_msg


def test_hl7v2_simulator_stream_batch_and_validation_errors() -> None:
    """Verify batch stream generation and MLLP frame validation error handling."""
    orchestrator = SyntheaOrchestrator(seed=99)
    bundles = orchestrator.generate_cohort(patient_count=2)
    simulator = HL7v2Simulator()

    messages = simulator.generate_stream_from_bundles(bundles)
    assert len(messages) == 4  # 1 ADT^A01 + 1 ORU^R01 per bundle

    with pytest.raises(ValueError, match="Invalid MLLP frame"):
        simulator.unwrap_mllp_frame(b"MSH|^~\\&|NO_FRAMING")
