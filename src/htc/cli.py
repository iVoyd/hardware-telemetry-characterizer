"""Command-line interface for discovery, characterization, replay, and reports."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .collectors import (
    HWMONCollector,
    IPMICollector,
    NetworkCollector,
    SmartCollector,
    SystemCollector,
)
from .experiment import (
    ExperimentConfig,
    ExperimentEngine,
    default_worker_count,
    install_signal_handlers,
)
from .measurement import utc_now
from .replay import replay_scenario
from .reporting import report_run, write_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="htc",
        description="Read-only Linux telemetry acquisition and controlled characterization.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser("discover", help="collect one snapshot from available sources")
    discover.add_argument(
        "--json", action="store_true", help="emit normalized measurements as JSON"
    )

    characterize = subparsers.add_parser(
        "characterize", help="run passive or bounded CPU characterization"
    )
    characterize.add_argument("--mode", choices=("passive", "cpu"), default="passive")
    characterize.add_argument(
        "--duration", type=float, default=10.0, help="passive duration in seconds"
    )
    characterize.add_argument(
        "--interval", type=float, default=2.0, help="requested sample interval in seconds"
    )
    characterize.add_argument("--baseline", type=float, default=6.0)
    characterize.add_argument("--stimulus-duration", type=float, default=10.0)
    characterize.add_argument("--recovery", type=float, default=6.0)
    characterize.add_argument(
        "--workers", type=int, help="CPU worker count; default is about 25%% of logical CPUs"
    )
    characterize.add_argument(
        "--max-temperature", type=float, default=85.0, help="generic thermal abort guard in °C"
    )
    characterize.add_argument("--results-dir", default="results")
    characterize.add_argument(
        "--enable-stimulus",
        action="store_true",
        help="required opt-in for active CPU stimulus; has no effect in passive mode",
    )

    replay = subparsers.add_parser("replay", help="run an explicitly synthetic scenario")
    replay.add_argument("scenario", help="scenario name or path to scenario.json")
    replay.add_argument("--results-dir", default="results")

    report = subparsers.add_parser("report", help="render report.txt from a run directory")
    report.add_argument("run_dir")
    return parser


def _collectors() -> list[object]:
    return [
        SystemCollector(),
        HWMONCollector(),
        IPMICollector(),
        SmartCollector(),
        NetworkCollector(),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "discover":
        measurements = []
        timestamp = utc_now()
        for collector in _collectors():
            measurements.extend(collector.collect(timestamp))
        if args.json:
            print(json.dumps([measurement.as_row() for measurement in measurements], indent=2))
        else:
            for measurement in measurements:
                value = "<none>" if measurement.value is None else measurement.value
                detail = f" ({measurement.error})" if measurement.error else ""
                print(
                    f"{measurement.source:8} {measurement.device_id:18} {measurement.channel:32} "
                    f"{value!s:>12} {measurement.unit:8} {measurement.quality.value}{detail}"
                )
        return 0
    if args.command == "characterize":
        if args.mode == "cpu" and not args.enable_stimulus:
            parser.error("--mode cpu requires explicit --enable-stimulus")
        config = ExperimentConfig(
            mode=args.mode,
            interval_s=args.interval,
            duration_s=args.duration,
            baseline_s=args.baseline,
            stimulus_s=args.stimulus_duration,
            recovery_s=args.recovery,
            workers=args.workers if args.workers is not None else default_worker_count(),
            max_temperature_c=args.max_temperature,
        )
        restore_signals = install_signal_handlers()
        try:
            result = ExperimentEngine(_collectors(), config).run()
        finally:
            restore_signals()
        run_dir = write_result(result, args.results_dir)
        print(run_dir)
        return 0
    if args.command == "replay":
        print(replay_scenario(args.scenario, args.results_dir))
        return 0
    if args.command == "report":
        print(report_run(Path(args.run_dir)), end="")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
