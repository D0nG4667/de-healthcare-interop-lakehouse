"""Unit tests for the cross-platform Enterprise Gitflow and HIPAA git hook validators."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from scripts import git_hooks
from scripts.git_hooks import (
    block_phi_artifacts,
    protect_main_branch,
    validate_commit_msg,
)


def test_validate_commit_msg_accepts_conventional_and_merge_commits(tmp_path: Path) -> None:
    """Verify valid Conventional Commits and Gitflow Merge commits pass validation."""
    msg_file = tmp_path / "COMMIT_EDITMSG"

    msg_file.write_text(
        "feat(fhir-anonymizer): implement KMS HMAC-SHA256 tokenizer\n\n- Detailed bullet",
        encoding="utf-8",
    )
    assert validate_commit_msg(str(msg_file)) == 0

    msg_file.write_text(
        "Merge branch 'feature/fhir-anonymizer' into develop",
        encoding="utf-8",
    )
    assert validate_commit_msg(str(msg_file)) == 0


def test_validate_commit_msg_rejects_empty_or_non_conventional_subjects(
    tmp_path: Path,
) -> None:
    """Verify empty commit messages or unstructured commit titles are rejected."""
    msg_file = tmp_path / "COMMIT_EDITMSG"

    msg_file.write_text("   \n  ", encoding="utf-8")
    assert validate_commit_msg(str(msg_file)) == 1

    msg_file.write_text("updated some files quickly", encoding="utf-8")
    assert validate_commit_msg(str(msg_file)) == 1


def test_protect_main_branch_and_block_phi_artifacts_and_cli_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify branch protection, staged + tracked PHI scanning, and CLI dispatch."""
    # 1. protect_main_branch on feature vs main
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "feature/test\n")
    assert protect_main_branch() == 0

    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "main\n")
    assert protect_main_branch() == 1

    # 2. block_phi_artifacts checks both git diff --cached and git ls-files
    def fake_clean_git(cmd: list[str], text: bool = True) -> str:
        return "README.md\nsrc/healthcare_lakehouse/cli.py\n"

    monkeypatch.setattr(subprocess, "check_output", fake_clean_git)
    assert block_phi_artifacts() == 0

    def fake_tracked_phi_git(cmd: list[str], text: bool = True) -> str:
        if "ls-files" in cmd:
            return "README.md\ndata/leaked_dump.parquet\n"
        return ""

    monkeypatch.setattr(subprocess, "check_output", fake_tracked_phi_git)
    assert block_phi_artifacts() == 1

    # 3. CLI main() dispatch coverage
    monkeypatch.setattr(sys, "argv", ["git_hooks.py"])
    assert git_hooks.main() == 1

    monkeypatch.setattr(sys, "argv", ["git_hooks.py", "unknown"])
    assert git_hooks.main() == 1

    monkeypatch.setattr(subprocess, "check_output", fake_clean_git)
    monkeypatch.setattr(sys, "argv", ["git_hooks.py", "block-phi"])
    assert git_hooks.main() == 0

    monkeypatch.setattr(subprocess, "check_output", lambda *a, **kw: "develop\n")
    monkeypatch.setattr(sys, "argv", ["git_hooks.py", "protect-main"])
    assert git_hooks.main() == 0

    msg_file = tmp_path / "MSG"
    msg_file.write_text("chore(hooks): verify main entrypoint", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["git_hooks.py", "commit-msg", str(msg_file)])
    assert git_hooks.main() == 0
