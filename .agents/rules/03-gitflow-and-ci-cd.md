# Rule 03: Enterprise Gitflow, Branching, Worktrees & CI/CD

## Scope
Applies to all repository operations, commits, branches, pull requests, Lefthook hooks, and GitHub Actions workflows.

## Gitflow Topology

```text
main       (Production — protected, tagged releases vX.Y.Z only)
  ▲
staging    (Pre-Production QA & HIPAA Compliance Sign-Off)
  ▲
develop    (Continuous Integration Trunk)
  ▲
feature/*  (Isolated Feature / Module Development Branches)
```

1. **Branch Naming Conventions:**
   - Feature branches: `feature/<kebab-case-topic>` (e.g., `feature/fhir-anonymizer`, `feature/lakehouse-medallion-and-scoring`)
   - Bugfix branches: `fix/<kebab-case-issue>`
   - Hotfix branches: `hotfix/<kebab-case-critical-fix>`
   - Release/Promotion merges: Always use `git merge --no-ff` to preserve explicit branch history topology.

2. **Worktree Isolation:**
   - When using Git worktrees for parallel QA or branch verification, place local worktrees inside `.worktrees/<branch-slug>` (which is gitignored in `.gitignore`) and prune worktrees cleanly after verification (`git worktree remove` / `git worktree prune`).

3. **Commit Message Standard (Conventional Commits):**
   - Header: `<type>(<scope>): <imperative summary>` (`<= 72` characters, no trailing period)
   - Body: Bullet points explaining architectural decisions, HIPAA controls, and test coverage evidence.
   - Footer: Reference ADRs, BRD requirements, or compliance gates (e.g., `Refs: ADR-002, BRD-001`).

4. **Lefthook & GitHub Actions Parity:**
   - `lefthook.yml` enforces `ruff check`, `ruff format --check`, `mypy`, branch protection on `main`, conventional commit regex validation, and `pytest --cov-fail-under=100`.
   - `.github/workflows/ci-pipeline.yml` runs identical checks on GitHub Actions runners.
