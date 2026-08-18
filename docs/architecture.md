# Architecture

The V1 keeps acquisition, experiment control, and evidence generation separate.
Collectors expose generic Linux interfaces through injectable command and
filesystem seams, so replay and fault tests do not need root or a physical
machine.

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

- `measurement.py` defines the typed observation and explicit acquisition
  quality model.
- `adapters.py` contains shell-free command execution and filesystem seams.
- `collectors/` reads hwmon/sysfs, `/proc`, IPMI, SMART/NVMe, and network
  counters without changing the system.
- `experiment.py` provides absolute-time sampling, passive mode, CPU
  baseline/stimulus/recovery phases, process cleanup, and generic thermal
  guardrails.
- `statistics.py` calculates small, reproducible channel and timing summaries.
- `reporting.py` writes the four run artifacts and a human-readable report.
- `replay.py` turns explicitly synthetic scenario JSON into the same artifact
  shape as an actual run.
- `scripts/remote/` contains environment-driven deployment orchestration. It
  is intentionally not invoked by local tests or CI.

The source of truth is the code and tests. Documentation explains boundaries,
not unverified hardware behavior.
