# HIPAA Compliance & Data Governance Specification

> **Regulatory Standard:** 45 CFR §164.514(b)(2) (HIPAA Safe Harbor Method) & 45 CFR §164.312 (HIPAA Security Rule Technical Safeguards)  
> **Enforcing Modules:** [`src/healthcare_lakehouse/security/hipaa_anonymizer.py`](../../src/healthcare_lakehouse/security/hipaa_anonymizer.py), [`src/healthcare_lakehouse/security/kms_tokenizer.py`](../../src/healthcare_lakehouse/security/kms_tokenizer.py)

---

## 1. Complete 18 HIPAA Safe Harbor Identifiers Mapping Matrix

Every record transitioning from the **Bronze Zone** to the **Silver Zone** is transformed by `HIPAAAnonymizer` and audited by `HIPAAComplianceAuditor` across all 18 statutory identifiers:

| # | HIPAA Safe Harbor Identifier (45 CFR §164.514(b)(2)(i)) | FHIR R4 / HL7 v2 Source Field | De-Identification Control Applied | Verification Audit Check |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Names** | `Patient.name`, `PID-5`, `PV1-7` (Attending MD), Notes | Patient family/given replaced with `REDACTED` / `ANONYMIZED`; Practitioner tokenized (`practitioner:<hmac>`); names scrubbed from notes | Asserts `name.family == "REDACTED"` and no patient name tokens remain in notes |
| **2** | **Geographic subdivisions smaller than a State** | `Patient.address` (`line`, `city`, `postalCode`), `PID-11` | `line` & `city` redacted; `state` preserved; `postalCode` truncated to first 3 digits (`ZIP-3`) or `"000"` if in the 17 restricted low-population prefixes (`<= 20,000` residents) | Asserts `len(postal_code) == 3` and `postal_code not in HIPAA_RESTRICTED_ZIP3_PREFIXES` |
| **3** | **All elements of dates (except year) & Ages > 89** | `Patient.birthDate`, `PID-7`, `Encounter.period`, `Observation.effectiveDateTime`, `Condition.onsetDateTime`, `MedicationRequest.authoredOn` | Clinical timestamps shifted by deterministic patient offset $\Delta d \in [-365, -1]$ days; birth dates normalized to `YYYY-01-01`; patients aged `>= 90` top-coded to `age_years = 90` and `birth_date = (ref_year - 90)-01-01` | Asserts `birth_date.month == 1`, `birth_date.day == 1`, and `age_years <= 90` |
| **4** | **Telephone numbers** | `Patient.telecom[system=phone]`, `PID-13`, Notes | Stripped from `telecom`; scrubbed via `_PHONE_REGEX` in notes | Asserts `len(telecom) == 0` and zero phone regex matches |
| **5** | **Fax numbers** | `Patient.telecom[system=fax]`, Notes | Stripped from `telecom`; scrubbed via `_PHONE_REGEX` in notes | Asserts `len(telecom) == 0` |
| **6** | **Electronic mail addresses** | `Patient.telecom[system=email]`, Notes | Stripped from `telecom`; scrubbed via `_EMAIL_REGEX` in notes | Asserts zero `_EMAIL_REGEX` matches |
| **7** | **Social Security numbers** | `Patient.ssn` extension, `PID-19`, Notes | Set to `None` on `FHIRPatient`; scrubbed via `_SSN_REGEX` (`\b\d{3}-\d{2}-\d{4}\b`) in notes | Asserts `patient.ssn is None` and zero `_SSN_REGEX` matches |
| **8** | **Medical record numbers (MRNs)** | `Patient.identifier`, `PID-3`, Notes | Tokenized via `KMSTokenizer.tokenize(mrn, namespace="mrn")`; scrubbed via `_MRN_REGEX` in notes | Asserts `":" in identifier.value` and zero raw `MRN-\d+` in notes |
| **9** | **Health plan beneficiary numbers** | `Patient.identifier` | Tokenized via `KMSTokenizer` | Asserts all identifiers carry `<kid>:<hmac>` format |
| **10** | **Account numbers** | `Encounter.id`, `PV1-19` | Tokenized via `KMSTokenizer.tokenize(enc_id, namespace="encounter")` | Asserts `":" in encounter.id` |
| **11** | **Certificate/license numbers** | `Encounter.attending_physician` (`NPI`) | Tokenized via `KMSTokenizer.tokenize(md, namespace="practitioner")` | Verified pseudonymized |
| **12** | **Vehicle identifiers & serial numbers** | Free-text clinical notes | Redacted during note normalization | Audited via compliance gate |
| **13** | **Device identifiers & serial numbers** | Bedside monitor serials / device metadata | Stripped prior to Silver projection | Verified absent in Silver schema |
| **14** | **Web Universal Resource Locators (URLs)** | `Patient.telecom[system=url]`, Notes | Stripped from `telecom`; scrubbed via `_URL_REGEX` in notes | Asserts zero `https?://` matches |
| **15** | **Internet Protocol (IP) addresses** | `Patient.device_ip` extension, Notes | Set to `None`; scrubbed via `_IPV4_REGEX` in notes | Asserts `patient.device_ip is None` and zero IPv4 matches |
| **16** | **Biometric identifiers** | Excluded at schema level | Forbidden by `ConfigDict(extra="forbid")` | Schema-enforced |
| **17** | **Full-face photographs** | Excluded at schema level | Forbidden by `ConfigDict(extra="forbid")` | Schema-enforced |
| **18** | **Any other unique identifying number or code** | `Patient.id`, `Observation.id`, `Condition.id`, `MedicationRequest.id` | Deterministically tokenized via `KMSTokenizer` (`<kid>:<hmac>`) | Asserts `":" in patient.id` |

---

## 2. Restricted Low-Population 3-Digit ZIP Prefixes (`<= 20,000` Residents)

Per 45 CFR §164.514(b)(2)(i)(B), the initial 3 digits of a ZIP code must be replaced with `"000"` if the geographic unit formed by combining all ZIP codes with those 3 initial digits contains `20,000` or fewer people according to the US Bureau of the Census:

```text
036, 059, 063, 102, 203, 556, 692, 790, 821, 823, 830, 831, 878, 879, 884, 890, 893
```
Defined as an immutable `frozenset[str]` (`HIPAA_RESTRICTED_ZIP3_PREFIXES`) in [`src/healthcare_lakehouse/config/settings.py`](../../src/healthcare_lakehouse/config/settings.py).
