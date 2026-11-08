"""Unit tests for the cross-platform Enterprise Gitflow and HIPAA git hook validators."""

from __future__ import annotations

from pathlib import Path

from scripts.git_hooks import validate_commit_msg


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
