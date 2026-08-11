# M02 Practical High-Precision Policy Implementation Plan

> **For agentic workers:** Execute inline and test-first. Do not delegate or run
> Julia, PowerShell, determinants, radial integration, the Kerr solver, or a
> mathematical campaign.

**Goal:** Keep 80-decimal-digit BigFloat arithmetic while replacing its
10⁻⁶²-class solve demand with a coherent 10⁻¹⁸–10⁻²⁰ policy and make every
dashboard precision label unit-aware.

**Architecture:** Define the 80-tier request controls at the existing Julia
adapter boundary, bind their exact values into the canonical PRIMARY precision
contract, and extend exact success-only migration to the immediately preceding
recovery identity. Reuse PR #32's live progress projection and change only its
precision presentation plus the report table's display-only threshold.

**Tech stack:** Python 3.12 standard library, existing Julia request schema,
canonical JSON/SHA-256 identities, `unittest`, TaskPlanner 2.1.1.

## Global Constraints

- BigFloat 80 remains 80 decimal digits and 298 working bits.
- The 120-digit request policy and all promotion/terminal-state gates remain
  unchanged.
- Only exact one-stage authenticated binary64 successes may cross a prior
  precision-policy identity.
- Existing `@@KERR_QNM_PROGRESS@@` events remain the only worker protocol.
- No mathematical or cross-language workload may run in this implementation.

---

### Task 1: Freeze the 80-tier request bundle

**Files:**
- Modify: `tests/test_julia_response_backend.py`
- Modify: `src/windows_solver/julia_response_backend.py`

- [ ] Assert the base 80 request contains root/relative 10⁻¹⁸, absolute 10⁻²⁰,
  derivative step 10⁻⁶, 80 decimal digits, and 298 bits.
- [ ] Assert the refined 80 request contains root/relative/absolute 10⁻²⁰ and
  derivative step 10⁻⁷.
- [ ] Assert both 120 request bundles retain their current exact values.
- [ ] Run the focused request tests red, implement the smallest policy table,
  and rerun them green.

### Task 2: Bind the policy and preserve binary64 preload compatibility

**Files:**
- Modify: `tests/test_solved_leaf_cache.py`
- Modify: `tests/test_linear_response_precision.py`
- Modify: `src/windows_solver/response_batches.py`

- [ ] Assert the canonical PRIMARY contract contains the exact tier controls
  and changes the checkpoint binding.
- [ ] Assert a one-stage binary64 success under the immediately preceding
  recovery identity migrates to the new identity without stage execution.
- [ ] Assert an old promoted or unresolved receipt is not migrated or treated
  as current scientific evidence.
- [ ] Keep the older binary64-only success migration path green.
- [ ] Run the focused identity/cache tests red, implement exact predecessor
  lookup, and rerun them green.

### Task 3: Complete unit-aware dashboard presentation

**Files:**
- Modify: `tests/test_campaign_reports.py`
- Modify: `src/windows_solver/campaign_reports.py`
- Modify: `src/windows_solver/progress_output.py`

- [ ] Assert the completed-stage table renders `binary64 (~15.95 dec)`,
  `BigFloat 80 dec`, and `BigFloat 120 dec` rather than bare integers.
- [ ] Assert BigFloat 80 `D_OVER_TOL` uses 10⁻¹⁸ while binary64 and BigFloat
  120 retain their declared thresholds.
- [ ] Preserve the separate completed/executing/live panels and heartbeat
  cadence.
- [ ] Run the focused report test red, widen the fixed-width table minimally,
  and rerun it green.

### Task 4: Structural verification and PR handoff

**Files:**
- Modify: `.tasks/IN_PROGRESS.md`
- Add: this design and plan

- [ ] Run only the relevant synthetic Python suites, Python compilation,
  TaskPlanner validation, and `git diff --check`.
- [ ] Review the exact diff for policy, identity, cache, and UI regressions.
- [ ] Commit and publish the verified changes to a new PR #33 branch created
  directly from post-PR-#32 `main`; do not merge.
- [ ] Hand mathematical execution back to the user's local PowerShell campaign.
