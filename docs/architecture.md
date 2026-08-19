# Architecture

HTC separates acquisition, experiment control, and reporting so each part can
be tested independently.

```text
Physical / Synthetic Sources
            ↓
      Collector Layer
            ↓
   Normalized Measurements
            ↓
      Experiment Engine
            ↓
   Statistics / Guardrails
            ↓
       CSV + JSON + Report
```

## Responsibilities

- `measurement.py` defines the typed observation model and acquisition quality
  states.
- `adapters.py` provides shell-free command execution and filesystem interfaces.
  Tests replace these interfaces with deterministic fakes.
- `collectors/` reads hwmon/sysfs, `/proc`, IPMI, SMART/NVMe, and network
  counters without changing system configuration.
- `experiment.py` schedules passive and CPU experiments against an absolute
  timeline. CPU runs have baseline, stimulus, and recovery phases, generic
  thermal guards, and workload cleanup before recovery. A shutdown failure is
  recorded and blocks recovery until cleanup succeeds; outer cleanup remains
  best effort.
- `statistics.py` calculates channel and timing summaries. Interval-derived
  CPU-utilization measurements that cross a phase boundary remain in the raw
  samples but are excluded from phase statistics.
- `reporting.py` writes `metadata.json`, `samples.csv`, `summary.json`, and
  `report.txt`.
- `replay.py` turns synthetic scenario JSON into the same artifact shape as an
  actual run.
- `scripts/remote/` handles environment-driven deployment. It shares one SSH
  configuration across SSH, rsync, and scp, and retrieves one result directory
  into ignored local storage. `setup_dut.sh` performs a read-only prerequisite
  check; `validate_dut.sh` defaults to passive observation and requires
  interactive confirmation for CPU stimulus.

The source and tests are the source of truth. The documentation describes
interfaces and boundaries rather than unverified hardware behavior.
