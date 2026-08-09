"""Spin-minus-two generalized Sasaki--Nakamura equations from vendored source."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


POTENTIALS_SOURCE = (
    Path(__file__).resolve().parent
    / "data"
    / "native_kernel"
    / "potentials.fixture"
)
def _julia_branch_expression(function_name: str, next_function_name: str) -> str:
    if not POTENTIALS_SOURCE.is_file() or POTENTIALS_SOURCE.is_symlink():
        raise RuntimeError("GSN potential expression source is unavailable")
    try:
        source = POTENTIALS_SOURCE.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError("GSN potential expression source is unreadable") from error
    if not source:
        raise RuntimeError("GSN potential expression source is empty")
    begin = source.index(f"function {function_name}(")
    finish = source.index(f"function {next_function_name}(", begin)
    body = source[begin:finish]
    branch = body[body.index("elseif s == -2") :]
    expression = branch[branch.index("return begin") + len("return begin") :]
    expression = expression[: expression.index("\n        end")]
    expression = expression.replace("^", "**")
    expression = re.sub(r"\blambda\b", "lam", expression)
    expression = re.sub(r"\bI\b", "1j", expression)
    return " ".join(expression.split())


@lru_cache(maxsize=1)
def _compiled_equations():
    s_f = compile(
        _julia_branch_expression("sF", "sU"),
        str(POTENTIALS_SOURCE) + ":sF:s=-2",
        "eval",
    )
    s_u = compile(
        _julia_branch_expression("sU", "VT"),
        str(POTENTIALS_SOURCE) + ":sU:s=-2",
        "eval",
    )
    return s_f, s_u


def tortoise_coefficients(a, m, omega, lam, r):
    """Return the vendored GSN tortoise-coordinate coefficients F and U."""
    s_f, s_u = _compiled_equations()
    values = {"a": a, "m": m, "omega": omega, "lam": lam, "r": r}
    return (
        eval(s_f, {"__builtins__": {}}, values),
        eval(s_u, {"__builtins__": {}}, values),
    )


def radial_coordinate_coefficients(a, m, omega, lam, r):
    """Return p and q in X_rr + p X_r + q X = 0."""
    s_f, s_u = tortoise_coefficients(a, m, omega, lam, r)
    radial_factor = (r * r - 2 * r + a * a) / (r * r + a * a)
    radial_factor_derivative = 2 * (r * r - a * a) / (r * r + a * a) ** 2
    p = (radial_factor_derivative - s_f) / radial_factor
    q = -s_u / radial_factor**2
    return p, q
