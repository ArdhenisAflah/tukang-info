from pathlib import Path

import pytest

from main import load_targets, normalize_phone


def test_load_targets_ignores_comments_blanks_and_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "targets.txt"
    path.write_text(
        """
        # comment

        @Alice
        bob
        alice
        """,
        encoding="utf-8",
    )

    assert load_targets(path) == ["alice", "bob"]


def test_load_targets_supports_numeric_ids(tmp_path: Path) -> None:
    path = tmp_path / "targets.txt"
    path.write_text(
        """
        @Alice
        1234567890
        alice
        1234567890
        """,
        encoding="utf-8",
    )

    assert load_targets(path) == ["alice", "1234567890"]


def test_load_targets_raises_when_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        load_targets(tmp_path / "missing.txt")


def test_normalize_phone_accepts_international_format() -> None:
    assert normalize_phone("+62 812-3456-7890") == "+6281234567890"


def test_normalize_phone_rejects_local_format() -> None:
    assert normalize_phone("081234567890") is None
