from __future__ import annotations

import os
import pty
import select
import shutil
import subprocess
import sys
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


def _fake_remote_workspace(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    workspace = tmp_path / "workspace"
    remote_dir = workspace / "scripts" / "remote"
    remote_dir.mkdir(parents=True)
    for relative in (
        "AGENTS.md",
        "pyproject.toml",
        "scripts/remote/deploy_and_run.py",
        "scripts/remote/result_tools.py",
        "scripts/remote/validate_dut.sh",
    ):
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    (workspace / ".env").write_text(
        "HTC_DUT_HOST=example.invalid\n"
        "HTC_DUT_USER=operator\n"
        "HTC_DUT_PORT=22\n"
        "HTC_DUT_DIR=/tmp/htc-deploy\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "ssh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "python3").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'script="${1:-}"\n'
        'if [[ "$script" == */deploy_and_run.py ]]; then\n'
        '    if [[ "${2:-}" == "--check-config" ]]; then exit 0; fi\n'
        '    printf "%s\\n" "$@" > "$HTC_TEST_HELPER_LOG"\n'
        '    run_dir="$HTC_TEST_REPO/hardware-results/run-test"\n'
        '    mkdir -p "$run_dir"\n'
        '    printf \'{"config":{"mode":"cpu"},"synthetic":false}\\n\' > "$run_dir/metadata.json"\n'
        '    printf \'{"mode":"cpu","sample_frame_count":0,'
        '"guardrail_triggered":null,"workload_error":null,"interrupted":false,'
        '"timing":{"overall":{"mean_s":0,"min_s":0,"max_s":0}}}\\n\' > "$run_dir/summary.json"\n'
        '    printf "quality\\n" > "$run_dir/samples.csv"\n'
        '    printf "test report\\n" > "$run_dir/report.txt"\n'
        '    printf "%s\\n" "$run_dir"\n'
        "    exit 0\n"
        "fi\n"
        'if [[ "$script" == */result_tools.py ]]; then\n'
        '    exec "$HTC_TEST_REAL_PYTHON" "$@"\n'
        "fi\n"
        'exec "$HTC_TEST_REAL_PYTHON" "$@"\n',
        encoding="utf-8",
    )
    for executable in (fake_bin / "ssh", fake_bin / "python3"):
        executable.chmod(0o755)
    helper_log = tmp_path / "helper-argv.txt"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "HTC_TEST_REPO": str(workspace),
            "HTC_TEST_HELPER_LOG": str(helper_log),
            "HTC_TEST_REAL_PYTHON": sys.executable,
        }
    )
    return workspace, helper_log, environment


def _run_interactive(command: list[str], cwd: Path, env: dict[str, str], input_text: str):
    master, slave = pty.openpty()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    os.close(slave)
    os.write(master, input_text.encode())
    output: list[bytes] = []
    while True:
        readable, _, _ = select.select([master], [], [], 0.1)
        if readable:
            try:
                output.append(os.read(master, 4096))
            except OSError:
                break
        elif process.poll() is not None:
            break
    os.close(master)
    return process.wait(timeout=5), b"".join(output).decode(errors="replace")


def test_validate_wrapper_cpu_layer_excludes_remote_only_stimulus_flag(tmp_path: Path) -> None:
    workspace, helper_log, environment = _fake_remote_workspace(tmp_path)
    script = workspace / "scripts/remote/validate_dut.sh"
    result, output = _run_interactive(
        [
            str(script),
            "--cpu",
            "--privileged-read",
            "--baseline",
            "7",
            "--stimulus-duration",
            "8",
            "--recovery",
            "9",
            "--max-temperature",
            "80",
            "--workers",
            "2",
            "--no-archive",
        ],
        workspace,
        environment,
        "CPU\n",
    )
    assert result == 0, output
    helper_args = helper_log.read_text(encoding="utf-8").splitlines()
    assert helper_args[1:3] == ["--mode", "cpu"]
    assert "--privileged-read" in helper_args
    assert "--baseline" in helper_args
    assert "7" in helper_args
    assert "--stimulus-duration" in helper_args
    assert "8" in helper_args
    assert "--recovery" in helper_args
    assert "9" in helper_args
    assert "--max-temperature" in helper_args
    assert "80" in helper_args
    assert "--workers" in helper_args
    assert "2" in helper_args
    assert "--enable-stimulus" not in helper_args


def test_validate_wrapper_rejects_incorrect_cpu_confirmation(tmp_path: Path) -> None:
    workspace, helper_log, environment = _fake_remote_workspace(tmp_path)
    result, output = _run_interactive(
        [str(workspace / "scripts/remote/validate_dut.sh"), "--cpu"],
        workspace,
        environment,
        "yes\n",
    )
    assert result != 0
    assert "was not confirmed" in output
    assert not helper_log.exists()


def test_validate_wrapper_rejects_noninteractive_cpu_mode(tmp_path: Path) -> None:
    workspace, helper_log, environment = _fake_remote_workspace(tmp_path)
    result = subprocess.run(
        [str(workspace / "scripts/remote/validate_dut.sh"), "--cpu"],
        cwd=workspace,
        env=environment,
        input="CPU\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "requires an interactive terminal" in result.stderr
    assert not helper_log.exists()


def test_validate_wrapper_is_executable_and_requires_cpu_opt_in() -> None:
    script = REPO_ROOT / "scripts/remote/validate_dut.sh"
    assert script.stat().st_mode & 0o111
    contents = script.read_text(encoding="utf-8")
    assert "Starting passive validation" in contents
    assert "privileged_read=false" in contents
    assert "helper_command+=(--privileged-read)" in contents
    setup_contents = (REPO_ROOT / "scripts/remote/setup_dut.sh").read_text(encoding="utf-8")
    assert "SMART discovery: available" in setup_contents
    assert "smartctl -a -d nvme" in setup_contents

    result = subprocess.run(
        [str(script), "--baseline", "1"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "require explicit --cpu" in result.stderr
