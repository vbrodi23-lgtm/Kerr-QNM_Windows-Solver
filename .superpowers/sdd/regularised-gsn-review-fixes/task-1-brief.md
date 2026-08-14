# Task 1 brief — non-blocking raw horizon determinant evidence

## Goal

Make the raw horizon determinant diagnostic incapable of aborting a finite, safe normalised horizon chart when large finite coefficients overflow in the raw subtraction.

## Reviewer evidence

`Solutions.jl` currently computes `Cinc - reflectivity*Cref` and asserts it is finite before it forms the safer `Cinc/Cref - reflectivity`. Finite near-floatmax coefficients can therefore overflow only the raw diagnostic while the normalised chart remains finite and well-conditioned.

## Required workflow

1. Work test-first. Add a runnable Python static/source contract that fails on the current implementation. Also add an air-gapped Julia behavioural specification using finite near-floatmax synthetic coefficients whose raw subtraction overflows while the normalised ratio remains finite.
2. Record the Python static RED failure before changing production code.
3. Establish `Cref` chart safety and compute/validate the normalised determinant first.
4. Collect raw diagnostic evidence without letting overflow block the normalised result. Represent unavailable or saturated evidence explicitly and honestly; do not clamp an overflowed value and present it as an exact raw determinant.
5. Propagate any representation change through worker output, Python schema/readout validation, public contracts, and tests as narrowly as necessary. Prefer a versioned explicit status/availability field over ambiguous nullability. Do not weaken exterior/horizon mechanism separation or exact promoted determinant requirements.
6. Run only focused mocked/static Python tests. Do not execute Julia, PowerShell, solver code, Kerr determinants, or any scientific payload.
7. Commit the reviewed task changes with a focused commit. Do not push.

## Acceptance

- The normalised horizon chart is computed and gated before raw diagnostic collection.
- The synthetic overflow case specifies success of the normalised chart and explicit raw-unavailable/saturated evidence.
- Existing finite raw-diagnostic cases retain their evidence.
- Current response/checkpoint validation cannot confuse unavailable raw evidence with an exterior determinant family.
- Focused mocked/static Python tests pass; Julia spec is present but unexecuted.
- Report exact files, tests, RED/GREEN evidence, limitations, and commit SHA.
