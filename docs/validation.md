# Validation Strategy

HTC validates both its characterization logic and the measurement system
interfaces that supply it. The supported runtime is Python `>=3.10`; CI runs
the synthetic suite on Python 3.10, 3.11, and 3.12.

## Unit tests

Unit tests replace filesystem and command interfaces to exercise scaling,
parsing, quality states, timing, statistics, identity, and process control.
They do not access `/sys`, `/proc`, IPMI, SMART, a network DUT, or root-only
interfaces on real hardware. CPU safety tests verify that workload stop is
observable before the first recovery sample.

## Replay tests

`tests/fixtures/scenarios/` contains synthetic scenarios for normal
single- and three-controller observations, unavailable tools, command timeout,
malformed IPMI output, missing and stale sensors, thermal guard activation,
workload failure, and the hwmon identity-collision regression. SMART fixtures
cover percentages, thousands separators, hexadecimal values, and textual
health results.

Replay writes the same `metadata.json`, `samples.csv`, `summary.json`, and
`report.txt` shape as an actual run. This makes CLI and reporting behavior
reviewable without physical evidence.

## Negative and regression tests

Fault tests turn failures into quality states instead of swallowing them. The
identity regression gives three generic `nvme` hwmon instances different values
and verifies that all survive normalization and reporting independently.
Privileged-read tests verify the exact shell-free `sudo -n smartctl` and
`sudo -n ipmitool` argument vectors, while default tests verify that no sudo
prefix is used.

CPU experiment tests cover normal completion, thermal guards, worker failure,
interrupts, exceptions, shutdown failure, phase-boundary interval metadata,
and exclusion of boundary values from phase statistics.

## Physical validation

Physical validation can be run against a separately managed Linux system while
results are retained outside Git. It can reveal interface compatibility,
timing behavior, parser gaps, and operational issues for the tested
environment. It does not establish universal hardware compatibility,
calibration, universal repeatability, product qualification, or production
acceptance limits. Any physical result should be reviewed for privacy and
intellectual property before it is shared.
