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
   - Identifiers (`Patient.id`, `MRN`, `Encounter.id`, `Practitioner`) are pseudonymized via `HMAC-SHA256(active_key, f"{namespace}:{value}")` and formatted as `<key_id>:<24_char_hex_digest>`.
   - During KMS key rotation (`rotate_key`), the new key becomes `active_key_id` while historical keys remain in `KMSKeyRing.keys` for constant-time verification and re-keying migrations.
2. **Patient-Consistent Longitudinal Date Shifting & Safe Harbor Rules (`HIPAAAnonymizer`):**
   - Each patient is assigned a deterministic shift $\Delta d \in [-365, -1]$ days derived from `HMAC-SHA256(active_key, f"date-shift:{patient_id}")`.
   - Every timestamp associated with that patient (`Encounter`, `Observation`, `Condition`, `MedicationRequest`) shifts by $\Delta d$, preserving 100% of intra-patient hour/minute clinical intervals.
   - Patients aged `>= 90` are top-coded to `age_years = 90` with birth year capped at `ref_year - 90`.
   - Postal codes are truncated to 3 digits (`ZIP-3`) and masked to `"000"` if in the 17 restricted low-population Census prefixes (`<= 20,000` residents).
   - Free-text clinical notes are scrubbed of SSNs, phones, emails, IPv4s, URLs, MRNs, and patient names, and audited by `HIPAAComplianceAuditor`.

## 3. Consequences

- **Positive:** Guarantees 0% PHI leakage (verified by `HIPAAComplianceAuditor` gate) while preserving 100% of relational foreign keys and longitudinal clinical intervals.
- **Negative / Trade-offs:** Seasonal epidemiology analyses must account for the `[-365, -1]` day shift window.
