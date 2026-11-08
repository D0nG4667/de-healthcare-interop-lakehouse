"""Hierarchical HL7 FHIR R4 JSON and XML Bundle parser and clinical entity extractor."""

from __future__ import annotations

import json
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


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _child_attr(parent: ET.Element, child_name: str, attr: str = "value") -> str:
    for child in parent:
        if _local_tag(child.tag) == child_name:
            return child.attrib.get(attr, "")
    return ""


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
        start_ts = datetime.fromisoformat(_child_attr(enc_el, "periodStart"))
        facility = _child_attr(enc_el, "facilityId") or "FAC-BOS-GEN-01"
        return FHIREncounter(
            id=enc_id,
            subject_id=subj_ref,
            period_start=start_ts,
            facility_id=facility,
        )

    @staticmethod
    def _parse_xml_observation(obs_el: ET.Element) -> FHIRObservation:
        obs_id = _child_attr(obs_el, "id")
        subj_ref = _child_attr(obs_el, "subject", "reference").split("/")[-1]
        enc_ref = _child_attr(obs_el, "encounter", "reference").split("/")[-1]
        eff_ts = datetime.fromisoformat(_child_attr(obs_el, "effectiveDateTime"))

        coding_el: ET.Element | None = None
        vq_el: ET.Element | None = None
        vs_val: str | None = None
        note_text: str | None = None

        for el in obs_el:
            tag = _local_tag(el.tag)
            if tag == "code":
                for sub in el:
                    if _local_tag(sub.tag) == "coding":
                        coding_el = sub
            elif tag == "valueQuantity":
                vq_el = el
            elif tag == "valueString":
                vs_val = el.attrib.get("value", "")
            elif tag == "note":
                note_text = el.attrib.get("text")

        sys_str = (
            coding_el.attrib.get("system", "http://loinc.org")
            if coding_el is not None
            else "http://loinc.org"
        )
        code_str = coding_el.attrib.get("code", "8867-4") if coding_el is not None else "8867-4"
        disp_str = coding_el.attrib.get("display", code_str) if coding_el is not None else code_str

        return FHIRObservation(
            id=obs_id,
            subject_id=subj_ref,
            encounter_id=enc_ref,
            effective_datetime=eff_ts,
            code=FHIRCodeableConcept(
                coding=(FHIRCoding(system=sys_str, code=code_str, display=disp_str),),
                text=disp_str,
            ),
            value_quantity=(
                FHIRQuantity(
                    value=float(vq_el.attrib["value"]),
                    unit=vq_el.attrib["unit"],
                    code=vq_el.attrib.get("code", vq_el.attrib["unit"]),
                )
                if vq_el is not None
                else None
            ),
            value_string=vs_val,
            note=note_text,
        )

    @staticmethod
    def _parse_xml_condition(cond_el: ET.Element) -> FHIRCondition:
        cond_id = _child_attr(cond_el, "id")
        subj_ref = _child_attr(cond_el, "subject", "reference").split("/")[-1]
        enc_ref = _child_attr(cond_el, "encounter", "reference").split("/")[-1]
        onset_ts = datetime.fromisoformat(_child_attr(cond_el, "onsetDateTime"))
        sys_str = _child_attr(cond_el, "coding", "system")
        code_str = _child_attr(cond_el, "coding", "code")
        disp_str = _child_attr(cond_el, "coding", "display")
        return FHIRCondition(
            id=cond_id,
            subject_id=subj_ref,
            encounter_id=enc_ref,
            onset_datetime=onset_ts,
            code=FHIRCodeableConcept(
                coding=(FHIRCoding(system=sys_str, code=code_str, display=disp_str),),
                text=disp_str,
            ),
        )

    @staticmethod
    def _parse_xml_medication(med_el: ET.Element) -> FHIRMedicationRequest:
        med_id = _child_attr(med_el, "id")
        subj_ref = _child_attr(med_el, "subject", "reference").split("/")[-1]
        enc_ref = _child_attr(med_el, "encounter", "reference").split("/")[-1]
        auth_ts = datetime.fromisoformat(_child_attr(med_el, "authoredOn"))
        sys_str = _child_attr(med_el, "coding", "system")
        code_str = _child_attr(med_el, "coding", "code")
        disp_str = _child_attr(med_el, "coding", "display")
        dosage = _child_attr(med_el, "dosageText")
        return FHIRMedicationRequest(
            id=med_id,
            subject_id=subj_ref,
            encounter_id=enc_ref,
            authored_on=auth_ts,
            medication_code=FHIRCodeableConcept(
                coding=(FHIRCoding(system=sys_str, code=code_str, display=disp_str),),
                text=disp_str,
            ),
            dosage_text=dosage,
        )
