#!/usr/bin/env julia

# M03's stdout is a protocol channel.  All human diagnostics go to stderr.
using JSON
using SHA
using LinearAlgebra
using GeneralizedSasakiNakamura
using SpinWeightedSpheroidalHarmonics

const RPC_SCHEMA = "windows-solver.m03-json-rpc/1"
const WORKER_KIND = "m03-julia-scientific-engine"
const WORKER_VERSION = "m03-worker-v1"
const ALLOWED_PRECISION_TIERS = Set(("bigfloat-40", "bigfloat-80"))

function canonical_json(value)
    if value isa AbstractDict
        names = sort!(String[string(key) for key in keys(value)])
        return "{" * join(
            (JSON.json(name) * ":" * canonical_json(value[name]) for name in names),
            ",",
        ) * "}"
    elseif value isa AbstractVector || value isa Tuple
        return "[" * join((canonical_json(item) for item in value), ",") * "]"
    elseif value === nothing || value isa Bool || value isa Number || value isa AbstractString
        return JSON.json(value)
    end
    error("M03 protocol contains a non-JSON value")
end

canonical_sha256(value) = bytes2hex(SHA.sha256(codeunits(canonical_json(value))))

function required(mapping, name)
    haskey(mapping, name) || error("missing required M03 field: " * name)
    return mapping[name]
end

function exact_keys(mapping, names)
    Set(string(key) for key in keys(mapping)) == Set(names) ||
        error("M03 request fields are invalid")
end

function ensure_sha256(value, subject)
    text = string(value)
    occursin(r"^[0-9a-f]{64}$", text) || error(subject * " is not a SHA-256")
    return text
end

function ensure_decimal_identity(value, subject)
    value isa AbstractString || error(subject * " must be canonical text")
    parsed = tryparse(BigFloat, value)
    parsed === nothing && error(subject * " is not parseable")
    isfinite(parsed) || error(subject * " is non-finite")
    return value, parsed
end

function validate_node_request(params)
    exact_keys(params, (
        "request_schema", "node_identity_sha256", "mode", "spin_identity",
        "frozen_omega", "frozen_A", "upstream_root_identity",
        "m02_handoff_sha256", "branch_identity", "chain_position",
        "predecessor_state_reference", "precision_tier",
        "numerical_policy_identity", "numerical_policy", "output_root",
        "source_revision", "root_movement_permitted",
    ))
    required(params, "request_schema") == "windows-solver.m03-node-request/1" ||
        error("M03 node request schema is invalid")
    ensure_sha256(required(params, "node_identity_sha256"), "node identity")
    ensure_sha256(required(params, "m02_handoff_sha256"), "handoff identity")
    ensure_sha256(required(params, "numerical_policy_identity"), "policy identity")
    required(params, "root_movement_permitted") === false ||
        error("M03 request permits movement of the frozen root")
    precision = string(required(params, "precision_tier"))
    precision in ALLOWED_PRECISION_TIERS ||
        error("binary64/BF120 are not admissible M03 field tiers")
    omega = required(params, "frozen_omega")
    angular = required(params, "frozen_A")
    omega isa AbstractDict || error("frozen omega identity is invalid")
    angular isa AbstractDict || error("frozen A identity is invalid")
    omega_real_text, omega_real = ensure_decimal_identity(required(omega, "real"), "omega real")
    omega_imag_text, omega_imag = ensure_decimal_identity(required(omega, "imaginary"), "omega imaginary")
    angular_real_text, angular_real = ensure_decimal_identity(required(angular, "real"), "A real")
    angular_imag_text, angular_imag = ensure_decimal_identity(required(angular, "imaginary"), "A imaginary")
    omega_imag < 0 || error("M03 frozen root is not damped")
    return Dict{String,Any}(
        "precision_tier" => precision,
        "working_precision_bits" => precision == "bigfloat-40" ? 165 : 298,
        "omega_text" => Dict("real" => omega_real_text, "imaginary" => omega_imag_text, "units" => required(omega, "units")),
        "A_text" => Dict("real" => angular_real_text, "imaginary" => angular_imag_text),
        "omega" => Complex{BigFloat}(omega_real, omega_imag),
        "A" => Complex{BigFloat}(angular_real, angular_imag),
    )
end

function production_blockers(policy)
    conventions = required(policy, "conventions")
    blockers = String[]
    thresholds = required(policy, "validation_thresholds")
    required(thresholds, "review_state") == "FROZEN" ||
        push!(blockers, "validation_thresholds:" * string(required(thresholds, "required_decision")))
    for name in ("right_state", "co_mode", "residue", "branch_classification")
        convention = required(conventions, name)
        required(convention, "review_state") == "FROZEN" ||
            push!(blockers, name * ":" * string(required(convention, "required_decision")))
    end
    return blockers
end

function atomic_json(path, value)
    mkpath(dirname(path))
    temporary = path * ".tmp-" * string(getpid()) * "-" * bytes2hex(rand(UInt8, 8))
    open(temporary, "w") do io
        write(io, canonical_json(value))
        flush(io)
    end
    digest = bytes2hex(SHA.sha256(read(temporary)))
    mv(temporary, path; force=false)
    return digest
end

function solve_node(params)
    context = validate_node_request(params)
    blockers = production_blockers(required(params, "numerical_policy"))
    isempty(blockers) || error(
        "BLOCKED_HUMAN_MATH_REVIEW: " * join(blockers, "; ")
    )

    # The production implementation is deliberately reached only after the
    # reviewed convention receipt is frozen.  This guard must remain ahead of
    # every field construction so an implementer cannot accidentally produce
    # a co-mode or residue under an implicit Euclidean/conjugate convention.
    error("BLOCKED_HUMAN_MATH_REVIEW: reviewed M03 scientific activation receipt is absent")
end

function reduce_branch(params)
    exact_keys(params, (
        "request_schema", "branch_identity", "ordered_nodes", "output_root",
        "root_solves_permitted",
    ))
    required(params, "request_schema") == "windows-solver.m03-branch-request/1" ||
        error("M03 branch request schema is invalid")
    required(params, "root_solves_permitted") == 0 ||
        error("M03 branch reduction attempted a root solve")
    branch_identity = string(required(params, "branch_identity"))
    nodes = required(params, "ordered_nodes")
    nodes isa AbstractVector || error("M03 ordered branch nodes are invalid")
    unresolved = [
        string(required(node, "node_identity_sha256"))
        for node in nodes if required(node, "status") == "UNRESOLVED"
    ]
    summary = Dict{String,Any}(
        "schema" => "windows-solver.m03-branch-artifact/1",
        "branch_identity" => branch_identity,
        "ordered_node_ids" => [string(required(node, "node_identity_sha256")) for node in nodes],
        "predecessor_successor_links" => [
            Dict("predecessor" => string(required(nodes[index - 1], "node_identity_sha256")),
                 "successor" => string(required(nodes[index], "node_identity_sha256")))
            for index in 2:length(nodes)
        ],
        "unresolved_gaps" => unresolved,
        "classification" => isempty(unresolved) ? "PENDING_REVIEWED_CLASSIFICATION" : "UNRESOLVED",
        "root_solves" => 0,
    )
    summary["branch_evidence_sha256"] = canonical_sha256(summary)
    relative = joinpath("branches", branch_identity, "branch.json")
    digest = atomic_json(joinpath(string(required(params, "output_root")), relative), summary)
    return Dict{String,Any}(
        "branch_identity" => branch_identity,
        "disposition" => isempty(unresolved) ? "PRODUCED" : "UNRESOLVED",
        "artifact_path" => replace(relative, '\\' => '/'),
        "artifact_sha256" => digest,
        "reason" => isempty(unresolved) ? nothing : "UNRESOLVED_BRANCH_GAP",
    )
end

function analytic_simple_pole_fixture(params)
    # Deterministic algebraic fixture only; it is never a Kerr field fallback.
    F0 = ComplexF64.(required(params, "F0"))
    dF = ComplexF64.(required(params, "dF"))
    right = ComplexF64.(required(params, "right"))
    dual = ComplexF64.(required(params, "dual"))
    denominator = transpose(dual) * dF * right
    abs(denominator) > 0 || return Dict(
        "disposition" => "UNRESOLVED", "reason" => "ZERO_PAIRING"
    )
    projector = (right * transpose(dual)) / denominator
    return Dict{String,Any}(
        "disposition" => "PRODUCED",
        "right_residual_abs" => norm(F0 * right),
        "dual_residual_abs" => norm(transpose(F0) * dual),
        "pairing" => Dict("real" => real(denominator), "imaginary" => imag(denominator)),
        "projector" => [
            [Dict("real" => real(value), "imaginary" => imag(value)) for value in projector[row, :]]
            for row in axes(projector, 1)
        ],
    )
end

function dispatch(method, params)
    method == "hello" && return Dict{String,Any}(
        "worker_kind" => WORKER_KIND,
        "worker_version" => WORKER_VERSION,
        "protocol_schema" => RPC_SCHEMA,
        "persistent" => true,
        "scientific_engine_count" => 1,
    )
    method == "solve_node" && return solve_node(params)
    method == "reduce_branch" && return reduce_branch(params)
    method == "analytic_simple_pole_fixture" && return analytic_simple_pole_fixture(params)
    method == "shutdown" && return Dict{String,Any}("shutdown" => true)
    error("unknown M03 RPC method: " * method)
end

function response(request, ok, result, failure)
    sealed = Dict{String,Any}(
        "schema" => RPC_SCHEMA,
        "request_id" => get(request, "request_id", nothing),
        "request_identity_sha256" => get(request, "request_identity_sha256", nothing),
        "ok" => ok,
        "result" => result,
        "error" => failure,
    )
    sealed["response_identity_sha256"] = canonical_sha256(sealed)
    return sealed
end

function serve()
    for line in eachline(stdin)
        request = Dict{String,Any}()
        terminal = false
        reply = try
            request = JSON.parse(line)
            request isa AbstractDict || error("M03 RPC request is not an object")
            exact_keys(request, (
                "schema", "request_id", "method", "params", "request_identity_sha256",
            ))
            required(request, "schema") == RPC_SCHEMA || error("M03 RPC schema is invalid")
            sealed = Dict{String,Any}(
                "schema" => request["schema"],
                "request_id" => request["request_id"],
                "method" => request["method"],
                "params" => request["params"],
            )
            canonical_sha256(sealed) == request["request_identity_sha256"] ||
                error("M03 RPC request digest is invalid")
            result = dispatch(string(request["method"]), request["params"])
            terminal = string(request["method"]) == "shutdown"
            response(request, true, result, nothing)
        catch exception
            message = sprint(showerror, exception)
            println(stderr, "[m03-worker] " * message)
            failure_class = occursin("identity", lowercase(message)) ||
                occursin("reserialized", lowercase(message)) ?
                "IDENTITY_REJECTION" : "SYSTEM_FAILURE"
            response(request, false, nothing, Dict(
                "class" => failure_class,
                "message" => message,
            ))
        end
        println(stdout, canonical_json(reply))
        flush(stdout)
        terminal && return
    end
end

if "--probe" in ARGS
    println(stderr, "M03 worker probe OK")
    exit(0)
end

serve()
