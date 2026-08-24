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

# Keep the historical full manifest only as a version-comparison oracle.
# The slim environment must be resolved cleanly from the reduced project.
shutil.copy2(SRC / "m02_project" / "Manifest.seed.toml", STAGE / "project" / "Manifest.seed.toml")
shutil.copytree(SRC / "GeneralizedSasakiNakamura.jl", STAGE / "vendor" / "GeneralizedSasakiNakamura.jl")
shutil.copytree(SRC / "SpinWeightedSpheroidalHarmonics.jl", STAGE / "vendor" / "SpinWeightedSpheroidalHarmonics.jl")
shutil.copy2(SRC / "m02_worker.jl", STAGE / "m02_worker.jl")

(STAGE / "project" / "Project.toml").write_text('''[deps]
GeneralizedSasakiNakamura = "7d2aac85-6cc1-40c7-a4aa-e1a43f13f131"
JSON = "682c06a0-de6a-54ab-a142-c8b1cf79cde6"
OrdinaryDiffEqRosenbrock = "43230ef6-c299-4910-a778-202eb28ce4ce"
OrdinaryDiffEqVerner = "79d7bb75-1356-48c1-b8c0-6832512096c2"
SciMLBase = "0bca4576-84f4-4d90-8ffe-ffa030f20462"
SpinWeightedSpheroidalHarmonics = "680e17a6-2a17-48fd-ae01-e2b5a643bef0"

[compat]
JSON = "=1.6.1"
OrdinaryDiffEqRosenbrock = "=1.31.1"
OrdinaryDiffEqVerner = "=1.14.0"
SciMLBase = "=2.155.1"
julia = "1.10"
''', encoding="utf-8")

gsn = STAGE / "vendor" / "GeneralizedSasakiNakamura.jl"
(gsn / "Project.toml").write_text('''name = "GeneralizedSasakiNakamura"
uuid = "7d2aac85-6cc1-40c7-a4aa-e1a43f13f131"
version = "0.9.0"
authors = ["Rico Ka Lok Lo", "Yucheng Yin"]

[deps]
ForwardDiff = "f6369f11-7733-5829-9624-2563aa707210"
HypergeometricFunctions = "34004b35-14d8-5ef3-9330-4cdb6864b03a"
Interpolations = "a98d9a8b-a2ab-59e6-89dd-64a1c18fca59"
LinearAlgebra = "37e2e46d-f89d-539d-b4ee-838fcccc9c8e"
Logging = "56ddb016-857b-54e1-b83d-db4d58db5568"
LoggingExtras = "e6f89c97-d47a-5376-807f-9c37f3926c36"
OrdinaryDiffEqRosenbrock = "43230ef6-c299-4910-a778-202eb28ce4ce"
OrdinaryDiffEqVerner = "79d7bb75-1356-48c1-b8c0-6832512096c2"
Roots = "f2b01f46-fcfa-551c-844a-d8ac1e96c665"
SciMLBase = "0bca4576-84f4-4d90-8ffe-ffa030f20462"
SpinWeightedSpheroidalHarmonics = "680e17a6-2a17-48fd-ae01-e2b5a643bef0"
StaticArrays = "90137ffa-7385-5640-81b9-e52037218182"
TaylorSeries = "6aa5eb33-94cf-58f4-a9d0-e4b2c4fc25ea"

[compat]
ForwardDiff = "^0.10"
HypergeometricFunctions = "^0.3.23"
Interpolations = "0.15, 0.16"
LoggingExtras = "1.2.0"
OrdinaryDiffEqRosenbrock = "=1.31.1"
OrdinaryDiffEqVerner = "=1.14.0"
Roots = "2"
SciMLBase = "=2.155.1"
SpinWeightedSpheroidalHarmonics = "^1"
StaticArrays = "^1.9.11"
TaylorSeries = "^0.18"
julia = "^1.10"

[extras]
Test = "8dfed614-e22c-5e08-85e1-65c5234f0b40"

[targets]
test = ["Test"]
''', encoding="utf-8")

# The production M02 worker only uses the homogeneous/complex-frequency GSN path.
gsn_module = gsn / "src" / "GeneralizedSasakiNakamura.jl"
text = gsn_module.read_text(encoding="utf-8")
text = text.replace('export GSN_pointparticle_mode, Teukolsky_pointparticle_mode # Inhomogeneous solutions\n', '')
marker = 'include("Inhomogeneous/AsymptoticExpansionCoefficientsY.jl")'
if marker not in text:
    raise SystemExit("GSN inhomogeneous marker not found")
text = text.split(marker, 1)[0].rstrip() + "\n\nend\n"
text = text.replace('using DifferentialEquations # Should have been compiled by now', 'using SciMLBase\nusing OrdinaryDiffEqVerner\nusing OrdinaryDiffEqRosenbrock')
gsn_module.write_text(text, encoding="utf-8")

ode_import = 'using SciMLBase\nusing OrdinaryDiffEqVerner\nusing OrdinaryDiffEqRosenbrock'
for rel in (
    "src/Homogeneous/Solutions.jl",
    "src/Homogeneous/ComplexFrequencies.jl",
):
    path = gsn / rel
    text = path.read_text(encoding="utf-8")
    text = text.replace("using DifferentialEquations", ode_import)
    text = text.replace("DifferentialEquations.SciMLBase.", "SciMLBase.")
    path.write_text(text, encoding="utf-8")

# Keep the numerical factored-propagation spec runnable against the reduced imports.
spec = gsn / "test" / "factored_propagation_spec.jl"
text = spec.read_text(encoding="utf-8")
text = text.replace("using DifferentialEquations", "using SciMLBase")
text = text.replace("DifferentialEquations.SciMLBase.", "SciMLBase.")
spec.write_text(text, encoding="utf-8")

swsh = STAGE / "vendor" / "SpinWeightedSpheroidalHarmonics.jl"
(swsh / "Project.toml").write_text('''name = "SpinWeightedSpheroidalHarmonics"
uuid = "680e17a6-2a17-48fd-ae01-e2b5a643bef0"
version = "1.3.0"
authors = ["Rico Ka Lok Lo"]

[deps]
LinearAlgebra = "37e2e46d-f89d-539d-b4ee-838fcccc9c8e"

[compat]
julia = "^1.10"

[extras]
Test = "8dfed614-e22c-5e08-85e1-65c5234f0b40"

[targets]
test = ["Test"]
''', encoding="utf-8")
(swsh / "src" / "SpinWeightedSpheroidalHarmonics.jl").write_text('''module SpinWeightedSpheroidalHarmonics

using LinearAlgebra

include("spectral.jl")

export spin_weighted_spheroidal_eigenvalue
export spin_weighted_spherical_eigenvalue
export Teukolsky_lambda_const

function spin_weighted_spheroidal_eigenvalue(s::Int, l::Int, m::Int, c; N::Int=-1)
    if N == -1
        N = _determine_matrix_size_N(s, l, m)
    end
    return Teukolsky_lambda_const(c, s, l, m, N)
end

function spin_weighted_spherical_eigenvalue(s::Int, l::Int, m::Int=0)
    return Teukolsky_lambda_const(0, s, l, m)
end

end
''', encoding="utf-8")

worker = STAGE / "m02_worker.jl"
text = worker.read_text(encoding="utf-8")
text = text.replace("using DifferentialEquations", ode_import)
worker.write_text(text, encoding="utf-8")

print(STAGE)
