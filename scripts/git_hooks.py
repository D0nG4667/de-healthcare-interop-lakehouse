"""Cross-platform Enterprise Gitflow & HIPAA Gate hooks invoked by Lefthook."""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

FORBIDDEN_EXTENSIONS: tuple[str, ...] = (
    ".csv",
    ".hl7",
    ".mllp",
    ".fhir.json",
    ".fhir.xml",
    ".parquet",
    ".pem",
    ".key",
    ".kms",
)

CONVENTIONAL_COMMIT_PATTERN: re.Pattern[str] = re.compile(
    r"^(Merge |Revert |"
    r"(feat|fix|docs|style|refactor|perf|test|build|ci|chore|security)"
    r"(\([a-z0-9_-]+\))?!?: .{3,100}$)"
)


def protect_main_branch() -> int:
    """Prevent direct commits on the production main branch."""
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip()
    if branch == "main":
        sys.stderr.write(
            "ERROR: Direct commits to 'main' are prohibited by Enterprise Gitflow. "
            "Use a 'feature/*' branch and promote via 'develop' -> 'staging' -> 'main'.\n"
        )
        return 1
    return 0


def block_phi_artifacts() -> int:
    """Block accidental staging of raw clinical data files or KMS private keys."""
    staged = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"], text=True
    ).splitlines()
    forbidden = [f for f in staged if f.lower().endswith(FORBIDDEN_EXTENSIONS)]
    if forbidden:
        sys.stderr.write(
            f"HIPAA GATE BLOCKED: Forbidden raw clinical/key files staged: {forbidden}\n"
        )
        return 1
    return 0


def validate_commit_msg(msg_file: str) -> int:
    """Enforce Conventional Commits specification on commit subject lines."""
    content = pathlib.Path(msg_file).read_text(encoding="utf-8").strip()
    if not content:
        sys.stderr.write("ERROR: Commit message cannot be empty.\n")
        return 1
    subject = content.splitlines()[0].strip()
    if not CONVENTIONAL_COMMIT_PATTERN.match(subject):
        sys.stderr.write(
            f"ERROR: Commit subject does not follow Conventional Commits: '{subject}'\n"
            "Expected: <type>(<scope>): <description> "
            "(e.g., feat(fhir-anonymizer): add KMS HMAC tokenizer)\n"
        )
        return 1
    return 0


def main() -> int:
    """Dispatch git hook check by command argument."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: python scripts/git_hooks.py <protect-main|block-phi|commit-msg>\n")
        return 1
    command = sys.argv[1]
    if command == "protect-main":
        return protect_main_branch()
    if command == "block-phi":
        return block_phi_artifacts()
    if command == "commit-msg" and len(sys.argv) >= 3:
        return validate_commit_msg(sys.argv[2])
    sys.stderr.write(f"Unknown command: {command}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
