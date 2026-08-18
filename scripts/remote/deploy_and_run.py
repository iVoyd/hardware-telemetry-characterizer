#!/usr/bin/env python3
"""Deploy the current tree to a temporary remote directory and retrieve results.

This helper is intentionally environment-driven and is not exercised against a
physical DUT during project bootstrap. Commands are passed as argv where
possible; the unavoidable remote command string is assembled with ``shlex``.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

EXCLUDES = (
    ".git/",
    ".venv/",
    "results/",
    "hardware-results/",
    ".env",
    "credentials/",
    "caches/",
)
_REMOTE_TEMP_PATH = re.compile(r"^[A-Za-z0-9_./-]+$")


@dataclass(frozen=True, slots=True)
class RemoteConfig:
    host: str
    user: str
    parent_dir: str
    port: int = 22
    ssh_key: str | None = None

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}"


def config_from_environment(environ: dict[str, str] | None = None) -> RemoteConfig:
    values = os.environ if environ is None else environ
    missing = [
        name for name in ("HTC_DUT_HOST", "HTC_DUT_USER", "HTC_DUT_DIR") if not values.get(name)
    ]
    if missing:
        raise ValueError("missing required environment variable(s): " + ", ".join(missing))
    try:
        port = int(values.get("HTC_DUT_PORT", "22"))
    except ValueError as exc:
        raise ValueError("HTC_DUT_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("HTC_DUT_PORT must be between 1 and 65535")
    return RemoteConfig(
        host=values["HTC_DUT_HOST"],
        user=values["HTC_DUT_USER"],
        parent_dir=values["HTC_DUT_DIR"],
        port=port,
        ssh_key=values.get("HTC_DUT_SSH_KEY") or None,
    )


def ssh_base(config: RemoteConfig) -> list[str]:
    command = ["ssh", "-p", str(config.port)]
    if config.ssh_key:
        command.extend(["-i", config.ssh_key])
    command.append(config.target)
    return command


def remote_command(config: RemoteConfig, command: list[str]) -> list[str]:
    return [*ssh_base(config), shlex.join(command)]


def run(
    config: RemoteConfig,
    *,
    mode: str,
    duration: float,
    interval: float,
    workers: int | None,
) -> Path:
    """Perform one explicit remote run and return the local ignored result path."""

    repository = Path(__file__).resolve().parents[2]
    local_results = (
        repository / "hardware-results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    local_results.mkdir(parents=True, exist_ok=False)
    subprocess.run(remote_command(config, ["mkdir", "-p", config.parent_dir]), check=True)
    temp_result = subprocess.run(
        remote_command(config, ["mktemp", "-d", "--tmpdir", config.parent_dir, "htc-run.XXXXXX"]),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not temp_result:
        raise RuntimeError("remote temporary directory was not returned")
    parent_prefix = config.parent_dir.rstrip("/") + "/"
    if not _REMOTE_TEMP_PATH.fullmatch(temp_result) or not temp_result.startswith(parent_prefix):
        raise RuntimeError("remote temporary directory was not a safe child of HTC_DUT_DIR")

    try:
        _deploy(repository, config, temp_result)
        characterize = [
            "python3",
            "-m",
            "htc",
            "characterize",
            "--mode",
            mode,
            "--duration",
            str(duration),
            "--interval",
            str(interval),
            "--results-dir",
            "results",
        ]
        if mode == "cpu":
            characterize.append("--enable-stimulus")
            if workers is not None:
                characterize.extend(["--workers", str(workers)])
        remote_script = (
            f"cd {shlex.quote(temp_result)} && exec env PYTHONPATH=src {shlex.join(characterize)}"
        )
        subprocess.run(remote_command(config, ["sh", "-c", remote_script]), check=True)
        _retrieve(config, temp_result, local_results)
    finally:
        subprocess.run(remote_command(config, ["rm", "-rf", "--", temp_result]), check=False)
    return local_results


def _deploy(repository: Path, config: RemoteConfig, remote_dir: str) -> None:
    if shutil.which("rsync"):
        command = ["rsync", "-az"]
        command.extend(arg for exclude in EXCLUDES for arg in ("--exclude", exclude))
        command.extend([f"{repository}/", f"{config.target}:{remote_dir}/"])
        subprocess.run(command, check=True)
        return
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as archive:
        archive_path = Path(archive.name)
    try:
        tar_command = ["tar", "-czf", str(archive_path), "-C", str(repository)]
        tar_command.extend(arg for exclude in EXCLUDES for arg in ("--exclude", exclude))
        tar_command.append(".")
        subprocess.run(tar_command, check=True)
        subprocess.run([*ssh_base(config), "mkdir -p " + shlex.quote(remote_dir)], check=True)
        subprocess.run(
            [
                *scp_base(config),
                str(archive_path),
                f"{config.target}:{remote_dir}/source.tar.gz",
            ],
            check=True,
        )
        subprocess.run(
            remote_command(
                config, ["tar", "-xzf", f"{remote_dir}/source.tar.gz", "-C", remote_dir]
            ),
            check=True,
        )
    finally:
        archive_path.unlink(missing_ok=True)


def _retrieve(config: RemoteConfig, remote_dir: str, local_dir: Path) -> None:
    source = f"{config.target}:{remote_dir}/results/"
    if shutil.which("rsync"):
        subprocess.run(["rsync", "-az", source, f"{local_dir}/"], check=True)
    else:
        subprocess.run([*scp_base(config), "-r", source, f"{local_dir}/"], check=True)


def scp_base(config: RemoteConfig) -> list[str]:
    command = ["scp", "-P", str(config.port)]
    if config.ssh_key:
        command.extend(["-i", config.ssh_key])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("passive", "cpu"), default="passive")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--workers", type=int)
    args = parser.parse_args()
    config = config_from_environment()
    print(
        run(
            config,
            mode=args.mode,
            duration=args.duration,
            interval=args.interval,
            workers=args.workers,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
