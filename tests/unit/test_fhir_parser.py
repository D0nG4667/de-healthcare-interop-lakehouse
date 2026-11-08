"""Unit tests for the hierarchical HL7 FHIR R4 JSON and XML parser."""

from __future__ import annotations

import json

import pytest

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


def test_fhir_parser_parses_xml_str_and_bytes_and_handles_invalid_xml() -> None:
    """Verify FHIRParser parses FHIR R4 XML bundles (str and bytes) and rejects invalid roots."""
    orchestrator = SyntheaOrchestrator(seed=42)
    source_bundle = orchestrator.simulate_patient_lifecycle(
        patient_index=0,
        module_name="sepsis_deterioration",
        force_critical_trajectory=True,
    )
    xml_str = orchestrator.bundle_to_fhir_xml(source_bundle)
    parser = FHIRParser()

    parsed_from_str = parser.parse_xml_bundle(xml_str)
    parsed_from_bytes = parser.parse_xml_bundle(xml_str.encode("utf-8"))

    assert parsed_from_str.id == source_bundle.id
    assert parsed_from_bytes.id == source_bundle.id
    assert len(parsed_from_str.patients()) == 1
    assert parsed_from_str.patients()[0].ssn == source_bundle.patients()[0].ssn
    assert len(parsed_from_str.encounters()) == 1
    assert len(parsed_from_str.observations()) == len(source_bundle.observations())
    assert len(parsed_from_str.conditions()) == 1
    assert len(parsed_from_str.medication_requests()) == 1

    # Test XML with <fullUrl>, unknown extension, <code><text/>, and default facilityId
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
            <valueString value="normal"/>
          </Observation>
        </resource>
      </entry>
    </Bundle>
    """
    custom_bundle = parser.parse_xml_bundle(custom_xml)
    assert custom_bundle.encounters()[0].facility_id == "FAC-BOS-GEN-01"
    assert custom_bundle.observations()[0].value_string == "normal"

    with pytest.raises(ValueError, match="Expected XML root <Bundle>"):
        parser.parse_xml_bundle("<Patient xmlns='http://hl7.org/fhir'><id value='p1'/></Patient>")
