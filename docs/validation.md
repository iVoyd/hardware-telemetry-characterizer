# Validation Strategy

The project is designed to validate both the characterization logic and the
measurement system that supplies it.

## Unit tests

Unit tests inject filesystem and command adapters to exercise scaling, parsing,
quality states, timing, statistics, identity, and process-control decisions.
They do not access `/sys`, `/proc`, IPMI, SMART, a network DUT, or root-only
interfaces through real hardware.

## Replay tests

`tests/fixtures/scenarios/` contains explicitly synthetic scenarios for normal
single- and three-controller observations, unavailable tools, command timeout,
malformed IPMI output, missing and stale sensors, a thermal guard trigger, a
workload process failure, and the hwmon identity-collision regression.

Replay writes the same `metadata.json`, `samples.csv`, `summary.json`, and
`report.txt` shape as an actual run. This makes CLI and reporting behavior
reviewable without physical evidence.

## Negative and regression tests

Fault tests assert that failures become explicit quality states rather than
being swallowed. The identity regression gives three generic `nvme` hwmon
instances different values and verifies that all three survive normalization
and reporting independently.

## Optional physical validation

An operator may later run the read-only workflow against a separately managed
Linux system and retain results outside Git. Physical validation can reveal
interface compatibility, timing behavior, parser gaps, and operational safety
issues for that environment. It cannot by itself establish calibration,
universal repeatability, product qualification, or production acceptance
limits. Any physical result must be reviewed for privacy and intellectual
property before being shared.
