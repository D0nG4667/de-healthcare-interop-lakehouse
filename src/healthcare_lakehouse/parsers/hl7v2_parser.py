"""HL7 v2.5.1 pipe-delimited / MLLP parser and canonical HL7 FHIR R4 translator."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from healthcare_lakehouse.models.fhir_resources import (
    FHIRAddress,
    FHIRBundle,
    FHIRBundleEntry,
    FHIRCodeableConcept,
    FHIRCoding,
    FHIRCondition,
    FHIRContactPoint,
    FHIREncounter,
    FHIRHumanName,
    FHIRIdentifier,
    FHIRObservation,
    FHIRPatient,
    FHIRQuantity,
)
from healthcare_lakehouse.synthetic.hl7v2_simulator import (
    MLLP_END_BLOCK,
    MLLP_START_BLOCK,
)

_HL7_ESCAPE_MAP: tuple[tuple[str, str], ...] = (
    (r"\F\\", "|"),
    (r"\S\\", "^"),
    (r"\T\\", "&"),
    (r"\R\\", "~"),
    (r"\E\\", "\\"),
)


def _unescape_hl7_value(value: str) -> str:
    """Decode standard HL7 v2.5.1 escape sequences (\\F\\, \\S\\, \\T\\, \\R\\, \\E\\)."""
    # Replace \E\ via sentinel first so literal '\F\' from '\E\F\E\' does not double-decode
    sentinel = "\x00"
    decoded = value.replace(r"\E" + "\\", sentinel)
    decoded = decoded.replace(r"\F" + "\\", "|")
    decoded = decoded.replace(r"\S" + "\\", "^")
    decoded = decoded.replace(r"\T" + "\\", "&")
    decoded = decoded.replace(r"\R" + "\\", "~")
    return decoded.replace(sentinel, "\\")


class HL7v2Segment(BaseModel):
    """Parsed representation of a single pipe-delimited HL7 v2 segment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    segment_id: str
    fields: tuple[str, ...]

    def raw_field(self, index: int) -> str:
        """Return unsplit, un-unescaped 1-based HL7 field value."""
        if index < 1 or index >= len(self.fields):
            return ""
        return self.fields[index]

    def field(self, index: int) -> str:
        """Return 1-based HL7 field value (where MSH-1 is '|' and PID-3 is index 3)."""
        raw = self.raw_field(index)
        if not raw:
            return ""
        if self.segment_id == "MSH" and index in {1, 2}:
            return raw
        return _unescape_hl7_value(raw)

    def repetitions(self, index: int) -> tuple[tuple[str, ...], ...]:
        """Return '~'-split repetitions, each split on '^' and unescaped."""
        raw = self.raw_field(index)
        if not raw:
            return ()
        return tuple(
            tuple(_unescape_hl7_value(comp) for comp in rep.split("^")) for rep in raw.split("~")
        )

    def components(self, index: int) -> tuple[str, ...]:
        """Return '^'-split sub-components for the first repetition of a 1-based field."""
        reps = self.repetitions(index)
        return reps[0] if reps else ()


class HL7v2ParsedMessage(BaseModel):
    """Structured representation of a complete HL7 v2.5.1 message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_control_id: str
    message_type: str
    sending_application: str
    sending_facility: str
    timestamp: datetime
    segments: tuple[HL7v2Segment, ...]


class HL7v2Parser:
    """Parses HL7 v2.5.1 pipe-delimited messages and translates them into FHIR R4 Bundles."""

    def parse_message(self, raw_hl7_or_mllp: str | bytes) -> HL7v2ParsedMessage:
        """Parse an HL7 v2 string or MLLP byte frame into an HL7v2ParsedMessage."""
        text = self._decode_input(raw_hl7_or_mllp)
        lines = [
            ln.strip()
            for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if ln.strip()
        ]
        if not lines:
            raise ValueError("Empty HL7 v2 message payload.")

        if not lines[0].startswith("MSH|"):
            raise ValueError("Invalid HL7 v2 message: payload must begin with an MSH segment.")

        segments: list[HL7v2Segment] = []
        for line in lines:
            parts = line.split("|")
            seg_id = parts[0]
            # In HL7 v2, MSH-1 is the field separator '|' and MSH-2 is '^~\&'
            fields = ("MSH", "|", *parts[1:]) if seg_id == "MSH" else tuple(parts)
            segments.append(HL7v2Segment(segment_id=seg_id, fields=fields))

        msh = segments[0]
        sending_app = msh.field(3)
        sending_fac = msh.field(4)
        ts = self._parse_hl7_datetime(msh.field(7))
        msg_type_comps = msh.components(9)
        msg_type = (
            f"{msg_type_comps[0]}^{msg_type_comps[1]}" if len(msg_type_comps) >= 2 else msh.field(9)
        )
        control_id = msh.field(10) or "MSG-UNKNOWN"

        return HL7v2ParsedMessage(
            message_control_id=control_id,
            message_type=msg_type,
            sending_application=sending_app,
            sending_facility=sending_fac,
            timestamp=ts,
            segments=tuple(segments),
        )

    def translate_to_fhir_bundle(self, raw_hl7_or_mllp: str | bytes) -> FHIRBundle:
        """Translate a legacy HL7 v2.5.1 message (ADT/ORU) into a canonical FHIR R4 Bundle."""
        parsed = self.parse_message(raw_hl7_or_mllp)
        pid_seg = next((s for s in parsed.segments if s.segment_id == "PID"), None)
        if pid_seg is None:
            raise ValueError("HL7 v2 message is missing required PID segment.")

        patient = self._translate_pid_to_patient(pid_seg)
        pv1_seg = next((s for s in parsed.segments if s.segment_id == "PV1"), None)
        encounter = self._translate_pv1_to_encounter(
            pv1_seg=pv1_seg,
            patient_id=patient.id,
            facility_id=parsed.sending_facility,
            default_ts=parsed.timestamp,
            message_type=parsed.message_type,
        )

        entries: list[FHIRBundleEntry] = [patient, encounter]

        for idx, seg in enumerate(parsed.segments, start=1):
            if seg.segment_id == "OBX":
                entries.append(
                    self._translate_obx_to_observation(
                        obx_seg=seg,
                        patient_id=patient.id,
                        encounter_id=encounter.id,
                        default_ts=parsed.timestamp,
                        seq_idx=idx,
                    )
                )
            elif seg.segment_id == "DG1":
                entries.append(
                    self._translate_dg1_to_condition(
                        dg1_seg=seg,
                        patient_id=patient.id,
                        encounter_id=encounter.id,
                        default_ts=parsed.timestamp,
                        seq_idx=idx,
                    )
                )

        return FHIRBundle(
            id=f"bundle-hl7-{parsed.message_control_id}",
            bundle_type="message",
            timestamp=parsed.timestamp,
            entries=tuple(entries),
        )

    @staticmethod
    def _decode_input(raw: str | bytes) -> str:
        if isinstance(raw, bytes):
            if raw.startswith(MLLP_START_BLOCK) and raw.endswith(MLLP_END_BLOCK):
                return raw[len(MLLP_START_BLOCK) : -len(MLLP_END_BLOCK)].decode("utf-8")
            return raw.decode("utf-8")
        return raw

    @staticmethod
    def _parse_hl7_datetime(raw_ts: str) -> datetime:
        cleaned = raw_ts.strip()[:14]
        return datetime.strptime(cleaned.ljust(14, "0"), "%Y%m%d%H%M%S").replace(tzinfo=UTC)

    @staticmethod
    def _translate_pid_to_patient(pid_seg: HL7v2Segment) -> FHIRPatient:
        pid3_reps = pid_seg.repetitions(3)
        identifiers: list[FHIRIdentifier] = []
        primary_mrn = "MRN-UNKNOWN"
        for rep in pid3_reps:
            id_val = rep[0] if rep and rep[0] else "MRN-UNKNOWN"
            id_type = rep[4] if len(rep) >= 5 and rep[4] else "MR"
            if primary_mrn == "MRN-UNKNOWN" and id_type == "MR":
                primary_mrn = id_val
            identifiers.append(
                FHIRIdentifier(
                    system="http://hospital.example.org/mrn",
                    value=id_val,
                    type_code=id_type,
                )
            )
        if not identifiers:
            identifiers.append(
                FHIRIdentifier(
                    system="http://hospital.example.org/mrn",
                    value=primary_mrn,
                    type_code="MR",
                )
            )

        name_comps = pid_seg.components(5)
        family = name_comps[0] if name_comps else "Unknown"
        given = (name_comps[1],) if len(name_comps) >= 2 and name_comps[1] else ("Unknown",)
        prefix = (name_comps[4],) if len(name_comps) >= 5 and name_comps[4] else ()

        dob_digits = "".join(ch for ch in pid_seg.field(7) if ch.isdigit())
        birth_date = (
            date(int(dob_digits[:4]), int(dob_digits[4:6]), int(dob_digits[6:8]))
            if len(dob_digits) >= 8
            else date(1970, 1, 1)
        )

        sex_raw = pid_seg.field(8).upper()
        gender_map: dict[str, Literal["male", "female", "other", "unknown"]] = {
            "M": "male",
            "F": "female",
            "O": "other",
        }
        gender: Literal["male", "female", "other", "unknown"] = gender_map.get(sex_raw, "unknown")

        addr_comps = pid_seg.components(11)
        street = (addr_comps[0],) if addr_comps and addr_comps[0] else ("Unknown Street",)
        city = addr_comps[2] if len(addr_comps) >= 3 else "Boston"
        state = addr_comps[3] if len(addr_comps) >= 4 else "MA"
        postal = addr_comps[4] if len(addr_comps) >= 5 else "02115"

        phone = pid_seg.field(13)
        telecom = (FHIRContactPoint(system="phone", value=phone, use="home"),) if phone else ()
        ssn = pid_seg.field(19) or None

        return FHIRPatient(
            id=f"pat-{primary_mrn.lower()}",
            identifiers=tuple(identifiers),
            names=(FHIRHumanName(family=family, given=given, prefix=prefix),),
            telecom=telecom,
            gender=gender,
            birth_date=birth_date,
            addresses=(
                FHIRAddress(
                    line=street,
                    city=city,
                    state=state,
                    postal_code=postal,
                ),
            ),
            ssn=ssn,
            clinical_note=f"Translated from HL7v2 PID for {given[0]} {family} (MRN {primary_mrn})",
        )

    def _translate_pv1_to_encounter(
        self,
        pv1_seg: HL7v2Segment | None,
        patient_id: str,
        facility_id: str,
        default_ts: datetime,
        message_type: str = "ADT^A01",
    ) -> FHIREncounter:
        if pv1_seg is None:
            return FHIREncounter(
                id=f"enc-{patient_id}",
                subject_id=patient_id,
                period_start=default_ts,
                facility_id=facility_id,
            )

        raw_class = pv1_seg.field(2)
        valid_classes: dict[str, Literal["IMP", "EMER", "AMB", "ICU"]] = {
            "IMP": "IMP",
            "EMER": "EMER",
            "AMB": "AMB",
            "ICU": "ICU",
        }
        class_code: Literal["IMP", "EMER", "AMB", "ICU"] = valid_classes.get(raw_class, "ICU")
        visit_num = pv1_seg.field(19) or f"enc-{patient_id}"
        doc_comps = pv1_seg.components(7)
        attending = (
            f"Dr. {doc_comps[2]} {doc_comps[1]}".strip()
            if len(doc_comps) >= 3 and doc_comps[2]
            else (" ".join(doc_comps[1:3]).strip() if len(doc_comps) >= 2 else None)
        )
        admit_raw = pv1_seg.field(44)
        admit_ts = self._parse_hl7_datetime(admit_raw) if admit_raw else default_ts

        discharge_raw = pv1_seg.field(45)
        discharge_ts = self._parse_hl7_datetime(discharge_raw) if discharge_raw else None
        is_discharged = discharge_ts is not None or message_type.startswith("ADT^A03")
        status: Literal["planned", "in-progress", "finished", "cancelled"] = (
            "finished" if is_discharged else "in-progress"
        )

        return FHIREncounter(
            id=visit_num,
            status=status,
            class_code=class_code,
            subject_id=patient_id,
            period_start=admit_ts,
            period_end=discharge_ts,
            facility_id=facility_id,
            attending_physician=attending,
        )

    def _translate_obx_to_observation(
        self,
        obx_seg: HL7v2Segment,
        patient_id: str,
        encounter_id: str,
        default_ts: datetime,
        seq_idx: int,
    ) -> FHIRObservation:
        val_type = obx_seg.field(2)
        id_comps = obx_seg.components(3)
        code_str = id_comps[0] if id_comps else "8867-4"
        display_str = id_comps[1] if len(id_comps) >= 2 else code_str

        raw_val = obx_seg.field(5)
        unit_comps = obx_seg.components(6)
        unit_str = unit_comps[0] if unit_comps else "{score}"
        interp = obx_seg.field(8) or "N"
        obs_ts_raw = obx_seg.field(14)
        obs_ts = self._parse_hl7_datetime(obs_ts_raw) if obs_ts_raw else default_ts

        concept = FHIRCodeableConcept(
            coding=(
                FHIRCoding(
                    system="http://loinc.org",
                    code=code_str,
                    display=display_str,
                ),
            ),
            text=display_str,
        )

        if val_type == "NM":
            return FHIRObservation(
                id=f"obs-{encounter_id}-{seq_idx:02d}",
                subject_id=patient_id,
                encounter_id=encounter_id,
                effective_datetime=obs_ts,
                code=concept,
                value_quantity=FHIRQuantity(
                    value=float(raw_val),
                    unit=unit_str,
                    code=unit_str,
                ),
                interpretation_code=interp,
            )
        return FHIRObservation(
            id=f"obs-{encounter_id}-{seq_idx:02d}",
            subject_id=patient_id,
            encounter_id=encounter_id,
            effective_datetime=obs_ts,
            code=concept,
            value_string=raw_val,
            interpretation_code=interp,
        )

    def _translate_dg1_to_condition(
        self,
        dg1_seg: HL7v2Segment,
        patient_id: str,
        encounter_id: str,
        default_ts: datetime,
        seq_idx: int,
    ) -> FHIRCondition:
        diag_comps = dg1_seg.components(3)
        code_str = diag_comps[0] if diag_comps else "A41.9"
        display_str = diag_comps[1] if len(diag_comps) >= 2 else (dg1_seg.field(4) or code_str)
        dg1_ts_raw = dg1_seg.field(5)
        onset_ts = self._parse_hl7_datetime(dg1_ts_raw) if dg1_ts_raw else default_ts

        return FHIRCondition(
            id=f"cond-{encounter_id}-{seq_idx:02d}",
            subject_id=patient_id,
            encounter_id=encounter_id,
            onset_datetime=onset_ts,
            code=FHIRCodeableConcept(
                coding=(
                    FHIRCoding(
                        system="http://hl7.org/fhir/sid/icd-10-cm",
                        code=code_str,
                        display=display_str,
                    ),
                ),
                text=display_str,
            ),
        )
