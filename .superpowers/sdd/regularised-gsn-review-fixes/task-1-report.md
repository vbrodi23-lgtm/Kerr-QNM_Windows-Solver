# Task 1 report

## Scope

Made the raw horizon determinant an explicitly optional diagnostic: a finite,
safe `Cinc/Cref - R` chart is computed and gated before raw evidence is
collected.  A raw subtraction overflow is reported as
`unavailable-overflow/v1`, never clamped or presented as an exact raw
determinant.  Exterior determinants use the distinct
`not-applicable/v1` status.

## Files changed

- `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/src/Homogeneous/Solutions.jl`
- `src/windows_solver/data/julia/GeneralizedSasakiNakamura.jl/test/scaled_scattering_spec.jl`
- `src/windows_solver/data/julia/m02_worker.jl`
- `src/windows_solver/julia_response_backend.py`
- `src/windows_solver/response_engine.py`
- `tests/fixtures.py`
- `tests/test_regularised_gsn_scattering_static.py`

## RED evidence

Before production edits:

```text
python -m unittest tests.test_regularised_gsn_scattering_static.RegularisedGsnScatteringSourceTests.test_safe_chart_precedes_explicit_nonblocking_raw_overflow_evidence

FAIL: raw_determinant::Union{Nothing,Complex{T}} was absent from
DeterminantChartAssessment (the existing field was raw_determinant::Complex{T}).
```

The failing source contract would also require an explicit raw-evidence
status, normalised-chart-before-raw ordering, and the synthetic Julia spec.

## GREEN evidence

```text
PYTHONPATH=src python -m unittest tests.test_regularised_gsn_scattering_static tests.test_regularised_gsn_worker_static tests.test_numerical_conditioning_contract

Ran 73 tests in 3.272s
OK
```

`git diff --check` also exited successfully.

## Execution boundary and limitations

The new Julia spec uses finite near-`floatmax(Float64)` synthetic
coefficients and is intentionally unexecuted in this air-gapped session.  No
Julia, Kerr determinant, PowerShell, solver, or scientific payload was run.
This checkpoint proves static and mocked Python contracts only; native Julia
semantic validation remains a later, explicitly blocked step.

## Commit

`3aee58d` — `fix: keep raw horizon diagnostic nonblocking`
