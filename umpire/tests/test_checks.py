"""One section per check: a passing case from the healthy fixture and the planted failures."""

import dataclasses
from datetime import date

from conftest import PRE, add_audit, cut, entry, experiment, exposures, metric, payload, run_review, set_rate

from third_umpire import checks
from third_umpire.checks import FAIL, PASS, WARN
from third_umpire.model import parse_time

PRIMARY, GUARDRAIL = 901, 902


def test_healthy_fixture_passes_every_check(healthy):
    review = run_review(healthy)
    assert {k: c.status for k, c in review.checks.items()} == {k: PASS for k in review.checks}


# ---------------------------------------------------------------- pre-registration


def test_preregistration_missing_fails(healthy):
    review = run_review(healthy, pre=None)
    assert review.status("preregistration") == FAIL


def test_preregistration_written_after_launch_fails(healthy):
    late = dataclasses.replace(PRE, registered_on=date(2026, 11, 27))
    review = run_review(healthy, pre=late)
    assert review.status("preregistration") == FAIL
    assert "after the experiment started" in review.checks["preregistration"].summary


def test_preregistration_primary_metric_mismatch_fails(healthy):
    defs = entry(healthy, "/experiment-metrics/")
    defs[0]["definition"]["event"] = "round_completed"
    review = run_review(healthy)
    assert review.status("preregistration") == FAIL
    assert "round_completed" in review.checks["preregistration"].summary


def test_preregistration_split_mismatch_fails(healthy):
    experiment(healthy)["experiment_rollout"]["multivariate_feature_state_values"][0]["percentage_allocation"] = 30
    review = run_review(healthy)
    assert review.status("preregistration") == FAIL
    assert "50/50" in review.checks["preregistration"].summary


# ---------------------------------------------------------------- SRM


def test_srm_fails_on_the_planted_skew(bad):
    check = run_review(bad).checks["srm"]
    assert check.status == FAIL
    assert check.data["p_value"] < 0.001
    assert check.data["reported_p_value"] is None
    assert any("would not have warned" in e for e in check.evidence)


def test_srm_tests_the_rollout_split_not_the_environment_default(healthy):
    review = run_review(healthy)
    assert review.ctx.shares == {"control": 0.5, "near_miss": 0.5}
    assert review.ctx.shares_source == "experiment rollout"
    option = experiment(healthy)["feature"]["multivariate_options"][0]
    assert option["default_percentage_allocation"] == 0.0


def test_srm_fails_when_flagsmith_itself_flags_it(healthy):
    payload(healthy)["srm_p_value"] = 0.0002
    assert run_review(healthy).status("srm") == FAIL


def test_srm_warns_below_the_minimum_sample(healthy):
    for m in payload(healthy)["metrics"]:
        m["variants"]["control"]["n"] = 40
        m["variants"]["near_miss"]["n"] = 45
    check = run_review(healthy).checks["srm"]
    assert check.status == WARN
    assert "can't be tested below 100" in check.summary


def test_srm_warns_without_a_configured_split(healthy):
    experiment(healthy)["experiment_rollout"] = None
    assert run_review(healthy).status("srm") == WARN


# ---------------------------------------------------------------- one-sided exposures


def test_one_sided_fails_when_an_arm_never_gets_exposures(healthy):
    for m in payload(healthy)["metrics"]:
        m["variants"]["near_miss"] = {"n": 0, "sum": 0.0, "sum_squares": 0.0}
        m["inference"]["near_miss"] = None
    check = run_review(healthy).checks["one_sided"]
    assert check.status == FAIL
    assert "near_miss" in check.summary


def test_one_sided_fails_when_one_arm_stops_arriving(healthy):
    threshold = cut(healthy, 2 / 3)
    for point in payload(healthy)["exposures_timeseries"]["points"]:
        if parse_time(point["bucket"]) >= threshold:
            point["new_identities"]["near_miss"] = 0
    check = run_review(healthy).checks["one_sided"]
    assert check.status == FAIL
    assert "stopped arriving on near_miss" in check.summary


# ---------------------------------------------------------------- dual exposure


def test_dual_exposure_fails_on_the_planted_fixture(bad):
    check = run_review(bad).checks["dual_exposure"]
    assert check.status == FAIL
    assert check.data["excluded"] == 37


def test_dual_exposure_warns_on_a_handful(healthy):
    exposures(healthy)["excluded_identities"] = 3
    assert run_review(healthy).status("dual_exposure") == WARN


def test_dual_exposure_warns_when_exposures_are_missing(healthy):
    entry(healthy, "/exposures/")["exposures"] = None
    assert run_review(healthy).status("dual_exposure") == WARN


# ---------------------------------------------------------------- conversion wiring


def test_conversion_wiring_fails_when_conversions_flatline(healthy):
    threshold = cut(healthy, 2 / 3)
    for point in metric(healthy, PRIMARY)["conversions_timeseries"]["points"]:
        if parse_time(point["bucket"]) >= threshold:
            point["converted_identities"] = {"control": 0, "near_miss": 0}
    check = run_review(healthy).checks["conversion_wiring"]
    assert check.status == FAIL
    assert "flatlined" in check.summary
    assert run_review(healthy).verdict.call == "DON'T SHIP"


def test_conversion_wiring_fails_with_no_conversions_at_all(healthy):
    for arm in ("control", "near_miss"):
        metric(healthy, PRIMARY)["variants"][arm].update(sum=0.0, sum_squares=0.0)
    check = run_review(healthy).checks["conversion_wiring"]
    assert check.status == FAIL
    assert "zero conversions" in check.summary


def test_conversion_wiring_warns_on_a_sharp_drop(healthy):
    threshold = cut(healthy, 2 / 3)
    points = [p for p in metric(healthy, PRIMARY)["conversions_timeseries"]["points"]
              if parse_time(p["bucket"]) >= threshold]
    for i, point in enumerate(points):
        point["converted_identities"] = {"control": 1 if i < 5 else 0, "near_miss": 1 if i < 5 else 0}
    assert run_review(healthy).status("conversion_wiring") == WARN


# ---------------------------------------------------------------- audit log


def test_audit_fails_on_post_launch_edits(bad):
    check = run_review(bad).checks["audit"]
    assert check.status == FAIL
    assert check.data["edits"] == 4
    assert any("rollout set to 100.0%" in e for e in check.evidence)


def test_audit_ignores_launch_entries_and_other_environments(healthy):
    add_audit(healthy, 3, "Flag state updated for feature: miss_feedback", "FEATURE_STATE", 140233,
              environment_id=52010)
    assert run_review(healthy).status("audit") == PASS


def test_audit_fails_on_a_project_level_flag_edit(healthy):
    add_audit(healthy, 4, "Flag / Remote Config updated: miss_feedback", "FEATURE", 140233, environment_id=None)
    assert run_review(healthy).status("audit") == FAIL


def test_audit_fails_on_a_segment_override_mentioning_the_flag(healthy):
    add_audit(healthy, 5, "Segment Flag state updated for feature: miss_feedback, segment: beta", "SEGMENT", 7)
    assert run_review(healthy).status("audit") == FAIL


def test_audit_warns_on_pause(healthy):
    add_audit(healthy, 6, "Experiment 'Near-miss feedback vs plain miss' paused for environment Production",
              "EXPERIMENT", 412)
    review = run_review(healthy)
    assert review.status("audit") == WARN
    assert review.verdict.call == "SHIP"
    assert review.verdict.warnings


def test_audit_warns_when_the_log_is_unavailable(healthy):
    key = next(k for k in healthy["api"] if k.endswith("/audit/"))
    healthy["api"][key] = {"__status__": 403, "body": {"detail": "Upgrade your plan."}}
    check = run_review(healthy).checks["audit"]
    assert check.status == WARN
    assert "403" in check.evidence[0]


def test_audit_only_counts_metrics_attached_to_the_experiment(healthy):
    add_audit(healthy, 2, "Metric 'Something else' updated", "METRIC", 777)
    assert run_review(healthy).status("audit") == PASS
    add_audit(healthy, 2, "Metric 'Second round started' updated", "METRIC", PRIMARY)
    assert run_review(healthy).status("audit") == FAIL


# ---------------------------------------------------------------- sample size


def test_sample_size_fails_when_read_early(bad):
    check = run_review(bad).checks["sample_size"]
    assert check.status == FAIL
    assert "peeking" in check.summary
    assert check.data["runtime_hours"] < 24


def test_sample_size_reports_underpowered_after_the_hard_stop(early):
    early["now"] = "2026-11-29T07:00:00.000Z"
    review = run_review(early)
    assert review.status("sample_size") == FAIL
    assert "hard stop" in review.checks["sample_size"].summary
    assert review.verdict.call == "DON'T SHIP"


def test_sample_size_passes_when_both_conditions_are_met(healthy):
    check = run_review(healthy).checks["sample_size"]
    assert check.status == PASS
    assert check.data["smallest_arm"] >= 375


# ---------------------------------------------------------------- interval


def test_interval_warns_when_it_crosses_zero(healthy):
    set_rate(healthy, PRIMARY, "near_miss", 0.36)
    check = run_review(healthy).checks["interval"]
    assert check.status == WARN
    assert check.data["ci_low"] < 0 < check.data["ci_high"]


def test_interval_fails_when_credibly_worse(healthy):
    set_rate(healthy, PRIMARY, "near_miss", 0.20)
    assert run_review(healthy).status("interval") == FAIL


def test_interval_warns_when_flagsmith_numbers_dont_reproduce(healthy):
    metric(healthy, PRIMARY)["inference"]["near_miss"]["chance_to_win"] = 0.80
    check = run_review(healthy).checks["interval"]
    assert check.status == WARN
    assert any("differs by" in e for e in check.evidence)


def test_interval_recomputes_when_flagsmith_shows_collecting_data(healthy):
    metric(healthy, PRIMARY)["inference"]["near_miss"] = None
    check = run_review(healthy).checks["interval"]
    assert check.status == PASS
    assert any("recomputed from the raw sums" in e for e in check.evidence)


# ---------------------------------------------------------------- guardrail


def test_guardrail_fails_when_credibly_worse(healthy):
    set_rate(healthy, GUARDRAIL, "near_miss", 0.40)
    review = run_review(healthy)
    assert review.status("guardrail") == FAIL
    assert review.verdict.call == "DON'T SHIP"
    assert "guardrail" in review.verdict.headline.lower()


def test_guardrail_warns_when_leaning_worse(healthy):
    control = metric(healthy, GUARDRAIL)["variants"]["control"]
    set_rate(healthy, GUARDRAIL, "near_miss", control["sum"] / control["n"] * 1.18)
    check = run_review(healthy).checks["guardrail"]
    assert check.status == WARN, check.evidence


def test_guardrail_warns_when_not_attached(healthy):
    experiment(healthy)["metrics"] = [m for m in experiment(healthy)["metrics"] if m["metric"] != GUARDRAIL]
    check = run_review(healthy).checks["guardrail"]
    assert check.status == WARN
    assert "quit_within_10s" in check.summary


def test_guardrail_uses_the_pre_registered_event(healthy):
    review = run_review(healthy)
    assert [m.event for m in review.ctx.guardrails] == ["quit_within_10s"]


# ---------------------------------------------------------------- novelty


def test_novelty_fails_on_the_planted_fade(bad):
    check = run_review(bad).checks["novelty"]
    assert check.status == FAIL
    assert check.data["early_lift"] > 0 >= check.data["late_lift"]


def test_novelty_fails_when_the_late_lift_vanishes(healthy):
    mid = cut(healthy, 1 / 2)
    for point in metric(healthy, PRIMARY)["conversions_timeseries"]["points"]:
        if parse_time(point["bucket"]) >= mid:
            point["converted_identities"]["near_miss"] = int(point["converted_identities"]["control"] * 0.8)
    review = run_review(healthy)
    assert review.status("novelty") == FAIL
    assert review.verdict.call == "KEEP RUNNING"


def test_novelty_warns_without_enough_data(healthy, monkeypatch):
    monkeypatch.setattr(checks, "NOVELTY_MIN_PER_HALF", 10_000)
    assert run_review(healthy).status("novelty") == WARN


# ---------------------------------------------------------------- stopping rule


def test_stopping_rule_ships_under_rule_2(healthy):
    check = run_review(healthy).checks["stopping_rule"]
    assert (check.status, check.data["rule"]) == (PASS, 2)


def test_stopping_rule_blocks_peeking_under_rule_1(early):
    check = run_review(early).checks["stopping_rule"]
    assert (check.status, check.data["rule"]) == (FAIL, 1)
    assert check.data["chance_to_win"] > 0.95


def test_stopping_rule_keeps_control_under_rule_3(healthy):
    set_rate(healthy, PRIMARY, "near_miss", 0.25)
    check = run_review(healthy).checks["stopping_rule"]
    assert (check.status, check.data["rule"]) == (FAIL, 3)


def test_stopping_rule_inconclusive_under_rule_4(healthy):
    control = metric(healthy, PRIMARY)["variants"]["control"]
    set_rate(healthy, PRIMARY, "near_miss", control["sum"] / control["n"] * 1.06)
    check = run_review(healthy).checks["stopping_rule"]
    assert (check.status, check.data["rule"]) == (FAIL, 4)
    assert run_review(healthy).verdict.call == "DON'T SHIP"


def test_stopping_rule_guardrail_overrides_a_win(healthy):
    set_rate(healthy, GUARDRAIL, "near_miss", 0.40)
    check = run_review(healthy).checks["stopping_rule"]
    assert (check.status, check.data["rule"]) == (FAIL, 3)
