#!/usr/bin/env julia

using JSON
using SHA

include(joinpath(@__DIR__, "m03_core.jl"))
using .M03Core

const RPC_SCHEMA = "windows-solver.m03-json-rpc/2"
const WORKER_KIND = "m03-julia-protocol-worker"
const WORKER_VERSION = "m03-worker-v2"
const NODE_REQUEST_SCHEMA = "windows-solver.m03-node-request/2"
const BRANCH_REQUEST_SCHEMA = "windows-solver.m03-branch-request/2"

# ---------------------------------------------------------------------------
# Precision tiers
# ---------------------------------------------------------------------------

const PRECISION_TIERS = Dict{String,Int}(
    "bigfloat-40" => 165,
    "bigfloat-80" => 298,
)

function validate_precision_tier(tier)
    isa(tier, AbstractString) || return nothing
    haskey(PRECISION_TIERS, tier) || return nothing
    return PRECISION_TIERS[tier]
end

# ---------------------------------------------------------------------------
# Canonical JSON hashing
# ---------------------------------------------------------------------------

function canonical_json_bytes(obj)
    io = IOBuffer()
    _write_canonical(io, obj)
    return take!(io)
end

function _write_canonical(io::IO, obj::AbstractDict)
    write(io, '{')
    keys_sorted = sort(collect(keys(obj)); by=string)
    for (i, k) in enumerate(keys_sorted)
        i > 1 && write(io, ',')
        _write_canonical(io, string(k))
        write(io, ':')
        _write_canonical(io, obj[k])
    end
    write(io, '}')
end

function _write_canonical(io::IO, arr::AbstractVector)
    write(io, '[')
    for (i, v) in enumerate(arr)
        i > 1 && write(io, ',')
        _write_canonical(io, v)
    end
    write(io, ']')
end

_write_canonical(io::IO, t::Tuple) = _write_canonical(io, collect(t))

function _write_canonical(io::IO, s::AbstractString)
    write(io, '"')
    for ch in s
        if ch == '"'
            write(io, "\\\"")
        elseif ch == '\\'
            write(io, "\\\\")
        elseif ch == '\n'
            write(io, "\\n")
        elseif ch == '\r'
            write(io, "\\r")
        elseif ch == '\t'
            write(io, "\\t")
        else
            write(io, ch)
        end
    end
    write(io, '"')
end

function _write_canonical(io::IO, n::Number)
    if isinteger(n) && !isa(n, AbstractFloat)
        write(io, string(Int(n)))
    else
        write(io, string(n))
    end
end

function _write_canonical(io::IO, b::Bool)
    write(io, b ? "true" : "false")
end

function _write_canonical(io::IO, ::Nothing)
    write(io, "null")
end

function sha256_hex(bytes::Vector{UInt8})
    return bytes2hex(sha256(bytes))
end

function sha256_hex(s::AbstractString)
    return sha256_hex(Vector{UInt8}(codeunits(s)))
end

function sha256_file(path::String)
    open(path, "r") do f
        return bytes2hex(sha256(f))
    end
end

function compute_request_identity(envelope::Dict)
    stripped = Dict{String,Any}()
    for (k, v) in envelope
        k == "request_identity_sha256" && continue
        stripped[k] = v
    end
    return sha256_hex(canonical_json_bytes(stripped))
end

# ---------------------------------------------------------------------------
# Complex BigFloat serialization (canonical decimal text)
# ---------------------------------------------------------------------------

function serialize_bigfloat(x::BigFloat)
    return string(x)
end

function serialize_complex(z::Complex{<:AbstractFloat})
    return Dict{String,Any}(
        "real" => serialize_bigfloat(real(z)),
        "imaginary" => serialize_bigfloat(imag(z)),
    )
end

function serialize_complex_vector(v::AbstractVector{<:Complex})
    return [serialize_complex(z) for z in v]
end

function serialize_complex_matrix(M::AbstractMatrix{<:Complex})
    rows, cols = size(M)
    return [
        [serialize_complex(M[r, c]) for c in 1:cols]
        for r in 1:rows
    ]
end

function serialize_real(x::AbstractFloat)
    return string(x)
end

function serialize_real_vector(v::AbstractVector{<:AbstractFloat})
    return [serialize_real(x) for x in v]
end

# Recursive canonical serializer for scientific values: BigFloat -> decimal
# string, Complex -> {real, imaginary}, containers -> recursively serialized.
# Bool and Integer remain native JSON. Ensures no raw BigFloat/Complex leaks
# into artifacts or RPC responses.
canonicalize_value(x::Bool) = x
canonicalize_value(x::Integer) = x
canonicalize_value(x::AbstractFloat) = serialize_real(x)
canonicalize_value(z::Complex) = serialize_complex(z)
canonicalize_value(s::AbstractString) = s
canonicalize_value(::Nothing) = nothing
canonicalize_value(v::AbstractVector) = [canonicalize_value(e) for e in v]
canonicalize_value(M::AbstractMatrix) = [[canonicalize_value(M[r, c]) for c in 1:size(M, 2)] for r in 1:size(M, 1)]
canonicalize_value(d::AbstractDict) = Dict{String,Any}(string(k) => canonicalize_value(v) for (k, v) in d)

# ---------------------------------------------------------------------------
# Parse helpers (must be called inside setprecision scope)
# ---------------------------------------------------------------------------

function parse_complex(::Type{T}, obj) where {T<:AbstractFloat}
    isa(obj, AbstractDict) ||
        error("IDENTITY_REJECTION:complex value must be an object")
    haskey(obj, "real") && haskey(obj, "imaginary") ||
        error("IDENTITY_REJECTION:complex value is missing a component")
    r = tryparse(T, obj["real"])
    i = tryparse(T, obj["imaginary"])
    (r !== nothing && i !== nothing) ||
        error("IDENTITY_REJECTION:complex value contains invalid decimal text")
    (isfinite(r) && isfinite(i)) ||
        error("IDENTITY_REJECTION:non-finite parsed complex value")
    return Complex{T}(r, i)
end

function parse_real(::Type{T}, s::AbstractString) where {T<:AbstractFloat}
    v = tryparse(T, s)
    v !== nothing || error("IDENTITY_REJECTION:invalid decimal text: $s")
    isfinite(v) || error("IDENTITY_REJECTION:non-finite parsed real value: $s")
    return v
end

# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

function _validate_path_component(s::String, label::String)
    occursin("..", s) && error("path traversal in $label")
    occursin("/", s) && error("path separator in $label")
    occursin("\\", s) && error("path separator in $label")
    all(c -> isletter(c) || isdigit(c) || c == '-' || c == '_', s) ||
        error("invalid characters in $label")
end

function safe_node_path(output_root::String, node_sha::String)
    _validate_path_component(node_sha, "node identity")
    return joinpath(output_root, "nodes", node_sha)
end

function safe_attempt_path(output_root::String, node_sha::String, request_sha::String)
    _validate_path_component(node_sha, "node identity")
    _validate_path_component(request_sha, "request identity")
    return joinpath(output_root, "nodes", node_sha, "attempts", request_sha)
end

function safe_branch_path(output_root::String, branch_id::String)
    _validate_path_component(branch_id, "branch identity")
    return joinpath(output_root, "branches", branch_id)
end

# ---------------------------------------------------------------------------
# RPC error response builders
# ---------------------------------------------------------------------------

function rpc_error(request_id, request_sha, error_class::String, message::String)
    resp = Dict{String,Any}(
        "schema" => RPC_SCHEMA,
        "request_id" => request_id,
        "request_identity_sha256" => request_sha,
        "ok" => false,
        "result" => nothing,
        "error" => Dict{String,Any}(
            "class" => error_class,
            "message" => message,
        ),
    )
    resp["response_identity_sha256"] = sha256_hex(canonical_json_bytes(resp))
    return resp
end

function rpc_success(request_id, request_sha, result::Dict{String,Any})
    resp = Dict{String,Any}(
        "schema" => RPC_SCHEMA,
        "request_id" => request_id,
        "request_identity_sha256" => request_sha,
        "ok" => true,
        "result" => result,
        "error" => nothing,
    )
    resp["response_identity_sha256"] = sha256_hex(canonical_json_bytes(resp))
    return resp
end

# ---------------------------------------------------------------------------
# Identity validation
# ---------------------------------------------------------------------------

const NODE_REQUEST_REQUIRED_FIELDS = Set([
    "request_schema", "node_identity_sha256", "mode",
    "spin_identity", "frozen_omega", "frozen_A",
    "upstream_root_identity", "background_identity_sha256",
    "m02_handoff_sha256", "branch_identity", "chain_position",
    "predecessor_state_reference", "precision_tier",
    "m02_domega_evidence", "numerical_policy_identity",
    "numerical_policy", "output_root", "source_revision",
    "root_movement_permitted", "base_angular_eigenvalue_solve_permitted",
])

const DOMEGA_EVIDENCE_FIELDS = Set([
    "schema", "request_sha256", "root_identity_sha256",
    "determinant_family", "determinant_convention",
    "determinant_normalisation", "scientific_operation_identity",
    "source_precision_tier", "source_precision_bits", "h", "D0",
    "D_plus_h", "D_minus_h", "D_plus_half_h", "D_minus_half_h",
    "coarse_derivative", "fine_derivative", "disagreement_abs",
    "source_leaf_id", "source_stage_sha256",
    "source_sample_receipt_sha256s",
])

const NUMERICAL_POLICY_FIELDS = Set([
    "readout_radius", "rho_inner", "rho_outer", "endpoint_order",
    "angular_pad", "ode_reltol", "ode_abstol",
    "angular_derivative_step", "frequency_audit_step", "quadrature_panels",
    "angular_right_residual_max", "angular_transpose_residual_max",
    "angular_symmetry_residual_max", "angular_c_product_min",
    "lambda_derivative_disagreement_max", "radial_wronskian_max",
    "matching_right_null_max", "matching_left_null_max",
    "transpose_endpoint_residual_max", "transpose_readout_residual_max",
    "dual_projective_disagreement_max", "bilinear_conservation_max",
    "domega_stencil_relative_disagreement_max",
    "local_domega_to_m02_relative_max",
    "contour_to_readout_denominator_relative_max",
    "bridge_closure_relative_max", "residue_rescaling_relative_max",
    "projector_rescaling_relative_max", "projector_idempotence_relative_max",
    "projector_action_relative_max", "local_resolvent_residue_relative_max",
    "local_resolvent_projector_relative_max", "adjugate_residue_relative_max",
    "retained_rho_grid",
])

const PREDECESSOR_REFERENCE_FIELDS = Set([
    "artifact_path", "node_identity_sha256", "root_identity_sha256",
    "branch_identity", "chain_position", "manifest_sha256",
])

function _require_exact_keys(value, expected::Set{String}, label::String)
    isa(value, AbstractDict) || error("IDENTITY_REJECTION:$label must be an object")
    actual = Set(string(k) for k in keys(value))
    actual == expected || error("IDENTITY_REJECTION:$label fields are invalid")
end

function _require_decimal_text(value, label::String)
    isa(value, AbstractString) && !isempty(value) ||
        error("IDENTITY_REJECTION:$label must be canonical decimal text")
end

function _require_complex_text(value, label::String)
    _require_exact_keys(value, Set(["real", "imaginary"]), label)
    _require_decimal_text(value["real"], "$label.real")
    _require_decimal_text(value["imaginary"], "$label.imaginary")
end

function _validate_sha256_format(value, label::String)
    isa(value, AbstractString) ||
        error("IDENTITY_REJECTION:$label must be a lowercase SHA-256 string")
    length(value) == 64 || error("IDENTITY_REJECTION:$label is not a 64-character hex digest (got $(length(value)) chars)")
    all(c -> c in "0123456789abcdef", value) || error("IDENTITY_REJECTION:$label contains non-hex characters")
end

function validate_node_request!(params::Dict)
    for f in NODE_REQUEST_REQUIRED_FIELDS
        haskey(params, f) || error("IDENTITY_REJECTION:missing required field: $f")
    end

    extras = setdiff(Set(keys(params)), NODE_REQUEST_REQUIRED_FIELDS)
    isempty(extras) || error("IDENTITY_REJECTION:unexpected fields in node request: $(join(sort(collect(extras)), ", "))")

    params["request_schema"] == NODE_REQUEST_SCHEMA ||
        error("IDENTITY_REJECTION:wrong request schema: $(params["request_schema"])")

    params["root_movement_permitted"] === false ||
        error("POLICY_REJECTION:root_movement_permitted must be false")
    params["base_angular_eigenvalue_solve_permitted"] === false ||
        error("POLICY_REJECTION:base_angular_eigenvalue_solve_permitted must be false")

    bits = validate_precision_tier(params["precision_tier"])
    bits === nothing &&
        error("POLICY_REJECTION:unsupported precision tier: $(params["precision_tier"])")

    _validate_sha256_format(params["node_identity_sha256"], "node_identity_sha256")
    _validate_sha256_format(params["upstream_root_identity"], "upstream_root_identity")
    _validate_sha256_format(params["background_identity_sha256"], "background_identity_sha256")
    _validate_sha256_format(params["m02_handoff_sha256"], "m02_handoff_sha256")
    _validate_sha256_format(params["numerical_policy_identity"], "numerical_policy_identity")

    isa(params["branch_identity"], AbstractString) &&
        !isempty(params["branch_identity"]) ||
        error("IDENTITY_REJECTION:branch_identity must be non-empty text")
    isa(params["chain_position"], Integer) &&
        !isa(params["chain_position"], Bool) &&
        params["chain_position"] >= 0 ||
        error("IDENTITY_REJECTION:chain_position must be a nonnegative integer")
    isa(params["output_root"], AbstractString) && !isempty(params["output_root"]) ||
        error("IDENTITY_REJECTION:output_root must be non-empty text")
    isa(params["source_revision"], AbstractString) && !isempty(params["source_revision"]) ||
        error("IDENTITY_REJECTION:source_revision must be non-empty text")

    mode = params["mode"]
    isa(mode, AbstractDict) || error("IDENTITY_REJECTION:mode must be a dictionary")
    for k in ("s", "ell", "m", "n")
        haskey(mode, k) || error("IDENTITY_REJECTION:mode missing field: $k")
        isa(mode[k], Integer) && !isa(mode[k], Bool) ||
            error("IDENTITY_REJECTION:mode.$k must be an integer")
    end

    spin = params["spin_identity"]
    isa(spin, AbstractDict) || error("IDENTITY_REJECTION:spin_identity must be an object")
    haskey(spin, "physical_spin_text") ||
        error("IDENTITY_REJECTION:spin_identity missing physical_spin_text")
    _require_decimal_text(spin["physical_spin_text"], "spin_identity.physical_spin_text")

    omega = params["frozen_omega"]
    _require_exact_keys(omega, Set(["real", "imaginary", "units"]), "frozen_omega")
    _require_decimal_text(omega["real"], "frozen_omega.real")
    _require_decimal_text(omega["imaginary"], "frozen_omega.imaginary")
    omega["units"] == "Momega" ||
        error("IDENTITY_REJECTION:frozen_omega units must be Momega")

    frozen_A = params["frozen_A"]
    _require_complex_text(frozen_A, "frozen_A")

    evidence = params["m02_domega_evidence"]
    _require_exact_keys(evidence, DOMEGA_EVIDENCE_FIELDS, "m02_domega_evidence")
    evidence["schema"] == "windows-solver.m02-domega-stencil/1" ||
        error("IDENTITY_REJECTION:wrong M02 Domega evidence schema")
    evidence["determinant_family"] == "exterior-wronskian/v1" ||
        error("IDENTITY_REJECTION:wrong M02 determinant family")
    evidence["determinant_convention"] ==
        "wronskian-perturbed-Xin-with-Xup/v1" ||
        error("IDENTITY_REJECTION:wrong M02 determinant convention")
    evidence["determinant_normalisation"] ==
        "unit-asymptotic-branch-wronskian/v1" ||
        error("IDENTITY_REJECTION:wrong M02 determinant normalisation")
    evidence["scientific_operation_identity"] ==
        "canonical-exterior-background-wronskian/v1" ||
        error("IDENTITY_REJECTION:wrong M02 scientific operation identity")

    _validate_sha256_format(evidence["root_identity_sha256"], "m02_domega_evidence.root_identity_sha256")
    _validate_sha256_format(evidence["request_sha256"], "m02_domega_evidence.request_sha256")
    evidence_material = Dict{String,Any}(
        string(key) => value for (key, value) in evidence
        if key != "request_sha256"
    )
    sha256_hex(canonical_json_bytes(evidence_material)) == evidence["request_sha256"] ||
        error("IDENTITY_REJECTION:M02 Domega evidence identity mismatch")

    validate_precision_tier(evidence["source_precision_tier"]) === nothing &&
        error("POLICY_REJECTION:unsupported M02 source precision tier: $(evidence["source_precision_tier"])")
    evidence["source_precision_bits"] == PRECISION_TIERS[evidence["source_precision_tier"]] ||
        error("IDENTITY_REJECTION:M02 source precision bits do not match its tier")

    for name in ("D0", "D_plus_h", "D_minus_h", "D_plus_half_h", "D_minus_half_h",
                 "coarse_derivative", "fine_derivative")
        _require_complex_text(evidence[name], "m02_domega_evidence.$name")
    end
    _require_decimal_text(evidence["h"], "m02_domega_evidence.h")
    _require_decimal_text(evidence["disagreement_abs"], "m02_domega_evidence.disagreement_abs")
    _validate_sha256_format(evidence["source_stage_sha256"], "m02_domega_evidence.source_stage_sha256")
    isa(evidence["source_leaf_id"], AbstractString) &&
        !isempty(evidence["source_leaf_id"]) ||
        error("IDENTITY_REJECTION:M02 Domega source leaf ID must be non-empty text")
    receipts = evidence["source_sample_receipt_sha256s"]
    isa(receipts, AbstractVector) && length(receipts) == 4 ||
        error("IDENTITY_REJECTION:M02 Domega evidence must bind four sample receipts")
    length(unique(receipts)) == 4 ||
        error("IDENTITY_REJECTION:M02 Domega sample receipts must be distinct")
    for (index, receipt) in enumerate(receipts)
        _validate_sha256_format(receipt, "m02_domega_evidence.source_sample_receipt_sha256s[$index]")
    end

    evidence["root_identity_sha256"] == params["upstream_root_identity"] ||
        error("IDENTITY_REJECTION:Domega evidence root identity does not match upstream_root_identity")

    policy = params["numerical_policy"]
    _require_exact_keys(policy, NUMERICAL_POLICY_FIELDS, "numerical_policy")
    sha256_hex(canonical_json_bytes(policy)) == params["numerical_policy_identity"] ||
        error("IDENTITY_REJECTION:numerical policy identity mismatch")
    for name in ("endpoint_order", "angular_pad", "quadrature_panels")
        isa(policy[name], Integer) && !isa(policy[name], Bool) && policy[name] > 0 ||
            error("POLICY_REJECTION:numerical_policy.$name must be a positive integer")
    end
    for name in setdiff(NUMERICAL_POLICY_FIELDS,
                        Set(["endpoint_order", "angular_pad", "quadrature_panels",
                             "retained_rho_grid"]))
        _require_decimal_text(policy[name], "numerical_policy.$name")
    end
    retained_grid = policy["retained_rho_grid"]
    isa(retained_grid, AbstractVector) && length(retained_grid) >= 3 ||
        error("POLICY_REJECTION:numerical_policy.retained_rho_grid must contain at least three points")
    for (index, coordinate) in enumerate(retained_grid)
        _require_decimal_text(coordinate,
            "numerical_policy.retained_rho_grid[$index]")
    end

    predecessor = params["predecessor_state_reference"]
    if predecessor !== nothing
        _require_exact_keys(predecessor, PREDECESSOR_REFERENCE_FIELDS,
            "predecessor_state_reference")
        _validate_sha256_format(predecessor["node_identity_sha256"],
            "predecessor_state_reference.node_identity_sha256")
        _validate_sha256_format(predecessor["root_identity_sha256"],
            "predecessor_state_reference.root_identity_sha256")
        _validate_sha256_format(predecessor["manifest_sha256"],
            "predecessor_state_reference.manifest_sha256")
        predecessor["branch_identity"] == params["branch_identity"] ||
            error("IDENTITY_REJECTION:predecessor branch identity does not match request")
        isa(predecessor["chain_position"], Integer) &&
            !isa(predecessor["chain_position"], Bool) ||
            error("IDENTITY_REJECTION:predecessor chain position must be an integer")
        predecessor["chain_position"] + 1 == params["chain_position"] ||
            error("IDENTITY_REJECTION:predecessor is not adjacent to successor")
    end

    return bits
end

# ---------------------------------------------------------------------------
# Typed input construction (inside precision scope)
# ---------------------------------------------------------------------------

function validate_typed_policy!(policy::NumericalPolicy{T}) where {T<:AbstractFloat}
    positive_policy_values = (
        policy.readout_radius,
        policy.ode_reltol,
        policy.ode_abstol,
        policy.angular_derivative_step,
        policy.frequency_audit_step,
        policy.angular_right_residual_max,
        policy.angular_transpose_residual_max,
        policy.angular_symmetry_residual_max,
        policy.angular_c_product_min,
        policy.lambda_derivative_disagreement_max,
        policy.radial_wronskian_max,
        policy.matching_right_null_max,
        policy.matching_left_null_max,
        policy.transpose_endpoint_residual_max,
        policy.transpose_readout_residual_max,
        policy.dual_projective_disagreement_max,
        policy.bilinear_conservation_max,
        policy.domega_stencil_relative_disagreement_max,
        policy.local_domega_to_m02_relative_max,
        policy.contour_to_readout_denominator_relative_max,
        policy.bridge_closure_relative_max,
        policy.residue_rescaling_relative_max,
        policy.projector_rescaling_relative_max,
        policy.projector_idempotence_relative_max,
        policy.projector_action_relative_max,
        policy.local_resolvent_residue_relative_max,
        policy.local_resolvent_projector_relative_max,
        policy.adjugate_residue_relative_max,
    )
    all(value -> value > zero(T), positive_policy_values) ||
        error("POLICY_REJECTION:M03 numerical tolerances and thresholds must be positive")
    policy.rho_inner < zero(T) < policy.rho_outer ||
        error("POLICY_REJECTION:M03 numerical contour must straddle rho=0")
    issorted(policy.retained_rho_grid) &&
        length(unique(policy.retained_rho_grid)) == length(policy.retained_rho_grid) &&
        first(policy.retained_rho_grid) >= policy.rho_inner &&
        last(policy.retained_rho_grid) <= policy.rho_outer &&
        any(iszero, policy.retained_rho_grid) ||
        error("POLICY_REJECTION:M03 retained rho grid is invalid")
    return policy
end

function build_typed_inputs(::Type{T}, params::Dict) where {T<:AbstractFloat}
    mode = params["mode"]
    omega_obj = params["frozen_omega"]
    A_obj = params["frozen_A"]
    spin_obj = params["spin_identity"]
    evidence = params["m02_domega_evidence"]
    policy_obj = params["numerical_policy"]
    tier = params["precision_tier"]

    omega = parse_complex(T, omega_obj)
    A = parse_complex(T, A_obj)
    spin = parse_real(T, spin_obj["physical_spin_text"])

    imag(omega) <= zero(T) || error("IDENTITY_REJECTION:damped root must have Im(omega) <= 0")
    abs(spin) < one(T) || error("IDENTITY_REJECTION:Kerr spin must satisfy abs(a/M) < 1")

    seed = RootSeed{T}(
        params["node_identity_sha256"],
        params["upstream_root_identity"],
        params["background_identity_sha256"],
        params["m02_handoff_sha256"],
        Int(mode["s"]), Int(mode["ell"]), Int(mode["m"]), Int(mode["n"]),
        params["branch_identity"],
        Int(params["chain_position"]),
        spin_obj["physical_spin_text"],
        spin,
        omega_obj["real"], omega_obj["imaginary"],
        omega,
        A_obj["real"], A_obj["imaginary"],
        A,
        tier,
    )

    h = parse_real(T, evidence["h"])
    D0 = parse_complex(T, evidence["D0"])
    Dph = parse_complex(T, evidence["D_plus_h"])
    Dmh = parse_complex(T, evidence["D_minus_h"])
    Dphh = parse_complex(T, evidence["D_plus_half_h"])
    Dmhh = parse_complex(T, evidence["D_minus_half_h"])
    coarse = parse_complex(T, evidence["coarse_derivative"])
    fine = parse_complex(T, evidence["fine_derivative"])
    disagree = parse_real(T, evidence["disagreement_abs"])
    h > zero(T) || error("IDENTITY_REJECTION:M02 Domega stencil step must be positive")
    disagree >= zero(T) ||
        error("IDENTITY_REJECTION:M02 Domega disagreement must be nonnegative")

    source_tier = evidence["source_precision_tier"]
    source_bits = PRECISION_TIERS[source_tier]

    stencil = DomegaStencil{T}(
        evidence["request_sha256"],
        evidence["root_identity_sha256"],
        evidence["determinant_family"],
        evidence["determinant_convention"],
        evidence["determinant_normalisation"],
        evidence["scientific_operation_identity"],
        source_tier,
        source_bits,
        h, D0, Dph, Dmh, Dphh, Dmhh,
        coarse, fine, disagree,
    )

    np = policy_obj
    policy = NumericalPolicy{T}(
        params["numerical_policy_identity"],
        tier,
        PRECISION_TIERS[tier],
        parse_real(T, np["readout_radius"]),
        parse_real(T, np["rho_inner"]),
        parse_real(T, np["rho_outer"]),
        Int(np["endpoint_order"]),
        Int(np["angular_pad"]),
        parse_real(T, np["ode_reltol"]),
        parse_real(T, np["ode_abstol"]),
        parse_real(T, np["angular_derivative_step"]),
        parse_real(T, np["frequency_audit_step"]),
        Int(np["quadrature_panels"]),
        parse_real(T, np["angular_right_residual_max"]),
        parse_real(T, np["angular_transpose_residual_max"]),
        parse_real(T, np["angular_symmetry_residual_max"]),
        parse_real(T, np["angular_c_product_min"]),
        parse_real(T, np["lambda_derivative_disagreement_max"]),
        parse_real(T, np["radial_wronskian_max"]),
        parse_real(T, np["matching_right_null_max"]),
        parse_real(T, np["matching_left_null_max"]),
        parse_real(T, np["transpose_endpoint_residual_max"]),
        parse_real(T, np["transpose_readout_residual_max"]),
        parse_real(T, np["dual_projective_disagreement_max"]),
        parse_real(T, np["bilinear_conservation_max"]),
        parse_real(T, np["domega_stencil_relative_disagreement_max"]),
        parse_real(T, np["local_domega_to_m02_relative_max"]),
        parse_real(T, np["contour_to_readout_denominator_relative_max"]),
        parse_real(T, np["bridge_closure_relative_max"]),
        parse_real(T, np["residue_rescaling_relative_max"]),
        parse_real(T, np["projector_rescaling_relative_max"]),
        parse_real(T, np["projector_idempotence_relative_max"]),
        parse_real(T, np["projector_action_relative_max"]),
        parse_real(T, np["local_resolvent_residue_relative_max"]),
        parse_real(T, np["local_resolvent_projector_relative_max"]),
        parse_real(T, np["adjugate_residue_relative_max"]),
        T[parse_real(T, x) for x in np["retained_rho_grid"]],
    )

    validate_typed_policy!(policy)

    predecessor = nothing
    pred_ref = params["predecessor_state_reference"]
    if pred_ref !== nothing && isa(pred_ref, AbstractDict) && haskey(pred_ref, "artifact_path")
        predecessor = _load_predecessor(T, pred_ref, params["output_root"])
    end

    return seed, stencil, policy, predecessor
end

# ---------------------------------------------------------------------------
# Predecessor loading from artifact
# ---------------------------------------------------------------------------

function _path_is_within(root::String, candidate::String)
    ispath(root) && ispath(candidate) || return false
    relative = relpath(realpath(candidate), realpath(root))
    return relative != ".." && !startswith(relative, "../") && !startswith(relative, "..\\")
end

function _load_predecessor(
    ::Type{T}, ref::Dict, output_root::String
) where {T<:AbstractFloat}
    path = ref["artifact_path"]
    isa(path, AbstractString) ||
        error("IDENTITY_REJECTION:predecessor artifact_path must be text")
    _path_is_within(output_root, path) ||
        error("IDENTITY_REJECTION:predecessor artifact is outside output_root")
    isdir(path) || error("IDENTITY_REJECTION:predecessor artifact path does not exist: $path")

    manifest_path = joinpath(path, "node-manifest.json")
    isfile(manifest_path) || error("IDENTITY_REJECTION:predecessor manifest missing")
    manifest = JSON.parsefile(manifest_path)

    sha256_file(manifest_path) == ref["manifest_sha256"] ||
        error("IDENTITY_REJECTION:predecessor manifest SHA mismatch")

    haskey(ref, "node_identity_sha256") || error("IDENTITY_REJECTION:predecessor reference missing node_identity_sha256")
    manifest["node_identity_sha256"] == ref["node_identity_sha256"] ||
        error("IDENTITY_REJECTION:predecessor manifest identity mismatch")
    manifest["root_identity_sha256"] == ref["root_identity_sha256"] ||
        error("IDENTITY_REJECTION:predecessor root identity mismatch")
    manifest["branch_identity"] == ref["branch_identity"] ||
        error("IDENTITY_REJECTION:predecessor branch identity mismatch")
    manifest["chain_position"] == ref["chain_position"] ||
        error("IDENTITY_REJECTION:predecessor chain position mismatch")

    get(manifest, "disposition", nothing) == "PRODUCED" ||
        error("IDENTITY_REJECTION:predecessor is not PRODUCED (disposition=$(get(manifest, "disposition", "missing")))")

    ang_path = joinpath(path, "angular-state.json")
    isfile(ang_path) || error("IDENTITY_REJECTION:predecessor angular-state.json missing")
    _verify_payload_hash(manifest, "angular-state.json", ang_path)
    ang_data = JSON.parsefile(ang_path)

    radial_right_path = joinpath(path, "radial-right.json")
    isfile(radial_right_path) || error("IDENTITY_REJECTION:predecessor radial-right.json missing")
    _verify_payload_hash(manifest, "radial-right.json", radial_right_path)
    right_data = JSON.parsefile(radial_right_path)

    radial_dual_path = joinpath(path, "radial-dual.json")
    isfile(radial_dual_path) || error("IDENTITY_REJECTION:predecessor radial-dual.json missing")
    _verify_payload_hash(manifest, "radial-dual.json", radial_dual_path)
    dual_data = JSON.parsefile(radial_dual_path)

    angular_right = Complex{T}[parse_complex(T, c) for c in ang_data["right_coefficients"]]

    right_samples = _parse_field_matrix(T, right_data["retained_samples"])
    dual_samples = _parse_field_matrix(T, dual_data["retained_samples"])

    return RetainedPredecessor{T}(
        ref["node_identity_sha256"],
        ref["root_identity_sha256"],
        ref["branch_identity"],
        ref["chain_position"],
        angular_right,
        right_samples,
        dual_samples,
    )
end

function _parse_field_matrix(::Type{T}, data) where {T<:AbstractFloat}
    rows = length(data)
    rows == 0 && return Matrix{Complex{T}}(undef, 0, 0)
    cols = length(data[1])
    M = Matrix{Complex{T}}(undef, rows, cols)
    for r in 1:rows
        for c in 1:cols
            M[r, c] = parse_complex(T, data[r][c])
        end
    end
    return M
end

function _verify_payload_hash(manifest::Dict, filename::String, filepath::String)
    haskey(manifest, "payload_hashes") ||
        error("IDENTITY_REJECTION:manifest missing payload_hashes section")
    hashes = manifest["payload_hashes"]
    haskey(hashes, filename) ||
        error("IDENTITY_REJECTION:manifest missing hash for required payload: $filename")
    expected = hashes[filename]
    actual = sha256_file(filepath)
    actual == expected ||
        error("IDENTITY_REJECTION:payload hash mismatch for $filename: expected $expected, got $actual")
end

# ---------------------------------------------------------------------------
# Artifact serialization
# ---------------------------------------------------------------------------

function serialize_node_artifacts(
    result::SpectralStateResult{T}, params::Dict, request_sha::String;
    continuation_edge=nothing
) where {T<:AbstractFloat}
    artifacts = Dict{String,Any}()

    artifacts["request.json"] = JSON.json(Dict{String,Any}(
        "request_identity_sha256" => request_sha,
        "node_identity_sha256" => params["node_identity_sha256"],
        "params" => params,
    ))

    artifacts["angular-state.json"] = JSON.json(_angular_artifact(result))
    artifacts["radial-right.json"] = JSON.json(_radial_right_artifact(result))
    artifacts["radial-dual.json"] = JSON.json(_radial_dual_artifact(result))
    artifacts["pole-object.json"] = JSON.json(_pole_artifact(result))
    artifacts["validation.json"] = JSON.json(_validation_artifact(result))

    if continuation_edge !== nothing
        artifacts["continuation.json"] = JSON.json(_continuation_artifact(continuation_edge, params))
    end

    artifacts["_disposition"] = result.disposition
    artifacts["_reason"] = result.reason
    artifacts["_root_identity_sha256"] = params["upstream_root_identity"]
    artifacts["_branch_identity"] = params["branch_identity"]
    artifacts["_chain_position"] = Int(params["chain_position"])
    artifacts["_handoff_identity_sha256"] = params["m02_handoff_sha256"]
    artifacts["_precision_tier"] = params["precision_tier"]
    artifacts["_numerical_policy_identity"] = params["numerical_policy_identity"]

    return artifacts
end

function _continuation_artifact(edge, params::Dict)
    d = Dict{String,Any}(
        "predecessor_sha256" => edge.predecessor_sha256,
        "successor_sha256" => edge.successor_sha256,
        "angular_overlap_raw" => serialize_complex(edge.angular_overlap_raw),
        "angular_overlap_aligned" => serialize_real(edge.angular_overlap_aligned),
        "angular_phase_factor" => serialize_complex(edge.angular_phase_factor),
        "radial_right_overlap_raw" => serialize_complex(edge.radial_right_overlap_raw),
        "radial_right_overlap_aligned" => serialize_real(edge.radial_right_overlap_aligned),
        "radial_right_phase_factor" => serialize_complex(edge.radial_right_phase_factor),
        "radial_dual_overlap_raw" => serialize_complex(edge.radial_dual_overlap_raw),
        "radial_dual_overlap_aligned" => serialize_real(edge.radial_dual_overlap_aligned),
        "radial_dual_phase_factor" => serialize_complex(edge.radial_dual_phase_factor),
    )
    return d
end

function _angular_artifact(r::SpectralStateResult{T}) where {T}
    d = Dict{String,Any}(
        "disposition" => r.disposition,
        "precision_tier" => r.precision_tier,
    )
    r.angular_right !== nothing &&
        (d["right_coefficients"] = serialize_complex_vector(r.angular_right))
    r.angular_transpose !== nothing &&
        (d["transpose_coefficients"] = serialize_complex_vector(r.angular_transpose))
    r.angular_c_product !== nothing &&
        (d["c_product"] = serialize_complex(r.angular_c_product))
    r.Ac_prime !== nothing &&
        (d["Ac_prime"] = serialize_complex(r.Ac_prime))
    r.Aomega_prime !== nothing &&
        (d["Aomega_prime"] = serialize_complex(r.Aomega_prime))
    r.lambda_prime !== nothing &&
        (d["lambda_prime"] = serialize_complex(r.lambda_prime))
    r.lambda !== nothing &&
        (d["lambda"] = serialize_complex(r.lambda))
    return d
end

function _radial_right_artifact(r::SpectralStateResult{T}) where {T}
    d = Dict{String,Any}(
        "disposition" => r.disposition,
        "precision_tier" => r.precision_tier,
    )
    r.matching_matrix !== nothing &&
        (d["matching_matrix"] = serialize_complex_matrix(r.matching_matrix))
    r.matching_determinant !== nothing &&
        (d["matching_determinant"] = serialize_complex(r.matching_determinant))
    r.coefficient_right !== nothing &&
        (d["coefficient_right"] = serialize_complex_vector(r.coefficient_right))
    r.retained_right_samples !== nothing &&
        (d["retained_samples"] = serialize_complex_matrix(r.retained_right_samples))
    r.retained_rho_grid !== nothing &&
        (d["retained_rho_grid"] = serialize_real_vector(r.retained_rho_grid))
    return d
end

function _radial_dual_artifact(r::SpectralStateResult{T}) where {T}
    d = Dict{String,Any}(
        "disposition" => r.disposition,
        "precision_tier" => r.precision_tier,
    )
    r.eta_horizon !== nothing &&
        (d["eta_horizon"] = serialize_complex(r.eta_horizon))
    r.eta_infinity !== nothing &&
        (d["eta_infinity"] = serialize_complex(r.eta_infinity))
    r.dual_z_match !== nothing &&
        (d["z_match"] = serialize_complex_vector(r.dual_z_match))
    r.coefficient_left !== nothing &&
        (d["coefficient_left"] = serialize_complex_vector(r.coefficient_left))
    r.retained_dual_samples !== nothing &&
        (d["retained_samples"] = serialize_complex_matrix(r.retained_dual_samples))
    return d
end

function _pole_artifact(r::SpectralStateResult{T}) where {T}
    d = Dict{String,Any}(
        "disposition" => r.disposition,
        "precision_tier" => r.precision_tier,
    )
    r.matching_derivative !== nothing &&
        (d["F_prime"] = serialize_complex_matrix(r.matching_derivative))
    r.adjugate_matrix !== nothing &&
        (d["adjugate"] = serialize_complex_matrix(r.adjugate_matrix))
    r.coefficient_right !== nothing &&
        (d["coefficient_right"] = serialize_complex_vector(r.coefficient_right))
    r.coefficient_left !== nothing &&
        (d["coefficient_left"] = serialize_complex_vector(r.coefficient_left))
    r.denominator_bulk !== nothing &&
        (d["denominator_bulk"] = serialize_complex(r.denominator_bulk))
    r.denominator_horizon_trace !== nothing &&
        (d["denominator_horizon_trace"] = serialize_complex(r.denominator_horizon_trace))
    r.denominator_infinity_trace !== nothing &&
        (d["denominator_infinity_trace"] = serialize_complex(r.denominator_infinity_trace))
    r.denominator_raw !== nothing &&
        (d["denominator_raw"] = serialize_complex(r.denominator_raw))
    r.denominator_readout !== nothing &&
        (d["denominator_readout"] = serialize_complex(r.denominator_readout))
    r.bridge !== nothing &&
        (d["bridge"] = serialize_complex(r.bridge))
    r.residue !== nothing &&
        (d["residue"] = serialize_complex_matrix(r.residue))
    r.projector !== nothing &&
        (d["projector"] = serialize_complex_matrix(r.projector))
    r.m02_Domega_fine !== nothing &&
        (d["m02_Domega_fine"] = serialize_complex(r.m02_Domega_fine))
    r.m02_Domega_coarse !== nothing &&
        (d["m02_Domega_coarse"] = serialize_complex(r.m02_Domega_coarse))
    r.local_determinant_derivative !== nothing &&
        (d["local_determinant_derivative"] = serialize_complex(r.local_determinant_derivative))
    return d
end

function _validation_artifact(r::SpectralStateResult{T}) where {T}
    return Dict{String,Any}(
        "disposition" => r.disposition,
        "reason" => r.reason,
        "precision_tier" => r.precision_tier,
        "root_solves" => r.root_solves,
        "base_angular_eigenvalue_solves" => r.base_angular_eigenvalue_solves,
        "m02_response_solves" => r.m02_response_solves,
        "gates" => canonicalize_value(r.gates),
    )
end

# ---------------------------------------------------------------------------
# Atomic publication
# ---------------------------------------------------------------------------

function atomic_publish!(
    artifacts::Dict{String,Any}, final_path::String, node_sha::String, request_sha::String
)
    isdir(final_path) && error("attempt directory already exists: $final_path")

    parent = dirname(final_path)
    isdir(parent) || mkpath(parent)

    tmp_path = final_path * ".tmp." * string(getpid()) * "." * string(time_ns())
    mkpath(tmp_path)

    payload_hashes = Dict{String,String}()

    for (filename, content) in artifacts
        filename == "node-manifest.json" && continue
        startswith(filename, "_") && continue
        isa(content, AbstractString) || continue
        filepath = joinpath(tmp_path, filename)
        open(filepath, "w") do f
            write(f, content)
        end
        flush_and_sync(filepath)
        payload_hashes[filename] = sha256_hex(content)
    end

    manifest = Dict{String,Any}(
        "schema" => "windows-solver.m03-node-manifest/1",
        "disposition" => get(artifacts, "_disposition", "UNKNOWN"),
        "reason" => get(artifacts, "_reason", nothing),
        "node_identity_sha256" => node_sha,
        "request_identity_sha256" => request_sha,
        "root_identity_sha256" => get(artifacts, "_root_identity_sha256", ""),
        "branch_identity" => get(artifacts, "_branch_identity", ""),
        "chain_position" => get(artifacts, "_chain_position", 0),
        "handoff_identity_sha256" => get(artifacts, "_handoff_identity_sha256", ""),
        "precision_tier" => get(artifacts, "_precision_tier", ""),
        "numerical_policy_identity" => get(artifacts, "_numerical_policy_identity", ""),
        "payload_hashes" => payload_hashes,
        "worker_kind" => WORKER_KIND,
        "worker_version" => WORKER_VERSION,
        "core_schema" => M03Core.CORE_SCHEMA,
        "core_version" => M03Core.CORE_VERSION,
    )

    manifest_content = JSON.json(manifest)
    manifest_path = joinpath(tmp_path, "node-manifest.json")
    open(manifest_path, "w") do f
        write(f, manifest_content)
    end
    flush_and_sync(manifest_path)

    for (filename, expected_hash) in payload_hashes
        filepath = joinpath(tmp_path, filename)
        actual = sha256_file(filepath)
        actual == expected_hash ||
            error("SYSTEM_FAILURE:post-write hash verification failed for $filename")
    end

    mv(tmp_path, final_path)
    return sha256_hex(manifest_content)
end

function flush_and_sync(filepath::String)
    open(filepath, "r") do f
        if Sys.iswindows()
            ccall(:_commit, Cint, (Cint,), fd(f))
        else
            ccall(:fsync, Cint, (Cint,), fd(f))
        end
    end
end

# The canonical node root holds a POINTER to the accepted attempt, not a copy of
# the attempt manifest (whose payload_hashes reference files inside the attempt
# directory). This keeps the payload contract truthful.
#
# Idempotent and crash-seam safe: if a valid pointer already exists (its
# referenced attempt directory holds a PRODUCED manifest whose on-disk SHA
# matches), it is preserved — a later replay must not demote an existing
# canonical choice. If the pointer is absent (the classic commit-then-die seam)
# or structurally invalid, it is (re)written to reference this PRODUCED attempt.
function publish_or_verify_canonical_node_pointer(
    output_root::String, node_sha::String, request_sha::String,
    attempt_manifest_sha::String, tier::String,
)
    node_dir = safe_node_path(output_root, node_sha)
    isdir(node_dir) || mkpath(node_dir)
    pointer_path = joinpath(node_dir, "node-manifest.json")

    if isfile(pointer_path) && _canonical_pointer_is_valid(output_root, node_sha, pointer_path)
        return sha256_file(pointer_path)
    end

    pointer = Dict{String,Any}(
        "schema" => "windows-solver.m03-canonical-node/1",
        "node_identity_sha256" => node_sha,
        "canonical_attempt_request_sha256" => request_sha,
        "canonical_attempt_path" => joinpath("attempts", request_sha),
        "canonical_attempt_manifest_sha256" => attempt_manifest_sha,
        "disposition" => "PRODUCED",
        "precision_tier" => tier,
    )
    pointer_json = JSON.json(pointer)

    tmp_pointer = pointer_path * ".tmp." * string(getpid()) * "." * string(time_ns())
    open(tmp_pointer, "w") do f
        write(f, pointer_json)
    end
    flush_and_sync(tmp_pointer)
    mv(tmp_pointer, pointer_path; force=true)
    return sha256_hex(pointer_json)
end

# A canonical pointer is valid iff it is a well-formed canonical-node manifest
# whose referenced attempt directory still holds a PRODUCED manifest whose
# on-disk SHA matches the recorded canonical_attempt_manifest_sha256.
function _canonical_pointer_is_valid(output_root::String, node_sha::String, pointer_path::String)
    pointer = try
        JSON.parsefile(pointer_path)
    catch
        return false
    end
    isa(pointer, AbstractDict) || return false
    get(pointer, "schema", nothing) == "windows-solver.m03-canonical-node/1" || return false
    get(pointer, "node_identity_sha256", nothing) == node_sha || return false
    get(pointer, "disposition", nothing) == "PRODUCED" || return false

    rel = get(pointer, "canonical_attempt_path", nothing)
    isa(rel, AbstractString) || return false
    recorded_sha = get(pointer, "canonical_attempt_manifest_sha256", nothing)
    isa(recorded_sha, AbstractString) || return false

    attempt_manifest = joinpath(safe_node_path(output_root, node_sha), rel, "node-manifest.json")
    isfile(attempt_manifest) || return false
    sha256_file(attempt_manifest) == recorded_sha || return false

    attempt = try
        JSON.parsefile(attempt_manifest)
    catch
        return false
    end
    return get(attempt, "disposition", nothing) == "PRODUCED"
end

# ---------------------------------------------------------------------------
# Zero-work reuse
# ---------------------------------------------------------------------------

function check_reuse(attempt_path::String, request_sha::String, node_sha::String)
    isdir(attempt_path) || return nothing

    manifest_path = joinpath(attempt_path, "node-manifest.json")
    isfile(manifest_path) ||
        error("IDENTITY_REJECTION:existing attempt directory is missing its manifest")

    manifest = JSON.parsefile(manifest_path)

    get(manifest, "schema", nothing) == "windows-solver.m03-node-manifest/1" ||
        error("IDENTITY_REJECTION:existing artifact manifest schema mismatch")
    get(manifest, "node_identity_sha256", nothing) == node_sha ||
        error("IDENTITY_REJECTION:existing artifact identity mismatch")
    get(manifest, "request_identity_sha256", nothing) == request_sha ||
        error("IDENTITY_REJECTION:existing artifact request identity mismatch")

    # Any completed attempt (PRODUCED, PROMOTION_REQUIRED, UNRESOLVED) is
    # reusable without numerical work; its original disposition is preserved.
    get(manifest, "disposition", nothing) in
        ("PRODUCED", "PROMOTION_REQUIRED", "UNRESOLVED") ||
        error("IDENTITY_REJECTION:existing artifact disposition is invalid")

    haskey(manifest, "payload_hashes") ||
        error("IDENTITY_REJECTION:existing artifact manifest missing payload_hashes")
    for (filename, expected) in manifest["payload_hashes"]
        filepath = joinpath(attempt_path, filename)
        isfile(filepath) || error("IDENTITY_REJECTION:existing artifact missing payload: $filename")
        actual = sha256_file(filepath)
        actual == expected ||
            error("IDENTITY_REJECTION:existing artifact hash mismatch for $filename")
    end

    return manifest
end

# ---------------------------------------------------------------------------
# Response summary builder
# ---------------------------------------------------------------------------

function build_summary(result::SpectralStateResult{T}, params::Dict) where {T<:AbstractFloat}
    summary = Dict{String,Any}(
        "disposition" => result.disposition,
        "root_solves" => result.root_solves,
        "base_angular_eigenvalue_solves" => result.base_angular_eigenvalue_solves,
        "m02_response_solves" => result.m02_response_solves,
    )

    summary["echoed_spin"] = params["spin_identity"]["physical_spin_text"]
    summary["echoed_omega_real"] = params["frozen_omega"]["real"]
    summary["echoed_omega_imag"] = params["frozen_omega"]["imaginary"]
    summary["echoed_A_real"] = params["frozen_A"]["real"]
    summary["echoed_A_imag"] = params["frozen_A"]["imaginary"]
    summary["echoed_root_identity"] = params["upstream_root_identity"]
    summary["echoed_handoff_identity"] = params["m02_handoff_sha256"]
    summary["echoed_policy_identity"] = params["numerical_policy_identity"]

    summary["gates"] = canonicalize_value(result.gates)

    return summary
end

# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------

function handle_hello(request_id, request_sha)
    result = Dict{String,Any}(
        "worker_kind" => WORKER_KIND,
        "worker_version" => WORKER_VERSION,
        "core_schema" => M03Core.CORE_SCHEMA,
        "core_version" => M03Core.CORE_VERSION,
        "rpc_schema" => RPC_SCHEMA,
    )
    return rpc_success(request_id, request_sha, result)
end

function handle_probe(request_id, request_sha)
    result = Dict{String,Any}(
        "worker_kind" => WORKER_KIND,
        "worker_version" => WORKER_VERSION,
        "core_loaded" => true,
        "core_schema" => M03Core.CORE_SCHEMA,
        "core_version" => M03Core.CORE_VERSION,
    )
    return rpc_success(request_id, request_sha, result)
end

function handle_solve_node(request_id, request_sha, params::Dict)
    bits = validate_node_request!(params)
    tier = params["precision_tier"]

    node_sha = params["node_identity_sha256"]
    output_root = params["output_root"]
    attempt_path = safe_attempt_path(output_root, node_sha, request_sha)

    reused = check_reuse(attempt_path, request_sha, node_sha)
    if reused !== nothing
        original_disposition = reused["disposition"]
        # Repair the canonical pointer if a crash left it absent between the
        # attempt commit and the pointer publish. Idempotent: keeps a valid
        # existing pointer, writes one only when missing or corrupt.
        if original_disposition == "PRODUCED"
            attempt_manifest_sha = sha256_file(joinpath(attempt_path, "node-manifest.json"))
            publish_or_verify_canonical_node_pointer(output_root, node_sha, request_sha,
                attempt_manifest_sha, tier)
        end
        result = Dict{String,Any}(
            "disposition" => "REUSED",
            "original_disposition" => original_disposition,
            "node_identity_sha256" => node_sha,
            "root_identity_sha256" => params["upstream_root_identity"],
            "precision_tier" => tier,
            "artifact_path" => attempt_path,
            "artifact_sha256" => sha256_file(joinpath(attempt_path, "node-manifest.json")),
            "reason" => get(reused, "reason", nothing),
            "spin_identity" => params["spin_identity"],
            "frozen_omega" => params["frozen_omega"],
            "frozen_A" => params["frozen_A"],
            "handoff_identity_sha256" => params["m02_handoff_sha256"],
            "numerical_policy_identity" => params["numerical_policy_identity"],
            "summary" => Dict{String,Any}(
                "disposition" => "REUSED",
                "original_disposition" => original_disposition,
                "root_solves" => 0,
                "base_angular_eigenvalue_solves" => 0,
                "m02_response_solves" => 0,
                "echoed_spin" => params["spin_identity"]["physical_spin_text"],
                "echoed_omega_real" => params["frozen_omega"]["real"],
                "echoed_omega_imag" => params["frozen_omega"]["imaginary"],
                "echoed_A_real" => params["frozen_A"]["real"],
                "echoed_A_imag" => params["frozen_A"]["imaginary"],
                "echoed_root_identity" => params["upstream_root_identity"],
                "echoed_handoff_identity" => params["m02_handoff_sha256"],
                "echoed_policy_identity" => params["numerical_policy_identity"],
            ),
        )
        return rpc_success(request_id, request_sha, result)
    end

    spectral_result, cont_edge = setprecision(BigFloat, bits) do
        seed, stencil, policy, predecessor = build_typed_inputs(BigFloat, params)

        if predecessor !== nothing
            predecessor.branch_identity == params["branch_identity"] ||
                error("IDENTITY_REJECTION:predecessor branch identity does not match request branch_identity")
            predecessor.chain_position + 1 == Int(params["chain_position"]) ||
                error("IDENTITY_REJECTION:predecessor chain_position $(predecessor.chain_position) + 1 != request chain_position $(params["chain_position"])")
        end

        sr = M03Core.solve_node(seed, stencil, policy)

        edge = nothing
        if predecessor !== nothing && sr.disposition == "PRODUCED"
            edge = M03Core.compare_continuation(predecessor, sr, policy)
        end

        (sr, edge)
    end

    artifacts = setprecision(BigFloat, bits) do
        serialize_node_artifacts(spectral_result, params, request_sha;
            continuation_edge=cont_edge)
    end

    manifest_sha = atomic_publish!(artifacts, attempt_path, node_sha, request_sha)

    if spectral_result.disposition == "PRODUCED"
        publish_or_verify_canonical_node_pointer(output_root, node_sha, request_sha,
            manifest_sha, tier)
    end

    summary = setprecision(BigFloat, bits) do
        build_summary(spectral_result, params)
    end

    result = Dict{String,Any}(
        "disposition" => spectral_result.disposition,
        "node_identity_sha256" => node_sha,
        "root_identity_sha256" => spectral_result.root_identity_sha256,
        "precision_tier" => tier,
        "artifact_path" => attempt_path,
        "artifact_sha256" => manifest_sha,
        "reason" => spectral_result.reason,
        "summary" => summary,
        "spin_identity" => params["spin_identity"],
        "frozen_omega" => params["frozen_omega"],
        "frozen_A" => params["frozen_A"],
        "handoff_identity_sha256" => params["m02_handoff_sha256"],
        "numerical_policy_identity" => params["numerical_policy_identity"],
    )
    return rpc_success(request_id, request_sha, result)
end

function _serialize_edge(e)
    return Dict{String,Any}(
        "predecessor_sha256" => e.predecessor_sha256,
        "successor_sha256" => e.successor_sha256,
        "angular_overlap_raw" => serialize_complex(e.angular_overlap_raw),
        "angular_overlap_aligned" => serialize_real(e.angular_overlap_aligned),
        "angular_phase_factor" => serialize_complex(e.angular_phase_factor),
        "radial_right_overlap_raw" => serialize_complex(e.radial_right_overlap_raw),
        "radial_right_overlap_aligned" => serialize_real(e.radial_right_overlap_aligned),
        "radial_right_phase_factor" => serialize_complex(e.radial_right_phase_factor),
        "radial_dual_overlap_raw" => serialize_complex(e.radial_dual_overlap_raw),
        "radial_dual_overlap_aligned" => serialize_real(e.radial_dual_overlap_aligned),
        "radial_dual_phase_factor" => serialize_complex(e.radial_dual_phase_factor),
    )
end

function handle_reduce_branch(request_id, request_sha, params::Dict)
    branch_fields = Set([
        "request_schema", "branch_identity", "branch_nodes", "precision_tier",
        "numerical_policy", "numerical_policy_identity", "output_root",
        "declared_unresolved_gaps",
    ])
    _require_exact_keys(params, branch_fields, "branch request")
    params["request_schema"] == BRANCH_REQUEST_SCHEMA ||
        error("IDENTITY_REJECTION:wrong branch request schema")
    _require_exact_keys(params["numerical_policy"], NUMERICAL_POLICY_FIELDS,
        "numerical_policy")
    _validate_sha256_format(params["numerical_policy_identity"],
        "numerical_policy_identity")
    sha256_hex(canonical_json_bytes(params["numerical_policy"])) ==
        params["numerical_policy_identity"] ||
        error("IDENTITY_REJECTION:numerical policy identity mismatch")
    for name in ("endpoint_order", "angular_pad", "quadrature_panels")
        isa(params["numerical_policy"][name], Integer) &&
            !isa(params["numerical_policy"][name], Bool) &&
            params["numerical_policy"][name] > 0 ||
            error("POLICY_REJECTION:numerical_policy.$name must be a positive integer")
    end
    for name in setdiff(NUMERICAL_POLICY_FIELDS,
                        Set(["endpoint_order", "angular_pad", "quadrature_panels",
                             "retained_rho_grid"]))
        _require_decimal_text(params["numerical_policy"][name],
            "numerical_policy.$name")
    end
    branch_grid = params["numerical_policy"]["retained_rho_grid"]
    isa(branch_grid, AbstractVector) && length(branch_grid) >= 3 ||
        error("POLICY_REJECTION:numerical_policy.retained_rho_grid must contain at least three points")
    for (index, coordinate) in enumerate(branch_grid)
        _require_decimal_text(coordinate,
            "numerical_policy.retained_rho_grid[$index]")
    end

    branch_id = params["branch_identity"]
    isa(branch_id, AbstractString) && !isempty(branch_id) ||
        error("IDENTITY_REJECTION:branch_identity must not be empty")
    isa(params["branch_nodes"], AbstractVector) ||
        error("IDENTITY_REJECTION:branch_nodes must be an array")
    isempty(params["branch_nodes"]) &&
        error("IDENTITY_REJECTION:branch_nodes must not be empty")
    isa(params["declared_unresolved_gaps"], AbstractVector) ||
        error("IDENTITY_REJECTION:declared_unresolved_gaps must be an array")
    isa(params["output_root"], AbstractString) && !isempty(params["output_root"]) ||
        error("IDENTITY_REJECTION:output_root must be non-empty text")

    tier = params["precision_tier"]
    bits = validate_precision_tier(tier)
    bits === nothing && error("POLICY_REJECTION:unsupported precision tier: $tier")

    branch_result = setprecision(BigFloat, bits) do
        node_refs = params["branch_nodes"]
        np = params["numerical_policy"]

        policy = NumericalPolicy{BigFloat}(
            params["numerical_policy_identity"],
            tier,
            bits,
            parse_real(BigFloat, np["readout_radius"]),
            parse_real(BigFloat, np["rho_inner"]),
            parse_real(BigFloat, np["rho_outer"]),
            Int(np["endpoint_order"]),
            Int(np["angular_pad"]),
            parse_real(BigFloat, np["ode_reltol"]),
            parse_real(BigFloat, np["ode_abstol"]),
            parse_real(BigFloat, np["angular_derivative_step"]),
            parse_real(BigFloat, np["frequency_audit_step"]),
            Int(np["quadrature_panels"]),
            parse_real(BigFloat, np["angular_right_residual_max"]),
            parse_real(BigFloat, np["angular_transpose_residual_max"]),
            parse_real(BigFloat, np["angular_symmetry_residual_max"]),
            parse_real(BigFloat, np["angular_c_product_min"]),
            parse_real(BigFloat, np["lambda_derivative_disagreement_max"]),
            parse_real(BigFloat, np["radial_wronskian_max"]),
            parse_real(BigFloat, np["matching_right_null_max"]),
            parse_real(BigFloat, np["matching_left_null_max"]),
            parse_real(BigFloat, np["transpose_endpoint_residual_max"]),
            parse_real(BigFloat, np["transpose_readout_residual_max"]),
            parse_real(BigFloat, np["dual_projective_disagreement_max"]),
            parse_real(BigFloat, np["bilinear_conservation_max"]),
            parse_real(BigFloat, np["domega_stencil_relative_disagreement_max"]),
            parse_real(BigFloat, np["local_domega_to_m02_relative_max"]),
            parse_real(BigFloat, np["contour_to_readout_denominator_relative_max"]),
            parse_real(BigFloat, np["bridge_closure_relative_max"]),
            parse_real(BigFloat, np["residue_rescaling_relative_max"]),
            parse_real(BigFloat, np["projector_rescaling_relative_max"]),
            parse_real(BigFloat, np["projector_idempotence_relative_max"]),
            parse_real(BigFloat, np["projector_action_relative_max"]),
            parse_real(BigFloat, np["local_resolvent_residue_relative_max"]),
            parse_real(BigFloat, np["local_resolvent_projector_relative_max"]),
            parse_real(BigFloat, np["adjugate_residue_relative_max"]),
            BigFloat[parse_real(BigFloat, x) for x in np["retained_rho_grid"]],
        )
        validate_typed_policy!(policy)

        ordered = SpectralStateResult{BigFloat}[]
        chain_positions = Int[]
        for ref in node_refs
            isa(ref, AbstractDict) || error("IDENTITY_REJECTION:branch node reference must be an object")
            node_ref_fields = Set([
                "artifact_path", "node_identity_sha256", "root_identity_sha256",
                "branch_identity", "chain_position", "precision_tier",
                "manifest_sha256",
            ])
            _require_exact_keys(ref, node_ref_fields, "branch node reference")
            _validate_sha256_format(ref["node_identity_sha256"],
                "branch node reference node_identity_sha256")
            _validate_sha256_format(ref["root_identity_sha256"],
                "branch node reference root_identity_sha256")
            _validate_sha256_format(ref["manifest_sha256"],
                "branch node reference manifest_sha256")
            isa(ref["chain_position"], Integer) &&
                !isa(ref["chain_position"], Bool) &&
                ref["chain_position"] >= 0 ||
                error("IDENTITY_REJECTION:branch node chain_position must be a nonnegative integer")
            validate_precision_tier(ref["precision_tier"]) !== nothing ||
                error("POLICY_REJECTION:branch node has an unsupported precision tier")
            (tier == "bigfloat-80" || ref["precision_tier"] == "bigfloat-40") ||
                error("POLICY_REJECTION:BF40 branch reduction cannot consume a BF80 node")
            artifact_path = ref["artifact_path"]
            isa(artifact_path, AbstractString) ||
                error("IDENTITY_REJECTION:branch artifact_path must be text")
            _path_is_within(params["output_root"], artifact_path) ||
                error("IDENTITY_REJECTION:branch node artifact is outside output_root")
            isdir(artifact_path) || error("IDENTITY_REJECTION:node artifact not found: $artifact_path")

            ref["branch_identity"] == branch_id ||
                error("IDENTITY_REJECTION:branch node reference branch identity does not match requested branch_identity")

            node_result = _load_node_result(
                BigFloat, artifact_path, ref,
                params["numerical_policy_identity"],
            )
            push!(ordered, node_result)
            push!(chain_positions, Int(ref["chain_position"]))
        end

        # Declared unresolved gaps: intervals [from, to] (from == last resolved
        # position, to == next resolved position) the caller explicitly marks as
        # a known break in the chain. Any non-unit step must be covered exactly
        # by such a declaration, so an unresolved node cannot silently vanish
        # from the list and leave the remaining subset looking complete.
        declared_gaps = Set{Tuple{Int,Int}}()
        for g in params["declared_unresolved_gaps"]
            (isa(g, AbstractVector) && length(g) == 2) ||
                error("IDENTITY_REJECTION:declared_unresolved_gaps entries must be [from, to] pairs")
            all(value -> isa(value, Integer) && !isa(value, Bool), g) ||
                error("IDENTITY_REJECTION:declared unresolved gap positions must be integers")
            push!(declared_gaps, (Int(g[1]), Int(g[2])))
        end

        length(unique(chain_positions)) == length(chain_positions) ||
            error("IDENTITY_REJECTION:branch chain positions must be unique")
        first(chain_positions) == 0 ||
            error("IDENTITY_REJECTION:branch reduction must begin at chain position zero")
        observed_gaps = Set{Tuple{Int,Int}}()
        for i in 2:length(chain_positions)
            prev = chain_positions[i-1]
            cur = chain_positions[i]
            cur > prev ||
                error("IDENTITY_REJECTION:branch chain positions must be strictly increasing (got $prev then $cur)")
            if cur != prev + 1
                push!(observed_gaps, (prev, cur))
                (prev, cur) in declared_gaps ||
                    error("IDENTITY_REJECTION:non-contiguous branch chain positions $prev -> $cur without a declared unresolved gap")
            end
        end
        observed_gaps == declared_gaps ||
            error("IDENTITY_REJECTION:declared unresolved gaps do not match the ordered branch nodes")

        M03Core.reduce_branch(branch_id, ordered, policy, chain_positions, declared_gaps)
    end

    output_root = params["output_root"]
    branch_artifact = Dict{String,Any}(
        "branch_identity" => branch_result.branch_identity,
        "node_identities" => branch_result.node_identities,
        "edges" => [_serialize_edge(e) for e in branch_result.edges],
        "precision_history" => branch_result.precision_history,
        "unresolved_gaps" => [collect(g) for g in branch_result.unresolved_gaps],
        "completion_status" => branch_result.completion_status,
        "completion_evidence" => branch_result.completion_evidence,
    )
    branch_json = JSON.json(branch_artifact)
    branch_hash = sha256_hex(branch_json)
    disposition = branch_result.completion_status == "COMPLETE" ? "PRODUCED" : "UNRESOLVED"

    branch_dir = safe_branch_path(output_root, branch_id)

    local branch_manifest_sha::String
    if isdir(branch_dir)
        existing_manifest_path = joinpath(branch_dir, "branch-manifest.json")
        isfile(existing_manifest_path) ||
            error("IDENTITY_REJECTION:existing branch directory missing manifest")
        existing_manifest = JSON.parsefile(existing_manifest_path)
        existing_manifest["branch_identity"] == branch_id ||
            error("IDENTITY_REJECTION:existing branch manifest identity mismatch")
        get(existing_manifest, "disposition", nothing) == disposition ||
            error("IDENTITY_REJECTION:existing branch manifest disposition mismatch")
        get(existing_manifest, "request_identity_sha256", nothing) == request_sha ||
            error("IDENTITY_REJECTION:existing branch artifact request identity mismatch (stale or different request)")
        get(existing_manifest, "precision_tier", nothing) == tier ||
            error("IDENTITY_REJECTION:existing branch manifest precision tier mismatch")
        get(existing_manifest, "numerical_policy_identity", nothing) ==
            params["numerical_policy_identity"] ||
            error("IDENTITY_REJECTION:existing branch numerical policy identity mismatch")
        haskey(existing_manifest, "payload_hashes") ||
            error("IDENTITY_REJECTION:existing branch manifest missing payload_hashes")
        existing_hash = get(existing_manifest["payload_hashes"], "branch-result.json", nothing)
        existing_hash == branch_hash ||
            error("IDENTITY_REJECTION:existing branch artifact hash mismatch (stale or different reduction)")
        existing_result_path = joinpath(branch_dir, "branch-result.json")
        isfile(existing_result_path) || error("IDENTITY_REJECTION:existing branch result missing")
        sha256_file(existing_result_path) == branch_hash ||
            error("IDENTITY_REJECTION:existing branch result on-disk hash mismatch")
        branch_manifest_sha = sha256_file(existing_manifest_path)
    else
        isdir(dirname(branch_dir)) || mkpath(dirname(branch_dir))
        tmp_branch = branch_dir * ".tmp." * string(getpid()) * "." * string(time_ns())
        mkpath(tmp_branch)
        branch_path = joinpath(tmp_branch, "branch-result.json")
        open(branch_path, "w") do f
            write(f, branch_json)
        end
        flush_and_sync(branch_path)
        manifest = Dict{String,Any}(
            "schema" => "windows-solver.m03-branch-manifest/1",
            "disposition" => disposition,
            "branch_identity" => branch_id,
            "request_identity_sha256" => request_sha,
            "precision_tier" => tier,
            "numerical_policy_identity" => params["numerical_policy_identity"],
            "payload_hashes" => Dict("branch-result.json" => branch_hash),
        )
        manifest_json = JSON.json(manifest)
        open(joinpath(tmp_branch, "branch-manifest.json"), "w") do f
            write(f, manifest_json)
        end
        flush_and_sync(joinpath(tmp_branch, "branch-manifest.json"))
        mv(tmp_branch, branch_dir)
        branch_manifest_sha = sha256_hex(manifest_json)
    end

    result = Dict{String,Any}(
        "disposition" => disposition,
        "branch_identity" => branch_result.branch_identity,
        "node_count" => length(branch_result.node_identities),
        "edge_count" => length(branch_result.edges),
        "completion_status" => branch_result.completion_status,
        "unresolved_gaps" => [collect(g) for g in branch_result.unresolved_gaps],
        "artifact_path" => branch_dir,
        "artifact_sha256" => branch_manifest_sha,
        "reason" => disposition == "PRODUCED" ? nothing : "branch contains unresolved nodes or gaps",
        "root_solves" => 0,
        "base_angular_solves" => 0,
        "right_radial_solves" => 0,
        "radial_transpose_solves" => 0,
        "julia_process_launches" => 0,
    )

    return rpc_success(request_id, request_sha, result)
end

function _load_node_result(
    ::Type{T}, path::String, ref::Dict, policy_identity::String
) where {T<:AbstractFloat}
    manifest_path = joinpath(path, "node-manifest.json")
    isfile(manifest_path) || error("IDENTITY_REJECTION:node manifest missing at $path")
    manifest = JSON.parsefile(manifest_path)

    haskey(manifest, "schema") && manifest["schema"] == "windows-solver.m03-node-manifest/1" ||
        error("IDENTITY_REJECTION:node manifest schema mismatch or missing")

    # Every branch-node reference must fully specify identity, membership,
    # ordering, precision, and the accepted attempt manifest SHA.
    for f in ("node_identity_sha256", "root_identity_sha256", "branch_identity",
              "chain_position", "precision_tier", "manifest_sha256")
        haskey(ref, f) || error("IDENTITY_REJECTION:branch node reference missing required field: $f")
    end

    manifest["node_identity_sha256"] == ref["node_identity_sha256"] ||
        error("IDENTITY_REJECTION:node manifest identity mismatch: expected $(ref["node_identity_sha256"]), got $(manifest["node_identity_sha256"])")
    manifest["root_identity_sha256"] == ref["root_identity_sha256"] ||
        error("IDENTITY_REJECTION:node root identity mismatch")
    manifest["branch_identity"] == ref["branch_identity"] ||
        error("IDENTITY_REJECTION:node branch identity mismatch")
    manifest["chain_position"] == ref["chain_position"] ||
        error("IDENTITY_REJECTION:node chain position mismatch")
    manifest["precision_tier"] == ref["precision_tier"] ||
        error("IDENTITY_REJECTION:node precision tier mismatch")
    get(manifest, "numerical_policy_identity", nothing) == policy_identity ||
        error("IDENTITY_REJECTION:node numerical policy identity mismatch")

    actual_manifest_sha = sha256_file(manifest_path)
    actual_manifest_sha == ref["manifest_sha256"] ||
        error("IDENTITY_REJECTION:node manifest SHA mismatch: expected $(ref["manifest_sha256"]), got $actual_manifest_sha")

    get(manifest, "disposition", nothing) in ("PRODUCED", "UNRESOLVED") ||
        error("IDENTITY_REJECTION:cannot reduce branch from non-terminal node at $path (disposition=$(get(manifest, "disposition", "missing")))")

    for payload_file in ("validation.json", "angular-state.json", "radial-right.json",
                         "radial-dual.json", "pole-object.json")
        fpath = joinpath(path, payload_file)
        isfile(fpath) || error("IDENTITY_REJECTION:node artifact missing: $payload_file at $path")
        _verify_payload_hash(manifest, payload_file, fpath)
    end

    validation = JSON.parsefile(joinpath(path, "validation.json"))
    get(validation, "disposition", nothing) == manifest["disposition"] ||
        error("IDENTITY_REJECTION:node validation disposition disagrees with its manifest")
    ang = JSON.parsefile(joinpath(path, "angular-state.json"))
    right = JSON.parsefile(joinpath(path, "radial-right.json"))
    dual = JSON.parsefile(joinpath(path, "radial-dual.json"))
    pole = JSON.parsefile(joinpath(path, "pole-object.json"))

    angular_right = haskey(ang, "right_coefficients") ?
        Complex{T}[parse_complex(T, c) for c in ang["right_coefficients"]] : nothing
    angular_transpose = haskey(ang, "transpose_coefficients") ?
        Complex{T}[parse_complex(T, c) for c in ang["transpose_coefficients"]] : nothing

    _pc(d, k) = haskey(d, k) ? parse_complex(T, d[k]) : nothing
    _pm(d, k) = haskey(d, k) ? _parse_field_matrix(T, d[k]) : nothing

    retained_right = _pm(right, "retained_samples")
    retained_dual = _pm(dual, "retained_samples")
    retained_grid = haskey(right, "retained_rho_grid") ?
        T[parse_real(T, x) for x in right["retained_rho_grid"]] : nothing

    gates = get(validation, "gates", Dict{String,Any}())

    return SpectralStateResult{T}(
        validation["disposition"],
        get(validation, "reason", nothing),
        manifest["node_identity_sha256"],
        manifest["root_identity_sha256"],
        validation["precision_tier"],
        get(validation, "root_solves", 0),
        get(validation, "base_angular_eigenvalue_solves", 0),
        get(validation, "m02_response_solves", 0),
        angular_right, angular_transpose,
        _pc(ang, "c_product"), _pc(ang, "Ac_prime"),
        _pc(ang, "Aomega_prime"), _pc(ang, "lambda_prime"),
        nothing, nothing,  # angular matrix/derivative not persisted
        _pc(ang, "lambda"),
        _pm(right, "matching_matrix"),
        _pc(right, "matching_determinant"),
        _pm(pole, "F_prime"), _pm(pole, "adjugate"),
        haskey(right, "coefficient_right") ?
            Complex{T}[parse_complex(T, c) for c in right["coefficient_right"]] : nothing,
        haskey(dual, "coefficient_left") ?
            Complex{T}[parse_complex(T, c) for c in dual["coefficient_left"]] : nothing,
        nothing,  # adjugate_factor_error
        _pc(dual, "eta_horizon"), _pc(dual, "eta_infinity"),
        haskey(dual, "z_match") ?
            Complex{T}[parse_complex(T, c) for c in dual["z_match"]] : nothing,
        _pc(pole, "denominator_bulk"),
        _pc(pole, "denominator_horizon_trace"),
        _pc(pole, "denominator_infinity_trace"),
        _pc(pole, "denominator_raw"),
        _pc(pole, "denominator_readout"),
        _pc(pole, "m02_Domega_fine"),
        _pc(pole, "m02_Domega_coarse"),
        nothing,  # m02_stencil_disagreement
        _pc(pole, "local_determinant_derivative"),
        _pc(pole, "bridge"),
        _pm(pole, "residue"), _pm(pole, "projector"),
        retained_grid, retained_right, retained_dual,
        gates,
    )
end

# ---------------------------------------------------------------------------
# Main server loop
# ---------------------------------------------------------------------------

function run_server()
    println(stderr, "[$WORKER_KIND] $WORKER_VERSION starting, core=$(M03Core.CORE_VERSION)")

    for line in eachline(stdin)
        stripped = strip(line)
        isempty(stripped) && continue

        local envelope
        try
            envelope = JSON.parse(stripped)
        catch e
            err_resp = rpc_error(nothing, nothing, "SYSTEM_FAILURE",
                "malformed JSON: $(sprint(showerror, e))")
            println(stdout, JSON.json(err_resp))
            flush(stdout)
            continue
        end

        request_id = get(envelope, "request_id", nothing)
        request_sha = nothing

        local response
        try
            required_envelope_fields = Set(["schema", "request_id", "method", "params", "request_identity_sha256"])
            envelope_keys = Set(keys(envelope))
            missing_env = setdiff(required_envelope_fields, envelope_keys)
            isempty(missing_env) || error("SYSTEM_FAILURE:missing envelope fields: $(join(sort(collect(missing_env)), ", "))")
            extra_env = setdiff(envelope_keys, required_envelope_fields)
            isempty(extra_env) || error("SYSTEM_FAILURE:unexpected envelope fields: $(join(sort(collect(extra_env)), ", "))")

            envelope["schema"] == RPC_SCHEMA ||
                error("IDENTITY_REJECTION:wrong RPC schema: $(envelope["schema"])")

            claimed_sha = envelope["request_identity_sha256"]
            isa(claimed_sha, AbstractString) || error("IDENTITY_REJECTION:request_identity_sha256 must be a string")
            _validate_sha256_format(claimed_sha, "request_identity_sha256")
            computed_sha = compute_request_identity(envelope)
            claimed_sha == computed_sha ||
                error("IDENTITY_REJECTION:request identity hash mismatch")
            request_sha = computed_sha

            method = envelope["method"]
            params = envelope["params"]
            isa(params, AbstractDict) || error("SYSTEM_FAILURE:params must be an object")

            if method == "hello"
                response = handle_hello(request_id, request_sha)
            elseif method == "probe"
                response = handle_probe(request_id, request_sha)
            elseif method == "solve_node"
                response = handle_solve_node(request_id, request_sha, params)
            elseif method == "reduce_branch"
                response = handle_reduce_branch(request_id, request_sha, params)
            elseif method == "shutdown"
                resp = rpc_success(request_id, computed_sha,
                    Dict{String,Any}("shutdown" => true))
                println(stdout, JSON.json(resp))
                flush(stdout)
                println(stderr, "[$WORKER_KIND] shutdown requested, exiting")
                return
            else
                error("SYSTEM_FAILURE:unknown method: $method")
            end
        catch e
            msg = sprint(showerror, e)
            error_class = "SYSTEM_FAILURE"
            if startswith(msg, "IDENTITY_REJECTION:")
                error_class = "IDENTITY_REJECTION"
                msg = msg[length("IDENTITY_REJECTION:")+1:end]
            elseif startswith(msg, "POLICY_REJECTION:")
                error_class = "POLICY_REJECTION"
                msg = msg[length("POLICY_REJECTION:")+1:end]
            end
            err_sha = request_sha
            response = rpc_error(request_id, err_sha, error_class, msg)
        end

        println(stdout, JSON.json(response))
        flush(stdout)
    end

    println(stderr, "[$WORKER_KIND] stdin closed, exiting")
end

if abspath(PROGRAM_FILE) == @__FILE__
    if ARGS == ["--probe"]
        println(stderr,
            "[$WORKER_KIND] dependency probe passed, core=$(M03Core.CORE_VERSION)")
    elseif isempty(ARGS)
        run_server()
    else
        error("unsupported M03 worker arguments: $(join(ARGS, " "))")
    end
end
