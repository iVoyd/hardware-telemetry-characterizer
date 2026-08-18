from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path

from htc.adapters import CommandResult


class FakeFilesystem:
    def __init__(self, files: dict[str, str], directories: Iterable[str] = ()):
        self.files = dict(files)
        self.directories = set(directories)

    def read_text(self, path: str | Path) -> str:
        key = str(path)
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    def glob(self, pattern: str | Path) -> list[Path]:
        key = str(pattern)
        candidates = self.directories | set(self.files)
        return sorted(Path(item) for item in candidates if fnmatch.fnmatch(item, key))

    def exists(self, path: str | Path) -> bool:
        return str(path) in self.files or str(path) in self.directories


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult | Exception]):
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def run(self, command: Iterable[str], timeout_s: float) -> CommandResult:
        key = tuple(command)
        self.calls.append(key)
        response = self.responses[key]
        if isinstance(response, Exception):
            raise response
        return response
