"""Injectable operating-system seams for deterministic collector tests."""

from __future__ import annotations

import glob as glob_module
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class CommandUnavailable(RuntimeError):
    """Raised when an optional external command is not installed."""


class CommandTimeout(RuntimeError):
    """Raised when a command exceeds its bounded timeout."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured result from a command invocation."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float


class CommandRunner(Protocol):
    def run(self, command: Iterable[str], timeout_s: float) -> CommandResult:
        """Run a command without a shell and return captured output."""


class SubprocessRunner:
    """Production command runner using a shell-free subprocess invocation."""

    def run(self, command: Iterable[str], timeout_s: float) -> CommandResult:
        argv = tuple(command)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_s,
            )
        except FileNotFoundError as exc:
            raise CommandUnavailable("command not found: " + argv[0]) from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandTimeout("command timed out: " + " ".join(argv)) from exc
        return CommandResult(
            command=argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_s=time.monotonic() - started,
        )


class Filesystem(Protocol):
    def read_text(self, path: str | Path) -> str:
        """Read UTF-8 text from a path."""

    def glob(self, pattern: str | Path) -> list[Path]:
        """Return matching paths in deterministic order."""

    def exists(self, path: str | Path) -> bool:
        """Return whether a path exists."""

    def resolve(self, path: str | Path) -> Path:
        """Resolve symlinks where the filesystem supports them."""


class PathFilesystem:
    """Production filesystem adapter."""

    def read_text(self, path: str | Path) -> str:
        return Path(path).read_text(encoding="utf-8")

    def glob(self, pattern: str | Path) -> list[Path]:
        return sorted(Path(item) for item in glob_module.glob(str(pattern)))

    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def resolve(self, path: str | Path) -> Path:
        return Path(path).resolve(strict=False)
