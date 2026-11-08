# Deployment & Operations Runbook — `de-healthcare-interop-lakehouse`

> **Operational Scope:** Local Containerized Lakehouse Deployment (Docker Compose + MinIO S3), Production Cloud Deployment (AWS S3 + KMS + Spark/EMR), KMS Key Rotation Ceremonies, and Epidemic Surge Playbooks.

---

## 1. Containerized Deployment (Docker & Docker Compose)

The repository includes a multi-stage production [`Dockerfile`](../../Dockerfile) and [`docker-compose.yml`](../../docker-compose.yml) that spin up:
1. **`minio-s3`:** Local S3-compatible object storage for Bronze, Silver, and Gold zones.
2. **`lakehouse-pipeline`:** Executes the end-to-end synthetic clinical simulation, Bronze/Silver/Gold Medallion transformation, and HIPAA Safe Harbor Zero-PHI verification gate.
3. **`lakehouse-qa`:** Runs the full `ruff`, `mypy --strict`, and `pytest --cov-fail-under=100` verification suite inside the immutable container image.

```bash
# Build and run the complete containerized pipeline and QA suite
docker compose up --build --abort-on-container-exit
```

---

## 2. Production AWS Cloud Reference Architecture

In production hospital deployments, the Medallion zones map to isolated AWS KMS-encrypted S3 buckets with strict IAM boundary policies:

| Medallion Zone | S3 Bucket / Prefix | KMS Key Policy | Access Control |
| :--- | :--- | :--- | :--- |
| **Bronze (Raw PHI)** | `s3://prod-hc-lakehouse-bronze-phi/` | `alias/hc-bronze-phi-cmk` | Write-only by Ingestion Gateway; Read-only by Silver Anonymizer IAM Role; **0 human/analyst access**. |
| **Silver (HIPAA Safe Harbor)** | `s3://prod-hc-lakehouse-silver-clean/` | `alias/hc-silver-analytics-cmk` | Populated exclusively after `HIPAAComplianceAuditor.assert_bundle_compliant` passes with 0 violations. |
| **Gold (Alerts & Cohorts)** | `s3://prod-hc-lakehouse-gold-research/` | `alias/hc-gold-research-cmk` | Read access for ICU Clinical Decision Support dashboards, Athena/Trino/Spark SQL, and research cohorts. |

---

## 3. Standard Operating Procedure: KMS Key Rotation Ceremony

To comply with **45 CFR §164.312(a)(2)(iv)** cryptographic key management standards, the HMAC tokenization key is rotated quarterly or annually using [`KMSTokenizer.rotate_key`](../../src/healthcare_lakehouse/security/kms_tokenizer.py):

1. **Provision New KMS Key Version:** Generate a new 256-bit secret key in AWS KMS / Secrets Manager with version identifier `kms-hipaa-key-2027-v2`.
2. **Update Active Key Ring:** Register `kms-hipaa-key-2027-v2` as `active_key_id` in `KMSKeyRing` while keeping `kms-hipaa-key-2026-v1` in `KMSKeyRing.keys`.
3. **Backward Verification:** Because every Silver/Gold token embeds its key version prefix (`kms-hipaa-key-2026-v1:<hmac>`), `KMSTokenizer.verify_token(...)` seamlessly validates both `v1` and `v2` tokens during the transition window without downtime.
4. **Scheduled Re-Keying Compaction:** During a low-traffic maintenance window, run a background Silver/Gold compaction job that re-tokens `v1` foreign keys to `v2`.

---

## 4. Incident Response: HIPAA Gate Failure (`HIPAAComplianceError`)

If `HIPAAComplianceAuditor` detects any unmasked PHI in a candidate Silver bundle:
1. **Fail-Closed Halt:** `assert_bundle_compliant` immediately raises `HIPAAComplianceError` *in memory* before ` _write_silver_tables` is invoked—guaranteeing zero contaminated bytes are written to Silver or Gold Parquet files.
2. **Quarantine & Alert:** The offending Bronze `envelope_id` is logged (without printing raw PHI to stdout logs) so platform engineers can update the parser or regex scrubber rule and replay from Bronze.
