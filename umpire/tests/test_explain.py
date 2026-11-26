import json
import urllib.error

import pytest
from conftest import run_review

from third_umpire import explain
from third_umpire.tokens import Ledger


@pytest.fixture
def reviews(bad, healthy, early):
    return {"bad": run_review(bad), "healthy": run_review(healthy), "early": run_review(early)}


def test_templates_follow_the_verdict(reviews):
    bad = reviews["bad"]
    text = explain.template(bad.ctx, list(bad.checks.values()), bad.verdict)
    assert text.startswith("Don't ship near_miss.") and "3 validity checks" in text and "99.8%" in text
    early = reviews["early"]
    text = explain.template(early.ctx, list(early.checks.values()), early.verdict)
    assert text.startswith("Keep it running.") and "more hours" in text
    good = reviews["healthy"]
    text = explain.template(good.ctx, list(good.checks.values()), good.verdict)
    assert text.startswith("Ship near_miss.") and "100% of Production" in text


def test_no_key_means_template(reviews):
    r = reviews["healthy"]
    out = explain.explain(r.ctx, list(r.checks.values()), r.verdict, env={})
    assert out.source.startswith("template")


@pytest.mark.parametrize("env, provider, model", [
    ({"OPENAI_API_KEY": "sk-1"}, "openai", "gpt-4.1-mini"),
    ({"ANTHROPIC_API_KEY": "a-1"}, "anthropic", "claude-3-5-haiku-latest"),
    ({"XAI_API_KEY": "x-1"}, "xai", "grok-3-mini"),
    ({"UMPIRE_LLM_PROVIDER": "xai", "UMPIRE_LLM_API_KEY": "k", "UMPIRE_LLM_MODEL": "grok-4"}, "xai", "grok-4"),
    ({"OPENAI_API_KEY": "sk-1", "XAI_API_KEY": "x-1", "UMPIRE_LLM_PROVIDER": "xai"}, "xai", "grok-3-mini"),
])
def test_provider_selection(env, provider, model):
    config = explain.configured(env)
    assert (config.provider, config.model) == (provider, model)


def test_provider_can_be_switched_off():
    assert explain.configured({"OPENAI_API_KEY": "sk", "UMPIRE_LLM_PROVIDER": "none"}) is None


@pytest.mark.parametrize("provider, url, auth_header", [
    ("openai", "https://api.openai.com/v1/chat/completions", "Authorization"),
    ("xai", "https://api.x.ai/v1/chat/completions", "Authorization"),
    ("anthropic", "https://api.anthropic.com/v1/messages", "x-api-key"),
])
def test_requests_match_each_provider_api(monkeypatch, reviews, provider, url, auth_header):
    seen = {}

    def fake_post(u, headers, body, timeout=30):
        seen.update(url=u, headers=headers, body=body)
        text = "Ship near_miss: it cleared every check and the pre-registered rule, so approving rolls it out."
        if provider == "anthropic":
            return {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 410, "output_tokens": 40}}
        return {"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 400, "completion_tokens": 38}}

    monkeypatch.setattr(explain, "_post", fake_post)
    r = reviews["healthy"]
    ledger = Ledger()
    key_var = explain.PROVIDERS[provider]["key"]
    out = explain.explain(r.ctx, list(r.checks.values()), r.verdict, env={key_var: "secret"}, ledger=ledger)
    assert out.source.startswith(f"written by {provider}")
    assert seen["url"] == url
    assert auth_header in seen["headers"]
    facts = json.loads(seen["body"]["messages"][-1]["content"])
    assert facts["verdict"] == "SHIP"
    assert ledger.totals()["llm-prompt"] > 0


def test_model_output_that_changes_the_verdict_is_rejected(monkeypatch, reviews):
    monkeypatch.setattr(explain, "call_model", lambda c, p: ("KEEP RUNNING for another day.", 1, 1))
    r = reviews["healthy"]
    out = explain.explain(r.ctx, list(r.checks.values()), r.verdict, env={"OPENAI_API_KEY": "k"})
    assert "rejected" in out.source and "KEEP RUNNING" in out.source
    assert out.text.startswith("Ship near_miss.")


def test_model_output_with_invented_numbers_is_rejected(monkeypatch, reviews):
    monkeypatch.setattr(explain, "call_model", lambda c, p: ("Don't ship: only a 42.0% chance.", 1, 1))
    r = reviews["bad"]
    out = explain.explain(r.ctx, list(r.checks.values()), r.verdict, env={"OPENAI_API_KEY": "k"})
    assert "42.0%" in out.source


def test_model_output_that_contradicts_is_rejected(monkeypatch, reviews):
    monkeypatch.setattr(explain, "call_model", lambda c, p: ("It is safe to ship now.", 1, 1))
    r = reviews["early"]
    out = explain.explain(r.ctx, list(r.checks.values()), r.verdict, env={"OPENAI_API_KEY": "k"})
    assert "contradicts" in out.source


def test_negated_go_ahead_is_fine():
    text = "It isn't safe to ship now; keep it running."
    assert explain.validate(text, run_review_verdict("KEEP RUNNING"), "") is None


def run_review_verdict(call):
    from third_umpire.verdict import Verdict
    return Verdict(call, "", [])


def test_api_failure_falls_back_to_template(monkeypatch, reviews):
    def boom(c, p):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(explain, "call_model", boom)
    r = reviews["bad"]
    out = explain.explain(r.ctx, list(r.checks.values()), r.verdict, env={"ANTHROPIC_API_KEY": "k"})
    assert "call failed (401)" in out.source
    assert out.text.startswith("Don't ship")


def test_explain_off():
    assert explain.explain(None, [], None, mode="off") is None
