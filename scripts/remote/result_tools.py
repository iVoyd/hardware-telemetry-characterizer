#!/usr/bin/env python3
"""Validate, summarize, and package one local hardware result directory."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tarfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REQUIRED_RESULT_FILES = ("metadata.json", "samples.csv", "summary.json", "report.txt")
ARCHIVE_EXCLUDED_NAMES = frozenset({".env", ".git", "credentials", "secrets", "src", "scripts"})


def parse_result_path(output: str, results_root: str | Path) -> Path:
    """Return the final absolute result path printed by the remote helper."""

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise ValueError("remote helper did not print a local result path")
    candidate = Path(lines[-1])
    if not candidate.is_absolute():
        raise ValueError("remote helper result path was not absolute")
    root = Path(results_root).resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("result path is outside the local hardware-results directory") from exc
    if not relative.parts:
        raise ValueError("result path must name a run directory")
    return resolved


def missing_result_files(run_dir: str | Path) -> list[str]:
    """Return required artifact names absent from a result directory."""

    path = Path(run_dir)
    return [name for name in REQUIRED_RESULT_FILES if not (path / name).is_file()]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def non_good_measurement_count(run_dir: str | Path) -> int:
    """Count acquired rows whose quality is not GOOD without judging DUT health."""

    with (Path(run_dir) / "samples.csv").open(newline="", encoding="utf-8") as handle:
        return sum(row.get("quality") != "GOOD" for row in csv.DictReader(handle))


def summary_lines(run_dir: str | Path) -> list[str]:
    """Return concise operator-facing evidence fields from one run."""

    path = Path(run_dir)
    metadata = _load_json(path / "metadata.json")
    summary = _load_json(path / "summary.json")
    timing = summary.get("timing", {})
    overall = timing.get("overall", {}) if isinstance(timing, dict) else {}
    config = metadata.get("config")
    configured_mode = config.get("mode", "unknown") if isinstance(config, dict) else "unknown"
    values = {
        "Mode": summary.get("mode", configured_mode),
        "Sample frames": summary.get("sample_frame_count", "not reported"),
        "Guardrail": summary.get("guardrail_triggered") or "not triggered",
        "Workload error": summary.get("workload_error") or "none reported",
        "Interrupted": summary.get("interrupted", "not reported"),
        "Timing mean (s)": overall.get("mean_s", "not reported"),
        "Timing min (s)": overall.get("min_s", "not reported"),
        "Timing max (s)": overall.get("max_s", "not reported"),
        "Non-GOOD measurements": non_good_measurement_count(path),
    }
    return [f"{label}: {value}" for label, value in values.items()]


def archive_result(run_dir: str | Path, packages_dir: str | Path) -> Path:
    """Create an archive containing only one validated run directory."""

    path = Path(run_dir).resolve()
    missing = missing_result_files(path)
    if missing:
        raise ValueError("cannot archive incomplete result; missing: " + ", ".join(missing))
    if not path.is_dir():
        raise ValueError(f"result directory does not exist: {path}")

    package_dir = Path(packages_dir).resolve()
    if package_dir == path or package_dir.is_relative_to(path):
        raise ValueError("archive directory must not be inside the result directory")
    package_dir.mkdir(parents=True, exist_ok=True)
    stem = path.name.removeprefix("run-")
    archive_path = package_dir / f"htc-result-{stem}.tar.gz"
    suffix = 1
    while archive_path.exists():
        archive_path = package_dir / f"htc-result-{stem}-{suffix}.tar.gz"
        suffix += 1

    def archive_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
        relative_parts = Path(member.name).parts[1:]
        if any(part in ARCHIVE_EXCLUDED_NAMES for part in relative_parts):
            return None
        return member

    with tarfile.open(archive_path, mode="w:gz") as archive:
        archive.add(path, arcname=path.name, recursive=True, filter=archive_filter)
    return archive_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse = subparsers.add_parser("parse", help="parse the helper's captured output")
    parse.add_argument("--output-file", type=Path, required=True)
    parse.add_argument("--results-root", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="verify required result artifacts")
    validate.add_argument("--run-dir", type=Path, required=True)

    summary = subparsers.add_parser("summary", help="print an operator-facing summary")
    summary.add_argument("--run-dir", type=Path, required=True)

    archive = subparsers.add_parser("archive", help="create an upload-friendly archive")
    archive.add_argument("--run-dir", type=Path, required=True)
    archive.add_argument("--packages-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "parse":
        print(parse_result_path(args.output_file.read_text(encoding="utf-8"), args.results_root))
        return 0
    if args.command == "validate":
        missing = missing_result_files(args.run_dir)
        if missing:
            print("Missing required result file(s): " + ", ".join(missing), file=sys.stderr)
            return 1
        return 0
    if args.command == "summary":
        print("\n".join(summary_lines(args.run_dir)))
        return 0
    if args.command == "archive":
        print(archive_result(args.run_dir, args.packages_dir))
        return 0
    parser.error("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
