from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from third_umpire import hypothesis
from third_umpire.flagsmith import fixture_hypothesis

REPO_HYPOTHESIS = Path(__file__).resolve().parents[2] / "HYPOTHESIS.md"


def test_reads_every_threshold_from_the_real_pre_registration():
    pre = hypothesis.load(REPO_HYPOTHESIS)
    assert pre.min_per_arm == 375
    assert pre.min_hours == 24
    assert pre.ship_chance == 0.95
    assert pre.keep_chance == 0.05
    assert pre.srm_alpha == 0.001
    assert pre.split == {"control": 50, "treatment": 50}
    assert pre.primary_event == "second_round_started"
    assert pre.guardrail_events == ["quit_within_10s"]
    assert pre.registered_on == date(2026, 11, 26)
    assert pre.hard_stop == datetime(2026, 11, 29, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert pre.amendments == []


def test_packaged_copy_matches_the_repo_file():
    assert fixture_hypothesis().read_text() == REPO_HYPOTHESIS.read_text()


def test_missing_rule_is_an_error_not_a_default():
    text = REPO_HYPOTHESIS.read_text().replace("≥ 375 exposed identities", "enough identities")
    with pytest.raises(hypothesis.HypothesisError, match="minimum exposed identities per arm"):
        hypothesis.parse(text)
    with pytest.raises(hypothesis.HypothesisError, match="Stopping rule"):
        hypothesis.parse("# Nothing here\n")


def test_amendments_are_listed():
    text = REPO_HYPOTHESIS.read_text().replace("_None yet._", "- 2026-11-27T10:00Z: guardrail window widened")
    assert hypothesis.parse(text).amendments == ["2026-11-27T10:00Z: guardrail window widened"]


def test_find_default_walks_up(tmp_path):
    (tmp_path / "HYPOTHESIS.md").write_text("x")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert hypothesis.find_default(nested) == tmp_path / "HYPOTHESIS.md"
