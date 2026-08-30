function deterministic_endpoint_receipts(
    ::Type{T}, request, limitation::String
) where {T<:AbstractFloat}
    policy = required(request, "fixed_root_endpoint_recovery_policy")
    required_digits = required_reliable_digits(T, request)
    adequate = limitation == CF.ENDPOINT_ADEQUATE
    predicted = adequate ? required_digits + T(5) : required_digits - one(T)
    intervention = adequate ? "ENTER_HOMOGENEOUS_ODE" :
        "PROMOTE_ARITHMETIC_TIER_IF_AGGREGATE_ALLOWS"
    result = adequate ? "ADEQUATE" : "ARITHMETIC_INADEQUATE"
    order = first(required(policy, "endpoint_order_schedule"))

    role = string(required(request, "readout_role"))
    match_radius = if role in FIXED_ROOT_SURVEY_BACKGROUND_ROLES
        parse_real(T, request, "readout_radius")
    else
        parse_real(T, request, "support_lower")
    end
    spin = parse_real(T, request, "spin")
    rplus = one(T) + sqrt(one(T) - spin^2)
    horizon_distance = T("0.01")
    horizon_radius = rplus + horizon_distance
    horizon_schedule = required(policy, "horizon_geometry_schedule")
    horizon_attempt = Dict{String,Any}(
        "rho" => first(horizon_schedule),
        "radius" => Dict(
            "real" => numeric_text(horizon_radius),
            "imaginary" => "0",
        ),
        "horizon_distance" => numeric_text(horizon_distance),
        "expansion_variable_magnitude" => numeric_text(horizon_distance),
        "exterior" => true,
        "on_real_axis" => true,
        "approaches_horizon" => true,
        "within_maximum_distance" => true,
        "attempted_endpoint_order" => order,
        "best_prefix_order" => order,
        "last_term_ratio" => "0.1",
        "predicted_reliable_digits" => numeric_text(predicted),
        "required_reliable_digits" => numeric_text(required_digits),
        "adequate" => adequate,
        "maximum_truncation_digits_lost" => "2",
        "maximum_recurrence_digits_lost" => "1",
        "maximum_series_evaluation_digits_lost" => "1",
        "candidate_limitation" => limitation,
    )
    horizon_receipt = Dict{String,Any}(
        "schema" => "windows-solver.exterior-endpoint-recovery-receipt/2",
        "endpoint_branch" => "horizon-ingoing",
        "contour_identity" => "real-inner-tortoise-contour/v1",
        "recovery_policy_identity" => required(policy, "identity"),
        "recovery_policy_sha256" => required(policy, "policy_sha256"),
        "match_radius" => numeric_text(match_radius),
        "rstar_match" => "1",
        "rho_floor" => required(policy, "horizon_endpoint_rho_floor"),
        "rho_schedule" => horizon_schedule,
        "coordinate_identity" => Dict{String,Any}(
            "passed" => true,
            "sample_count" => length(horizon_schedule),
            "maximum_absolute_residual" => "0",
            "maximum_relative_residual" => "0",
            "absolute_tolerance" => "1e-20",
            "relative_tolerance" => "1e-20",
            "maximum_absolute_residual_over_tolerance" => "0",
            "maximum_relative_residual_over_tolerance" => "0",
        ),
        "attempts" => Any[horizon_attempt],
        "selected_rho" => adequate ? first(horizon_schedule) : nothing,
        "selected_endpoint_order" => adequate ? order : nothing,
        "selected_best_prefix_order" => adequate ? order : nothing,
        "candidate_limitation" => limitation,
        "aggregate_limitation" => limitation,
        "maximum_truncation_digits_lost" => "2",
        "factored_homogeneous_rhs_evaluations_before_decision" => 0,
    )

    infinity_schedule = required(policy, "infinity_geometry_schedule")
    infinity_attempt = Dict{String,Any}(
        "endpoint_branch" => "infinity-outgoing",
        "attempted_endpoint_order" => order,
        "attempted_geometry" => first(infinity_schedule),
        "maximum_last_term_ratio" => "0.1",
        "maximum_truncation_digits_lost" => "2",
        "maximum_recurrence_digits_lost" => "1",
        "maximum_series_evaluation_digits_lost" => "1",
        "predicted_reliable_digits" => numeric_text(predicted),
        "required_reliable_digits" => numeric_text(required_digits),
        "candidate_limitation" => limitation,
        "selected_intervention" => intervention,
        "result" => result,
    )
    infinity_receipt = Dict{String,Any}(
        "schema" => "windows-solver.exterior-endpoint-recovery-receipt/1",
        "endpoint_branch" => "infinity-outgoing",
        "recovery_policy_identity" => required(policy, "identity"),
        "recovery_policy_sha256" => required(policy, "policy_sha256"),
        "base_endpoint_order" => required(policy, "base_endpoint_order"),
        "generated_maximum_order" =>
            required(policy, "generated_maximum_order"),
        "attempted_endpoint_orders" => [order],
        "terminal_endpoint_order" => order,
        "candidate_geometry_schedule" => infinity_schedule,
        "terminal_geometry" => first(infinity_schedule),
        "maximum_last_term_ratio" => "0.1",
        "maximum_truncation_digits_lost" => "2",
        "maximum_recurrence_digits_lost" => "1",
        "maximum_series_evaluation_digits_lost" => "1",
        "predicted_reliable_digits" => numeric_text(predicted),
        "required_reliable_digits" => numeric_text(required_digits),
        "candidate_limitation" => limitation,
        "aggregate_limitation" => limitation,
        "factored_homogeneous_rhs_evaluations" => 0,
        "attempts" => Any[infinity_attempt],
    )
    return Any[horizon_receipt, infinity_receipt]
end
