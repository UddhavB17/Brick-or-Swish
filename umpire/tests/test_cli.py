import json

import pytest

from third_umpire import cli


def run(capsys, *args):
    code = cli.main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_bad_fixture_exits_2_with_reasons(capsys, tmp_path):
    code, out, _ = run(capsys, "review", "--fixture", "bad-peeking", "--json", "--report-dir", str(tmp_path),
                       "--explain", "template")
    assert code == 2
    data = json.loads(out)
    assert data["verdict"] == "DON'T SHIP"
    assert {c["id"] for c in data["checks"] if c["status"] == "FAIL"} >= {"srm", "dual_exposure", "audit",
                                                                           "sample_size"}
    assert data["approval"]["outcome"] == "refused"
    report = (tmp_path / data["report"].split("/")[-1]).read_text()
    assert "**Verdict: DON'T SHIP.**" in report and "## Evidence" in report


def test_healthy_fixture_waits_for_approval_without_a_terminal(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    code, out, err = run(capsys, "review", "--fixture", "healthy", "--json", "--no-report")
    assert code == 4
    data = json.loads(out)
    assert data["verdict"] == "SHIP"
    phrase = "ship near_miss to 100% in Production"
    assert data["approval"] == {"outcome": "awaiting-approval", "confirm_phrase": phrase}
    assert "--approve" in err


def test_healthy_fixture_dry_run(capsys):
    code, out, _ = run(capsys, "review", "--fixture", "healthy", "--dry-run", "--no-report")
    assert code == 0
    assert "HUMAN APPROVAL REQUIRED" in out and "Dry run" in out


def test_healthy_fixture_with_phrase_is_simulated(capsys):
    code, out, _ = run(capsys, "review", "--fixture", "healthy", "--no-report", "--json",
                       "--approve", "ship near_miss to 100% in Production")
    assert code == 0
    assert json.loads(out)["approval"]["outcome"] == "simulated"


def test_keep_running_exits_3(capsys):
    code, out, _ = run(capsys, "review", "--fixture", "keep-running", "--json", "--no-report")
    assert code == 3
    assert json.loads(out)["verdict"] == "KEEP RUNNING"


def test_token_log(capsys, tmp_path):
    log = tmp_path / "tokens.json"
    run(capsys, "review", "--fixture", "bad-peeking", "--json", "--no-report", "--token-log", str(log))
    data = json.loads(log.read_text())
    assert data["totals"]["flagsmith-cli"] > 0 and data["totals"]["agent-output"] > 0
    assert data["totals"]["total"] == sum(e["tokens"] for e in data["entries"])


def test_unknown_fixture_is_an_error(capsys):
    code, _, err = run(capsys, "review", "--fixture", "nope")
    assert code == 1 and "packaged fixtures" in err


def test_fixtures_listing(capsys):
    code, out, _ = run(capsys, "fixtures")
    assert code == 0 and "bad-peeking" in out and "healthy" in out


def test_terminal_report_mentions_every_group(capsys):
    code, out, _ = run(capsys, "review", "--fixture", "bad-peeking", "--no-report", "--explain", "template")
    for heading in ("THIRD UMPIRE", "VALIDITY", "READINESS", "DECISION", "VERDICT", "DON'T SHIP"):
        assert heading in out
    assert "HUMAN APPROVAL REQUIRED" not in out


def test_environment_is_required_for_live_runs(capsys, monkeypatch):
    monkeypatch.delenv("FLAGSMITH_ENVIRONMENT", raising=False)
    monkeypatch.setenv("FLAGSMITH_BIN", "/bin/true")
    code, _, err = run(capsys, "review")
    assert code == 1 and "No environment" in err


@pytest.mark.parametrize("name", ["bad-peeking", "healthy", "keep-running"])
def test_markdown_report_is_written(capsys, tmp_path, name):
    run(capsys, "review", "--fixture", name, "--report-dir", str(tmp_path), "--dry-run")
    files = list(tmp_path.glob("412-*.md"))
    assert len(files) == 1
    assert files[0].read_text().startswith("# Third Umpire report:")
