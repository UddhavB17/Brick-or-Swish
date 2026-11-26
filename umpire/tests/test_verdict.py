from conftest import experiment, run_review

from third_umpire.verdict import DONT_SHIP, KEEP_RUNNING, SHIP


def test_bad_fixture_is_refused_with_every_reason(bad):
    review = run_review(bad)
    v = review.verdict
    assert v.call == DONT_SHIP
    assert v.plan is None
    assert "can't be trusted" in v.headline and "99.8%" in v.headline
    joined = " ".join(v.reasons)
    for phrase in ("Sample ratio mismatch", "saw both variants", "after launch", "peeking", "Novelty"):
        assert phrase in joined
    assert v.exit_code == 2


def test_healthy_fixture_ships_with_an_exact_plan(healthy):
    v = run_review(healthy).verdict
    assert v.call == SHIP
    assert v.winner == "near_miss"
    assert v.warnings == []
    plan = v.plan
    assert plan.path == "api/v1/environments/bos7fYq2LkPz9mWcR4tXvH/experiments/412/complete/"
    assert plan.body == {"rollout_decision": "variant", "rollout_variant": 77815}
    assert plan.environment_name == "Production" and plan.production
    assert plan.confirm_phrase == "ship near_miss to 100% in Production"
    assert v.exit_code == 0


def test_early_fixture_keeps_running_despite_a_high_chance(early):
    review = run_review(early)
    assert review.verdict.call == KEEP_RUNNING
    assert review.verdict.exit_code == 3
    assert "not a decision" in review.verdict.reasons[-1]


def test_validity_failures_outrank_readiness(bad):
    review = run_review(bad)
    assert review.status("sample_size") == "FAIL"
    assert review.verdict.call == DONT_SHIP


def test_completed_experiment_has_nothing_to_ship(healthy):
    experiment(healthy).update(status="completed", ended_at="2026-11-27T16:00:00.000Z", rollout_decision="control")
    v = run_review(healthy).verdict
    assert v.call == DONT_SHIP and "already ended" in v.headline


def test_unlaunched_experiment_keeps_running(healthy):
    experiment(healthy).update(status="created", started_at=None)
    assert run_review(healthy).verdict.call == KEEP_RUNNING


def test_variant_without_key_cannot_be_rolled_out(healthy):
    experiment(healthy)["feature"]["multivariate_options"][0]["key"] = None
    review = run_review(healthy)
    assert review.verdict.call != SHIP
