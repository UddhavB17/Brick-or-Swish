"""Token accounting for a review run.

Records every payload read during a review: each Flagsmith CLI response (read by
the umpire process, not by the agent), the summary the agent reads, and any LLM
call's reported usage. Counts use tiktoken's o200k_base encoding, falling back
to the usual 4-characters-per-token estimate when the encoding can't be loaded
(it is downloaded on first use); the output says which.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("o200k_base")
except Exception:  # noqa: BLE001 - any import or download failure means "estimate"
    _ENCODING = None


def count(text: str) -> int:
    if _ENCODING is not None:
        return len(_ENCODING.encode(text))
    return math.ceil(len(text) / 4)


def method() -> str:
    return "tiktoken o200k_base" if _ENCODING is not None else "estimate (characters / 4)"


@dataclass
class Entry:
    kind: str
    label: str
    chars: int
    tokens: int


@dataclass
class Ledger:
    entries: list[Entry] = field(default_factory=list)

    def record(self, kind: str, label: str, text: str) -> None:
        self.entries.append(Entry(kind, label, len(text), count(text)))

    def record_usage(self, label: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.entries.append(Entry("llm-prompt", label, 0, prompt_tokens))
        self.entries.append(Entry("llm-completion", label, 0, completion_tokens))

    def totals(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e.kind] = out.get(e.kind, 0) + e.tokens
        out["total"] = sum(e.tokens for e in self.entries)
        return out

    def write(self, path: str | Path) -> None:
        data = {"method": method(), "totals": self.totals(), "entries": [asdict(e) for e in self.entries]}
        Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
