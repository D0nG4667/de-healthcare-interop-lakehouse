"""Stateful Royal College of Physicians NEWS2 & qSOFA clinical deterioration engine."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from healthcare_lakehouse.models.fhir_resources import FHIRBundle


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
        patient_token = bundle.patients()[0].id
        encounters = bundle.encounters()
        encounter_token = encounters[0].id
        evaluated_at = bundle.timestamp

        rr = 16.0
        spo2 = 98.0
        fio2 = 21.0
        sbp = 120.0
        hr = 75.0
        temp = 37.0
        lactate = 1.0
        acvpu = "A"

        for obs in bundle.observations():
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
            else:
                acvpu = (obs.value_string or "A").strip().upper()

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
            (1 if snapshot.respiratory_rate >= 22.0 else 0)
            + (1 if snapshot.systolic_bp <= 100.0 else 0)
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
        if rr <= 8.0 or rr >= 25.0:
            return 3
        if rr >= 21.0:
            return 2
        if rr <= 11.0:
            return 1
        return 0

    @staticmethod
    def _score_spo2(spo2: float) -> int:
        if spo2 <= 91.0:
            return 3
        if spo2 <= 93.0:
            return 2
        if spo2 <= 95.0:
            return 1
        return 0

    @staticmethod
    def _score_systolic_bp(sbp: float) -> int:
        if sbp <= 90.0 or sbp >= 220.0:
            return 3
        if sbp <= 100.0:
            return 2
        if sbp <= 110.0:
            return 1
        return 0

    @staticmethod
    def _score_heart_rate(hr: float) -> int:
        if hr <= 40.0 or hr >= 131.0:
            return 3
        if hr >= 111.0:
            return 2
        if hr <= 50.0 or hr >= 91.0:
            return 1
        return 0

    @staticmethod
    def _score_temperature(temp: float) -> int:
        if temp <= 35.0:
            return 3
        if temp >= 39.1:
            return 2
        if temp <= 36.0 or temp >= 38.1:
            return 1
        return 0
