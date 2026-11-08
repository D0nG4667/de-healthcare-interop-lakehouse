# Enterprise Gitflow, Branching & Worktree Governance

> **Governance Standard:** Protected Multi-Environment Promotion (`feature/*` → `develop` → `staging` → `main`) with Automated Lefthook Pre-Commit/Pre-Push Gates and GitHub Actions CI/CD.

---

## 1. Branch Promotion Topology

```mermaid
gitGraph
    commit id: "46c9b88 Initial commit"
    branch develop
    checkout develop
    branch staging
    checkout develop
    branch feature/project-scaffolding-and-agent-rules
    commit id: "chore(scaffold): tooling & rules"
    checkout develop
    merge feature/project-scaffolding-and-agent-rules id: "Merge scaffold -> develop"
    branch feature/clinical-domain-and-synthea-generator
    commit id: "feat(synthetic): FHIR R4 & Synthea"
    checkout develop
    merge feature/clinical-domain-and-synthea-generator id: "Merge synthetic -> develop"
    branch feature/hl7-fhir-parser-and-translator
    commit id: "feat(parsers): HL7v2 & FHIR parser"
    checkout develop
    merge feature/hl7-fhir-parser-and-translator id: "Merge parsers -> develop"
    branch feature/fhir-anonymizer
    commit id: "feat(fhir-anonymizer): HIPAA & KMS"
    checkout develop
    merge feature/fhir-anonymizer id: "Merge fhir-anonymizer -> develop"
    branch feature/lakehouse-medallion-and-scoring
    commit id: "feat(medallion): NEWS2 & Parquet"
    checkout develop
    merge feature/lakehouse-medallion-and-scoring id: "Merge medallion -> develop"
    branch feature/enterprise-documentation-and-portfolio
    commit id: "docs(enterprise): BRD, ADRs & README"
    checkout develop
    merge feature/enterprise-documentation-and-portfolio id: "Merge docs -> develop"
    checkout staging
    merge develop id: "Promote develop -> staging (QA)"
    checkout main
    merge staging id: "Release staging -> main (v1.0.0)" tag: "v1.0.0"
```

---

## 2. Environment Branch Responsibilities

| Branch | Environment Role | Protection & Promotion Rules |
| :--- | :--- | :--- |
| **`feature/<scope>`** | Isolated feature / module development | Branched from `develop`; must pass `ruff`, `mypy --strict`, and `100% pytest coverage` before `--no-ff` merge into `develop`. |
| **`develop`** | Continuous Integration trunk | Integrates completed `feature/*` branches; verified continuously by GitHub Actions. |
| **`staging`** | Pre-Production QA & HIPAA Compliance Sign-Off | Promoted from `develop` via `--no-ff` merge; verified in isolated Git worktree (`.worktrees/staging-qa`) and end-to-end HIPAA audit CLI. |
| **`main`** | Production release branch | Direct commits to `main` are blocked by `lefthook.yml` (`protect-main-branch`); receives only verified `--no-ff` release promotions from `staging`. |

---

## 3. Using Git Worktrees for Isolated QA Verification

To validate `staging` or parallel `feature/*` branches without disturbing your active working directory:

```bash
# Create an isolated worktree for staging QA inside gitignored .worktrees/
git worktree add .worktrees/staging-qa staging

# Run full verification inside the isolated worktree
cd .worktrees/staging-qa
uv run --no-sync pytest
uv run --no-sync healthcare-lakehouse run-pipeline --patients 10 --verify-hipaa

# Clean up worktree after verification
cd ../..
git worktree remove .worktrees/staging-qa
```
