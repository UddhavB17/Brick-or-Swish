"""Keeps skills/third-umpire within the agentskills.io limits without needing the network.

The full validator is `uvx --from skills-ref agentskills validate skills/third-umpire`.
"""

import re
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2] / "skills" / "third-umpire"

pytestmark = pytest.mark.skipif(not SKILL.exists(), reason="skill directory not present")


def frontmatter() -> tuple[dict[str, str], str]:
    _, head, body = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("---\n", 2)
    fields = dict(re.findall(r"^([a-z-]+):[ \t]*(.*)$", head, re.M))
    return fields, body


def test_name_follows_the_spec_and_matches_the_directory():
    fields, _ = frontmatter()
    assert fields["name"] == SKILL.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fields["name"]) and len(fields["name"]) <= 64


def test_description_and_compatibility_fit_their_limits():
    fields, _ = frontmatter()
    assert 0 < len(fields["description"]) <= 1024
    assert "Use when" in fields["description"]
    assert 0 < len(fields["compatibility"]) <= 500


def test_body_stays_small_and_links_resolve():
    _, body = frontmatter()
    assert len(body.splitlines()) < 500
    for link in re.findall(r"\]\(((?:references|scripts)/[^)]+)\)", body):
        assert (SKILL / link).is_file(), link


def test_scripts_are_executable():
    for name in ("umpire", "preflight", "measure-tokens"):
        assert (SKILL / "scripts" / name).stat().st_mode & 0o111, name
