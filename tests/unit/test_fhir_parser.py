"""Unit tests for the hierarchical HL7 FHIR R4 JSON and XML parser."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from healthcare_lakehouse.models.fhir_resources import FHIRBundle, FHIREncounter
from healthcare_lakehouse.parsers.fhir_parser import FHIRParser
from healthcare_lakehouse.synthetic.synthea_orchestrator import SyntheaOrchestrator


def test_fhir_parser_parses_json_str_bytes_and_dict() -> None:
    """Verify FHIRParser parses JSON dict, str, and UTF-8 bytes into FHIRBundle."""
    orchestrator = SyntheaOrchestrator(seed=42)
    source_bundle = orchestrator.simulate_patient_lifecycle(
        patient_index=0,
        module_name="sepsis_deterioration",
        force_critical_trajectory=True,
    )
    parser = FHIRParser()

    json_dict = source_bundle.to_fhir_json_dict()
    json_str = json.dumps(json_dict)
    json_bytes = json_str.encode("utf-8")

    from_dict = parser.parse_json_bundle(json_dict)
    from_str = parser.parse_json_bundle(json_str)
    from_bytes = parser.parse_json_bundle(json_bytes)

    assert from_dict.id == source_bundle.id
    assert from_str.id == source_bundle.id
    assert from_bytes.id == source_bundle.id

    summary = parser.extract_clinical_summary(from_str)
    assert summary["patients"] == 1
    assert summary["encounters"] == 1
    assert summary["observations"] == len(source_bundle.observations())
    assert summary["conditions"] == 1
    assert summary["medication_requests"] == 1


def test_fhir_parser_preserves_encounter_class_on_xml_roundtrip_and_blocks_xxe() -> None:
    """Verify standard FHIR R4 XML roundtrip preserves Encounter class/status and blocks DTD/XXE."""
    orchestrator = SyntheaOrchestrator(seed=42)
    imp_bundle = orchestrator.simulate_patient_lifecycle(
        patient_index=1,
        module_name="cardiopulmonary_chronic",
        force_critical_trajectory=False,
    )
    assert imp_bundle.encounters()[0].class_code == "IMP"

    xml_str = orchestrator.bundle_to_fhir_xml(imp_bundle)
    parser = FHIRParser()

    parsed_from_str = parser.parse_xml_bundle(xml_str)
    parsed_from_bytes = parser.parse_xml_bundle(xml_str.encode("utf-8"))

    assert parsed_from_str.id == imp_bundle.id
    assert parsed_from_bytes.id == imp_bundle.id
    assert parsed_from_str.encounters()[0].class_code == "IMP"
    assert parsed_from_str.encounters()[0].status == imp_bundle.encounters()[0].status
    assert parsed_from_str.encounters()[0].period_end == imp_bundle.encounters()[0].period_end
    assert parsed_from_str.patients()[0].ssn == imp_bundle.patients()[0].ssn
    assert len(parsed_from_str.observations()) == len(imp_bundle.observations())
    assert len(parsed_from_str.conditions()) == 1
    assert len(parsed_from_str.medication_requests()) == 1

    # Also roundtrip critical sepsis bundle with string ACVPU observation
    sepsis_bundle = orchestrator.simulate_patient_lifecycle(
        patient_index=0,
        module_name="sepsis_deterioration",
        force_critical_trajectory=True,
    )
    sepsis_xml = orchestrator.bundle_to_fhir_xml(sepsis_bundle)
    parsed_sepsis = parser.parse_xml_bundle(sepsis_xml)
    assert any(o.value_string == "C" for o in parsed_sepsis.observations())

    # Reject XML payloads containing DOCTYPE or ENTITY declarations
    malicious_xml = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        '<Bundle xmlns="http://hl7.org/fhir"><id value="b1"/></Bundle>'
    )
    with pytest.raises(ValueError, match="Unsafe XML declaration"):
        parser.parse_xml_bundle(malicious_xml)

    # Test compact/legacy XML fallback elements (<periodStart>, attribute <coding/>, etc.)
    custom_xml = """
    <Bundle xmlns="http://hl7.org/fhir">
      <id value="bundle-custom-xml"/>
      <type value="collection"/>
      <timestamp value="2026-06-15T10:00:00+00:00"/>
      <entry>
        <fullUrl value="urn:uuid:pat-1"/>
        <resource>
          <Patient>
            <id value="pat-1"/>
            <gender value="female"/>
            <birthDate value="1980-01-01"/>
            <extension url="http://example.org/ext/unknown">
              <valueString value="ignored"/>
            </extension>
          </Patient>
          <UnknownResource/>
        </resource>
      </entry>
      <entry>
        <resource>
          <Encounter>
            <id value="enc-1"/>
            <subject reference="Patient/pat-1"/>
            <periodStart value="2026-06-15T10:00:00+00:00"/>
          </Encounter>
        </resource>
      </entry>
      <entry>
        <resource>
          <Observation>
            <id value="obs-1"/>
            <subject reference="Patient/pat-1"/>
            <encounter reference="Encounter/enc-1"/>
            <effectiveDateTime value="2026-06-15T10:05:00+00:00"/>
            <code>
              <text value="HR"/>
              <coding system="http://loinc.org" code="8867-4" display="Heart rate"/>
            </code>
            <valueQuantity value="78.0" unit="/min"/>
            <note text="compact note"/>
          </Observation>
        </resource>
      </entry>
      <entry>
        <resource>
          <Observation>
            <id value="obs-2"/>
            <subject reference="Patient/pat-1"/>
            <encounter reference="Encounter/enc-1"/>
            <effectiveDateTime value="2026-06-15T10:06:00+00:00"/>
            <valueString value="uncoded observation"/>
          </Observation>
        </resource>
      </entry>
      <entry>
        <resource>
          <Condition>
            <id value="cond-1"/>
            <subject reference="Patient/pat-1"/>
            <encounter reference="Encounter/enc-1"/>
            <onsetDateTime value="2026-06-15T10:00:00+00:00"/>
            <coding system="http://hl7.org/fhir/sid/icd-10-cm" code="A41.9" display="Sepsis"/>
          </Condition>
        </resource>
      </entry>
      <entry>
        <resource>
          <MedicationRequest>
            <id value="med-1"/>
            <subject reference="Patient/pat-1"/>
            <encounter reference="Encounter/enc-1"/>
            <authoredOn value="2026-06-15T10:10:00+00:00"/>
            <coding system="http://rxnorm" code="11124" display="Vancomycin"/>
            <dosageText value="1000 mg IV"/>
          </MedicationRequest>
        </resource>
      </entry>
    </Bundle>
    """
    custom_bundle = parser.parse_xml_bundle(custom_xml)
    assert custom_bundle.encounters()[0].facility_id == "FAC-BOS-GEN-01"
    assert custom_bundle.observations()[0].note == "compact note"
    assert custom_bundle.observations()[1].code.coding[0].code == "8867-4"
    assert custom_bundle.conditions()[0].code.coding[0].code == "A41.9"
    assert custom_bundle.medication_requests()[0].dosage_text == "1000 mg IV"

    # Also serialize an in-progress Encounter with period_end=None and attending_physician=None
    open_enc_bundle = FHIRBundle(
        id="bundle-open-enc",
        timestamp=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        entries=(
            FHIREncounter(
                id="enc-open",
                subject_id="pat-1",
                status="in-progress",
                period_start=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
                period_end=None,
                attending_physician=None,
            ),
        ),
    )
    open_enc_xml = orchestrator.bundle_to_fhir_xml(open_enc_bundle)
    parsed_open = parser.parse_xml_bundle(open_enc_xml)
    assert parsed_open.encounters()[0].period_end is None
    assert parsed_open.encounters()[0].attending_physician is None

    with pytest.raises(ValueError, match="Expected XML root <Bundle>"):
        parser.parse_xml_bundle("<Patient xmlns='http://hl7.org/fhir'><id value='p1'/></Patient>")
