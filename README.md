# Hardware Telemetry Characterizer

Hardware Telemetry Characterizer (`htc`) is a Python CLI for Linux hardware
telemetry and controlled characterization experiments. It collects observations
through standard Linux interfaces, normalizes them into typed measurements, and
produces artifacts that make a baseline, stimulus, and recovery run reviewable.

Monitoring asks what the sensors read. Characterization asks how a system
responds to a controlled condition, whether that response is repeatable, and
what evidence supports the conclusion. HTC is built for the second question;
it is not a monitoring dashboard.

## What it does

- Collects hwmon/sysfs temperatures and hardware channels, CPU and system
  counters, IPMI sensors, NVMe SMART data, and network interface counters.
- Preserves source, device identity, engineering units, timestamps, values, and
  acquisition quality in one measurement model.
- Samples against an absolute schedule and reports actual cadence and timing
  statistics.
- Runs passive observations or a bounded CPU baseline/stimulus/recovery
  experiment.
- Records unavailable tools, timeouts, stale data, command failures, and parse
  failures instead of silently dropping them.
- Supports synthetic replay and fault injection without hardware or root.

## Platform and dependencies

HTC runs on Linux with Python `>=3.10`. Core system telemetry uses standard
`/proc` and `/sys` interfaces, including `/proc/stat`, load averages, memory
information, cpufreq when exposed, and the logical CPU count. hwmon/sysfs
temperatures and other channels are available when the running kernel and
platform expose them. Network counters come from Linux sysfs interfaces.

SMART/NVMe collection uses `smartctl` when installed, and local IPMI sensor
collection uses `ipmitool` when installed. The optional `--privileged-read`
flag applies `sudo -n` only to those SMART and IPMI reads; HTC itself and the
CPU workload remain unprivileged. The remote workflow uses SSH and prefers
rsync, with an scp/archive fallback.

The collectors are capability-based rather than tied to a server vendor or
model. If a tool or interface is unavailable, HTC records the acquisition
state—often as `UNAVAILABLE`—and continues collecting other channels. That
condition is not automatically treated as a DUT failure.

## Architecture

Collectors normalize Linux interfaces into measurements. The experiment engine
schedules collection, controls phase transitions, applies generic safety
guardrails, and delegates statistics and reporting. See
[`docs/architecture.md`](docs/architecture.md) and
[`docs/measurement-model.md`](docs/measurement-model.md).

## CPU characterization

CPU mode collects a baseline, starts a bounded worker set, observes the
stimulus, stops every worker, and then collects recovery. The default workload
uses roughly 25% of logical CPUs and performs no disk or network I/O or
persistent configuration changes. `--enable-stimulus` is required, and the
remote wrapper also requires an operator to type `CPU` at its confirmation
prompt.

Thermal guards are safety controls for an active experiment, not DUT
qualification or production acceptance limits. A baseline guard prevents the
workload from starting. A stimulus guard or worker failure stops the workload
before recovery; interruptions and exceptions still clean up. If shutdown is
uncertain, recovery collection is withheld.

`cpu_utilization` is derived from an interval between `/proc/stat` samples. If
that interval crosses a phase boundary, HTC retains the raw GOOD measurement,
marks its metadata, and excludes it from phase-specific statistics. Instantaneous
first-frame measurements are not excluded.

## Collectors and quality

The hwmon collector resolves sysfs paths to controller identities such as
`nvme0` and `nvme1` when possible, with an instance-based fallback when path
resolution is unavailable. This keeps multiple controllers with the same
generic driver name independent. IPMI and SMART parsers retain acquisition
quality separately from any interpretation of DUT health.

Quality states include `GOOD`, `MISSING`, `STALE`, `TIMEOUT`, `PARSE_ERROR`,
`COMMAND_ERROR`, and `UNAVAILABLE`.

## Run artifacts

Each run creates a timestamped directory containing:

```text
metadata.json   configuration and run metadata
samples.csv     every normalized observation, including non-GOOD quality
summary.json    sample frames, timing, channel statistics, and phase deltas
report.txt      human-readable summary
```

Raw physical results belong under ignored `hardware-results/`. Committed
examples and replay scenarios are synthetic.

## Quick start

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

# One snapshot from the capabilities available on this Linux system.
.venv/bin/htc discover

# Optional read-only SMART/IPMI access through non-interactive sudo -n.
.venv/bin/htc discover --privileged-read

# Passive observation; output goes below ignored results/.
.venv/bin/htc characterize --mode passive --duration 10 --interval 2

# Synthetic operation with no hardware or root access.
.venv/bin/htc replay tests/fixtures/scenarios/normal_three_nvme
.venv/bin/htc report results/<run-directory>
```

For a bounded CPU run:

```bash
.venv/bin/htc characterize --mode cpu --enable-stimulus \
  --baseline 6 --stimulus-duration 10 --recovery 6 --interval 2
```

## Remote Linux workflow

Development, Git, and credentials remain on the local development machine. Set
up the connection once, then use the wrappers around the same deployment helper:

```bash
# One-time connection and read-only prerequisite check.
./scripts/remote/setup_dut.sh

# Passive validation: 30 seconds at a 2-second interval.
./scripts/remote/validate_dut.sh

# Optional read-only SMART/IPMI access.
./scripts/remote/validate_dut.sh --privileged-read

# Controlled CPU characterization with interactive confirmation.
./scripts/remote/validate_dut.sh --cpu
```

The wrappers read connection settings from the local `.env`, use one SSH
transport for SSH, rsync, and scp, deploy to a temporary remote directory, and
retrieve results under ignored `hardware-results/`. Passive duration and CPU
phase durations are separate options. `--privileged-read` never runs HTC or its
workload under sudo. See the helpers and [`.env.example`](.env.example) for the
available configuration names; do not commit real connection values.

## Development and validation

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src scripts tests
.venv/bin/ruff format --check src scripts tests
```

CI runs the synthetic suite on Python 3.10, 3.11, and 3.12 without root,
IPMI hardware, NVMe devices, a network DUT, or physical evidence. The testing
strategy is documented in [`docs/validation.md`](docs/validation.md).

## Limitations and data policy

HTC is not calibrated laboratory instrumentation and does not claim exhaustive
vendor-specific parsing, hardware qualification, or universal repeatability.
It performs no disk or network workload, power-state change, BMC configuration
change, SMART self-test, destructive NVMe command, or threshold modification.
Physical validation can reveal behavior and interface compatibility for the
tested environment, but its results stay outside Git and do not establish
qualification or production acceptance limits.

Keep committed fixtures synthetic. Omit any real identifiers, credentials,
inventory, or physical capture that is not safe to publish.

## License

This project is available under the MIT License. See [`LICENSE`](LICENSE).
