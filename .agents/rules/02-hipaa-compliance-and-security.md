# Rule 02: HIPAA Safe Harbor De-Identification & KMS Security

## Scope
Applies to `src/healthcare_lakehouse/security/`, all Lakehouse persistence layers, logging, and Git commits.

## Mandatory Security & Privacy Controls

1. **Complete 18 HIPAA Safe Harbor Identifiers (45 CFR §164.514(b)(2)):**
   Every clinical record transitioning from Bronze to Silver MUST strip, mask, or cryptographically pseudonymize all 18 identifiers:
   1. Names (`family`, `given`, `prefix`, `suffix`, full text names)
   2. Geographic subdivisions smaller than a State (street address, city, county, precinct, and ZIP code except initial 3 digits when population `> 20,000`)
   3. All elements of dates (except year) directly related to an individual (birth, admission, discharge, death) and ages `> 89`
   4. Telephone numbers
   5. Fax numbers
   6. Electronic mail addresses
   7. Social Security numbers (SSNs)
   8. Medical record numbers (MRNs)
   9. Health plan beneficiary numbers
   10. Account numbers
   11. Certificate/license numbers
   12. Vehicle identifiers and serial numbers, including license plates
   13. Device identifiers and serial numbers
   14. Web Universal Resource Locators (URLs)
   15. Internet Protocol (IP) address numbers
   16. Biometric identifiers, including finger and voice prints
   17. Full-face photographic images and any comparable images
   18. Any other unique identifying number, characteristic, or code

2. **KMS Key-Ring & Envelope Tokenization:**
   - Never hardcode production KMS master keys in source files.
   - Support key rotation via `KMSKeyRing` containing an `active_key_id` and historical key versions (`keys: dict[str, bytes]`), enabling verification of historical tokens and re-tokenization during key rotation ceremonies.

3. **Automated Zero-PHI Gate:**
   - `HIPAAComplianceAuditor.audit_patient_record(...)` and `audit_bundle(...)` must inspect anonymized structures and free-text notes against SSN, phone, email, IPv4, URL, raw MRN, unshifted birth date, restricted ZIP-3, and age `>= 90` rules, raising a `HIPAAComplianceError` or returning a detailed audit failure if any identifier leaks.
