# ADR-003: Legacy HL7 v2.5.1 Pipe-Delimited to Canonical HL7 FHIR R4 Translation

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Principal Forward-Deployed Data Engineer, Clinical Integration Team
- **Refs:** HL7 v2.5.1 Messaging Standard, HL7 FHIR R4 (v4.0.1)

---

## 1. Context

Hospital bedside telemetry monitors and legacy EHR ADT feeds transmit clinical events as pipe-delimited HL7 v2.5.1 messages (`ADT^A01`, `ADT^A08`, `ORU^R01`) framed in Minimal Lower Layer Protocol (`MLLP`, `0x0B .. 0x1C0D`), whereas modern cloud clinical repositories and research schemas operate on HL7 FHIR R4 resources. Maintaining separate downstream de-identification and scoring pipelines for HL7 v2 and FHIR R4 would duplicate compliance logic and risk inconsistent PHI masking.

## 2. Decision

We implement a canonical **Legacy-to-FHIR R4 Protocol Translator (`HL7v2Parser.translate_to_fhir_bundle`)** at the Bronze-to-Silver boundary:

- Strip MLLP framing bytes (`0x0B` start block and `0x1C0D` end block) automatically.
- Normalize `MSH` 1-based field indexing (`MSH-1 = "|"`, `MSH-2 = "^~\\&"`).
- Map `PID` → `FHIRPatient`, `PV1` → `FHIREncounter`, `OBX` (`NM` numeric and `ST` string) → `FHIRObservation` (preserving LOINC and UCUM codes), and `DG1` → `FHIRCondition` (preserving ICD-10-CM codes).
- Emit a canonical `FHIRBundle` identical in type and structure to bundles parsed by `FHIRParser` (`JSON` and `XML`).

## 3. Consequences

- **Positive:** Downstream `HIPAAAnonymizer`, `HIPAAComplianceAuditor`, `ClinicalDeteriorationScorer`, and Silver/Gold Parquet writers operate on a single unified `FHIRBundle` domain model regardless of whether the source was HL7 v2 MLLP, FHIR JSON, or FHIR XML.
- **Negative / Trade-offs:** Custom Z-segments in proprietary hospital HL7 v2 feeds must be mapped explicitly if added in future extensions.
