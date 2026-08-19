# Public Release Checklist

Use this checklist before a future public release. If any information is
uncertain, omit it and resolve the question before changing repository
visibility.

- [ ] Search the current tree and complete reachable history for employer,
      company, product, customer, fixture, and internal-system names.
- [ ] Run an available secrets scanner and inspect suspicious strings manually.
- [ ] Inspect every fixture and example; verify each committed sample is
      synthetic.
- [ ] Confirm no physical result directory, raw capture, log, inventory,
      serial number, MAC address, IP address, hostname, asset tag, credential,
      or customer data is tracked.
- [ ] Confirm `.gitignore` covers environment files, credentials, results,
      captures, inventories, logs, and raw SMART/IPMI/DMI files.
- [ ] Confirm no private source, internal QC procedure, proprietary sequence,
      acceptance criterion, or private limit has been reproduced.
- [ ] Review README, docs, CLI help, and public claims against the code and
      tests.
- [ ] Run pytest, Ruff lint and format checks, compile checks, and ShellCheck
      when available.
- [ ] Build and inspect the wheel and sdist; install the wheel in an isolated
      environment and run CLI and synthetic replay smoke tests.
- [ ] Verify the MIT `LICENSE` is present and package metadata identifies it.
- [ ] Confirm the final worktree and distribution contents contain no local or
      physical artifacts.
- [ ] Make the repository public only after the preceding checks pass.
- [ ] Create a release tag only after the public state is confirmed.

Keep experiment guardrails separate from production acceptance criteria. A
release tag and public visibility are separate final steps.
