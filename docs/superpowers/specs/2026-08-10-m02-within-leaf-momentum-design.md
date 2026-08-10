# M02 Within-Leaf Momentum Design

## Scope

Add optional PRIMARY-root predictors to the existing 212-leaf M02 component engine. This first increment is limited to continuation along the four signed ε rays inside one leaf. It does not change the campaign domain, campaign order, shared baselines, neighbouring-spin/κ continuation, or projective reduction.

## Execution contract

`run_component()` keeps one accepted root per signed ray. For each finer ε on that ray it proposes

`ω_seed,new = ω₀ + (ε_new/ε_old)(ω_old − ω₀)`.

The root-readout boundary becomes `read_root(job, amplitude, primary_predictor=None)`. The predictor affects only PRIMARY. TRUNCATION and RESOLUTION continue from the accepted PRIMARY result as before. SEED-PATH continues from its independently displaced authenticated-background seed.

The backend admits a predictor when it is finite and remains within the existing absolute branch-continuation radius. It does not spend an additional background determinant evaluation to compare seeds. The normal PRIMARY Newton solve starts from the admitted predictor. If that attempt fails to converge or escapes the existing branch neighbourhood, PRIMARY records the failed attempt and retries from the authenticated background. Out-of-branch or non-finite predictors fall back before determinant work.

## Evidence and compatibility boundaries

Predictors and seed telemetry are disposable execution state. They are not serialized into `RootReadout`, `ComponentResult`, campaign checkpoints, uncertainty channels, or solved-leaf scientific identities. Historical solved-leaf records remain canonical and cache-compatible.

No determinant solve, refinement phase, tolerance, ε value, uncertainty channel, precision rule, or acceptance condition is removed or weakened.

## Telemetry

Progress records expose the selected seed kind, seed ω, initial determinant magnitude, fallback state, Newton iterations, determinant calls, resulting ω/residual, and elapsed time. Every completed root phase is appended to `<checkpoint>.progress/root-solves.jsonl`, including in normal progress mode. The live status aggregates PRIMARY solves by seed kind and reports the observed determinant-call difference between ε-continuation solves and authenticated-background solves. This is measurement, not a claim of causal speedup.

## Deferred work

- shared mode-spin zero-amplitude baselines;
- primary/control continuation across spin;
- deep continuation across κ;
- campaign traversal reordering;
- intermediate diagnostic projective reductions.

Shared baselines and cross-spin/κ continuation remain separate changes pending the user's Windows evidence from this increment. Campaign reordering remains an independently required fail-fast increment even if within-leaf continuation shows no runtime benefit.
