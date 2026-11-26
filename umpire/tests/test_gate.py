import copy
import io

from conftest import experiment, run_review
from rich.console import Console

from third_umpire import gate
from third_umpire.flagsmith import FixtureBackend


class LiveBackend(FixtureBackend):
    """A fixture that behaves like the real CLI: writes go through and change state."""

    writes_are_simulated = False

    def __init__(self, data, drift=None):
        super().__init__(copy.deepcopy(data), name="live")
        self.drift = drift
        self.reads = 0

    def get(self, path, jq=None):
        value = super().get(path, jq)
        if path.endswith(f"/experiments/{self.experiment_id}/"):
            self.reads += 1
            if self.drift and self.reads > 1:
                self.drift(value)
        return value

    def post(self, path, body=None, jq=None):
        self.writes.append((path, body))
        exp = self.api[f"api/v1/environments/{self.environment_key}/experiments/{self.experiment_id}/"]
        exp.update(status="completed", rollout_decision=body["rollout_decision"],
                   rollout_variant=body.get("rollout_variant"), experiment_rollout=None)
        return exp


def quiet():
    return Console(file=io.StringIO(), width=120)


def answers(*replies):
    queue = list(replies)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return queue.pop(0)

    ask.prompts = prompts
    return ask


def test_non_ship_verdicts_never_prompt_or_write(bad):
    review = run_review(bad)
    ask = answers()
    result = gate.run(review.verdict, review.ctx, review.backend, quiet(), interactive=True, ask=ask)
    assert result["outcome"] == gate.REFUSED
    assert ask.prompts == [] and review.backend.writes == []


def test_dry_run_shows_the_plan_and_sends_nothing(healthy):
    review = run_review(healthy)
    backend = LiveBackend(healthy)
    result = gate.run(review.verdict, review.ctx, backend, quiet(), dry_run=True, interactive=True, ask=answers())
    assert result["outcome"] == gate.DRY_RUN
    assert backend.writes == []
    assert result["body"] == {"rollout_decision": "variant", "rollout_variant": 77815}


def test_typed_yes_and_environment_name_apply_the_rollout(healthy):
    review = run_review(healthy)
    backend = LiveBackend(healthy)
    ask = answers("y", "Production")
    result = gate.run(review.verdict, review.ctx, backend, quiet(), interactive=True, ask=ask)
    assert result["outcome"] == gate.APPLIED
    assert "[y/N]" in ask.prompts[0] and "Production" in ask.prompts[0]
    assert backend.writes == [("api/v1/environments/bos7fYq2LkPz9mWcR4tXvH/experiments/412/complete/",
                               {"rollout_decision": "variant", "rollout_variant": 77815})]
    assert result["status_after"] == "completed"


def test_anything_but_yes_declines(healthy):
    review = run_review(healthy)
    backend = LiveBackend(healthy)
    for reply in ("", "n", "no", "sure"):
        result = gate.run(review.verdict, review.ctx, backend, quiet(), interactive=True, ask=answers(reply))
        assert result["outcome"] == gate.DECLINED
    assert backend.writes == []


def test_production_needs_the_environment_name(healthy):
    review = run_review(healthy)
    backend = LiveBackend(healthy)
    result = gate.run(review.verdict, review.ctx, backend, quiet(), interactive=True, ask=answers("y", "prod"))
    assert result["outcome"] == gate.DECLINED
    assert backend.writes == []


def test_non_production_skips_the_name_prompt(healthy):
    key = f"api/v1/environments/{healthy['environment_key']}/"
    healthy["api"][key]["name"] = "Demo"
    review = run_review(healthy)
    ask = answers("y")
    result = gate.run(review.verdict, review.ctx, LiveBackend(healthy), quiet(), interactive=True, ask=ask)
    assert result["outcome"] == gate.APPLIED
    assert len(ask.prompts) == 1


def test_no_terminal_waits_for_the_human_phrase(healthy):
    review = run_review(healthy)
    backend = LiveBackend(healthy)
    result = gate.run(review.verdict, review.ctx, backend, quiet(), interactive=False)
    assert result["outcome"] == gate.AWAITING
    assert result["confirm_phrase"] == "ship near_miss to 100% in Production"
    assert backend.writes == []


def test_wrong_phrase_is_declined_and_right_phrase_applies(healthy):
    review = run_review(healthy)
    backend = LiveBackend(healthy)
    wrong = gate.run(review.verdict, review.ctx, backend, quiet(), approve="ship it", interactive=False)
    assert wrong["outcome"] == gate.DECLINED and backend.writes == []
    right = gate.run(review.verdict, review.ctx, backend, quiet(),
                     approve="ship near_miss to 100% in Production", interactive=False)
    assert right["outcome"] == gate.APPLIED and len(backend.writes) == 1


def test_changes_since_the_review_block_the_write(healthy):
    review = run_review(healthy)

    def edit_split(exp):
        exp["experiment_rollout"]["multivariate_feature_state_values"][0]["percentage_allocation"] = 80.0

    backend = LiveBackend(healthy, drift=edit_split)
    backend.get(f"api/v1/environments/{backend.environment_key}/experiments/{backend.experiment_id}/")
    result = gate.run(review.verdict, review.ctx, backend, quiet(), interactive=True, ask=answers("y", "Production"))
    assert result["outcome"] == gate.STALE
    assert backend.writes == []


def test_fixture_mode_records_but_never_sends(healthy):
    review = run_review(healthy)
    result = gate.run(review.verdict, review.ctx, review.backend, quiet(), interactive=True,
                      ask=answers("y", "Production"))
    assert result["outcome"] == gate.SIMULATED
    assert review.backend.writes and review.backend.writes_are_simulated
    assert experiment(review.backend.data)["status"] == "running"


def test_cli_command_is_the_documented_flagsmith_call(healthy):
    review = run_review(healthy)
    command = gate.cli_command(review.backend, review.verdict.plan)
    assert command == ("echo '{\"rollout_decision\":\"variant\",\"rollout_variant\":77815}' | flagsmith api "
                       "api/v1/environments/bos7fYq2LkPz9mWcR4tXvH/experiments/412/complete/ -X POST --input -")
