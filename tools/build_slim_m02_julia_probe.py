#!/usr/bin/env python3
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = Path(sys.argv[1]).resolve()
SRC = ROOT / "src" / "windows_solver" / "data" / "julia"

if STAGE.exists():
    shutil.rmtree(STAGE)
(STAGE / "project").mkdir(parents=True)
(STAGE / "vendor").mkdir(parents=True)

# Deliberately stage the exact current environment first. No dependency
# trimming, no source edits, no resolver surgery. The subsequent workflow
# traces real file accesses and prunes only what the exercised solver never
# touches.
shutil.copy2(SRC / "m02_project" / "Project.toml", STAGE / "project" / "Project.toml")
shutil.copy2(SRC / "m02_project" / "Manifest.seed.toml", STAGE / "project" / "Manifest.toml")
shutil.copytree(SRC / "GeneralizedSasakiNakamura.jl", STAGE / "vendor" / "GeneralizedSasakiNakamura.jl")
shutil.copytree(SRC / "SpinWeightedSpheroidalHarmonics.jl", STAGE / "vendor" / "SpinWeightedSpheroidalHarmonics.jl")

for name in (
    "m02_worker.jl",
    "m02_worker_finite_difference_spec.jl",
    "m02_worker_fixed_root_diagnostic_spec.jl",
    "m02_worker_request_contract_spec.jl",
):
    shutil.copy2(SRC / name, STAGE / name)

# Some vendored GSN specs intentionally locate the worker two directories up
# from their test directory, matching the repository layout. Mirror that
# location inside this throwaway stage as well.
shutil.copy2(SRC / "m02_worker.jl", STAGE / "vendor" / "m02_worker.jl")

print(STAGE)
