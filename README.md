# Hardware Telemetry Characterizer

Hardware Telemetry Characterizer (`htc`) is a generic Linux framework for
turning read-only hardware observations into reproducible characterization
evidence.

Monitoring asks, “What are the sensors reading?” Characterization asks, “How
does the system respond to a controlled condition or stimulus, how repeatable
is that response, and what evidence supports the conclusion?” This project is
built for the second question. It is not a generic monitoring dashboard.

All committed sample data and fixtures are synthetic. The repository is
clean-room and public-safe by design: it contains no production logs, physical
DUT captures, credentials, customer data, or employer-specific procedures.

## What is implemented

- Typed, normalized measurements with timestamps, source, generic device and
  controller identity, engineering units, values, and explicit quality states.
- Injectable command and filesystem boundaries for hardware-free tests.
- Read-only Linux collectors for hwmon/sysfs, CPU/system files, IPMI,
  SMART/NVMe, and network sysfs counters.
- Deterministic scheduled sampling with actual cadence statistics.
- Passive observation and explicit-opt-in, bounded CPU baseline/stimulus/recovery
  characterization.
- Generic thermal guardrails and guaranteed workload cleanup on normal,
  interrupted, failed, and aborted paths.
- CSV, JSON, and text evidence artifacts for each run.
- Synthetic replay scenarios for normal operation, missing tools, malformed or
  timed-out commands, stale/missing sensors, identity collisions, thermal
  aborts, and workload failure.
- Environment-driven remote-DUT deployment scaffolding using rsync with a
  shell-safe scp/archive fallback. It is not run during CI or bootstrap.

## Architecture

Collectors normalize public Linux interfaces into one measurement model. The
experiment engine schedules acquisition, controls phase transitions, evaluates
generic safety guardrails, and delegates statistics/reporting. See
[`docs/architecture.md`](docs/architecture.md) and
[`docs/measurement-model.md`](docs/measurement-model.md).

## Quick start

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

# One read-only snapshot; absent optional tools become explicit quality states.
.venv/bin/htc discover

# Passive observation. Run output is written below ignored results/.
.venv/bin/htc characterize --mode passive --duration 10 --interval 2

# Synthetic operation with no hardware or root access.
.venv/bin/htc replay tests/fixtures/scenarios/normal_three_nvme
.venv/bin/htc report results/<run-directory>
```

The CPU mode requires an explicit safety opt-in:

```bash
.venv/bin/htc characterize --mode cpu --enable-stimulus \
  --baseline 6 --stimulus-duration 10 --recovery 6 --interval 2
```

The default worker count is approximately 25% of logical CPUs. The workload
does not perform disk or network I/O and does not change persistent system
configuration. `--max-temperature` is a generic acquisition guardrail, not a
DUT qualification or production acceptance limit.

## Collectors and quality

The hwmon collector includes the sysfs instance in the device identity. Thus
two generic `nvme` driver names remain independent (`nvme:hwmon0` and
`nvme:hwmon1`) instead of overwriting each other. IPMI and SMART tooling are
optional; missing commands, timeouts, command failures, and parse failures are
recorded rather than treated as DUT failures. Quality states include
`GOOD`, `MISSING`, `STALE`, `TIMEOUT`, `PARSE_ERROR`, `COMMAND_ERROR`, and
`UNAVAILABLE`.

## Run artifacts

Each run creates a timestamped directory containing:

```text
metadata.json   configuration and run metadata
samples.csv     every normalized observation, including non-GOOD quality
summary.json    timing, channel statistics, and modest phase deltas
report.txt      human-readable summary
```

Physical results belong under ignored `hardware-results/`. Committed examples
belong under `examples/synthetic/` and must remain explicitly synthetic.

## Development and validation

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src scripts tests
.venv/bin/ruff format --check src scripts tests
```

CI runs these checks without root access, IPMI hardware, NVMe devices, a
network DUT, or real physical evidence. Validation strategy and limits are
documented in [`docs/validation.md`](docs/validation.md).

## Remote DUT concept

Development, Git, and credentials remain on the development WSL machine. The
optional helper reads `HTC_DUT_HOST`, `HTC_DUT_USER`, `HTC_DUT_DIR`, and
`HTC_DUT_PORT` from the environment, deploys to a temporary remote directory,
runs a read-only or explicitly bounded command, and retrieves results to local
ignored `hardware-results/`. See [`scripts/remote/deploy_and_run.py`](scripts/remote/deploy_and_run.py)
and [`.env.example`](.env.example). Never commit real connection values.

## Current limitations

This V1 does not claim calibrated laboratory instrumentation, exhaustive
vendor-specific parsing, hardware qualification, or physical repeatability.
The IPMI and SMART parsers target common generic text forms. No disk workload,
network workload, power-state change, BMC configuration change, SMART
self-test, destructive NVMe command, or threshold modification is performed.
Physical validation is optional and must remain outside Git.

## Public-safe data policy

If data may contain an employer, product, customer, asset, host, address,
credential, serial, MAC, IP, raw inventory, or real DUT evidence, omit it.
Keep characterization guardrails conceptually separate from production
acceptance criteria. Before a public release, follow
[`docs/PUBLIC_RELEASE_CHECKLIST.md`](docs/PUBLIC_RELEASE_CHECKLIST.md), inspect
the complete history, and make only evidence-supported claims. A license is
intentionally not included yet.
