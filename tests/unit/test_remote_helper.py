from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def load_helper():
    path = Path(__file__).parents[2] / "scripts/remote/deploy_and_run.py"
    spec = importlib.util.spec_from_file_location("htc_remote_helper", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_remote_configuration_is_environment_driven() -> None:
    helper = load_helper()
    config = helper.config_from_environment(
        {
            "HTC_DUT_HOST": "example.invalid",
            "HTC_DUT_USER": "operator",
            "HTC_DUT_DIR": "/tmp/htc-deploy",
            "HTC_DUT_PORT": "2222",
        }
    )
    assert config.target == "operator@example.invalid"
    assert config.port == 2222


def test_rsync_transport_honors_default_and_custom_ssh_settings(monkeypatch) -> None:
    helper = load_helper()
    default = helper.RemoteConfig("example.invalid", "operator", "/tmp/htc")
    assert helper.rsync_ssh_transport(default) == "ssh -p 22"
    custom = helper.RemoteConfig("example.invalid", "operator", "/tmp/htc", 2222, "/tmp/dut key")
    expected_transport = "ssh -p 2222 -i '/tmp/dut key'"
    assert helper.rsync_ssh_transport(custom) == expected_transport

    calls: list[list[str]] = []
    monkeypatch.setattr(helper.shutil, "which", lambda _name: "/usr/bin/rsync")
    monkeypatch.setattr(helper.subprocess, "run", lambda command, check: calls.append(command))
    helper._deploy(Path("/tmp/source"), custom, "/tmp/htc-run")
    helper._retrieve(custom, "/tmp/htc-run", Path("/tmp/results"))
    assert calls[0][0:4] == ["rsync", "-az", "-e", expected_transport]
    assert calls[1][0:4] == ["rsync", "-az", "-e", expected_transport]


def test_remote_configuration_rejects_missing_values() -> None:
    helper = load_helper()
    with pytest.raises(ValueError, match="HTC_DUT_HOST"):
        helper.config_from_environment({})


def test_remote_command_quotes_untrusted_connection_values() -> None:
    helper = load_helper()
    with pytest.raises(ValueError, match="HTC_DUT_HOST"):
        helper.RemoteConfig("example.invalid;touch /tmp/bad", "operator", "/tmp/htc", 22)
    with pytest.raises(ValueError, match="HTC_DUT_DIR"):
        helper.RemoteConfig("example.invalid", "operator", "/tmp/../bad", 22)
    config = helper.RemoteConfig("example.invalid", "operator", "/tmp/htc", 22)
    command = helper.remote_command(config, ["printf", "safe value"])
    assert command[-2] == "operator@example.invalid"
    assert command[-1] == "printf 'safe value'"


def test_remote_characterize_arguments_are_mode_specific() -> None:
    helper = load_helper()
    passive = helper.characterize_command(
        mode="passive",
        duration=30,
        interval=2,
        baseline=6,
        stimulus_duration=10,
        recovery=6,
        max_temperature=85,
        workers=None,
    )
    assert "--duration" in passive
    assert "--baseline" not in passive
    cpu = helper.characterize_command(
        mode="cpu",
        duration=30,
        interval=2,
        baseline=6,
        stimulus_duration=10,
        recovery=6,
        max_temperature=85,
        workers=2,
    )
    assert "--duration" not in cpu
    assert all(option in cpu for option in ("--baseline", "--stimulus-duration", "--recovery"))
    assert "--max-temperature" in cpu
    assert "--workers" in cpu
    assert "--enable-stimulus" in cpu
