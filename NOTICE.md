# Notices

## Pure-Kerr spectral lattice

PR #2 packages 2,736 locally polished Kerr QNM roots: 690 for ℓ=2, 966 for
ℓ=3, and 1,080 for ℓ=4. The determinant recurrence is the project’s canonical
Leaver implementation; its numerical depth ceiling was raised to permit
convergence at the most demanding high-spin coordinates. Branch-labelled
initial seeds were generated with `qnm` 0.4.4 under its MIT license. The
applicable notice accompanies the package at
`src/windows_solver/data/LICENSE-QNM-MIT.txt`.

The MIT license at
`src/windows_solver/data/LICENSE-CANONICAL-BACKEND-MIT.txt` applies only to the
canonical offline numerical backend named in that file. It does not alter the
repository's declared project license.

The Motohashi catalog release `v0.2.0` supplies 392 exact-coordinate comparison
values under CC BY 4.0. It does not supply the packaged root values. Its
license and transformation notice accompany the package at
`src/windows_solver/data/LICENSE-CC-BY-4.0.txt`.

The result has no formal root enclosure and carries scientific state
`NOT_EVALUATED`. PR #3 freezes the M01 release and authenticated-evidence
boundary. PR #4 begins the separate `linear-response` migration.
