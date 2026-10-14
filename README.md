# Hardware Telemetry Characterizer

A Python CLI that collects Linux hardware telemetry (temperatures, fans, CPU,
NVMe SMART, IPMI sensors, network counters) and runs controlled
baseline → stimulus → recovery experiments, with every reading tagged by
whether it can be trusted.

## Why I built this

At work I test server hardware, and a lot of that job comes down to reading
sensors and deciding whether a number actually means something. A temperature
that stopped updating, a tool that isn't installed, or two drives reporting
under the same name can all look like a clean reading. I built HTC on my own
time to work through that problem in the open: every measurement records where
it came from and whether it's good, and every run leaves evidence someone else
can review.

## What it does

- Reads hwmon/sysfs channels, `/proc` CPU and system counters, NVMe SMART
  (`smartctl`), IPMI sensors (`ipmitool`), and network interface counters.
- Tags every observation with a quality state: `GOOD`, `MISSING`, `STALE`,
  `TIMEOUT`, `PARSE_ERROR`, `COMMAND_ERROR`, or `UNAVAILABLE`. A missing tool or
  a hung command is recorded, not silently dropped.
- Samples on a fixed schedule and reports the timing it actually achieved.
- Runs a passive observation, or a bounded CPU experiment: baseline, then load
  on ~25% of cores, then recovery, with thermal guardrails that stop the load
  early.
- Replays synthetic scenarios, including fault cases, with no hardware or root.

## Quick start

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

.venv/bin/htc discover                                   # one snapshot of what this machine exposes
.venv/bin/htc characterize --mode passive --duration 10 --interval 2
.venv/bin/htc replay tests/fixtures/scenarios/normal_three_nvme   # no hardware needed

# CPU experiment (requires the explicit flag)
.venv/bin/htc characterize --mode cpu --enable-stimulus \
  --baseline 6 --stimulus-duration 10 --recovery 6 --interval 2
```

`--privileged-read` runs only the `smartctl` and `ipmitool` reads through
`sudo -n`; HTC and its workload never run as root.

## Sample output

Each run writes `metadata.json`, `samples.csv` (every observation, including
non-GOOD ones), `summary.json`, and a `report.txt` like this one from the
three-NVMe replay scenario:

```text
Mode: passive
Samples: 2
Guardrail: not triggered

Timing
------
Expected interval: 1.0 s
Observed interval mean: 1.0 s
Late samples: 0

Channel statistics (GOOD numeric observations)
-----------------------------------------------
passive/nvme0/temp1 [°C]: n=2 min=40 max=40.5 mean=40.25 stdev=0.25
passive/nvme1/temp1 [°C]: n=2 min=42 max=42.5 mean=42.25 stdev=0.25
passive/nvme2/temp1 [°C]: n=2 min=44 max=44.5 mean=44.25 stdev=0.25
```

## What broke on real hardware

The synthetic tests passed from the start. Running against a real Linux server
over SSH is what found these:

- **Drives overwriting each other.** All three NVMe drives exposed hwmon
  entries with the same generic `nvme` name, so their temperatures collapsed
  into one channel. HTC now resolves each entry to its controller (`nvme0`,
  `nvme1`, …), and a regression scenario keeps it that way.
- **Wrong load-average labels.** The 1-, 5-, and 15-minute load averages were
  labeled `load_1m`, `load_2m`, `load_3m` by position. Fixed with explicit names.
- **Recovery measured under load.** The CPU workload could still be running
  when recovery sampling started, which contaminates the recovery data. Recovery
  now waits until shutdown is confirmed and is skipped if it can't be.
- **Utilization smeared across phases.** CPU utilization comes from the
  difference between two `/proc/stat` reads. The first reading of a new phase
  spans the previous phase too, so it's now flagged and kept out of that
  phase's statistics while staying in the raw CSV.
- **Remote run plumbing.** Creating the temporary directory on the target,
  finding the result directory afterward, and running on the target's older
  Python 3.10 all failed in different ways. Each one got a fix and a test.

## Remote workflow

Code, Git, and credentials stay on the development machine. The wrappers deploy
to a temporary directory on the target over SSH, run, and pull the results back
into the ignored `hardware-results/`:

```bash
./scripts/remote/setup_dut.sh            # one-time connection check
./scripts/remote/validate_dut.sh         # 30 s passive run
./scripts/remote/validate_dut.sh --cpu   # CPU experiment, asks you to type CPU to confirm
```

Connection settings live in a local `.env` (see `.env.example`).

## Testing

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src scripts tests
```

CI runs the suite on Python 3.10–3.12 with no root, sensors, or drives. The
replay scenarios cover missing tools, timeouts, malformed IPMI output, stale
and disappearing sensors, a thermal guard trip, a crashed workload, and the
NVMe naming regression. More detail is in [`docs/validation.md`](docs/validation.md),
[`docs/architecture.md`](docs/architecture.md), and
[`docs/measurement-model.md`](docs/measurement-model.md).

## Limitations

- It's a characterization tool, not calibrated instrumentation or a
  qualification test. Guardrails are safety stops, not pass/fail limits.
- It never changes hardware state: no disk or network load, no BMC changes,
  no SMART self-tests.
- Parsing covers common `smartctl` and `ipmitool` output, not every vendor's
  format.
- All committed fixtures are synthetic; real captures stay out of the repo.

## License

MIT. See [`LICENSE`](LICENSE).
