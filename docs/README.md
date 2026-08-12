# Documentation authority map

Use each document according to its declared role:

- [`README.md`](../README.md) describes the current public boundary, supported
  commands, runtime entry points, and delivery status.
- [`release_domain_manifest.json`](../src/windows_solver/data/release_domain_manifest.json)
  is the machine-readable authority for frozen scope, claims, source receipts,
  conventions, and evidence ceilings. [`release-baseline.md`](release-baseline.md)
  is its human reconciliation.
- [`.tasks/`](../.tasks/README.md) is the only live delivery board. Its state
  files and work log control active, next, blocked, completed, and rejected work.
- [`response-replay-powershell.md`](response-replay-powershell.md),
  [`m02-admission-powershell.md`](m02-admission-powershell.md), and
  [`evidence-intake-powershell.md`](evidence-intake-powershell.md) are the
  current operator runbooks.
- `docs/superpowers/` and `docs/keystone/` contain dated design, planning, and
  task-creation records. They preserve the reasoning and scope at the time they
  were written; their headings and checkboxes do not override current code, the
  release manifest, or TaskPlanner.

For M02 specifically, PR #21 superseded the historical 553-leaf,
87-selector, 174-row production plan with the current 212-leaf,
48-selector campaign and 57-row reduction contract. Historical files keep the
old figures only as provenance and must carry a supersession notice when they
would otherwise look executable.
