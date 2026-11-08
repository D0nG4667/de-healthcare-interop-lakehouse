# Deployment & Operations Runbook — `de-healthcare-interop-lakehouse`

> **Operational Scope:** Local Containerized Lakehouse Deployment (Docker Compose Specification `compose.yaml` + Multi-Stage BuildKit `Dockerfile` + MinIO S3), Production Cloud Deployment (AWS S3 + KMS + Spark/EMR), KMS Key Rotation Ceremonies, and Epidemic Surge Playbooks.

---

## 1. Containerized Deployment (Multi-Stage `Dockerfile` & Canonical `compose.yaml`)

The repository follows the official **Docker Compose Specification** using the canonical [`compose.yaml`](../../compose.yaml) filename (preferred over legacy `docker-compose.yml`), paired with a BuildKit-optimized [`Dockerfile`](../../Dockerfile) and [`.dockerignore`](../../.dockerignore):

### Multi-Stage `Dockerfile` Architecture
1. **`builder` Stage (`ghcr.io/astral-sh/uv:python3.12-bookworm-slim`):**
   - Uses two-phase BuildKit cache and bind mounts (`--mount=type=cache,target=/root/.cache/uv`, `--mount=type=bind,source=uv.lock,target=uv.lock`) with `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, and `UV_PYTHON_DOWNLOADS=0` so dependency layers remain cached across source edits.
2. **`qa` Stage (CI / Quality Assurance Target):**
   - Extends `builder` with `--dev` dependencies, runs as non-root `lakehouse` (`UID=10001`), and executes `pytest --cov=src/healthcare_lakehouse --cov-branch --cov-fail-under=100`.
3. **`runtime` Stage (`python:3.12-slim-bookworm` — Zero `uv` / Zero Dev Tools):**
   - Copies only the compiled `/app/.venv` from `builder` (`COPY --from=builder --chown=lakehouse:lakehouse /app /app`), runs as unprivileged `USER lakehouse` (`UID=10001`, `/usr/sbin/nologin`), sets OCI metadata labels, and includes a container `HEALTHCHECK`.

### Canonical `compose.yaml` Services & Hardening
1. **`minio-s3`:** Pinned release (`minio/minio:RELEASE.2025-02-18T16-25-55Z`) with native `mc ready local` `healthcheck`.
2. **`lakehouse-pipeline`:** Targets `runtime`, waits for `minio-s3` via long-syntax `depends_on` (`condition: service_healthy`), and enforces `read_only: true`, `cap_drop: [ALL]`, and `security_opt: [no-new-privileges:true]`.
3. **`lakehouse-qa`:** Targets `qa` under `profiles: ["qa", "test"]` for isolated containerized verification.

```bash
# 1. Build and run the production Medallion pipeline against healthy MinIO S3
docker compose up --build --abort-on-container-exit

# 2. Run the containerized QA & 100% coverage suite via the 'qa' Compose profile
docker compose --profile qa run --rm lakehouse-qa
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
1. **Fail-Closed Halt:** `assert_bundle_compliant` immediately raises `HIPAAComplianceError` *in memory* before `_write_silver_tables` is invoked—guaranteeing zero contaminated bytes are written to Silver or Gold Parquet files.
2. **Quarantine & Alert:** The offending Bronze `envelope_id` is logged (without printing raw PHI to stdout logs) so platform engineers can update the parser or regex scrubber rule and replay from Bronze.
