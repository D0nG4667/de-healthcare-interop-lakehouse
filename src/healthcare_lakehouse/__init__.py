"""Enterprise Healthcare Clinical Interoperability Medallion Lakehouse.

Provides end-to-end ingestion, normalization, HIPAA Safe Harbor 18-identifier
de-identification, KMS HMAC-SHA256 envelope tokenization, stateful NEWS2/qSOFA
clinical deterioration scoring, and Bronze/Silver/Gold Parquet storage for
real-time HL7 v2.5.1 and Synthea-orchestrated HL7 FHIR R4 clinical streams.
"""

from __future__ import annotations

__version__: str = "1.0.0"
__all__: list[str] = ["__version__"]
