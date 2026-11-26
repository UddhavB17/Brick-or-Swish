"""Reads the pre-registered stopping rule out of HYPOTHESIS.md.

The file is prose written for people, so each number is pulled out by a pattern
anchored on the wording of the rule it belongs to. Anything that can't be found
is reported rather than defaulted: the umpire never invents a threshold.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_TZ = {"IST": timezone(timedelta(hours=5, minutes=30)), "UTC": timezone.utc, "GMT": timezone.utc}


class HypothesisError(ValueError):
    pass


@dataclass(frozen=True)
class PreRegistration:
    path: str
    sha256: str
    registered_on: date | None
    min_per_arm: int
    min_hours: float
    ship_chance: float
    keep_chance: float
    hard_stop: datetime | None
    srm_alpha: float
    split: dict[str, int]
    primary_event: str | None
    guardrail_events: list[str]
    amendments: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return text.replace("**", "").replace("\u2009", " ").replace("\u00a0", " ")


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^##\s+{heading}.*?$(.*?)(?=^##\s|\Z)", text, re.M | re.S | re.I)
    return match.group(1) if match else ""


def parse(text: str, path: str = "HYPOTHESIS.md") -> PreRegistration:
    raw = text
    text = _clean(text)
    rule = _section(text, "Stopping rule")
    if not rule:
        raise HypothesisError(f"{path}: no '## Stopping rule' section")
    missing: list[str] = []

    def find(pattern: str, where: str, label: str) -> re.Match[str] | None:
        match = re.search(pattern, where, re.I | re.S)
        if not match:
            missing.append(label)
        return match

    per_arm = find(r"(?:≥|>=)\s*([\d,]+)\s*exposed identities", rule, "minimum exposed identities per arm")
    hours = find(r"run\s*(?:≥|>=)\s*(\d+(?:\.\d+)?)\s*hours?", rule, "minimum runtime in hours")
    ship = find(
        r"Ship\s+`?[\w-]+`?.*?chance to beat control.*?(?:≥|>=)\s*(\d+(?:\.\d+)?)\s*%", rule, "ship threshold"
    )
    keep = find(r"Keep\s+`?control`?.*?(?:≤|<=)\s*(\d+(?:\.\d+)?)\s*%", rule, "keep-control threshold")
    alpha = find(r"p\s*<\s*(\d+(?:\.\d+)?)", rule, "SRM threshold")
    stop = re.search(r"Hard stop:?\s*(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})\s*([A-Z]{2,4})?", rule)

    split_match = re.search(r"split\s+(\d+)\s*/\s*(\d+)", text, re.I)
    if not split_match:
        missing.append("traffic split")

    metrics = _section(text, "Metrics")
    primary = re.search(r"^\|\s*Primary\s*\|\s*`([^`]+)`", metrics, re.M | re.I)
    guardrails = re.findall(r"^\|\s*Guardrail\s*\|\s*`([^`]+)`", metrics, re.M | re.I)
    if not primary:
        missing.append("primary metric")

    if missing:
        raise HypothesisError(f"{path}: could not find {', '.join(missing)}")

    registered = re.search(r"Registered:?\s*(\d{4}-\d{2}-\d{2})", text)
    hard_stop = None
    if stop:
        tz = _TZ.get((stop.group(3) or "UTC").upper(), timezone.utc)
        hard_stop = datetime.fromisoformat(f"{stop.group(1)}T{stop.group(2)}").replace(tzinfo=tz)

    amendments_text = _section(text, "Amendments").strip()
    amendments = [] if re.fullmatch(r"_?None yet\.?_?", amendments_text, re.I) or not amendments_text else [
        line.strip("-* ").strip() for line in amendments_text.splitlines() if line.strip()
    ]

    return PreRegistration(
        path=path,
        sha256=hashlib.sha256(raw.encode()).hexdigest(),
        registered_on=date.fromisoformat(registered.group(1)) if registered else None,
        min_per_arm=int(per_arm.group(1).replace(",", "")),
        min_hours=float(hours.group(1)),
        ship_chance=float(ship.group(1)) / 100,
        keep_chance=float(keep.group(1)) / 100,
        hard_stop=hard_stop,
        srm_alpha=float(alpha.group(1)),
        split={"control": int(split_match.group(1)), "treatment": int(split_match.group(2))},
        primary_event=primary.group(1),
        guardrail_events=guardrails,
        amendments=amendments,
    )


def load(path: str | Path) -> PreRegistration:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise HypothesisError(f"cannot read {p}: {exc.strerror}") from exc
    return parse(text, str(p))


def find_default(start: Path | None = None) -> Path | None:
    """HYPOTHESIS.md in the working directory or any parent, like flagsmith.json discovery."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / "HYPOTHESIS.md"
        if candidate.is_file():
            return candidate
    return None
