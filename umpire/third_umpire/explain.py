"""Plain-English explanation of a verdict that has already been decided.

A model only rewrites the computed findings as prose. It gets the verdict, the
check summaries and the numbers, and its answer is thrown away (in favour of a
deterministic template) if it names a different verdict or quotes a figure that
isn't in the evidence. With no API key configured, the template is used.

Environment:
  UMPIRE_LLM_PROVIDER   openai | anthropic | xai | none   (default: first key found)
  UMPIRE_LLM_API_KEY    key for the chosen provider (else OPENAI_API_KEY, ANTHROPIC_API_KEY, XAI_API_KEY)
  UMPIRE_LLM_MODEL      model id (defaults below)
  UMPIRE_LLM_BASE_URL   OpenAI-compatible base URL override
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .checks import FAIL, PASS, WARN, Check, Context, pct
from .tokens import Ledger
from .verdict import DONT_SHIP, KEEP_RUNNING, SHIP, Verdict

PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {"key": "OPENAI_API_KEY", "model": "gpt-4.1-mini", "url": "https://api.openai.com/v1"},
    "anthropic": {"key": "ANTHROPIC_API_KEY", "model": "claude-3-5-haiku-latest", "url": "https://api.anthropic.com/v1"},
    "xai": {"key": "XAI_API_KEY", "model": "grok-3-mini", "url": "https://api.x.ai/v1"},
}

SYSTEM_PROMPT = (
    "You explain the result of an A/B test review to a product team. The verdict and every number were computed "
    "by deterministic checks. Do not change, soften or second-guess the verdict, do not recommend a different "
    "action, and do not use any number that is not in the input. Write 3 to 5 plain sentences, under 110 words, "
    "no headings, no lists, no sports metaphors. Start with what to do, then why."
)

_VERDICT_WORDS = {SHIP: "SHIP", DONT_SHIP: "DON'T SHIP", KEEP_RUNNING: "KEEP RUNNING"}


@dataclass
class Explanation:
    text: str
    source: str


@dataclass
class ProviderConfig:
    provider: str
    api_key: str
    model: str
    base_url: str


def configured(env: dict[str, str] | None = None) -> ProviderConfig | None:
    env = dict(os.environ if env is None else env)
    choice = env.get("UMPIRE_LLM_PROVIDER", "").strip().lower()
    if choice in ("none", "off", "template"):
        return None
    order = [choice] if choice else list(PROVIDERS)
    for name in order:
        spec = PROVIDERS.get(name)
        if spec is None:
            continue
        key = env.get("UMPIRE_LLM_API_KEY") if choice else None
        key = key or env.get(spec["key"])
        if key:
            return ProviderConfig(name, key, env.get("UMPIRE_LLM_MODEL") or spec["model"],
                                  (env.get("UMPIRE_LLM_BASE_URL") or spec["url"]).rstrip("/"))
    return None


def facts(ctx: Context, checks: list[Check], verdict: Verdict) -> dict[str, Any]:
    exp = ctx.snap.experiment
    inf = ctx.inference(ctx.primary, ctx.treatment)
    out: dict[str, Any] = {
        "verdict": verdict.call,
        "headline": verdict.headline,
        "reasons": verdict.reasons,
        "experiment": exp.name,
        "flag": exp.feature_name,
        "environment": ctx.snap.environment.name,
        "variant": ctx.treatment,
        "primary_metric": ctx.primary.event if ctx.primary else None,
        "checks": [{"check": c.title, "status": c.status, "finding": c.summary} for c in checks],
    }
    if inf:
        out["primary_result"] = {
            "lift": pct(inf.lift, True),
            "interval": [pct(inf.ci_low, True), pct(inf.ci_high, True)],
            "chance_to_beat_control": pct(inf.chance_to_win),
        }
    if verdict.plan:
        out["if_approved"] = verdict.plan.after
    return out


def _post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed provider URLs
        return json.loads(response.read().decode())


def call_model(config: ProviderConfig, payload: str) -> tuple[str, int, int]:
    if config.provider == "anthropic":
        data = _post(
            f"{config.base_url}/messages",
            {"x-api-key": config.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            {"model": config.model, "max_tokens": 300, "system": SYSTEM_PROMPT,
             "messages": [{"role": "user", "content": payload}]},
        )
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        usage = data.get("usage") or {}
        return text.strip(), int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    data = _post(
        f"{config.base_url}/chat/completions",
        {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        {"model": config.model, "max_tokens": 300, "temperature": 0.2,
         "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": payload}]},
    )
    text = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage") or {}
    return text.strip(), int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?%")
_LABEL = re.compile(r"\b(DON'T SHIP|KEEP RUNNING|SHIP)\b")
_GO_AHEAD = [r"(?<!not )(?<!n't )\b(go ahead and ship|ship it now|safe to ship now)\b"]
_CONTRADICTIONS = {
    SHIP: [r"\bdon'?t ship\b", r"\bdo not ship\b"],
    DONT_SHIP: _GO_AHEAD,
    KEEP_RUNNING: _GO_AHEAD,
}


def validate(text: str, verdict: Verdict, payload: str) -> str | None:
    """Why a model's explanation must be discarded, or None if it is usable."""
    if not text:
        return "empty answer"
    for label in _LABEL.findall(text.replace("’", "'")):
        if label != _VERDICT_WORDS[verdict.call]:
            return f"it names a different verdict ({label})"
    lowered = text.lower().replace("’", "'")
    for pattern in _CONTRADICTIONS[verdict.call]:
        found = re.search(pattern, lowered)
        if found:
            return f"it contradicts the verdict ('{found.group(0)}')"
    known = {n.lstrip("+") for n in _NUMBER.findall(payload)}
    for number in _NUMBER.findall(text):
        if number.lstrip("+") not in known:
            return f"it quotes {number}, which isn't in the evidence"
    return None


def template(ctx: Context, checks: list[Check], verdict: Verdict) -> str:
    by_id = {c.id: c for c in checks}
    key = ctx.treatment or "the variant"
    inf = ctx.inference(ctx.primary, ctx.treatment)
    chance = pct(inf.chance_to_win) if inf else "its"
    failed = [c for c in checks if c.status == FAIL and c.kind == "validity"]
    if verdict.call == DONT_SHIP and failed:
        listed = "; ".join(c.summary.split(". ")[0].rstrip(".") for c in failed)
        text = (f"Don't ship {key}. The {chance} chance to beat control comes from data that fails "
                f"{len(failed)} validity check{'s' if len(failed) > 1 else ''}: {listed}.")
        sample = by_id.get("sample_size")
        if sample and sample.status == FAIL:
            text += f" It was also read too early: {sample.summary.split(' (')[1].split(')')[0]}."
        return text + " End this experiment, fix the cause and start a fresh one under the same pre-registration."
    if verdict.call == KEEP_RUNNING:
        sample = by_id.get("sample_size")
        text = f"Keep it running. Nothing looks broken, but {verdict.reasons[0][0].lower()}{verdict.reasons[0][1:]}"
        if sample and sample.data.get("runtime_hours") and ctx.pre:
            per_hour = sample.data["smallest_arm"] / sample.data["runtime_hours"]
            if per_hour > 0:
                remaining = max(ctx.pre.min_per_arm / per_hour, ctx.pre.min_hours) - sample.data["runtime_hours"]
                text += f" At the current rate the rule is met in about {max(remaining, 0):.0f} more hours."
        return text + f" A {chance} chance to win this early is what the stopping rule exists to ignore."
    if verdict.call == SHIP and inf:
        guard = by_id.get("guardrail")
        srm = by_id.get("srm")
        text = (f"Ship {key}. It beats control on {ctx.primary.event or ctx.primary.name} by {pct(inf.lift, True)} "
                f"(95% interval {pct(inf.ci_low, True)} to {pct(inf.ci_high, True)}, {pct(inf.chance_to_win)} chance "
                "to win), which meets the pre-registered rule with the planned sample and runtime.")
        if guard:
            text += f" {guard.summary}"
        if srm and srm.status == PASS:
            text += " The split is clean, nobody saw both variants and nothing was edited after launch."
        warns = [c.title.lower() for c in checks if c.status == WARN]
        if warns:
            text += f" Check the warnings first: {', '.join(warns)}."
        if verdict.plan:
            text += f" Approving ends the experiment and {verdict.plan.after.split('; ', 1)[1]}."
        return text
    return f"{verdict.headline} " + " ".join(verdict.reasons)


def explain(ctx: Context, checks: list[Check], verdict: Verdict, mode: str = "auto",
            ledger: Ledger | None = None, env: dict[str, str] | None = None) -> Explanation | None:
    if mode == "off":
        return None
    fallback = template(ctx, checks, verdict)
    config = configured(env) if mode == "auto" else None
    if config is None:
        return Explanation(fallback, "template; set an LLM API key for a model-written explanation")
    payload = json.dumps(facts(ctx, checks, verdict), ensure_ascii=False)
    label = f"{config.provider} {config.model}"
    try:
        text, prompt_tokens, completion_tokens = call_model(config, payload)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as exc:
        reason = getattr(exc, "code", None) or type(exc).__name__
        return Explanation(fallback, f"template; {label} call failed ({reason})")
    if ledger is not None:
        ledger.record_usage(label, prompt_tokens, completion_tokens)
    problem = validate(text, verdict, payload)
    if problem:
        return Explanation(fallback, f"template; {label} answer rejected because {problem}")
    return Explanation(text, f"written by {label}; the verdict above is computed, not generated")
