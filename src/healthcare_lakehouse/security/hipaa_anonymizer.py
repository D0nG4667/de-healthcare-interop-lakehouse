"""HIPAA Safe Harbor (45 CFR §164.514(b)(2)) 18-identifier de-identification engine."""

from __future__ import annotations

import re
from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from healthcare_lakehouse.config.settings import (
    HIPAA_RESTRICTED_ZIP3_PREFIXES,
    LakehouseSettings,
)
from healthcare_lakehouse.models.fhir_resources import (
    FHIRAddress,
    FHIRBundle,
    FHIRBundleEntry,
    FHIRCondition,
    FHIREncounter,
    FHIRHumanName,
    FHIRIdentifier,
    FHIRMedicationRequest,
    FHIRObservation,
    FHIRPatient,
)
from healthcare_lakehouse.security.kms_tokenizer import KMSTokenizer

_SSN_REGEX: re.Pattern[str] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE_REGEX: re.Pattern[str] = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")
_EMAIL_REGEX: re.Pattern[str] = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4_REGEX: re.Pattern[str] = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_URL_REGEX: re.Pattern[str] = re.compile(r"https?://[^\s,;]+")
_MRN_REGEX: re.Pattern[str] = re.compile(r"\bMRN-\d+\b")


class HIPAAComplianceError(ValueError):
    """Raised when a clinical record or bundle fails the HIPAA Safe Harbor Zero-PHI gate."""


class HIPAAAuditReport(BaseModel):
    """Immutable compliance verification report emitted by HIPAAComplianceAuditor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_compliant: bool
    checked_resources: int
    violations: tuple[str, ...]


class HIPAAAnonymizer:
    """De-identifies FHIR R4 clinical bundles across all 18 HIPAA Safe Harbor identifiers."""

    def __init__(
        self,
        tokenizer: KMSTokenizer | None = None,
        settings: LakehouseSettings | None = None,
    ) -> None:
        self._tokenizer = tokenizer or KMSTokenizer.from_default_dev_keyring()
        self._settings = settings or LakehouseSettings()

    @property
    def tokenizer(self) -> KMSTokenizer:
        """Return the active KMS tokenizer instance."""
        return self._tokenizer

    def anonymize_bundle(self, bundle: FHIRBundle) -> FHIRBundle:
        """De-identify all resources inside a FHIRBundle while preserving relational links."""
        ref_year = bundle.timestamp.year
        patient_shifts: dict[str, int] = {}
        sensitive_names: list[str] = []

        for pat in bundle.patients():
            patient_shifts[pat.id] = self._tokenizer.deterministic_date_shift_days(pat.id)
            for name in pat.names:
                sensitive_names.append(name.family)
                sensitive_names.extend(name.given)

        default_shift = next(iter(patient_shifts.values()), -30)
        shifted_bundle_ts = bundle.timestamp + timedelta(days=default_shift)

        anonymized_entries: list[FHIRBundleEntry] = []
        for entry in bundle.entries:
            if isinstance(entry, FHIRPatient):
                shift_days = patient_shifts[entry.id]
                anonymized_entries.append(
                    self._anonymize_patient(
                        patient=entry,
                        shift_days=shift_days,
                        ref_year=ref_year,
                        sensitive_names=sensitive_names,
                    )
                )
            elif isinstance(entry, FHIREncounter):
                shift_days = patient_shifts.get(entry.subject_id, default_shift)
                anonymized_entries.append(
                    self._anonymize_encounter(encounter=entry, shift_days=shift_days)
                )
            elif isinstance(entry, FHIRObservation):
                shift_days = patient_shifts.get(entry.subject_id, default_shift)
                anonymized_entries.append(
                    self._anonymize_observation(
                        observation=entry,
                        shift_days=shift_days,
                        sensitive_names=sensitive_names,
                    )
                )
            elif isinstance(entry, FHIRCondition):
                shift_days = patient_shifts.get(entry.subject_id, default_shift)
                anonymized_entries.append(
                    self._anonymize_condition(condition=entry, shift_days=shift_days)
                )
            else:
                shift_days = patient_shifts.get(entry.subject_id, default_shift)
                anonymized_entries.append(
                    self._anonymize_medication(medication=entry, shift_days=shift_days)
                )

        return FHIRBundle(
            id=self._tokenizer.tokenize(bundle.id, namespace="bundle"),
            bundle_type=bundle.bundle_type,
            timestamp=shifted_bundle_ts,
            entries=tuple(anonymized_entries),
        )

    def _anonymize_patient(
        self,
        patient: FHIRPatient,
        shift_days: int,
        ref_year: int,
        sensitive_names: list[str],
    ) -> FHIRPatient:
        patient_token = self._tokenizer.tokenize(patient.id, namespace="patient")
        tokenized_identifiers = tuple(
            FHIRIdentifier(
                system=ident.system,
                value=self._tokenizer.tokenize(ident.value, namespace="mrn"),
                type_code=ident.type_code,
            )
            for ident in patient.identifiers
        )

        raw_age = max(0, ref_year - patient.birth_date.year)
        if raw_age > self._settings.hipaa_safe_harbor_max_age:
            capped_age = 90
            safe_birth_date = date(ref_year - 90, 1, 1)
        else:
            capped_age = raw_age
            shifted_dob = patient.birth_date + timedelta(days=shift_days)
            safe_birth_date = date(shifted_dob.year, 1, 1)

        masked_addresses = tuple(
            FHIRAddress(
                line=("REDACTED",),
                city="REDACTED",
                state=addr.state,
                postal_code=self.mask_zip_code(addr.postal_code),
                country=addr.country,
            )
            for addr in patient.addresses
        )

        scrubbed_note = (
            self.scrub_free_text(patient.clinical_note, sensitive_names=sensitive_names)
            if patient.clinical_note
            else None
        )

        return FHIRPatient(
            id=patient_token,
            identifiers=tokenized_identifiers,
            names=(
                FHIRHumanName(
                    use="anonymous",
                    family="REDACTED",
                    given=("ANONYMIZED",),
                    prefix=(),
                ),
            ),
            telecom=(),
            gender=patient.gender,
            birth_date=safe_birth_date,
            addresses=masked_addresses,
            ssn=None,
            device_ip=None,
            clinical_note=scrubbed_note,
            age_years=capped_age,
        )

    def _anonymize_encounter(
        self,
        encounter: FHIREncounter,
        shift_days: int,
    ) -> FHIREncounter:
        delta = timedelta(days=shift_days)
        return FHIREncounter(
            id=self._tokenizer.tokenize(encounter.id, namespace="encounter"),
            status=encounter.status,
            class_code=encounter.class_code,
            subject_id=self._tokenizer.tokenize(encounter.subject_id, namespace="patient"),
            period_start=encounter.period_start + delta,
            period_end=(encounter.period_end + delta if encounter.period_end is not None else None),
            reason_code=encounter.reason_code,
            facility_id=encounter.facility_id,
            attending_physician=(
                self._tokenizer.tokenize(encounter.attending_physician, namespace="practitioner")
                if encounter.attending_physician
                else None
            ),
        )

    def _anonymize_observation(
        self,
        observation: FHIRObservation,
        shift_days: int,
        sensitive_names: list[str],
    ) -> FHIRObservation:
        delta = timedelta(days=shift_days)
        return FHIRObservation(
            id=self._tokenizer.tokenize(observation.id, namespace="observation"),
            status=observation.status,
            category_code=observation.category_code,
            code=observation.code,
            subject_id=self._tokenizer.tokenize(observation.subject_id, namespace="patient"),
            encounter_id=self._tokenizer.tokenize(observation.encounter_id, namespace="encounter"),
            effective_datetime=observation.effective_datetime + delta,
            value_quantity=observation.value_quantity,
            value_string=observation.value_string,
            interpretation_code=observation.interpretation_code,
            note=(
                self.scrub_free_text(observation.note, sensitive_names=sensitive_names)
                if observation.note
                else None
            ),
        )

    def _anonymize_condition(
        self,
        condition: FHIRCondition,
        shift_days: int,
    ) -> FHIRCondition:
        delta = timedelta(days=shift_days)
        return FHIRCondition(
            id=self._tokenizer.tokenize(condition.id, namespace="condition"),
            clinical_status=condition.clinical_status,
            verification_status=condition.verification_status,
            code=condition.code,
            subject_id=self._tokenizer.tokenize(condition.subject_id, namespace="patient"),
            encounter_id=self._tokenizer.tokenize(condition.encounter_id, namespace="encounter"),
            onset_datetime=condition.onset_datetime + delta,
        )

    def _anonymize_medication(
        self,
        medication: FHIRMedicationRequest,
        shift_days: int,
    ) -> FHIRMedicationRequest:
        delta = timedelta(days=shift_days)
        return FHIRMedicationRequest(
            id=self._tokenizer.tokenize(medication.id, namespace="medication"),
            status=medication.status,
            intent=medication.intent,
            medication_code=medication.medication_code,
            subject_id=self._tokenizer.tokenize(medication.subject_id, namespace="patient"),
            encounter_id=self._tokenizer.tokenize(medication.encounter_id, namespace="encounter"),
            authored_on=medication.authored_on + delta,
            dosage_text=medication.dosage_text,
        )

    def mask_zip_code(self, postal_code: str) -> str:
        """Truncate postal code to 3 digits or '000' for HIPAA restricted prefixes."""
        digits = "".join(ch for ch in postal_code if ch.isdigit())
        if len(digits) < 3:
            return "000"
        prefix3 = digits[:3]
        if prefix3 in self._settings.hipaa_restricted_zip3_prefixes:
            return "000"
        return prefix3

    @staticmethod
    def scrub_free_text(text: str, sensitive_names: list[str] | None = None) -> str:
        """Redact SSNs, phone numbers, emails, IPv4s, URLs, MRNs, and names in notes."""
        scrubbed = _URL_REGEX.sub("[REDACTED-URL]", text)
        scrubbed = _EMAIL_REGEX.sub("[REDACTED-EMAIL]", scrubbed)
        scrubbed = _SSN_REGEX.sub("[REDACTED-SSN]", scrubbed)
        scrubbed = _PHONE_REGEX.sub("[REDACTED-PHONE]", scrubbed)
        scrubbed = _IPV4_REGEX.sub("[REDACTED-IP]", scrubbed)
        scrubbed = _MRN_REGEX.sub("[REDACTED-MRN]", scrubbed)

        if sensitive_names:
            for name in sensitive_names:
                clean_name = name.strip()
                if len(clean_name) >= 2:
                    scrubbed = re.sub(
                        rf"\b{re.escape(clean_name)}\b",
                        "[REDACTED-NAME]",
                        scrubbed,
                        flags=re.IGNORECASE,
                    )
        return scrubbed


class HIPAAComplianceAuditor:
    """Automated Zero-PHI auditor verifying HIPAA Safe Harbor compliance on bundles."""

    def audit_bundle(self, bundle: FHIRBundle) -> HIPAAAuditReport:
        """Inspect all entries in a FHIRBundle and return a detailed HIPAAAuditReport."""
        violations: list[str] = []

        for pat in bundle.patients():
            if ":" not in pat.id:
                violations.append(f"Patient.id {pat.id!r} is not KMS-tokenized.")
            if pat.ssn is not None:
                violations.append("Patient.ssn is present and unmasked.")
            if pat.device_ip is not None:
                violations.append("Patient.device_ip is present and unmasked.")
            if pat.telecom:
                violations.append("Patient.telecom contains unmasked contact endpoints.")
            for ident in pat.identifiers:
                if ":" not in ident.value:
                    violations.append(f"Patient.identifier {ident.value!r} is not KMS-tokenized.")
            for name in pat.names:
                if name.family != "REDACTED" or name.given != ("ANONYMIZED",):
                    violations.append(f"Patient.name {name.family!r} is not redacted.")
            if pat.birth_date.month != 1 or pat.birth_date.day != 1:
                violations.append(
                    f"Patient.birth_date {pat.birth_date.isoformat()} exposes month/day."
                )
            if pat.age_years is not None and pat.age_years > 90:
                violations.append(
                    f"Patient.age_years {pat.age_years} exceeds HIPAA Safe Harbor 90+ cap."
                )
            for addr in pat.addresses:
                if addr.city != "REDACTED" or addr.line != ("REDACTED",):
                    violations.append("Patient.address street/city is not redacted.")
                if len(addr.postal_code) != 3 or addr.postal_code in HIPAA_RESTRICTED_ZIP3_PREFIXES:
                    violations.append(f"Restricted or unmasked postal_code: {addr.postal_code!r}.")
            if pat.clinical_note:
                violations.extend(self._scan_text_for_phi(pat.clinical_note, "Patient.note"))

        for obs in bundle.observations():
            if obs.note:
                violations.extend(self._scan_text_for_phi(obs.note, f"Observation({obs.id})"))

        return HIPAAAuditReport(
            is_compliant=len(violations) == 0,
            checked_resources=len(bundle.entries),
            violations=tuple(violations),
        )

    def assert_bundle_compliant(self, bundle: FHIRBundle) -> HIPAAAuditReport:
        """Audit a FHIRBundle and raise HIPAAComplianceError if any PHI violation exists."""
        report = self.audit_bundle(bundle)
        if not report.is_compliant:
            raise HIPAAComplianceError(
                f"HIPAA Safe Harbor audit failed with {len(report.violations)} "
                f"violation(s): {report.violations}"
            )
        return report

    @staticmethod
    def _scan_text_for_phi(text: str, context: str) -> list[str]:
        found: list[str] = []
        if _SSN_REGEX.search(text):
            found.append(f"{context}: raw SSN pattern detected.")
        if _EMAIL_REGEX.search(text):
            found.append(f"{context}: raw email pattern detected.")
        if _PHONE_REGEX.search(text):
            found.append(f"{context}: raw phone pattern detected.")
        if _IPV4_REGEX.search(text):
            found.append(f"{context}: raw IPv4 address detected.")
        if _URL_REGEX.search(text):
            found.append(f"{context}: raw URL detected.")
        if _MRN_REGEX.search(text):
            found.append(f"{context}: raw MRN detected.")
        return found
