module Kerr

export Delta, r_plus, r_minus, omega_horizon, stable_horizon_geometry, K

function Delta(a, r)
    r^2 - 2*r + a^2
end

function r_plus(a)
    1 + sqrt(1 - a^2)
end

function r_minus(a)
    1 - sqrt(1 - a^2)
end

function omega_horizon(a)
    rp = r_plus(a)
    return a/(2*1*rp)
end

function stable_horizon_geometry(a::T) where {T<:AbstractFloat}
    isfinite(a) || throw(ArgumentError("Kerr spin must be finite"))
    delta_squared = (one(T) - a) * (one(T) + a)
    delta_squared >= zero(T) || throw(DomainError(
        a, "real Kerr spin must satisfy abs(a) <= 1"
    ))
    delta = sqrt(delta_squared)
    rplus = one(T) + delta
    isfinite(rplus) && !iszero(rplus) || throw(ArgumentError(
        "stable outer-horizon radius must be finite and nonzero"
    ))
    rminus = a^2 / rplus
    isfinite(rminus) || throw(ArgumentError(
        "stable inner-horizon radius must be finite"
    ))
    horizon_frequency = a / (T(2) * rplus)
    return (
        delta=delta,
        rplus=rplus,
        rminus=rminus,
        omega_horizon=horizon_frequency,
    )
end

function K(m::Int, a, omega, r)
    (r^2 + a^2)*omega - m*a
end

end
