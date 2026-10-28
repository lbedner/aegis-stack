"""How many CPUs a process may use: its container's quota, not the machine's
cores, so heavy work (embedding) leaves one for serving."""

from pathlib import Path

from app.core import cpus


def test_a_quota_is_whole_cpus_and_heavy_work_leaves_one(tmp_path: Path) -> None:
    capped = tmp_path / "cpu.max"
    capped.write_text("200000 100000\n")

    assert cpus.allowed(capped) == 2
    assert cpus.spare_one(capped) == 1


def test_no_quota_is_every_core_and_never_none(tmp_path: Path) -> None:
    unbounded = tmp_path / "cpu.max"
    unbounded.write_text("max 100000\n")
    half = tmp_path / "half"
    half.write_text("50000 100000\n")

    assert cpus.allowed(unbounded) >= 1
    assert cpus.allowed(tmp_path / "missing") >= 1
    assert cpus.spare_one(half) == 1
