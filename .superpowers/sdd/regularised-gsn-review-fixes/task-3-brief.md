# Task 3 brief — validate worker success before cache publication

## Goal

Prevent a stale-schema, mechanism-swapped, or otherwise invalid successful worker response from entering and poisoning the root-readout work cache.

## Required workflow

1. Add a failing mocked regression before production changes. It must return `status: ok` with the correct request digest but violate the strict current root-readout/schema or mechanism-conditioning contract.
2. Prove the invalid fresh response is rejected and leaves no reusable cache entry.
3. Move cache publication behind the complete `JuliaPrecisionRootBackend._read_root` validation boundary. Adapter-level checks for status/request digest alone are not sufficient.
4. If a structurally valid cache envelope contains a response that fails the current root-readout contract, invalidate only that exact request/runtime cache entry so the next retry recomputes. Never delete a broad cache directory.
5. Add a regression that seeds such an invalid cached success, observes rejection/invalidation, then retries with a valid mocked worker response and confirms recomputation plus valid retention/reuse.
6. At this same post-validation boundary, retain a versioned worker-response evidence receipt that binds the exact decimal determinant texts to the exact request digest and runtime identity. Persist that receipt in each current promoted `RootReadout`, validate it on reconstruction, and include it in current checkpoint/cache evidence. Add a tamper regression that alters an exact determinant string within the same binary64 bin and reseals the ordinary outer checkpoint hashes but cannot preserve the original worker-response receipt.
7. Preserve generic adapter/cache tests by introducing an explicit post-validation retain operation or equivalent narrow interface; do not pretend adapter-only test payloads are scientific readouts.
8. Be precise about the integrity ceiling: an unkeyed local receipt cannot defend against an adversary who deliberately forges and reseals the receipt itself. Do not claim a detached signature or stronger cryptographic authentication unless one genuinely exists.
9. Run focused mocked Python tests only. Do not execute Julia, PowerShell, Kerr determinants, solver commands, or scientific payloads.
10. Commit locally, do not push.

## Preferred narrow interface

- Add a scientific validation path such as `evaluate_for_validation(request)` that returns the response plus whether it came from cache, without publishing a fresh response.
- Keep the generic adapter `evaluate()` behavior usable by the existing non-scientific cache tests; do not force their deliberately minimal payloads through the Julia root schema.
- After `_read_root` has completed all schema, mechanism, conditioning, branch, and numeric checks, call an explicit `retain_validated_readout(...)` boundary.
- If a reused response fails, invalidate only its exact `(request_sha256, runtime_identity_sha256)` regular-file entry, re-raise, and let the next caller recompute. Never remove a cache directory or unrelated entry.
- Version the root-readout cache directory/envelope rather than silently changing v1.

## Worker-response receipt shape

Use a closed, versioned mapping with at least:

- receipt schema/version;
- full canonical request binding and its SHA-256;
- runtime identity SHA-256;
- successful worker response schema version;
- exact top-level `root_residual_abs`, nullable `raw_determinant_abs`, and `raw_determinant_evidence_status` texts;
- receipt SHA-256 over every other receipt field.

The `RootReadout` must persist this receipt and compare its exact determinant texts to its own `Decimal` values on reconstruction. Current package-owned promoted evidence requires the receipt; explicitly historical/native/recorded evidence may lack it only through an identified compatibility path. Bind the receipt runtime identity to the persisted scientific runtime. If this changes the current checkpoint evidence contract, version that contract/schema honestly rather than letting same-number evidence drift.

## Acceptance

- Fresh invalid success never increases the reusable cache count.
- Invalid cache hit cannot permanently poison later retries.
- A fully validated readout is retained and reused under the exact request/runtime identity.
- Current promoted checkpoint evidence rejects exact-determinant text drift against the retained worker-response receipt even when ordinary outer content hashes are recomputed.
- Cache errors remain non-fatal to recomputation and event reporting remains coherent.

## Report

Write `.superpowers/sdd/regularised-gsn-review-fixes/task-3-report.md` with exact RED/GREEN evidence, files, limitations, and commit SHA; update the Task 3 ledger line.
