# M02 Mechanism-Local Traversal and Spin Momentum Design

## Purpose

Run the frozen 212-leaf M02 domain in an order that preserves computational
momentum and exposes projective evidence early, without changing any
scientific calculation or identity.

## Protected scientific state

- Keep `B_PRIME_RELEASE_DOMAIN.production_leaves` and every leaf ID unchanged.
- Keep `CampaignPlan.leaves`, campaign ID, selection ID, checkpoint schema,
  scientific-computation identity, response jobs, policies, thresholds,
  uncertainty construction, acceptance, and projective reduction unchanged.
- Keep the authenticated background QNM root of each new spin as the zero and
  branch anchor for that leaf.
- Keep TRUNCATION and RESOLUTION seeded from accepted PRIMARY and keep
  SEED-PATH independently seeded from the authenticated background root.
- Existing terminal leaf records remain valid and reusable.

## Execution traversal

The runner derives a separate execution schedule from the selected leaf IDs.
The authenticated selection remains in its existing canonical order.

Role order prioritizes hypothesis-bearing rows before controls:

1. primary
2. deep
3. control

Within each role the schedule is mechanism, then mode, then ascending physical
spin. Direct coordinates therefore run `.95 → .99 → .999 → .9999`. The deep
Mκ coordinates run `.01 → .002 → .001`, because decreasing Mκ is increasing
Kerr spin toward extremality.

Primary mechanism order:

1. `horizon-admittance`
2. `exterior-light-ring`
3. `exterior-throat-kappa`
4. `exterior-alpha-half`
5. `exterior-fixed-r3`

Primary mode order:

1. 220
2. 440
3. 330
4. 221
5. 441
6. 331
7. 222

Deep order is mechanism-local with `220 → 221 → 222 → 210`, completing K22
before its control mode. Control modes retain their declared order. Deep and
control mechanism order is the applicable subsequence of horizon,
light-ring, throat-kappa, alpha-one/alpha-half, fixed-r3.

## Checkpoint compatibility

Partial checkpoints may contain any authenticated subset of the selection,
serialized in canonical selection order. The existing prefix form remains a
valid subset. Execution indexes records by leaf ID, skips terminal records,
and writes the current subset in canonical order after every successful
stage. No checkpoint field or schema version is added.

This permits an old-order checkpoint to resume directly. Its existing record
objects are not rewritten or reinterpreted; only newly produced records are
added.

## Cross-spin continuation

One invocation-local predictor state is maintained for each exact chain:

`(role, mode, mechanism, coordinate role)`

Only a terminal `PRODUCED` record with a finite response centre advances the
chain. A reused authenticated record may advance it. `UNRESOLVED`, rejected,
missing, or non-finite evidence clears that chain so momentum never jumps an
unresolved coordinate.

For the next higher-spin coordinate in the same chain, response coefficient `r_prev`
predicts only the PRIMARY displacement:

`ω_seed = ω₀,new + amplitude × r_prev`

The coarse signed rays use this spin predictor. Finer amplitudes then use the
existing within-leaf signed-ray continuation. The baseline still starts at
`ω₀,new`. No response is carried between modes, mechanisms, roles, direct-spin
and Mκ coordinates, or different component chains.

Predictor rejection/fallback uses the existing finite/radius screening and
normal Newton failure/branch-escape path. It adds no comparison determinant
preflight.

## Telemetry and proof

PRIMARY seed telemetry distinguishes `SPIN_CONTINUATION` from
`EPSILON_CONTINUATION`; fallback remains `FALLBACK_BACKGROUND`. Binary64 and
Julia promoted-precision adapters carry the same seed-kind contract. Tests
must prove exact traversal, old-checkpoint resume, cache-fed prediction,
same-chain isolation, authenticated-background anchoring, independent
SEED-PATH, no dual determinant preflight, and unchanged historical
scientific-computation identity.

No Kerr, Julia, determinant, or campaign workload is executed in development.
