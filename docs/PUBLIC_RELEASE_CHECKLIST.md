# Public Release Checklist

Complete this checklist immediately before any public release. Do not add a
license or tag `v0.1.0` until the audit is complete.

- [ ] Grep the repository and history for employer, company, product, customer, fixture, and internal-system names.
- [ ] Run a secrets scan and inspect suspicious high-entropy strings manually.
- [ ] Inspect the complete Git history, not only the current tree.
- [ ] Inspect every fixture and example.
- [ ] Verify every committed example and sample is explicitly synthetic.
- [ ] Verify no physical DUT result directory or raw capture is tracked.
- [ ] Verify no serial number, MAC address, IP address, hostname, asset tag, credential, or customer information is present.
- [ ] Verify `.gitignore` covers environment files, credentials, results, captures, inventories, logs, and raw SMART/IPMI/DMI files.
- [ ] Verify no code was copied from a private repository.
- [ ] Verify no internal QC procedure, acceptance criterion, proprietary sequence, or private limit is reproduced.
- [ ] Verify claims in README and docs are supported by code or tests.
- [ ] Run the complete pytest suite.
- [ ] Run Ruff lint and format checks.
- [ ] Verify CI passes using synthetic fixtures only.
- [ ] Select an appropriate open-source license.
- [ ] Add `LICENSE` only immediately before public release.
- [ ] Tag `v0.1.0` only after the audit and license decision.

If any data is uncertain, omit it. Keep generic characterization guardrails
separate from production acceptance criteria.
