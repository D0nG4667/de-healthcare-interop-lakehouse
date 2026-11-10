"""Hierarchical HL7 FHIR R4 JSON and XML Bundle parser and clinical entity extractor."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any, Literal

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
    FHIRMedicationRequest,
    FHIRObservation,
    FHIRPatient,
    FHIRQuantity,
)

_UNSAFE_XML_PATTERN: re.Pattern[str] = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _find_child(parent: ET.Element, child_name: str) -> ET.Element | None:
    for child in parent:
        if _local_tag(child.tag) == child_name:
            return child
    return None


def _child_attr(parent: ET.Element, child_name: str, attr: str = "value") -> str:
    child = _find_child(parent, child_name)
    return child.attrib.get(attr, "") if child is not None else ""


def _parse_coding_element(
    coding_el: ET.Element | None,
    default_system: str,
    default_code: str,
) -> FHIRCoding:
    if coding_el is None:
        return FHIRCoding(system=default_system, code=default_code, display=default_code)
    sys_str = coding_el.attrib.get("system") or _child_attr(coding_el, "system") or default_system
    code_str = coding_el.attrib.get("code") or _child_attr(coding_el, "code") or default_code
    disp_str = coding_el.attrib.get("display") or _child_attr(coding_el, "display") or code_str
    return FHIRCoding(system=sys_str, code=code_str, display=disp_str)


class FHIRParser:
    """Parses hierarchical HL7 FHIR R4 JSON and XML bundles into typed domain objects."""

    def parse_json_bundle(self, raw_json: str | bytes | dict[str, Any]) -> FHIRBundle:
        """Parse a FHIR R4 Bundle from a JSON string, UTF-8 bytes, or dictionary."""
        if isinstance(raw_json, bytes):
            payload: dict[str, Any] = json.loads(raw_json.decode("utf-8"))
        elif isinstance(raw_json, str):
            payload = json.loads(raw_json)
        else:
            payload = raw_json
        return FHIRBundle.from_fhir_json_dict(payload)

    def parse_xml_bundle(self, raw_xml: str | bytes) -> FHIRBundle:
        """Parse a hierarchical HL7 FHIR R4 XML Bundle into a canonical FHIRBundle."""
        xml_text = raw_xml.decode("utf-8") if isinstance(raw_xml, bytes) else raw_xml
        if _UNSAFE_XML_PATTERN.search(xml_text):
            raise ValueError("Unsafe XML declaration (DOCTYPE/ENTITY) rejected.")
        root = ET.fromstring(xml_text)
        if _local_tag(root.tag) != "Bundle":
            raise ValueError(f"Expected XML root <Bundle>, got <{_local_tag(root.tag)}>.")

        bundle_id = _child_attr(root, "id") or "bundle-xml"
        bundle_type_raw = _child_attr(root, "type") or "collection"
        valid_types: dict[str, Literal["transaction", "collection", "message"]] = {
            "transaction": "transaction",
            "collection": "collection",
            "message": "message",
        }
        bundle_type: Literal["transaction", "collection", "message"] = valid_types.get(
            bundle_type_raw, "collection"
        )
        timestamp = datetime.fromisoformat(_child_attr(root, "timestamp"))

        entries: list[FHIRBundleEntry] = []
        for child in root:
            if _local_tag(child.tag) != "entry":
                continue
            for res_container in child:
                if _local_tag(res_container.tag) != "resource":
                    continue
                for res_el in res_container:
                    rname = _local_tag(res_el.tag)
                    if rname == "Patient":
                        entries.append(self._parse_xml_patient(res_el))
                    elif rname == "Encounter":
                        entries.append(self._parse_xml_encounter(res_el))
                    elif rname == "Observation":
                        entries.append(self._parse_xml_observation(res_el))
                    elif rname == "Condition":
                        entries.append(self._parse_xml_condition(res_el))
                    elif rname == "MedicationRequest":
                        entries.append(self._parse_xml_medication(res_el))

        return FHIRBundle(
            id=bundle_id,
            bundle_type=bundle_type,
            timestamp=timestamp,
            entries=tuple(entries),
        )

    @staticmethod
    def extract_clinical_summary(bundle: FHIRBundle) -> dict[str, int]:
        """Compute entity counts across resource categories within a FHIRBundle."""
        return {
            "patients": len(bundle.patients()),
            "encounters": len(bundle.encounters()),
            "observations": len(bundle.observations()),
            "conditions": len(bundle.conditions()),
            "medication_requests": len(bundle.medication_requests()),
        }

    @staticmethod
    def _parse_xml_patient(pat_el: ET.Element) -> FHIRPatient:
        pat_id = _child_attr(pat_el, "id")
        gender_raw = _child_attr(pat_el, "gender")
        gender_map: dict[str, Literal["male", "female", "other", "unknown"]] = {
            "male": "male",
            "female": "female",
            "other": "other",
        }
        gender: Literal["male", "female", "other", "unknown"] = gender_map.get(
            gender_raw, "unknown"
        )
        birth_date = date.fromisoformat(_child_attr(pat_el, "birthDate"))

        identifiers: list[FHIRIdentifier] = []
        names: list[FHIRHumanName] = []
        telecoms: list[FHIRContactPoint] = []
        addresses: list[FHIRAddress] = []
        ssn: str | None = None
        device_ip: str | None = None
        clinical_note: str | None = None

        for el in pat_el:
            tag = _local_tag(el.tag)
            if tag == "identifier":
                identifiers.append(
                    FHIRIdentifier(
                        system=_child_attr(el, "system"),
                        value=_child_attr(el, "value"),
                    )
                )
            elif tag == "name":
                givens = tuple(
                    sub.attrib.get("value", "") for sub in el if _local_tag(sub.tag) == "given"
                )
                names.append(FHIRHumanName(family=_child_attr(el, "family"), given=givens))
            elif tag == "telecom":
                sys_raw = _child_attr(el, "system")
                sys_map: dict[str, Literal["phone", "email", "fax", "url"]] = {
                    "phone": "phone",
                    "email": "email",
                    "fax": "fax",
                    "url": "url",
                }
                telecoms.append(
                    FHIRContactPoint(
                        system=sys_map.get(sys_raw, "phone"),
                        value=_child_attr(el, "value"),
                    )
                )
            elif tag == "address":
                lines = tuple(
                    sub.attrib.get("value", "") for sub in el if _local_tag(sub.tag) == "line"
                )
                addresses.append(
                    FHIRAddress(
                        line=lines,
                        city=_child_attr(el, "city"),
                        state=_child_attr(el, "state"),
                        postal_code=_child_attr(el, "postalCode"),
                    )
                )
            elif tag == "extension":
                url = el.attrib.get("url", "")
                val = _child_attr(el, "valueString")
                if url.endswith("patient-ssn"):
                    ssn = val
                elif url.endswith("device-ip"):
                    device_ip = val
                elif url.endswith("clinical-note"):
                    clinical_note = val

        return FHIRPatient(
            id=pat_id,
            identifiers=tuple(identifiers),
            names=tuple(names),
            telecom=tuple(telecoms),
            gender=gender,
            birth_date=birth_date,
            addresses=tuple(addresses),
            ssn=ssn,
            device_ip=device_ip,
            clinical_note=clinical_note,
        )

    @staticmethod
    def _parse_xml_encounter(enc_el: ET.Element) -> FHIREncounter:
        enc_id = _child_attr(enc_el, "id")
        subj_ref = _child_attr(enc_el, "subject", "reference").split("/")[-1]

        status_raw = _child_attr(enc_el, "status")
        valid_statuses: dict[str, Literal["planned", "in-progress", "finished", "cancelled"]] = {
            "planned": "planned",
            "in-progress": "in-progress",
            "finished": "finished",
            "cancelled": "cancelled",
        }
        status: Literal["planned", "in-progress", "finished", "cancelled"] = valid_statuses.get(
            status_raw, "finished"
        )

        class_raw = _child_attr(enc_el, "class", "code")
        valid_classes: dict[str, Literal["IMP", "EMER", "AMB", "ICU"]] = {
            "IMP": "IMP",
            "EMER": "EMER",
            "AMB": "AMB",
            "ICU": "ICU",
        }
        class_code: Literal["IMP", "EMER", "AMB", "ICU"] = valid_classes.get(class_raw, "ICU")

        period_el = _find_child(enc_el, "period")
        start_raw = (
            _child_attr(period_el, "start")
            if period_el is not None
            else _child_attr(enc_el, "periodStart")
        )
        end_raw = _child_attr(period_el, "end") if period_el is not None else ""
        start_ts = datetime.fromisoformat(start_raw)
        end_ts = datetime.fromisoformat(end_raw) if end_raw else None

        sp_ref = _child_attr(enc_el, "serviceProvider", "reference")
        facility = (
            sp_ref.split("/")[-1]
            if sp_ref
            else (_child_attr(enc_el, "facilityId") or "FAC-BOS-GEN-01")
        )

        part_el = _find_child(enc_el, "participant")
        attending = (
            (_child_attr(part_el, "individual", "display") or None) if part_el is not None else None
        )

        return FHIREncounter(
            id=enc_id,
            status=status,
            class_code=class_code,
            subject_id=subj_ref,
            period_start=start_ts,
            period_end=end_ts,
            facility_id=facility,
            attending_physician=attending,
        )

    @staticmethod
    def _parse_xml_observation(obs_el: ET.Element) -> FHIRObservation:
        obs_id = _child_attr(obs_el, "id")
        subj_ref = _child_attr(obs_el, "subject", "reference").split("/")[-1]
        enc_ref = _child_attr(obs_el, "encounter", "reference").split("/")[-1]
        eff_ts = datetime.fromisoformat(_child_attr(obs_el, "effectiveDateTime"))

        code_container = _find_child(obs_el, "code")
        coding_el = _find_child(code_container, "coding") if code_container is not None else None
        coding = _parse_coding_element(coding_el, "http://loinc.org", "8867-4")

        vq_el = _find_child(obs_el, "valueQuantity")
        value_quantity: FHIRQuantity | None = None
        if vq_el is not None:
            num_raw = vq_el.attrib.get("value") or _child_attr(vq_el, "value")
            unit_raw = vq_el.attrib.get("unit") or _child_attr(vq_el, "unit")
            code_raw = vq_el.attrib.get("code") or _child_attr(vq_el, "code") or unit_raw
            value_quantity = FHIRQuantity(value=float(num_raw), unit=unit_raw, code=code_raw)

        vs_el = _find_child(obs_el, "valueString")
        vs_val = vs_el.attrib.get("value", "") if vs_el is not None else None

        note_el = _find_child(obs_el, "note")
        note_text = (
            (note_el.attrib.get("text") or _child_attr(note_el, "text") or None)
            if note_el is not None
            else None
        )

        return FHIRObservation(
            id=obs_id,
            subject_id=subj_ref,
            encounter_id=enc_ref,
            effective_datetime=eff_ts,
            code=FHIRCodeableConcept(coding=(coding,), text=coding.display),
            value_quantity=value_quantity,
            value_string=vs_val,
            note=note_text,
        )

    @staticmethod
    def _parse_xml_condition(cond_el: ET.Element) -> FHIRCondition:
        cond_id = _child_attr(cond_el, "id")
        subj_ref = _child_attr(cond_el, "subject", "reference").split("/")[-1]
        enc_ref = _child_attr(cond_el, "encounter", "reference").split("/")[-1]
        onset_ts = datetime.fromisoformat(_child_attr(cond_el, "onsetDateTime"))

        code_container = _find_child(cond_el, "code")
        coding_el = (
            _find_child(code_container, "coding")
            if code_container is not None
            else _find_child(cond_el, "coding")
        )
        coding = _parse_coding_element(coding_el, "http://hl7.org/fhir/sid/icd-10-cm", "A41.9")

        return FHIRCondition(
            id=cond_id,
            subject_id=subj_ref,
            encounter_id=enc_ref,
            onset_datetime=onset_ts,
            code=FHIRCodeableConcept(coding=(coding,), text=coding.display),
        )

    @staticmethod
    def _parse_xml_medication(med_el: ET.Element) -> FHIRMedicationRequest:
        med_id = _child_attr(med_el, "id")
        subj_ref = _child_attr(med_el, "subject", "reference").split("/")[-1]
        enc_ref = _child_attr(med_el, "encounter", "reference").split("/")[-1]
        auth_ts = datetime.fromisoformat(_child_attr(med_el, "authoredOn"))

        med_cc = _find_child(med_el, "medicationCodeableConcept")
        coding_el = (
            _find_child(med_cc, "coding") if med_cc is not None else _find_child(med_el, "coding")
        )
        coding = _parse_coding_element(
            coding_el, "http://www.nlm.nih.gov/research/umls/rxnorm", "11124"
        )

        dosage_el = _find_child(med_el, "dosageInstruction")
        dosage = (
            _child_attr(dosage_el, "text")
            if dosage_el is not None
            else _child_attr(med_el, "dosageText")
        )

        return FHIRMedicationRequest(
            id=med_id,
            subject_id=subj_ref,
            encounter_id=enc_ref,
            authored_on=auth_ts,
            medication_code=FHIRCodeableConcept(coding=(coding,), text=coding.display),
            dosage_text=dosage,
        )
