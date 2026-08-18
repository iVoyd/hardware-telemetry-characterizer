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


def test_remote_configuration_rejects_missing_values() -> None:
    helper = load_helper()
    with pytest.raises(ValueError, match="HTC_DUT_HOST"):
        helper.config_from_environment({})


def test_remote_command_quotes_untrusted_connection_values() -> None:
    helper = load_helper()
    config = helper.RemoteConfig("example.invalid;touch /tmp/bad", "operator", "/tmp/htc", 22)
    command = helper.remote_command(config, ["printf", "safe value"])
    assert command[-2] == "operator@example.invalid;touch /tmp/bad"
    assert command[-1] == "printf 'safe value'"
