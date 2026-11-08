"""Domain models for HL7 FHIR R4 resources and Medallion schemas."""

from __future__ import annotations

from healthcare_lakehouse.models.fhir_resources import (
    FHIRAddress,
    FHIRBundle,
    FHIRBundleEntry,
    FHIRCodeableConcept,
    FHIRCoding,
    FHIRCondition,
    FHIRContactPoint,
    FHIREncounter,
    FHIRHumanName,
    FHIRIdentifier,
    FHIRMedicationRequest,
    FHIRObservation,
    FHIRPatient,
    FHIRQuantity,
)

__all__: list[str] = [
    "FHIRAddress",
    "FHIRBundle",
    "FHIRBundleEntry",
    "FHIRCodeableConcept",
    "FHIRCoding",
    "FHIRCondition",
    "FHIRContactPoint",
    "FHIREncounter",
    "FHIRHumanName",
    "FHIRIdentifier",
    "FHIRMedicationRequest",
    "FHIRObservation",
    "FHIRPatient",
    "FHIRQuantity",
]
