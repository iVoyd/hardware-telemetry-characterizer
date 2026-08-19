from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

import pytest
from scripts.remote import result_tools

REPO_ROOT = Path(__file__).parents[2]


def _write_run(run_dir: Path, *, complete: bool = True) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        '{"config": {"mode": "passive"}, "synthetic": false}\n', encoding="utf-8"
    )
    (run_dir / "summary.json").write_text(
        '{"mode": "passive", "sample_frame_count": 2, '
        '"guardrail_triggered": null, "workload_error": null, '
        '"interrupted": false, "timing": {"overall": '
        '{"mean_s": 2.0, "min_s": 2.0, "max_s": 2.0}}}\n',
        encoding="utf-8",
    )
    (run_dir / "samples.csv").write_text("quality\nGOOD\nMISSING\n", encoding="utf-8")
    if complete:
        (run_dir / "report.txt").write_text("synthetic report\n", encoding="utf-8")


def test_result_path_parser_uses_final_absolute_local_path(tmp_path: Path) -> None:
    results_root = tmp_path / "hardware-results"
    run_dir = results_root / "run-20260819T123456Z"
    output = f"/tmp/remote-run/results/run-x\n{run_dir}\n"

    assert result_tools.parse_result_path(output, results_root) == run_dir.resolve()
    with pytest.raises(ValueError, match="outside"):
        result_tools.parse_result_path(f"{tmp_path / 'elsewhere'}\n", results_root)


def test_missing_required_result_files_are_reported(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-incomplete"
    _write_run(run_dir, complete=False)

    assert result_tools.missing_result_files(run_dir) == ["report.txt"]
    with pytest.raises(ValueError, match="missing: report.txt"):
        result_tools.archive_result(run_dir, tmp_path / "packages")


def test_archive_contains_only_the_selected_run(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    run_dir = repository / "hardware-results" / "run-20260819T123456Z"
    _write_run(run_dir)
    (run_dir / ".env").write_text("HTC_DUT_HOST=example.invalid\n", encoding="utf-8")
    (run_dir / "src").mkdir()
    (run_dir / "src" / "not_source.py").write_text("not archived\n", encoding="utf-8")
    (repository / ".env").write_text("HTC_DUT_HOST=example.invalid\n", encoding="utf-8")
    (repository / "src").mkdir()
    (repository / "src" / "private_source.py").write_text("not archived\n", encoding="utf-8")

    archive_path = result_tools.archive_result(run_dir, repository / "hardware-results/packages")

    with tarfile.open(archive_path, mode="r:gz") as archive:
        names = archive.getnames()
    assert all(name == run_dir.name or name.startswith(f"{run_dir.name}/") for name in names)
    assert not any(name.endswith(".env") or name.startswith("src/") for name in names)
    assert f"{run_dir.name}/.env" not in names
    assert f"{run_dir.name}/src" not in names


def test_env_and_package_directories_are_ignored() -> None:
    for path in (".env", "hardware-results/packages/example.tar.gz"):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, f"{path} is not gitignored"


def test_validate_wrapper_is_executable_and_requires_cpu_opt_in() -> None:
    script = REPO_ROOT / "scripts/remote/validate_dut.sh"
    assert script.stat().st_mode & 0o111
    contents = script.read_text(encoding="utf-8")
    assert "Starting passive validation" in contents
    assert "--enable-stimulus" in contents
    assert "privileged_read=false" in contents
    assert "helper_command+=(--privileged-read)" in contents

    result = subprocess.run(
        [str(script), "--baseline", "1"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "require explicit --cpu" in result.stderr
