from fractions import Fraction


EXPECTED_KAPPA_SPINS = {
    Fraction(1, 100): (0.999791731748236, "0x1.ffe4b3ad56fa5p-1"),
    Fraction(1, 200): (0.9999489834961278, "0x1.fff9502b91917p-1"),
    Fraction(1, 500): (0.9999919355814243, "0x1.fffef1672c027p-1"),
    Fraction(1, 1000): (0.9999979919739198, "0x1.ffffbc9f2ff3bp-1"),
}


def expected_lattice_keys() -> set[tuple[int, int, int, int, int]]:
    """Return the approved pure-Kerr lattice with canonical rational χ keys."""

    high = {
        Fraction(97, 100), Fraction(49, 50), Fraction(99, 100),
        Fraction(199, 200), Fraction(997, 1000), Fraction(999, 1000),
    }
    keys = set()
    for ell in (2, 3, 4):
        spins = (
            {Fraction(19 * i, 780) for i in range(40)} | high
            if ell in (2, 3)
            else {Fraction(i, 52) for i in range(40)}
        )
        for m in range(-ell, ell + 1):
            for n in range(3):
                for spin in spins:
                    keys.add((ell, m, n, spin.numerator, spin.denominator))
    return keys


VALID_STUDY = {
    "schema_version": 1,
    "target": "problem-contract",
    "theory_id": "general-relativity",
    "convention_id": "kerr-mass-normalized-outgoing",
    "modes": [
        {
            "s": -2,
            "ell": 2,
            "m": 2,
            "n": 0,
            "branch": "damped",
            "polarization": "plus",
        }
    ],
    "spins": [0.0, 0.7],
    "evidence_profile": "research",
    "numerical_policy": {"precision_bits": 128, "root_tolerance": 1e-10},
}


SUPPORTED_SPECTRUM_STUDY = {
    "schema_version": 1,
    "target": "spectral-core",
    "theory_id": "general-relativity",
    "convention_id": "kerr-mass-normalized-outgoing",
    "modes": [
        {
            "s": -2,
            "ell": 2,
            "m": 2,
            "n": 0,
            "branch": "schwarzschild-overtone-continuation",
            "polarization": "gravitational",
        }
    ],
    "spins": [0.95, 0.997],
    "evidence_profile": "research",
    "numerical_policy": {},
}
