# RFC: <title>

Core contracts in `cogniflow.core` are SemVer'd. Adding a plugin needs no RFC. Changing
or breaking a core contract (a type field, a Protocol signature, a conformance check)
does - it can break every downstream plugin. Copy this template into a PR description.

- **RFC**: short slug
- **Status**: draft | accepted | rejected | superseded
- **Affected contract(s)**: e.g. `FalsificationVerdict`, `AsyncSubstrate.read`
- **SemVer impact**: patch | minor | major (breaking)

## Motivation
What is impossible or wrong today, and why a contract change is the right fix (not a
plugin).

## Proposal
The exact change to the contract and its conformance suite. Show before/after.

## Impact on plugins
Who breaks, and the migration path. A breaking change ships with a deprecation window
where feasible.

## Alternatives
What else was considered, including "do it as a plugin instead".

## Sign-off
- [ ] Maintainer review
- [ ] Conformance suites updated
- [ ] CHANGELOG + version bump
