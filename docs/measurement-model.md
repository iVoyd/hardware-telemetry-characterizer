# Measurement Model

Every observation is a typed `Measurement` with:

- an aware UTC timestamp;
- source and generic device identity;
- channel name;
- engineering unit;
- numeric, text, or absent value;
- explicit `Quality`; and
- optional error text and generic metadata.

## Identity

Identity must survive multiple instances of a generic driver. The hwmon
collector resolves the symlink-backed sysfs path and uses a generic controller
component such as `nvme0` when available. If resolution is unavailable, it
combines the driver name with the hwmon instance directory, so generic `nvme`
names still do not collapse separate controllers. Network interfaces use
generic interface names. No serial, MAC, hostname, IP, or asset identity is
required by the model.

## Cadence and timing

The sampler schedules against an absolute monotonic timeline. Acquisition time
is therefore accounted for rather than added to every requested sleep. Each
sample records scheduled, start, and finish timestamps. Reports calculate
expected interval, actual minimum/maximum/mean, standard deviation, and late
sample count per phase and overall.

The summary separates experiment sample frames from numeric observations:
`sample_frame_count` counts acquisition frames, while
`numeric_observation_count` counts GOOD numeric channel values used by channel
statistics.

## Transient and steady-state behavior

Passive runs describe observation over time. CPU runs divide evidence into
baseline, bounded stimulus, and recovery phases. Phase-level statistics make
simple transient and steady-state comparisons possible: baseline means,
stimulus maximum/mean deltas, and recovery final/mean deltas. A V1 summary is
descriptive; it does not infer causality beyond the configured experiment.

## Missing, stale, and error data

`GOOD` numeric values are eligible for numeric statistics. `MISSING`, `STALE`,
`TIMEOUT`, `PARSE_ERROR`, `COMMAND_ERROR`, and `UNAVAILABLE` remain in
`samples.csv` and are never silently dropped. Missing optional tooling is an
acquisition condition, not automatically a DUT failure. A user-defined rule or
future analysis may evaluate measurements separately from collector quality.

## Stability and guardrails

Repeatability requires more than a small standard deviation: cadence quality,
channel availability, phase definition, and the measurement system itself must
also be understood. The generic thermal guard is an emergency control for an
active experiment. It is explicitly not a calibrated thermal limit,
qualification limit, or production acceptance criterion.
