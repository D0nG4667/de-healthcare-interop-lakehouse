"""Synthea state-machine clinical lifecycle orchestrator and FHIR R4 Bundle generator."""

from __future__ import annotations

import json
import random
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

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
    FHIRMedicationRequest,
    FHIRObservation,
    FHIRPatient,
    FHIRQuantity,
)

MODULES_DIR: Path = Path(__file__).resolve().parent / "modules"

_FIRST_NAMES_FEMALE: tuple[str, ...] = (
    "Elena",
    "Miriam",
    "Fatima",
    "Hannah",
    "Amina",
    "Clara",
)
_FIRST_NAMES_MALE: tuple[str, ...] = (
    "Marcus",
    "Samuel",
    "David",
    "Kwame",
    "Mateo",
    "Arthur",
)
_LAST_NAMES: tuple[str, ...] = (
    "Rodriguez",
    "Okafor",
    "Chen",
    "Kowalski",
    "Thornton",
    "Al-Mansoor",
)
_CITIES_AND_ZIPS: tuple[tuple[str, str, str], ...] = (
    ("Boston", "MA", "02115-5001"),
    ("Cambridge", "MA", "02139-4307"),
    # Restricted small-population HIPAA ZIP-3 prefixes (<= 20,000 residents)
    ("Charlestown", "NH", "03603-1102"),
    ("Guildhall", "VT", "05905-0012"),
    ("Yellowstone", "WY", "82190-0100"),
    ("Worcester", "MA", "01608-1200"),
)


class SyntheaModuleDefinition(BaseModel):
    """Parsed representation of a declarative Synthea state-machine JSON module."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    remarks: tuple[str, ...]
    states: dict[str, dict[str, Any]]


class SyntheaOrchestrator:
    """Executes Synthea JSON disease state-machine modules to emit longitudinal FHIR Bundles."""

    def __init__(self, seed: int = 42, modules_dir: Path | None = None) -> None:
        self._seed = seed
        self._rng = random.Random(seed)
        self._modules_dir = modules_dir or MODULES_DIR
        self._modules: dict[str, SyntheaModuleDefinition] = self._load_modules()

    def _load_modules(self) -> dict[str, SyntheaModuleDefinition]:
        loaded: dict[str, SyntheaModuleDefinition] = {}
        for path in sorted(self._modules_dir.glob("*_module.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            definition = SyntheaModuleDefinition(
                name=str(raw["name"]),
                remarks=tuple(str(r) for r in raw.get("remarks", [])),
                states=dict(raw["states"]),
            )
            loaded[definition.name] = definition
        return loaded

    def available_modules(self) -> tuple[str, ...]:
        """Return sorted names of registered Synthea state-machine disease modules."""
        return tuple(sorted(self._modules.keys()))

    def get_module(self, module_name: str) -> SyntheaModuleDefinition:
        """Retrieve a loaded Synthea disease module by name."""
        if module_name not in self._modules:
            raise ValueError(
                f"Unknown Synthea module {module_name!r}. Available: {self.available_modules()}"
            )
        return self._modules[module_name]

    def generate_cohort(self, patient_count: int = 10) -> tuple[FHIRBundle, ...]:
        """Generate a longitudinal cohort of patients across sepsis and chronic modules."""
        if patient_count < 1:
            raise ValueError("patient_count must be >= 1")

        module_names = ("sepsis_deterioration", "cardiopulmonary_chronic")
        bundles: list[FHIRBundle] = []
        for idx in range(patient_count):
            mod_name = module_names[idx % len(module_names)]
            critical = idx % 2 == 0
            bundles.append(
                self.simulate_patient_lifecycle(
                    patient_index=idx,
                    module_name=mod_name,
                    force_critical_trajectory=critical,
                )
            )
        return tuple(bundles)

    def simulate_patient_lifecycle(
        self,
        patient_index: int,
        module_name: str = "sepsis_deterioration",
        force_critical_trajectory: bool = True,
    ) -> FHIRBundle:
        """Run the state machine from Initial to Terminal for a single synthetic patient."""
        module = self.get_module(module_name)
        patient = self._synthesize_patient(patient_index=patient_index)

        base_ts = datetime(2026, 6, 15, 8, 0, tzinfo=UTC) + timedelta(hours=patient_index * 3)
        current_ts = base_ts
        entries: list[FHIRBundleEntry] = [patient]

        current_encounter_id = f"enc-{patient.id}"
        state_name: str | None = "Initial"
        obs_counter = 0
        cond_counter = 0
        med_counter = 0

        while state_name is not None and state_name != "Terminal":
            state = module.states[state_name]
            stype = str(state["type"])
            delay_mins = int(state.get("delay_minutes", 0))
            if delay_mins > 0:
                current_ts = current_ts + timedelta(minutes=delay_mins)

            if stype == "Encounter":
                reason_raw = state["reason"]
                enc_class: Literal["IMP", "EMER", "AMB", "ICU"] = state.get(
                    "encounter_class", "ICU"
                )
                encounter = FHIREncounter(
                    id=current_encounter_id,
                    status="in-progress",
                    class_code=enc_class,
                    subject_id=patient.id,
                    period_start=current_ts,
                    period_end=current_ts + timedelta(hours=12),
                    reason_code=FHIRCodeableConcept(
                        coding=(
                            FHIRCoding(
                                system=str(reason_raw["system"]),
                                code=str(reason_raw["code"]),
                                display=str(reason_raw["display"]),
                            ),
                        ),
                        text=str(reason_raw["display"]),
                    ),
                    facility_id=f"FAC-NE-{(patient_index % 3) + 1:02d}",
                    attending_physician="Dr. Sarah Jenkins, MD",
                )
                entries.append(encounter)

            elif stype == "ConditionOnset":
                cond_counter += 1
                codings = tuple(
                    FHIRCoding(
                        system=str(c["system"]),
                        code=str(c["code"]),
                        display=str(c["display"]),
                    )
                    for c in state["codes"]
                )
                condition = FHIRCondition(
                    id=f"cond-{patient.id}-{cond_counter:02d}",
                    subject_id=patient.id,
                    encounter_id=current_encounter_id,
                    onset_datetime=current_ts,
                    code=FHIRCodeableConcept(coding=codings, text=codings[0].display),
                )
                entries.append(condition)

            elif stype == "ObservationSeries":
                for obs_spec in state["observations"]:
                    obs_counter += 1
                    loinc_code = str(obs_spec["loinc"])
                    display = str(obs_spec["display"])
                    unit = str(obs_spec["unit"])
                    concept = FHIRCodeableConcept(
                        coding=(
                            FHIRCoding(
                                system="http://loinc.org",
                                code=loinc_code,
                                display=display,
                            ),
                        ),
                        text=display,
                    )
                    if "critical_value" in obs_spec:
                        raw_val = float(
                            obs_spec["critical_value"]
                            if force_critical_trajectory
                            else obs_spec["stable_value"]
                        )
                        jitter = self._rng.uniform(-0.3, 0.3) if loinc_code != "3150-0" else 0.0
                        val = round(raw_val + jitter, 1)
                        interp = "H" if force_critical_trajectory else "N"
                        entries.append(
                            FHIRObservation(
                                id=f"obs-{patient.id}-{obs_counter:02d}",
                                subject_id=patient.id,
                                encounter_id=current_encounter_id,
                                effective_datetime=current_ts,
                                code=concept,
                                value_quantity=FHIRQuantity(value=val, unit=unit, code=unit),
                                interpretation_code=interp,
                                note=(
                                    f"Recorded for {patient.names[0].given[0]} "
                                    f"{patient.names[0].family} (SSN {patient.ssn}) "
                                    f"at bed IP {patient.device_ip}"
                                ),
                            )
                        )
                    else:
                        str_val = str(
                            obs_spec["critical_string"]
                            if force_critical_trajectory
                            else obs_spec["stable_string"]
                        )
                        entries.append(
                            FHIRObservation(
                                id=f"obs-{patient.id}-{obs_counter:02d}",
                                subject_id=patient.id,
                                encounter_id=current_encounter_id,
                                effective_datetime=current_ts,
                                code=concept,
                                value_string=str_val,
                                interpretation_code="A" if str_val != "A" else "N",
                            )
                        )

            elif stype == "MedicationOrder":
                med_counter += 1
                med_codings = tuple(
                    FHIRCoding(
                        system=str(c["system"]),
                        code=str(c["code"]),
                        display=str(c["display"]),
                    )
                    for c in state["codes"]
                )
                entries.append(
                    FHIRMedicationRequest(
                        id=f"med-{patient.id}-{med_counter:02d}",
                        subject_id=patient.id,
                        encounter_id=current_encounter_id,
                        authored_on=current_ts,
                        medication_code=FHIRCodeableConcept(
                            coding=med_codings, text=med_codings[0].display
                        ),
                        dosage_text=str(state["dosage"]),
                    )
                )

            state_name = state.get("direct_transition")

        return FHIRBundle(
            id=f"bundle-{patient.id}",
            bundle_type="collection",
            timestamp=base_ts,
            entries=tuple(entries),
        )

    def _synthesize_patient(self, patient_index: int) -> FHIRPatient:
        is_female = patient_index % 2 == 0
        gender: Literal["male", "female"] = "female" if is_female else "male"
        given_pool = _FIRST_NAMES_FEMALE if is_female else _FIRST_NAMES_MALE
        given_name = given_pool[patient_index % len(given_pool)].strip().capitalize()
        family_name = _LAST_NAMES[patient_index % len(_LAST_NAMES)]
        city, state, postal = _CITIES_AND_ZIPS[patient_index % len(_CITIES_AND_ZIPS)]

        # Include elderly patients (90+ years old in 2026) on every 3rd index for HIPAA Safe Harbor
        birth_year = 1931 if patient_index % 3 == 0 else 1962 + (patient_index % 25)
        birth_month = (patient_index % 12) + 1
        birth_day = ((patient_index * 3) % 27) + 1

        ssn_area = 100 + (patient_index % 800)
        ssn_group = 10 + (patient_index % 80)
        ssn = f"{ssn_area:03d}-{ssn_group:02d}-{1000 + patient_index:04d}"
        mrn = f"MRN-{2026000 + patient_index}"
        phone = f"617-555-{1000 + patient_index:04d}"
        email = f"{given_name.lower()}.{family_name.lower()}{patient_index}@patient.example.org"
        device_ip = f"10.24.{patient_index % 250}.{(patient_index * 7) % 250 + 1}"

        return FHIRPatient(
            id=f"pat-{patient_index + 1:04d}",
            identifiers=(
                FHIRIdentifier(
                    system="http://hospital.example.org/mrn",
                    value=mrn,
                    type_code="MR",
                ),
            ),
            names=(
                FHIRHumanName(
                    use="official",
                    family=family_name,
                    given=(given_name,),
                    prefix=("Ms." if is_female else "Mr.",),
                ),
            ),
            telecom=(
                FHIRContactPoint(system="phone", value=phone, use="mobile"),
                FHIRContactPoint(system="email", value=email, use="home"),
                FHIRContactPoint(
                    system="url",
                    value=f"https://portal.example.org/patients/{mrn}",
                    use="work",
                ),
            ),
            gender=gender,
            birth_date=date(birth_year, birth_month, birth_day),
            addresses=(
                FHIRAddress(
                    line=(f"{100 + patient_index} Medical Center Way",),
                    city=city,
                    state=state,
                    postal_code=postal,
                ),
            ),
            ssn=ssn,
            device_ip=device_ip,
            clinical_note=(
                f"Patient {given_name} {family_name}, MRN {mrn}, SSN {ssn}, "
                f"contact {phone} / {email}, monitor IP {device_ip}, "
                f"portal https://portal.example.org/patients/{mrn}"
            ),
        )

    @staticmethod
    def bundle_to_fhir_xml(bundle: FHIRBundle) -> str:
        """Render a FHIRBundle into an HL7 FHIR R4 XML payload for XML ingestion testing."""
        root = ET.Element("Bundle", attrib={"xmlns": "http://hl7.org/fhir"})
        ET.SubElement(root, "id", attrib={"value": bundle.id})
        ET.SubElement(root, "type", attrib={"value": bundle.bundle_type})
        ET.SubElement(root, "timestamp", attrib={"value": bundle.timestamp.isoformat()})

        for patient in bundle.patients():
            entry_el = ET.SubElement(root, "entry")
            res_el = ET.SubElement(entry_el, "resource")
            pat_el = ET.SubElement(res_el, "Patient")
            ET.SubElement(pat_el, "id", attrib={"value": patient.id})
            if patient.identifiers:
                ident_el = ET.SubElement(pat_el, "identifier")
                ET.SubElement(ident_el, "system", attrib={"value": patient.identifiers[0].system})
                ET.SubElement(ident_el, "value", attrib={"value": patient.identifiers[0].value})
            if patient.names:
                name_el = ET.SubElement(pat_el, "name")
                ET.SubElement(name_el, "family", attrib={"value": patient.names[0].family})
                for g in patient.names[0].given:
                    ET.SubElement(name_el, "given", attrib={"value": g})
            for t in patient.telecom:
                tel_el = ET.SubElement(pat_el, "telecom")
                ET.SubElement(tel_el, "system", attrib={"value": t.system})
                ET.SubElement(tel_el, "value", attrib={"value": t.value})
            ET.SubElement(pat_el, "gender", attrib={"value": patient.gender})
            ET.SubElement(pat_el, "birthDate", attrib={"value": patient.birth_date.isoformat()})
            if patient.addresses:
                addr_el = ET.SubElement(pat_el, "address")
                for ln in patient.addresses[0].line:
                    ET.SubElement(addr_el, "line", attrib={"value": ln})
                ET.SubElement(addr_el, "city", attrib={"value": patient.addresses[0].city})
                ET.SubElement(addr_el, "state", attrib={"value": patient.addresses[0].state})
                ET.SubElement(
                    addr_el, "postalCode", attrib={"value": patient.addresses[0].postal_code}
                )
            if patient.ssn:
                ext_el = ET.SubElement(
                    pat_el,
                    "extension",
                    attrib={"url": "http://hl7.org/fhir/StructureDefinition/patient-ssn"},
                )
                ET.SubElement(ext_el, "valueString", attrib={"value": patient.ssn})
            if patient.device_ip:
                ext_ip = ET.SubElement(
                    pat_el,
                    "extension",
                    attrib={"url": "http://hospital.example.org/fhir/ext/device-ip"},
                )
                ET.SubElement(ext_ip, "valueString", attrib={"value": patient.device_ip})
            if patient.clinical_note:
                ext_note = ET.SubElement(
                    pat_el,
                    "extension",
                    attrib={"url": "http://hospital.example.org/fhir/ext/clinical-note"},
                )
                ET.SubElement(ext_note, "valueString", attrib={"value": patient.clinical_note})

        for enc in bundle.encounters():
            entry_el = ET.SubElement(root, "entry")
            res_el = ET.SubElement(entry_el, "resource")
            enc_el = ET.SubElement(res_el, "Encounter")
            ET.SubElement(enc_el, "id", attrib={"value": enc.id})
            ET.SubElement(enc_el, "status", attrib={"value": enc.status})
            ET.SubElement(enc_el, "class", attrib={"code": enc.class_code})
            ET.SubElement(enc_el, "subject", attrib={"reference": f"Patient/{enc.subject_id}"})
            period_el = ET.SubElement(enc_el, "period")
            ET.SubElement(period_el, "start", attrib={"value": enc.period_start.isoformat()})
            if enc.period_end is not None:
                ET.SubElement(period_el, "end", attrib={"value": enc.period_end.isoformat()})
            ET.SubElement(
                enc_el,
                "serviceProvider",
                attrib={"reference": f"Organization/{enc.facility_id}"},
            )
            if enc.attending_physician:
                part_el = ET.SubElement(enc_el, "participant")
                ET.SubElement(part_el, "individual", attrib={"display": enc.attending_physician})

        for obs in bundle.observations():
            entry_el = ET.SubElement(root, "entry")
            res_el = ET.SubElement(entry_el, "resource")
            obs_el = ET.SubElement(res_el, "Observation")
            ET.SubElement(obs_el, "id", attrib={"value": obs.id})
            ET.SubElement(obs_el, "status", attrib={"value": obs.status})
            ET.SubElement(obs_el, "subject", attrib={"reference": f"Patient/{obs.subject_id}"})
            ET.SubElement(
                obs_el, "encounter", attrib={"reference": f"Encounter/{obs.encounter_id}"}
            )
            ET.SubElement(
                obs_el, "effectiveDateTime", attrib={"value": obs.effective_datetime.isoformat()}
            )
            coding = obs.code.coding[0]
            code_el = ET.SubElement(obs_el, "code")
            coding_el = ET.SubElement(code_el, "coding")
            ET.SubElement(coding_el, "system", attrib={"value": coding.system})
            ET.SubElement(coding_el, "code", attrib={"value": coding.code})
            ET.SubElement(coding_el, "display", attrib={"value": coding.display})
            if obs.value_quantity is not None:
                vq_el = ET.SubElement(obs_el, "valueQuantity")
                ET.SubElement(vq_el, "value", attrib={"value": str(obs.value_quantity.value)})
                ET.SubElement(vq_el, "unit", attrib={"value": obs.value_quantity.unit})
                ET.SubElement(vq_el, "code", attrib={"value": obs.value_quantity.code})
            else:
                ET.SubElement(obs_el, "valueString", attrib={"value": obs.value_string or ""})
            if obs.note:
                note_el = ET.SubElement(obs_el, "note")
                ET.SubElement(note_el, "text", attrib={"value": obs.note})

        for cond in bundle.conditions():
            entry_el = ET.SubElement(root, "entry")
            res_el = ET.SubElement(entry_el, "resource")
            cond_el = ET.SubElement(res_el, "Condition")
            ET.SubElement(cond_el, "id", attrib={"value": cond.id})
            ET.SubElement(cond_el, "subject", attrib={"reference": f"Patient/{cond.subject_id}"})
            ET.SubElement(
                cond_el, "encounter", attrib={"reference": f"Encounter/{cond.encounter_id}"}
            )
            ET.SubElement(
                cond_el, "onsetDateTime", attrib={"value": cond.onset_datetime.isoformat()}
            )
            c0 = cond.code.coding[0]
            cond_code_el = ET.SubElement(cond_el, "code")
            cond_coding_el = ET.SubElement(cond_code_el, "coding")
            ET.SubElement(cond_coding_el, "system", attrib={"value": c0.system})
            ET.SubElement(cond_coding_el, "code", attrib={"value": c0.code})
            ET.SubElement(cond_coding_el, "display", attrib={"value": c0.display})

        for med in bundle.medication_requests():
            entry_el = ET.SubElement(root, "entry")
            res_el = ET.SubElement(entry_el, "resource")
            med_el = ET.SubElement(res_el, "MedicationRequest")
            ET.SubElement(med_el, "id", attrib={"value": med.id})
            ET.SubElement(med_el, "subject", attrib={"reference": f"Patient/{med.subject_id}"})
            ET.SubElement(
                med_el, "encounter", attrib={"reference": f"Encounter/{med.encounter_id}"}
            )
            ET.SubElement(med_el, "authoredOn", attrib={"value": med.authored_on.isoformat()})
            m0 = med.medication_code.coding[0]
            med_cc_el = ET.SubElement(med_el, "medicationCodeableConcept")
            med_coding_el = ET.SubElement(med_cc_el, "coding")
            ET.SubElement(med_coding_el, "system", attrib={"value": m0.system})
            ET.SubElement(med_coding_el, "code", attrib={"value": m0.code})
            ET.SubElement(med_coding_el, "display", attrib={"value": m0.display})
            dosage_el = ET.SubElement(med_el, "dosageInstruction")
            ET.SubElement(dosage_el, "text", attrib={"value": med.dosage_text})

        return ET.tostring(root, encoding="unicode")
