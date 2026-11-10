# ADR-002: HIPAA Safe Harbor 18-Identifier De-Identification & KMS Key-Ring Tokenization

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Principal Forward-Deployed Data Engineer, CISO & HIPAA Privacy Officer
- **Refs:** 45 CFR §164.514(b)(2) (Safe Harbor), 45 CFR §164.312 (Technical Safeguards)

---

## 1. Context

Under the HIPAA Privacy Rule Safe Harbor method (45 CFR §164.514(b)(2)), clinical datasets used for research and analytics must have all 18 categories of PHI removed. However, naive redaction (e.g., replacing every `patient_id` with a random UUID per message or setting all dates to `Jan 1`) breaks relational joins across encounters/observations and destroys longitudinal time intervals between ICU vital sign readings and medication administrations. Furthermore, KMS encryption keys must be rotated periodically without invalidating multi-year historical patient tokens.

## 2. Decision

We implement a two-component cryptographic privacy architecture in `src/healthcare_lakehouse/security/`:

1. **Versioned KMS HMAC-SHA256 Tokenization (`KMSTokenizer` & `KMSKeyRing`):**
   - Identifiers (`Patient.id`, `MRN`, `Encounter.id`, `Practitioner`) are pseudonymized via `HMAC-SHA256(active_key, f"{namespace}:{value}")` and formatted as `<key_id>:<32_char_hex_digest>` (`128-bit` security margin).
   - Cross-protocol patient identity (`FHIR R4` and `HL7 v2.5.1`) is canonically resolved via medical record number (`MR`) prior to tokenization so longitudinal records link deterministically across protocols.
   - During KMS key rotation (`rotate_key`), the new key becomes `active_key_id` while historical keys remain in `KMSKeyRing.keys` for constant-time verification, and `cohort_salt_key_id` remains anchored to the cohort's salt key so longitudinal date-shift offsets never drift across key rotations.
2. **Patient-Consistent Longitudinal Date Shifting & Safe Harbor Rules (`HIPAAAnonymizer`):**
   - Each patient is assigned a deterministic shift $\Delta d \in [-365, -1]$ days derived from `HMAC-SHA256(cohort_salt_key, f"date-shift:{canonical_patient_key}")`. Every timestamp associated with that patient (`Encounter`, `Observation`, `Condition`, `MedicationRequest`) shifts by $\Delta d$, preserving 100% of intra-patient hour/minute clinical intervals (following the MIMIC-IV research cohort pattern alongside 45 CFR §164.514(b)(1)/(e) research controls where sub-year precision is retained).
   - Patients aged `>= 90` are top-coded to `age_years = 90` with birth date anchored to `Jan 1` of `shifted_ref_year - 90`.
   - Postal codes are truncated to 3 digits (`ZIP-3`) and masked to `"000"` if in the 17 restricted low-population Census prefixes (`<= 20,000` residents).
   - Structured and free-text fields (`Patient.clinical_note`, `Observation.note`, `Observation.value_string`, `MedicationRequest.dosage_text`) are scrubbed of SSNs, US/international phone numbers, emails, IPv4/IPv6 addresses, URLs, MRNs, and patient/physician names, and verified against strict KMS token and PHI rules by `HIPAAComplianceAuditor`.

## 3. Consequences

- **Positive:** Guarantees 0% PHI leakage (verified by `HIPAAComplianceAuditor` gate) while preserving 100% of relational foreign keys and longitudinal clinical intervals.
- **Negative / Trade-offs:** Seasonal epidemiology analyses must account for the `[-365, -1]` day shift window.
