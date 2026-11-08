"""HL7 v2.5.1 pipe-delimited bedside telemetry & ADT message stream simulator."""

from __future__ import annotations

from collections.abc import Sequence

from healthcare_lakehouse.models.fhir_resources import FHIRBundle, FHIRPatient

MLLP_START_BLOCK: bytes = b"\x0b"
MLLP_END_BLOCK: bytes = b"\x1c\x0d"


class HL7v2Simulator:
    """Synthesizes standards-compliant HL7 v2.5.1 pipe-delimited ADT and ORU streams."""

    def generate_adt_a01_from_bundle(self, bundle: FHIRBundle) -> str:
        """Generate an HL7 v2.5.1 ADT^A01 (Patient Admit) message from a FHIRBundle."""
        patient = bundle.patients()[0]
        encounter = bundle.encounters()[0]
        conditions = bundle.conditions()

        ts_str = encounter.period_start.strftime("%Y%m%d%H%M%S")
        msh = (
            f"MSH|^~\\&|BEDSIDE_EHR|{encounter.facility_id}|LAKEHOUSE_INGEST|MEDALLION|"
            f"{ts_str}||ADT^A01^ADT_A01|MSG-{encounter.id}|P|2.5.1"
        )
        pid = self._build_pid_segment(patient)
        attending = (encounter.attending_physician or "Dr. House").replace(" ", "^")
        pv1 = (
            f"PV1|1|{encounter.class_code}|ICU-WEST^BED-04^01||||"
            f"NPI-9988^{attending}|||||||||||{encounter.id}|||||||||||||||||||||||||{ts_str}"
        )

        segments: list[str] = [msh, pid, pv1]
        for idx, cond in enumerate(conditions, start=1):
            coding = cond.code.coding[0]
            dg1_ts = cond.onset_datetime.strftime("%Y%m%d%H%M%S")
            segments.append(
                f"DG1|{idx}|I10|{coding.code}^{coding.display}^ICD10|{coding.display}|{dg1_ts}|F"
            )
        return "\n".join(segments)

    def generate_oru_r01_from_bundle(self, bundle: FHIRBundle) -> str:
        """Generate an HL7 v2.5.1 ORU^R01 (Unsolicited Observation) message from a FHIRBundle."""
        patient = bundle.patients()[0]
        encounter = bundle.encounters()[0]
        observations = bundle.observations()

        ts_str = encounter.period_start.strftime("%Y%m%d%H%M%S")
        msh = (
            f"MSH|^~\\&|ICU_TELEMETRY|{encounter.facility_id}|LAKEHOUSE_INGEST|MEDALLION|"
            f"{ts_str}||ORU^R01^ORU_R01|ORU-{encounter.id}|P|2.5.1"
        )
        pid = self._build_pid_segment(patient)
        pv1 = (
            f"PV1|1|{encounter.class_code}|ICU-WEST^BED-04^01||||"
            f"NPI-9988^Jenkins^Sarah|||||||||||{encounter.id}|||||||||||||||||||||||||{ts_str}"
        )
        obr = f"OBR|1|ORD-{encounter.id}|FIL-{encounter.id}|85353-1^Vital signs panel^LN|||{ts_str}"

        segments: list[str] = [msh, pid, pv1, obr]
        for idx, obs in enumerate(observations, start=1):
            coding = obs.code.coding[0]
            obs_ts = obs.effective_datetime.strftime("%Y%m%d%H%M%S")
            if obs.value_quantity is not None:
                val_type = "NM"
                val_str = str(obs.value_quantity.value)
                unit_str = f"{obs.value_quantity.unit}^{obs.value_quantity.unit}^UCUM"
            else:
                val_type = "ST"
                val_str = obs.value_string or ""
                unit_str = "{score}^{score}^UCUM"

            segments.append(
                f"OBX|{idx}|{val_type}|{coding.code}^{coding.display}^LN||"
                f"{val_str}|{unit_str}||{obs.interpretation_code}|||F|||{obs_ts}"
            )
        return "\n".join(segments)

    def generate_stream_from_bundles(self, bundles: Sequence[FHIRBundle]) -> tuple[str, ...]:
        """Generate paired ADT^A01 and ORU^R01 HL7 v2.5.1 messages for each bundle."""
        stream: list[str] = []
        for bundle in bundles:
            stream.append(self.generate_adt_a01_from_bundle(bundle))
            stream.append(self.generate_oru_r01_from_bundle(bundle))
        return tuple(stream)

    @staticmethod
    def wrap_mllp_frame(hl7_message: str) -> bytes:
        """Wrap an HL7 v2 message string inside Minimal Lower Layer Protocol (MLLP) bytes."""
        return MLLP_START_BLOCK + hl7_message.encode("utf-8") + MLLP_END_BLOCK

    @staticmethod
    def unwrap_mllp_frame(frame: bytes) -> str:
        """Strip MLLP framing bytes and decode the inner HL7 v2 message."""
        if not (frame.startswith(MLLP_START_BLOCK) and frame.endswith(MLLP_END_BLOCK)):
            raise ValueError(
                "Invalid MLLP frame: missing start block (0x0B) or end block (0x1C0D)."
            )
        return frame[len(MLLP_START_BLOCK) : -len(MLLP_END_BLOCK)].decode("utf-8")

    @staticmethod
    def _build_pid_segment(patient: FHIRPatient) -> str:
        mrn = patient.identifiers[0].value if patient.identifiers else patient.id
        name = patient.names[0]
        given = name.given[0] if name.given else "Unknown"
        prefix = name.prefix[0] if name.prefix else ""
        dob = patient.birth_date.strftime("%Y%m%d")
        sex_map = {"male": "M", "female": "F", "other": "O", "unknown": "U"}
        sex_code = sex_map.get(patient.gender, "U")

        addr = patient.addresses[0]
        street = addr.line[0] if addr.line else ""
        phone = next((t.value for t in patient.telecom if t.system == "phone"), "")
        ssn = patient.ssn or ""

        return (
            f"PID|1||{mrn}^^^HOSP^MR||{name.family}^{given}^^^{prefix}||"
            f"{dob}|{sex_code}|||{street}^^{addr.city}^{addr.state}^{addr.postal_code}^US||"
            f"{phone}||||||{ssn}"
        )
