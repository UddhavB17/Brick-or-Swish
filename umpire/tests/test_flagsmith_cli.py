"""Drives the real Flagsmith CLI binary against the local mock API. Skipped without the binary."""

import json
import os
import shutil
import threading
from pathlib import Path

import pytest
from conftest import load

from third_umpire import cli
from third_umpire.flagsmith import JQ_EXPERIMENT, FlagsmithCLI, FlagsmithError
from third_umpire.mockserver import DEMO_KEY, scoped_key_var, serve

BINARY = os.environ.get("FLAGSMITH_BIN") or shutil.which("flagsmith") or (
    str(Path.home() / ".local/bin/flagsmith") if (Path.home() / ".local/bin/flagsmith").exists() else None
)
needs_cli = pytest.mark.skipif(BINARY is None, reason="Flagsmith CLI not installed")


def test_command_uses_api_with_jq_and_no_prompts():
    client = FlagsmithCLI(binary="flagsmith", api_url="http://127.0.0.1:9")
    assert client.command("api/v1/environments/k/", jq="{id}") == [
        "flagsmith", "api", "api/v1/environments/k/", "--no-input", "--jq", "{id}", "--api-url", "http://127.0.0.1:9"]
    assert client.command("x/complete/", method="POST", body=True)[3:7] == ["--no-input", "-X", "POST", "--input"]


@pytest.fixture
def mock_api(monkeypatch):
    def start(name):
        server, mock = serve(load(name))
        host, port = server.server_address[:2]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://{host}:{port}"
        monkeypatch.setenv(scoped_key_var(host, port), DEMO_KEY)
        monkeypatch.setenv("FLAGSMITH_BIN", BINARY or "flagsmith")
        monkeypatch.delenv("FLAGSMITH_API_KEY", raising=False)
        servers.append(server)
        return url, mock

    servers = []
    yield start
    for s in servers:
        s.shutdown()


@needs_cli
def test_jq_projection_runs_inside_the_cli(mock_api):
    url, mock = mock_api("healthy")
    client = FlagsmithCLI(binary=BINARY, api_url=url)
    data = client.get(f"api/v1/environments/{mock.env_key}/experiments/{mock.experiment_id}/", jq=JQ_EXPERIMENT)
    assert set(data) == {"id", "name", "status", "hypothesis", "created_at", "started_at", "ended_at",
                         "rollout_decision", "rollout_variant", "feature", "metrics", "experiment_rollout"}
    assert "uuid" not in json.dumps(data)
    assert mock.requests[-1][2] == 200


@needs_cli
def test_cli_errors_surface_with_status(mock_api, monkeypatch):
    url, mock = mock_api("healthy")
    host_port = url.split("//")[1]
    host, port = host_port.split(":")
    monkeypatch.setenv(scoped_key_var(host, int(port)), "wrong.key")
    with pytest.raises(FlagsmithError) as err:
        FlagsmithCLI(binary=BINARY, api_url=url).get(f"api/v1/environments/{mock.env_key}/")
    assert err.value.status == 401


@needs_cli
def test_bad_experiment_is_refused_through_the_cli(mock_api, capsys, tmp_path):
    url, mock = mock_api("bad-peeking")
    code = cli.main(["review", "-e", mock.env_key, "--api-url", url, "--json", "--report-dir", str(tmp_path),
                     "--explain", "template"])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["verdict"] == "DON'T SHIP"
    assert not [r for r in mock.requests if r[0] == "POST"]


@needs_cli
def test_approved_rollout_goes_through_the_cli(mock_api, capsys):
    url, mock = mock_api("healthy")
    code = cli.main(["review", "-e", mock.env_key, "--api-url", url, "--json", "--no-report", "--explain", "off",
                     "--approve", "ship near_miss to 100% in Production"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["approval"]["outcome"] == "applied"
    posts = [r for r in mock.requests if r[0] == "POST"]
    assert posts == [("POST", f"/api/v1/environments/{mock.env_key}/experiments/412/complete/", 200)]
    exp = mock.api[mock.experiment_path]
    assert (exp["status"], exp["rollout_decision"], exp["rollout_variant"]) == ("completed", "variant", 77815)


@needs_cli
def test_unapproved_rollout_sends_nothing(mock_api, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    url, mock = mock_api("healthy")
    code = cli.main(["review", "-e", mock.env_key, "--api-url", url, "--json", "--no-report", "--explain", "off"])
    assert code == 4
    assert not [r for r in mock.requests if r[0] == "POST"]
