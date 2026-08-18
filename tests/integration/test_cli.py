from __future__ import annotations

from pathlib import Path

from htc.cli import main


def test_replay_and_report_cli_path(tmp_path: Path, capsys) -> None:
    assert main(["replay", "normal_three_nvme", "--results-dir", str(tmp_path)]) == 0
    run_path = Path(capsys.readouterr().out.strip())
    assert run_path.is_dir()
    assert main(["report", str(run_path)]) == 0
    assert "Hardware Telemetry Characterizer" in capsys.readouterr().out
