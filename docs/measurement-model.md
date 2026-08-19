# Measurement Model

Every observation is a typed `Measurement` with:

- an aware UTC timestamp;
- source and device identity;
- channel name and engineering unit;
- a numeric, text, or absent value;
- an explicit `Quality` state; and
- optional error text and metadata.

## Identity

Identity must distinguish multiple instances of the same driver. The hwmon
collector resolves the symlink-backed sysfs path and uses a controller
component such as `nvme0` when available. If resolution is unavailable, it
combines the driver name with the hwmon instance directory. Network interfaces
use their generic interface names. The model does not require serial numbers,
MAC addresses, hostnames, IP addresses, or asset identifiers.

## Cadence and timing

The sampler schedules against an absolute monotonic timeline, so acquisition
time is accounted for rather than added to every requested sleep. Each sample
records scheduled, start, and finish timestamps. Reports calculate the
requested interval, actual minimum/maximum/mean, standard deviation, and late
sample count per phase and overall.

The summary separates experiment frames from channel observations:

- `sample_frame_count` counts acquisition frames;
- `numeric_observation_count` counts all GOOD numeric channel values;
- `phase_statistic_observation_count` counts values included in phase
  statistics; and
- `phase_boundary_interval_count` counts tagged interval observations.

## Phase boundaries and derived values

CPU utilization is derived from the interval between `/proc/stat` samples. The
first value in a new CPU phase can therefore span the preceding phase. HTC keeps
that raw GOOD value in `samples.csv` and adds metadata identifying the previous
and current phases. Tagged boundary values are excluded from per-phase channel
statistics and phase deltas. Their presence remains visible through the total
and boundary counts above.

This rule applies to the known interval-derived system CPU-utilization channel,
not to every channel with the same display name. Instantaneous measurements—
such as temperature, frequency, fan speed, memory, SMART, IPMI, and voltage—
remain eligible when they are the first observation in a phase.

Passive runs have no phase transition and do not add boundary metadata.

## Transient and steady-state behavior

CPU runs divide observations into baseline, bounded stimulus, and recovery.
Phase statistics support simple comparisons such as baseline means, stimulus
maximum/mean deltas, and recovery final/mean deltas. A V1 summary is
descriptive; it does not infer causality beyond the configured experiment.

## Missing, stale, and error data

`GOOD` numeric values are eligible for numeric statistics. `MISSING`, `STALE`,
`TIMEOUT`, `PARSE_ERROR`, `COMMAND_ERROR`, and `UNAVAILABLE` remain in
`samples.csv`; acquisition failures are not silently dropped. Missing optional
tooling is an acquisition condition, not automatically a DUT failure. A
user-defined rule or later analysis can evaluate measurements separately from
collector quality.

## Stability and guardrails

Repeatability requires more than a small standard deviation. Cadence quality,
channel availability, phase definition, and the measurement system itself also
matter. The thermal guard is an emergency control for an active experiment. It
is not a calibrated thermal limit, qualification limit, or production
acceptance criterion.
