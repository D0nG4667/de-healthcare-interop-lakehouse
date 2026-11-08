"""Strict Pydantic v2 models for HL7 FHIR R4 (v4.0.1) clinical interoperability resources."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, model_validator


class FHIRCoding(BaseModel):
    """Standardized ontology code (LOINC, SNOMED-CT, RxNorm, ICD-10-CM)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str
    code: str
    display: str


class FHIRCodeableConcept(BaseModel):
    """Concept represented by one or more ontology codings and human-readable text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coding: tuple[FHIRCoding, ...]
    text: str


class FHIRIdentifier(BaseModel):
    """Clinical or administrative identifier (e.g., MRN, SSN, NPI, Encounter number)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: str
    value: str
    type_code: str = "MR"


class FHIRHumanName(BaseModel):
    """Structured human name component in FHIR R4."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    use: str = "official"
    family: str
    given: tuple[str, ...]
    prefix: tuple[str, ...] = ()


class FHIRAddress(BaseModel):
    """Structured patient postal address."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    line: tuple[str, ...]
    city: str
    state: str
    postal_code: str
    country: str = "US"


class FHIRContactPoint(BaseModel):
    """Telecommunications contact endpoint (phone, email, fax, url)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    system: Literal["phone", "email", "fax", "url"]
    value: str
    use: str = "home"


class FHIRQuantity(BaseModel):
    """Measured numerical value with UCUM unit metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    unit: str
    system: str = "http://unitsofmeasure.org"
    code: str


class FHIRPatient(BaseModel):
    """HL7 FHIR R4 Patient demographic resource."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_type: Literal["Patient"] = "Patient"
    id: str
    identifiers: tuple[FHIRIdentifier, ...]
    names: tuple[FHIRHumanName, ...]
    telecom: tuple[FHIRContactPoint, ...] = ()
    gender: Literal["male", "female", "other", "unknown"]
    birth_date: date
    addresses: tuple[FHIRAddress, ...] = ()
    ssn: str | None = None
    device_ip: str | None = None
    clinical_note: str | None = None
    age_years: int | None = None


class FHIREncounter(BaseModel):
    """HL7 FHIR R4 Encounter resource representing an inpatient, ED, or ICU visit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_type: Literal["Encounter"] = "Encounter"
    id: str
    status: Literal["planned", "in-progress", "finished", "cancelled"] = "in-progress"
    class_code: Literal["IMP", "EMER", "AMB", "ICU"] = "ICU"
    subject_id: str
    period_start: datetime
    period_end: datetime | None = None
    reason_code: FHIRCodeableConcept | None = None
    facility_id: str = "FAC-BOS-GEN-01"
    attending_physician: str | None = None


class FHIRObservation(BaseModel):
    """HL7 FHIR R4 Observation resource for vital signs and laboratory telemetry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_type: Literal["Observation"] = "Observation"
    id: str
    status: Literal["preliminary", "final", "amended"] = "final"
    category_code: str = "vital-signs"
    code: FHIRCodeableConcept
    subject_id: str
    encounter_id: str
    effective_datetime: datetime
    value_quantity: FHIRQuantity | None = None
    value_string: str | None = None
    interpretation_code: str = "N"
    note: str | None = None

    @model_validator(mode="after")
    def _validate_measurement_present(self) -> FHIRObservation:
        if self.value_quantity is None and self.value_string is None:
            raise ValueError(
                "FHIRObservation requires at least one of value_quantity or value_string."
            )
        return self


class FHIRCondition(BaseModel):
    """HL7 FHIR R4 Condition resource representing a clinical diagnosis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_type: Literal["Condition"] = "Condition"
    id: str
    clinical_status: Literal["active", "resolved", "remission"] = "active"
    verification_status: Literal["confirmed", "provisional"] = "confirmed"
    code: FHIRCodeableConcept
    subject_id: str
    encounter_id: str
    onset_datetime: datetime


class FHIRMedicationRequest(BaseModel):
    """HL7 FHIR R4 MedicationRequest resource representing an inpatient/outpatient order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_type: Literal["MedicationRequest"] = "MedicationRequest"
    id: str
    status: Literal["active", "completed", "stopped"] = "active"
    intent: Literal["order", "plan", "instance-order"] = "order"
    medication_code: FHIRCodeableConcept
    subject_id: str
    encounter_id: str
    authored_on: datetime
    dosage_text: str


FHIRBundleEntry: TypeAlias = (
    FHIRPatient | FHIREncounter | FHIRObservation | FHIRCondition | FHIRMedicationRequest
)


class FHIRBundle(BaseModel):
    """HL7 FHIR R4 Bundle container holding linked longitudinal clinical resources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resource_type: Literal["Bundle"] = "Bundle"
    id: str
    bundle_type: Literal["transaction", "collection", "message"] = "collection"
    timestamp: datetime
    entries: tuple[FHIRBundleEntry, ...]

    def patients(self) -> tuple[FHIRPatient, ...]:
        """Return all FHIRPatient resources inside the bundle."""
        return tuple(e for e in self.entries if isinstance(e, FHIRPatient))

    def encounters(self) -> tuple[FHIREncounter, ...]:
        """Return all FHIREncounter resources inside the bundle."""
        return tuple(e for e in self.entries if isinstance(e, FHIREncounter))

    def observations(self) -> tuple[FHIRObservation, ...]:
        """Return all FHIRObservation resources inside the bundle."""
        return tuple(e for e in self.entries if isinstance(e, FHIRObservation))

    def conditions(self) -> tuple[FHIRCondition, ...]:
        """Return all FHIRCondition resources inside the bundle."""
        return tuple(e for e in self.entries if isinstance(e, FHIRCondition))

    def medication_requests(self) -> tuple[FHIRMedicationRequest, ...]:
        """Return all FHIRMedicationRequest resources inside the bundle."""
        return tuple(e for e in self.entries if isinstance(e, FHIRMedicationRequest))

    def to_fhir_json_dict(self) -> dict[str, Any]:
        """Serialize bundle into standards-compliant HL7 FHIR R4 JSON dictionary format."""
        serialized_entries: list[dict[str, Any]] = []
        for entry in self.entries:
            if isinstance(entry, FHIRPatient):
                resource_dict: dict[str, Any] = {
                    "resourceType": "Patient",
                    "id": entry.id,
                    "identifier": [
                        {
                            "system": ident.system,
                            "value": ident.value,
                            "type": {"coding": [{"code": ident.type_code}]},
                        }
                        for ident in entry.identifiers
                    ],
                    "name": [
                        {
                            "use": n.use,
                            "family": n.family,
                            "given": list(n.given),
                            "prefix": list(n.prefix),
                        }
                        for n in entry.names
                    ],
                    "telecom": [
                        {"system": t.system, "value": t.value, "use": t.use} for t in entry.telecom
                    ],
                    "gender": entry.gender,
                    "birthDate": entry.birth_date.isoformat(),
                    "address": [
                        {
                            "line": list(a.line),
                            "city": a.city,
                            "state": a.state,
                            "postalCode": a.postal_code,
                            "country": a.country,
                        }
                        for a in entry.addresses
                    ],
                    "extension": [
                        *(
                            [
                                {
                                    "url": "http://hl7.org/fhir/StructureDefinition/patient-ssn",
                                    "valueString": entry.ssn,
                                }
                            ]
                            if entry.ssn
                            else []
                        ),
                        *(
                            [
                                {
                                    "url": "http://hospital.example.org/fhir/ext/device-ip",
                                    "valueString": entry.device_ip,
                                }
                            ]
                            if entry.device_ip
                            else []
                        ),
                        *(
                            [
                                {
                                    "url": "http://hospital.example.org/fhir/ext/clinical-note",
                                    "valueString": entry.clinical_note,
                                }
                            ]
                            if entry.clinical_note
                            else []
                        ),
                    ],
                }
            elif isinstance(entry, FHIREncounter):
                resource_dict = {
                    "resourceType": "Encounter",
                    "id": entry.id,
                    "status": entry.status,
                    "class": {"code": entry.class_code},
                    "subject": {"reference": f"Patient/{entry.subject_id}"},
                    "period": {
                        "start": entry.period_start.isoformat(),
                        **(
                            {"end": entry.period_end.isoformat()}
                            if entry.period_end is not None
                            else {}
                        ),
                    },
                    "serviceProvider": {"identifier": {"value": entry.facility_id}},
                    **(
                        {"participant": [{"individual": {"display": entry.attending_physician}}]}
                        if entry.attending_physician
                        else {}
                    ),
                    **(
                        {
                            "reasonCode": [
                                {
                                    "coding": [
                                        {
                                            "system": c.system,
                                            "code": c.code,
                                            "display": c.display,
                                        }
                                        for c in entry.reason_code.coding
                                    ],
                                    "text": entry.reason_code.text,
                                }
                            ]
                        }
                        if entry.reason_code is not None
                        else {}
                    ),
                }
            elif isinstance(entry, FHIRObservation):
                resource_dict = {
                    "resourceType": "Observation",
                    "id": entry.id,
                    "status": entry.status,
                    "category": [{"coding": [{"code": entry.category_code}]}],
                    "code": {
                        "coding": [
                            {"system": c.system, "code": c.code, "display": c.display}
                            for c in entry.code.coding
                        ],
                        "text": entry.code.text,
                    },
                    "subject": {"reference": f"Patient/{entry.subject_id}"},
                    "encounter": {"reference": f"Encounter/{entry.encounter_id}"},
                    "effectiveDateTime": entry.effective_datetime.isoformat(),
                    "interpretation": [{"coding": [{"code": entry.interpretation_code}]}],
                    **(
                        {
                            "valueQuantity": {
                                "value": entry.value_quantity.value,
                                "unit": entry.value_quantity.unit,
                                "system": entry.value_quantity.system,
                                "code": entry.value_quantity.code,
                            }
                        }
                        if entry.value_quantity is not None
                        else {"valueString": entry.value_string}
                    ),
                    **({"note": [{"text": entry.note}]} if entry.note else {}),
                }
            elif isinstance(entry, FHIRCondition):
                resource_dict = {
                    "resourceType": "Condition",
                    "id": entry.id,
                    "clinicalStatus": {"coding": [{"code": entry.clinical_status}]},
                    "verificationStatus": {"coding": [{"code": entry.verification_status}]},
                    "code": {
                        "coding": [
                            {"system": c.system, "code": c.code, "display": c.display}
                            for c in entry.code.coding
                        ],
                        "text": entry.code.text,
                    },
                    "subject": {"reference": f"Patient/{entry.subject_id}"},
                    "encounter": {"reference": f"Encounter/{entry.encounter_id}"},
                    "onsetDateTime": entry.onset_datetime.isoformat(),
                }
            else:
                resource_dict = {
                    "resourceType": "MedicationRequest",
                    "id": entry.id,
                    "status": entry.status,
                    "intent": entry.intent,
                    "medicationCodeableConcept": {
                        "coding": [
                            {"system": c.system, "code": c.code, "display": c.display}
                            for c in entry.medication_code.coding
                        ],
                        "text": entry.medication_code.text,
                    },
                    "subject": {"reference": f"Patient/{entry.subject_id}"},
                    "encounter": {"reference": f"Encounter/{entry.encounter_id}"},
                    "authoredOn": entry.authored_on.isoformat(),
                    "dosageInstruction": [{"text": entry.dosage_text}],
                }

            serialized_entries.append(
                {
                    "fullUrl": f"urn:uuid:{entry.id}",
                    "resource": resource_dict,
                }
            )

        return {
            "resourceType": "Bundle",
            "id": self.id,
            "type": self.bundle_type,
            "timestamp": self.timestamp.isoformat(),
            "entry": serialized_entries,
        }

    @classmethod
    def from_fhir_json_dict(cls, payload: dict[str, Any]) -> FHIRBundle:
        """Deserialize a standard HL7 FHIR R4 Bundle JSON dictionary into typed models."""
        if payload.get("resourceType") != "Bundle":
            raise ValueError(
                f"Expected FHIR Bundle resourceType, got: {payload.get('resourceType')!r}"
            )

        parsed_entries: list[FHIRBundleEntry] = []
        for item in payload.get("entry", []):
            res: dict[str, Any] = item.get("resource", item)
            rtype = res.get("resourceType")
            if rtype == "Patient":
                parsed_entries.append(_parse_patient_dict(res))
            elif rtype == "Encounter":
                parsed_entries.append(_parse_encounter_dict(res))
            elif rtype == "Observation":
                parsed_entries.append(_parse_observation_dict(res))
            elif rtype == "Condition":
                parsed_entries.append(_parse_condition_dict(res))
            elif rtype == "MedicationRequest":
                parsed_entries.append(_parse_medication_dict(res))
            else:
                raise ValueError(f"Unsupported FHIR resourceType in bundle: {rtype!r}")

        return cls(
            id=str(payload["id"]),
            bundle_type=payload.get("type", "collection"),
            timestamp=datetime.fromisoformat(str(payload["timestamp"])),
            entries=tuple(parsed_entries),
        )


def _strip_ref_prefix(ref: str) -> str:
    return ref.split("/")[-1]


def _parse_codeable_concept(raw: dict[str, Any]) -> FHIRCodeableConcept:
    codings = tuple(
        FHIRCoding(
            system=str(c.get("system", "http://loinc.org")),
            code=str(c["code"]),
            display=str(c.get("display", c["code"])),
        )
        for c in raw.get("coding", [])
    )
    text = str(raw.get("text") or (codings[0].display if codings else ""))
    return FHIRCodeableConcept(coding=codings, text=text)


def _parse_patient_dict(res: dict[str, Any]) -> FHIRPatient:
    ssn: str | None = None
    device_ip: str | None = None
    clinical_note: str | None = None
    for ext in res.get("extension", []):
        url = str(ext.get("url", ""))
        val = str(ext.get("valueString", ""))
        if url.endswith("patient-ssn"):
            ssn = val
        elif url.endswith("device-ip"):
            device_ip = val
        elif url.endswith("clinical-note"):
            clinical_note = val

    return FHIRPatient(
        id=str(res["id"]),
        identifiers=tuple(
            FHIRIdentifier(
                system=str(i.get("system", "http://hospital.example.org/mrn")),
                value=str(i["value"]),
                type_code=str(
                    i.get("type", {}).get("coding", [{"code": "MR"}])[0].get("code", "MR")
                ),
            )
            for i in res.get("identifier", [])
        ),
        names=tuple(
            FHIRHumanName(
                use=str(n.get("use", "official")),
                family=str(n["family"]),
                given=tuple(str(g) for g in n.get("given", [])),
                prefix=tuple(str(p) for p in n.get("prefix", [])),
            )
            for n in res.get("name", [])
        ),
        telecom=tuple(
            FHIRContactPoint(
                system=t["system"],
                value=str(t["value"]),
                use=str(t.get("use", "home")),
            )
            for t in res.get("telecom", [])
        ),
        gender=res.get("gender", "unknown"),
        birth_date=date.fromisoformat(str(res["birthDate"])),
        addresses=tuple(
            FHIRAddress(
                line=tuple(str(ln) for ln in a.get("line", [])),
                city=str(a["city"]),
                state=str(a["state"]),
                postal_code=str(a["postalCode"]),
                country=str(a.get("country", "US")),
            )
            for a in res.get("address", [])
        ),
        ssn=ssn,
        device_ip=device_ip,
        clinical_note=clinical_note,
    )


def _parse_encounter_dict(res: dict[str, Any]) -> FHIREncounter:
    period = res.get("period", {})
    reason_list = res.get("reasonCode", [])
    participants = res.get("participant", [])
    attending = (
        str(participants[0]["individual"]["display"])
        if participants and "individual" in participants[0]
        else None
    )
    return FHIREncounter(
        id=str(res["id"]),
        status=res.get("status", "in-progress"),
        class_code=res.get("class", {}).get("code", "ICU"),
        subject_id=_strip_ref_prefix(str(res["subject"]["reference"])),
        period_start=datetime.fromisoformat(str(period["start"])),
        period_end=(datetime.fromisoformat(str(period["end"])) if "end" in period else None),
        reason_code=_parse_codeable_concept(reason_list[0]) if reason_list else None,
        facility_id=str(
            res.get("serviceProvider", {}).get("identifier", {}).get("value", "FAC-BOS-GEN-01")
        ),
        attending_physician=attending,
    )


def _parse_observation_dict(res: dict[str, Any]) -> FHIRObservation:
    vq = res.get("valueQuantity")
    notes = res.get("note", [])
    interp = res.get("interpretation", [{"coding": [{"code": "N"}]}])
    cat = res.get("category", [{"coding": [{"code": "vital-signs"}]}])
    return FHIRObservation(
        id=str(res["id"]),
        status=res.get("status", "final"),
        category_code=str(cat[0]["coding"][0]["code"]),
        code=_parse_codeable_concept(res["code"]),
        subject_id=_strip_ref_prefix(str(res["subject"]["reference"])),
        encounter_id=_strip_ref_prefix(str(res["encounter"]["reference"])),
        effective_datetime=datetime.fromisoformat(str(res["effectiveDateTime"])),
        value_quantity=(
            FHIRQuantity(
                value=float(vq["value"]),
                unit=str(vq["unit"]),
                system=str(vq.get("system", "http://unitsofmeasure.org")),
                code=str(vq.get("code", vq["unit"])),
            )
            if vq is not None
            else None
        ),
        value_string=str(res["valueString"]) if "valueString" in res else None,
        interpretation_code=str(interp[0]["coding"][0]["code"]),
        note=str(notes[0]["text"]) if notes else None,
    )


def _parse_condition_dict(res: dict[str, Any]) -> FHIRCondition:
    return FHIRCondition(
        id=str(res["id"]),
        clinical_status=res.get("clinicalStatus", {}).get("coding", [{"code": "active"}])[0][
            "code"
        ],
        verification_status=res.get("verificationStatus", {}).get(
            "coding", [{"code": "confirmed"}]
        )[0]["code"],
        code=_parse_codeable_concept(res["code"]),
        subject_id=_strip_ref_prefix(str(res["subject"]["reference"])),
        encounter_id=_strip_ref_prefix(str(res["encounter"]["reference"])),
        onset_datetime=datetime.fromisoformat(str(res["onsetDateTime"])),
    )


def _parse_medication_dict(res: dict[str, Any]) -> FHIRMedicationRequest:
    dosage_list = res.get("dosageInstruction", [{"text": "As directed"}])
    return FHIRMedicationRequest(
        id=str(res["id"]),
        status=res.get("status", "active"),
        intent=res.get("intent", "order"),
        medication_code=_parse_codeable_concept(res["medicationCodeableConcept"]),
        subject_id=_strip_ref_prefix(str(res["subject"]["reference"])),
        encounter_id=_strip_ref_prefix(str(res["encounter"]["reference"])),
        authored_on=datetime.fromisoformat(str(res["authoredOn"])),
        dosage_text=str(dosage_list[0]["text"]),
    )
