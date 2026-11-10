"""Stateful Royal College of Physicians NEWS2 & qSOFA clinical deterioration engine."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from healthcare_lakehouse.models.fhir_resources import FHIRBundle

_VALID_ACVPU_CODES: frozenset[str] = frozenset({"A", "C", "V", "P", "U"})


class VitalSignSnapshot(BaseModel):
    """Normalized physiological vital signs snapshot for NEWS2 and qSOFA evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    respiratory_rate: float = 16.0
    spo2_percent: float = 98.0
    inhaled_o2_percent: float = 21.0
    systolic_bp: float = 120.0
    heart_rate: float = 75.0
    temperature_celsius: float = 37.0
    lactate_mmol_l: float = 1.0
    acvpu_consciousness: str = "A"


class ClinicalDeteriorationAlert(BaseModel):
    """Sub-second clinical deterioration scoring result for Gold telemetry alerting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    patient_token: str
    encounter_token: str
    evaluated_at: datetime
    news2_score: int
    qsofa_score: int
    risk_level: Literal["LOW", "LOW_MEDIUM", "MEDIUM", "HIGH"]
    sepsis_suspected: bool
    recommended_response: str
    triggered_parameters: tuple[str, ...]


class ClinicalDeteriorationScorer:
    """Computes NEWS2 and qSOFA clinical acuity scores from de-identified FHIR R4 Bundles."""

    def evaluate_bundle(self, bundle: FHIRBundle) -> ClinicalDeteriorationAlert:
        """Extract latest physiological vitals from a FHIRBundle and compute acuity scores."""
        patients = bundle.patients()
        encounters = bundle.encounters()
        sorted_observations = sorted(
            bundle.observations(),
            key=lambda item: item.effective_datetime,
        )

        patient_token = (
            patients[0].id
            if patients
            else (sorted_observations[0].subject_id if sorted_observations else "UNKNOWN-PATIENT")
        )
        encounter_token = (
            encounters[0].id
            if encounters
            else (
                sorted_observations[0].encounter_id if sorted_observations else "UNKNOWN-ENCOUNTER"
            )
        )
        evaluated_at = bundle.timestamp

        rr = 16.0
        spo2 = 98.0
        fio2 = 21.0
        sbp = 120.0
        hr = 75.0
        temp = 37.0
        lactate = 1.0
        acvpu = "A"

        for obs in sorted_observations:
            evaluated_at = max(evaluated_at, obs.effective_datetime)
            loinc = obs.code.coding[0].code
            if obs.value_quantity is not None:
                val = obs.value_quantity.value
                if loinc == "9279-1":
                    rr = val
                elif loinc == "2708-6":
                    spo2 = val
                elif loinc == "3150-0":
                    fio2 = val
                elif loinc == "8480-6":
                    sbp = val
                elif loinc == "8867-4":
                    hr = val
                elif loinc == "8310-5":
                    temp = val
                elif loinc == "2524-7":
                    lactate = val
            elif loinc == "67775-7" and obs.value_string is not None:
                candidate_acvpu = obs.value_string.strip().upper()
                acvpu = candidate_acvpu if candidate_acvpu in _VALID_ACVPU_CODES else "A"

        snapshot = VitalSignSnapshot(
            respiratory_rate=rr,
            spo2_percent=spo2,
            inhaled_o2_percent=fio2,
            systolic_bp=sbp,
            heart_rate=hr,
            temperature_celsius=temp,
            lactate_mmol_l=lactate,
            acvpu_consciousness=acvpu,
        )
        return self.score_snapshot(
            snapshot=snapshot,
            patient_token=patient_token,
            encounter_token=encounter_token,
            evaluated_at=evaluated_at,
        )

    def score_snapshot(
        self,
        snapshot: VitalSignSnapshot,
        patient_token: str,
        encounter_token: str,
        evaluated_at: datetime,
    ) -> ClinicalDeteriorationAlert:
        """Score a VitalSignSnapshot according to NEWS2 and qSOFA clinical standards."""
        subscores: list[tuple[str, int]] = [
            ("respiratory_rate", self._score_respiratory_rate(snapshot.respiratory_rate)),
            ("spo2", self._score_spo2(snapshot.spo2_percent)),
            ("supplemental_o2", 2 if snapshot.inhaled_o2_percent > 21.0 else 0),
            ("systolic_bp", self._score_systolic_bp(snapshot.systolic_bp)),
            ("heart_rate", self._score_heart_rate(snapshot.heart_rate)),
            ("temperature", self._score_temperature(snapshot.temperature_celsius)),
            ("consciousness", 0 if snapshot.acvpu_consciousness == "A" else 3),
        ]

        news2_total = sum(score for _, score in subscores)
        has_single_red = any(score == 3 for _, score in subscores)
        triggered = tuple(f"{name}(+{score})" for name, score in subscores if score > 0)

        qsofa = (
            (1 if round(snapshot.respiratory_rate) >= 22 else 0)
            + (1 if round(snapshot.systolic_bp) <= 100 else 0)
            + (1 if snapshot.acvpu_consciousness != "A" else 0)
        )

        if news2_total >= 7 or qsofa >= 2:
            risk_level: Literal["LOW", "LOW_MEDIUM", "MEDIUM", "HIGH"] = "HIGH"
            response = "Immediate ICU / Critical Care Outreach rapid response activation."
        elif news2_total >= 5:
            risk_level = "MEDIUM"
            response = "Urgent assessment by acute care clinician within 30 minutes."
        elif has_single_red:
            risk_level = "LOW_MEDIUM"
            response = "Urgent ward-based medical review for extreme single parameter."
        else:
            risk_level = "LOW"
            response = "Continue routine bedside telemetry monitoring every 4-6 hours."

        sepsis_suspected = qsofa >= 2 or (news2_total >= 5 and snapshot.lactate_mmol_l >= 2.0)

        return ClinicalDeteriorationAlert(
            patient_token=patient_token,
            encounter_token=encounter_token,
            evaluated_at=evaluated_at,
            news2_score=news2_total,
            qsofa_score=qsofa,
            risk_level=risk_level,
            sepsis_suspected=sepsis_suspected,
            recommended_response=response,
            triggered_parameters=triggered,
        )

    @staticmethod
    def _score_respiratory_rate(rr: float) -> int:
        val = round(rr)
        if val <= 8 or val >= 25:
            return 3
        if val >= 21:
            return 2
        if val <= 11:
            return 1
        return 0

    @staticmethod
    def _score_spo2(spo2: float) -> int:
        val = round(spo2)
        if val <= 91:
            return 3
        if val <= 93:
            return 2
        if val <= 95:
            return 1
        return 0

    @staticmethod
    def _score_systolic_bp(sbp: float) -> int:
        val = round(sbp)
        if val <= 90 or val >= 220:
            return 3
        if val <= 100:
            return 2
        if val <= 110:
            return 1
        return 0

    @staticmethod
    def _score_heart_rate(hr: float) -> int:
        val = round(hr)
        if val <= 40 or val >= 131:
            return 3
        if val >= 111:
            return 2
        if val <= 50 or val >= 91:
            return 1
        return 0

    @staticmethod
    def _score_temperature(temp: float) -> int:
        val = round(temp, 1)
        if val <= 35.0:
            return 3
        if val >= 39.1:
            return 2
        if val <= 36.0 or val >= 38.1:
            return 1
        return 0
