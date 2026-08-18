# Project Rules

This repository is intended for eventual public release. Keep every committed
file independently authored, generic, and safe to publish.

- Never add employer, company, product, customer, fixture, or internal-system names.
- Never copy code from private employer repositories or derive implementation by copying private source.
- Never reproduce internal QC procedures, proprietary test sequences, acceptance criteria, limits, or part-number mappings.
- Never commit actual DUT logs, captures, configurations, or raw physical-hardware evidence.
- Never commit serial numbers, MAC addresses, IP addresses, hostnames, credentials, asset tags, or customer data.
- Never commit raw SMART, IPMI FRU, DMI, inventory, or similar physical-machine captures.
- Physical hardware results and captures must remain in gitignored directories.
- Committed fixtures and examples must be explicitly synthetic and use generic identifiers only.
- Linux hwmon/sysfs, `/proc`, IPMI, SMART, ethtool, SSH, and other generic standards-based interfaces are acceptable.
- Never hard-code DUT connection information, credentials, device paths, or customer-specific values.
- Before any public release, perform a repository-wide privacy, intellectual-property, and secrets audit.
- If uncertain whether data is safe to publish, omit it.
- Do not invent physical validation, calibration, repeatability, or performance claims.
- Keep characterization guardrails separate from production acceptance or qualification criteria.
- Read-only collection is the default; active CPU stimulus must be explicit, bounded, and cleaned up on every exit path.

Before release, inspect the complete Git history as well as the working tree and follow
`docs/PUBLIC_RELEASE_CHECKLIST.md`.
