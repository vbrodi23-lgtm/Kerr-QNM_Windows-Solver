# M02 Authenticated Solved-Leaf Cache Implementation Plan

1. Add failing unit tests for empty-store write-through, identical reuse with zero backend calls, scientific identity invalidation, telemetry-only stability, deletion fallback, tamper rejection, stale entries, nonterminal/deep-incomplete rejection, checkpoint import, and checkpoint precedence/order.
2. Implement a small private-store module with strict receipt parsing, canonical hashes, atomic writes, exclusive locking, corruption quarantine, and Windows per-user root resolution.
3. Expose a reusable terminal-record semantic validation boundary and define the per-leaf scientific-computation identity from existing campaign/job contracts.
4. Refactor checkpoint parsing so strict resume remains unchanged while authenticated import can validate records under the current per-leaf scientific contract.
5. Integrate startup lookup, canonical checkpoint hydration, `LEAF_REUSED`, checkpoint-first write-through publication, diagnostics, and cache summaries.
6. Add a CLI checkpoint-import command and operator documentation without packaging private cache contents.
7. Run all synthetic/static tests and a temporary-store acceptance against the attached private checkpoint and status JSON. Never execute the Kerr backend.
8. Review the complete diff, commit intentionally, publish the branch, and open the new PR.
