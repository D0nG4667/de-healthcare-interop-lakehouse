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
_PHONE_REGEX: re.Pattern[str] = re.compile(
    r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)[-.\s]?|\b\d{3}[-.\s])\d{3}[-.\s]\d{4}\b"
)
_EMAIL_REGEX: re.Pattern[str] = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4_REGEX: re.Pattern[str] = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_REGEX: re.Pattern[str] = re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}\b")
_URL_REGEX: re.Pattern[str] = re.compile(r"https?://[^\s,;]+")
_MRN_REGEX: re.Pattern[str] = re.compile(r"\bMRN-\d+\b")
_KMS_TOKEN_REGEX: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+:[0-9a-f]{24,64}$")
_ACVPU_VALID_CODES: frozenset[str] = frozenset({"A", "C", "V", "P", "U"})


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
        self._settings = settings or LakehouseSettings()
        self._tokenizer = tokenizer or KMSTokenizer.from_default_dev_keyring(
            active_key_id=self._settings.kms_active_key_id,
            require_env_secret=(self._settings.environment == "production"),
        )

    @property
    def tokenizer(self) -> KMSTokenizer:
        """Return the active KMS tokenizer instance."""
        return self._tokenizer

    def anonymize_bundle(self, bundle: FHIRBundle) -> FHIRBundle:
        """De-identify all resources inside a FHIRBundle while preserving relational links."""
        ref_date = bundle.timestamp.date()
        canonical_patient_keys: dict[str, str] = {}
        patient_shifts: dict[str, int] = {}
        sensitive_names: list[str] = []

        for pat in bundle.patients():
            canonical_key = self._resolve_canonical_patient_key(pat)
            canonical_patient_keys[pat.id] = canonical_key
            patient_shifts[pat.id] = self._tokenizer.deterministic_date_shift_days(canonical_key)
            for name in pat.names:
                sensitive_names.append(name.family)
                sensitive_names.extend(name.given)

        for enc in bundle.encounters():
            if enc.attending_physician:
                for token_part in re.split(r"[\s,^]+", enc.attending_physician):
                    cleaned_part = token_part.strip(".")
                    if cleaned_part.upper() not in {"DR", "MD", "DO", "RN"}:
                        sensitive_names.append(cleaned_part)

        default_shift = next(iter(patient_shifts.values()), -30)
        shifted_bundle_ts = bundle.timestamp + timedelta(days=default_shift)
        shifted_ref_year = shifted_bundle_ts.year

        anonymized_entries: list[FHIRBundleEntry] = []
        for entry in bundle.entries:
            if isinstance(entry, FHIRPatient):
                shift_days = patient_shifts[entry.id]
                canonical_key = canonical_patient_keys[entry.id]
                anonymized_entries.append(
                    self._anonymize_patient(
                        patient=entry,
                        canonical_key=canonical_key,
                        shift_days=shift_days,
                        ref_date=ref_date,
                        shifted_ref_year=shifted_ref_year,
                        sensitive_names=sensitive_names,
                    )
                )
            elif isinstance(entry, FHIREncounter):
                shift_days = patient_shifts.get(entry.subject_id, default_shift)
                subj_key = canonical_patient_keys.get(entry.subject_id, entry.subject_id)
                anonymized_entries.append(
                    self._anonymize_encounter(
                        encounter=entry,
                        subject_canonical_key=subj_key,
                        shift_days=shift_days,
                    )
                )
            elif isinstance(entry, FHIRObservation):
                shift_days = patient_shifts.get(entry.subject_id, default_shift)
                subj_key = canonical_patient_keys.get(entry.subject_id, entry.subject_id)
                anonymized_entries.append(
                    self._anonymize_observation(
                        observation=entry,
                        subject_canonical_key=subj_key,
                        shift_days=shift_days,
                        sensitive_names=sensitive_names,
                    )
                )
            elif isinstance(entry, FHIRCondition):
                shift_days = patient_shifts.get(entry.subject_id, default_shift)
                subj_key = canonical_patient_keys.get(entry.subject_id, entry.subject_id)
                anonymized_entries.append(
                    self._anonymize_condition(
                        condition=entry,
                        subject_canonical_key=subj_key,
                        shift_days=shift_days,
                    )
                )
            else:
                shift_days = patient_shifts.get(entry.subject_id, default_shift)
                subj_key = canonical_patient_keys.get(entry.subject_id, entry.subject_id)
                anonymized_entries.append(
                    self._anonymize_medication(
                        medication=entry,
                        subject_canonical_key=subj_key,
                        shift_days=shift_days,
                        sensitive_names=sensitive_names,
                    )
                )

        return FHIRBundle(
            id=self._tokenizer.tokenize(bundle.id, namespace="bundle"),
            bundle_type=bundle.bundle_type,
            timestamp=shifted_bundle_ts,
            entries=tuple(anonymized_entries),
        )

    @staticmethod
    def _resolve_canonical_patient_key(patient: FHIRPatient) -> str:
        for ident in patient.identifiers:
            if ident.type_code == "MR" and ident.value.strip():
                return ident.value.strip().upper()
        return patient.id.strip()

    def _anonymize_patient(
        self,
        patient: FHIRPatient,
        canonical_key: str,
        shift_days: int,
        ref_date: date,
        shifted_ref_year: int,
        sensitive_names: list[str],
    ) -> FHIRPatient:
        patient_token = self._tokenizer.tokenize(canonical_key, namespace="patient")
        tokenized_identifiers = tuple(
            FHIRIdentifier(
                system=ident.system,
                value=self._tokenizer.tokenize(ident.value.strip().upper(), namespace="mrn"),
                type_code=ident.type_code,
            )
            for ident in patient.identifiers
        )

        birthday_not_reached = (ref_date.month, ref_date.day) < (
            patient.birth_date.month,
            patient.birth_date.day,
        )
        raw_age = max(
            0, ref_date.year - patient.birth_date.year - (1 if birthday_not_reached else 0)
        )
        if raw_age > self._settings.hipaa_safe_harbor_max_age:
            capped_age = 90
            safe_birth_date = date(shifted_ref_year - 90, 1, 1)
        else:
            capped_age = raw_age
            shifted_dob = patient.birth_date + timedelta(days=shift_days)
            clamped_birth_year = max(
                shifted_ref_year - self._settings.hipaa_safe_harbor_max_age,
                shifted_dob.year,
            )
            safe_birth_date = date(clamped_birth_year, 1, 1)

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
        subject_canonical_key: str,
        shift_days: int,
    ) -> FHIREncounter:
        delta = timedelta(days=shift_days)
        return FHIREncounter(
            id=self._tokenizer.tokenize(encounter.id, namespace="encounter"),
            status=encounter.status,
            class_code=encounter.class_code,
            subject_id=self._tokenizer.tokenize(subject_canonical_key, namespace="patient"),
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
        subject_canonical_key: str,
        shift_days: int,
        sensitive_names: list[str],
    ) -> FHIRObservation:
        delta = timedelta(days=shift_days)
        loinc_code = observation.code.coding[0].code
        raw_val_str = observation.value_string
        if raw_val_str is not None:
            is_acvpu = loinc_code == "67775-7" and raw_val_str.strip().upper() in _ACVPU_VALID_CODES
            safe_val_str: str | None = (
                raw_val_str.strip().upper()
                if is_acvpu
                else self.scrub_free_text(raw_val_str, sensitive_names=sensitive_names)
            )
        else:
            safe_val_str = None

        return FHIRObservation(
            id=self._tokenizer.tokenize(observation.id, namespace="observation"),
            status=observation.status,
            category_code=observation.category_code,
            code=observation.code,
            subject_id=self._tokenizer.tokenize(subject_canonical_key, namespace="patient"),
            encounter_id=self._tokenizer.tokenize(observation.encounter_id, namespace="encounter"),
            effective_datetime=observation.effective_datetime + delta,
            value_quantity=observation.value_quantity,
            value_string=safe_val_str,
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
        subject_canonical_key: str,
        shift_days: int,
    ) -> FHIRCondition:
        delta = timedelta(days=shift_days)
        return FHIRCondition(
            id=self._tokenizer.tokenize(condition.id, namespace="condition"),
            clinical_status=condition.clinical_status,
            verification_status=condition.verification_status,
            code=condition.code,
            subject_id=self._tokenizer.tokenize(subject_canonical_key, namespace="patient"),
            encounter_id=self._tokenizer.tokenize(condition.encounter_id, namespace="encounter"),
            onset_datetime=condition.onset_datetime + delta,
        )

    def _anonymize_medication(
        self,
        medication: FHIRMedicationRequest,
        subject_canonical_key: str,
        shift_days: int,
        sensitive_names: list[str],
    ) -> FHIRMedicationRequest:
        delta = timedelta(days=shift_days)
        return FHIRMedicationRequest(
            id=self._tokenizer.tokenize(medication.id, namespace="medication"),
            status=medication.status,
            intent=medication.intent,
            medication_code=medication.medication_code,
            subject_id=self._tokenizer.tokenize(subject_canonical_key, namespace="patient"),
            encounter_id=self._tokenizer.tokenize(medication.encounter_id, namespace="encounter"),
            authored_on=medication.authored_on + delta,
            dosage_text=self.scrub_free_text(
                medication.dosage_text, sensitive_names=sensitive_names
            ),
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
        """Redact SSNs, phone numbers, emails, IPv4/IPv6s, URLs, MRNs, and names in notes."""
        scrubbed = _URL_REGEX.sub("[REDACTED-URL]", text)
        scrubbed = _EMAIL_REGEX.sub("[REDACTED-EMAIL]", scrubbed)
        scrubbed = _SSN_REGEX.sub("[REDACTED-SSN]", scrubbed)
        scrubbed = _PHONE_REGEX.sub("[REDACTED-PHONE]", scrubbed)
        scrubbed = _IPV6_REGEX.sub("[REDACTED-IP]", scrubbed)
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

    @staticmethod
    def is_valid_kms_token(value: str) -> bool:
        """Return True iff value conforms to '<kid>:<24-64 lowercase hex digest>'."""
        return bool(_KMS_TOKEN_REGEX.match(value))

    def audit_bundle(self, bundle: FHIRBundle) -> HIPAAAuditReport:
        """Inspect all entries in a FHIRBundle and return a detailed HIPAAAuditReport."""
        violations: list[str] = []

        if not self.is_valid_kms_token(bundle.id):
            violations.append(f"Bundle.id {bundle.id!r} is not KMS-tokenized.")

        for pat in bundle.patients():
            if not self.is_valid_kms_token(pat.id):
                violations.append(f"Patient.id {pat.id!r} is not KMS-tokenized.")
            if pat.ssn is not None:
                violations.append("Patient.ssn is present and unmasked.")
            if pat.device_ip is not None:
                violations.append("Patient.device_ip is present and unmasked.")
            if pat.telecom:
                violations.append("Patient.telecom contains unmasked contact endpoints.")
            for ident in pat.identifiers:
                if not self.is_valid_kms_token(ident.value):
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

        for enc in bundle.encounters():
            if not self.is_valid_kms_token(enc.id):
                violations.append(f"Encounter.id {enc.id!r} is not KMS-tokenized.")
            if not self.is_valid_kms_token(enc.subject_id):
                violations.append(f"Encounter.subject_id {enc.subject_id!r} is not KMS-tokenized.")
            if enc.attending_physician is not None and not self.is_valid_kms_token(
                enc.attending_physician
            ):
                violations.append(
                    f"Encounter.attending_physician {enc.attending_physician!r} "
                    "is not KMS-tokenized."
                )

        for obs in bundle.observations():
            if not self.is_valid_kms_token(obs.id):
                violations.append(f"Observation.id {obs.id!r} is not KMS-tokenized.")
            if not self.is_valid_kms_token(obs.subject_id):
                violations.append(
                    f"Observation.subject_id {obs.subject_id!r} is not KMS-tokenized."
                )
            if not self.is_valid_kms_token(obs.encounter_id):
                violations.append(
                    f"Observation.encounter_id {obs.encounter_id!r} is not KMS-tokenized."
                )
            if obs.value_string:
                violations.extend(
                    self._scan_text_for_phi(obs.value_string, f"Observation({obs.id}).value_string")
                )
            if obs.note:
                violations.extend(self._scan_text_for_phi(obs.note, f"Observation({obs.id}).note"))

        for cond in bundle.conditions():
            if not self.is_valid_kms_token(cond.id):
                violations.append(f"Condition.id {cond.id!r} is not KMS-tokenized.")
            if not self.is_valid_kms_token(cond.subject_id):
                violations.append(f"Condition.subject_id {cond.subject_id!r} is not KMS-tokenized.")
            if not self.is_valid_kms_token(cond.encounter_id):
                violations.append(
                    f"Condition.encounter_id {cond.encounter_id!r} is not KMS-tokenized."
                )

        for med in bundle.medication_requests():
            if not self.is_valid_kms_token(med.id):
                violations.append(f"MedicationRequest.id {med.id!r} is not KMS-tokenized.")
            if not self.is_valid_kms_token(med.subject_id):
                violations.append(
                    f"MedicationRequest.subject_id {med.subject_id!r} is not KMS-tokenized."
                )
            if not self.is_valid_kms_token(med.encounter_id):
                violations.append(
                    f"MedicationRequest.encounter_id {med.encounter_id!r} is not KMS-tokenized."
                )
            violations.extend(
                self._scan_text_for_phi(med.dosage_text, f"MedicationRequest({med.id}).dosage_text")
            )

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
    def scan_text_for_phi(text: str, context: str) -> list[str]:
        """Return detected PHI pattern descriptions within an arbitrary text field."""
        return HIPAAComplianceAuditor._scan_text_for_phi(text, context)

    @staticmethod
    def _scan_text_for_phi(text: str, context: str) -> list[str]:
        found: list[str] = []
        if _SSN_REGEX.search(text):
            found.append(f"{context}: raw SSN pattern detected.")
        if _EMAIL_REGEX.search(text):
            found.append(f"{context}: raw email pattern detected.")
        if _PHONE_REGEX.search(text):
            found.append(f"{context}: raw phone pattern detected.")
        if _IPV6_REGEX.search(text):
            found.append(f"{context}: raw IPv6 address detected.")
        if _IPV4_REGEX.search(text):
            found.append(f"{context}: raw IPv4 address detected.")
        if _URL_REGEX.search(text):
            found.append(f"{context}: raw URL detected.")
        if _MRN_REGEX.search(text):
            found.append(f"{context}: raw MRN detected.")
        return found
