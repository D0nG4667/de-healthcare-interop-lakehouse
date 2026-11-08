# Rule 05: Synthetic Clinical Data Generation Strategy (Synthea™ & HL7 v2)

## Scope
Applies to `src/healthcare_lakehouse/synthetic/` and all test fixtures.

## Data Generation Mandate

1. **No Naive Faker Loops:**
   - Do NOT use flat, stateless random loops that generate uncorrelated strings or impossible vital signs.
   - Clinical pipelines require **multi-resource relational integrity**, **longitudinal time-series sequential consistency**, and **valid medical coding systems**.

2. **Option 1 — Synthea™ State-Machine Patient Lifecycles (`synthea_orchestrator.py`):**
   - Driven by declarative Synthea™-compatible JSON disease modules stored in `src/healthcare_lakehouse/synthetic/modules/`:
     - `sepsis_deterioration_module.json`: Models infection onset -> systemic inflammatory response -> progressive tachypnea, hypoxia, hypotension, tachycardia, fever, and hyperlactatemia -> ICU admission -> broad-spectrum IV antibiotics (`Vancomycin` / `Piperacillin-Tazobactam`) -> recovery or critical alert.
     - `cardiopulmonary_chronic_module.json`: Models chronic hypertension and COPD progression -> baseline outpatient encounters -> acute exacerbation -> bronchodilator/corticosteroid therapy.
   - Every synthesized `FHIRBundle` preserves strict referential integrity (`Observation.subject` -> `Patient.id`, `Observation.encounter` -> `Encounter.id`, `MedicationRequest.subject` -> `Patient.id`) and authentic **LOINC** (`8867-4` Heart rate, `9279-1` Respiratory rate, `2708-6` SpO2, `8480-6` Systolic BP, `8462-4` Diastolic BP, `8310-5` Body temp, `2524-7` Lactate), **SNOMED-CT**, **ICD-10-CM**, and **RxNorm** codes.

3. **Option 2 — Bedside HL7 v2.5.1 Pipe-Delimited Telemetry (`hl7v2_simulator.py`):**
   - Generates standards-compliant HL7 v2.5.1 messages (`ADT^A01`, `ADT^A03`, `ADT^A08`, `ORU^R01`) with valid `MSH`, `PID`, `PV1`, `OBR`, `OBX`, and `DG1` segments corresponding to the synthesized patient lifecycle states.
   - Includes realistic embedded synthetic PHI (synthetic SSNs, MRNs, street addresses, phone numbers, emails, attending physician notes) specifically designed to test and verify the HIPAA Safe Harbor de-identification and scrubbing gates.
