from __future__ import annotations

from pathlib import Path

import pytest

from htc import cli


def test_privileged_read_defaults_to_false_and_is_available_on_physical_commands() -> None:
    parser = cli.build_parser()
    discover = parser.parse_args(["discover"])
    characterize = parser.parse_args(["characterize"])
    assert discover.privileged_read is False
    assert characterize.privileged_read is False
    assert parser.parse_args(["discover", "--privileged-read"]).privileged_read is True
    assert parser.parse_args(["characterize", "--privileged-read"]).privileged_read is True

    collectors = cli._collectors(privileged_read=True)
    smart = next(collector for collector in collectors if collector.name == "smart")
    ipmi = next(collector for collector in collectors if collector.name == "ipmi")
    assert smart.command_prefix == ("sudo", "-n")
    assert ipmi.command_prefix == ("sudo", "-n")
    default_collectors = cli._collectors()
    default_smart = next(collector for collector in default_collectors if collector.name == "smart")
    default_ipmi = next(collector for collector in default_collectors if collector.name == "ipmi")
    assert default_smart.command_prefix == ()
    assert default_ipmi.command_prefix == ()


def test_discover_and_characterize_propagate_privileged_read(monkeypatch, tmp_path: Path) -> None:
    collector_calls: list[bool] = []

    class EmptyCollector:
        name = "synthetic"

        def collect(self, _timestamp):
            return []

    monkeypatch.setattr(
        cli,
        "_collectors",
        lambda *, privileged_read=False: (
            collector_calls.append(privileged_read) or [EmptyCollector()]
        ),
    )
    assert cli.main(["discover", "--privileged-read"]) == 0
    assert collector_calls == [True]

    configs = []

    class EmptyResultEngine:
        def __init__(self, _collectors, config):
            configs.append(config)

        def run(self):
            return object()

    monkeypatch.setattr(cli, "ExperimentEngine", EmptyResultEngine)
    monkeypatch.setattr(cli, "install_signal_handlers", lambda: lambda: None)
    monkeypatch.setattr(cli, "write_result", lambda _result, _base: tmp_path / "run")
    assert (
        cli.main(
            [
                "characterize",
                "--duration",
                "0",
                "--privileged-read",
                "--results-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert collector_calls == [True, True]
    assert configs[0].privileged_read is True


def test_privileged_read_does_not_bypass_cpu_stimulus_opt_in() -> None:
    with pytest.raises(SystemExit):
        cli.main(["characterize", "--mode", "cpu", "--privileged-read"])
