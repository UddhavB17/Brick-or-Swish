"""Renders the README screenshots of the umpire refusing the planted bad result and approving the healthy one.

The refusal replays the bad-peeking fixture. The approval goes through the real Flagsmith CLI against the local
mock API serving the healthy fixture, so the screenshot shows an actual `complete/` call. Needs the Flagsmith CLI
and Chrome (CHROME_PATH) to rasterise rich's SVG export.

    .venv/bin/python tools/terminal_screenshots.py [OUT_DIR]     # default ../docs/screenshots
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
UMPIRE = [sys.executable, "-m", "third_umpire"]
ENV = {**os.environ, "TERM": "xterm-256color", "COLUMNS": "120", "UMPIRE_LLM_PROVIDER": "none",
       "PYTHONPATH": str(HERE.parent)}
ENV.pop("NO_COLOR", None)
CHROME = os.environ.get("CHROME_PATH") or shutil.which("google-chrome") or shutil.which("chromium")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def rasterise(svg: Path, png: Path) -> None:
    width, height = (float(v) for v in re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg.read_text()).groups())
    profile = tempfile.mkdtemp()
    # Headless Chrome sometimes keeps running after writing the screenshot, so stop it once the file is written.
    chrome = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                               f"--user-data-dir={profile}", "--virtual-time-budget=5000",
                               "--force-device-scale-factor=2", f"--window-size={int(width)},{int(height)}",
                               f"--screenshot={png}", svg.as_uri()],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        for line in chrome.stderr:
            if "bytes written to file" in line:
                break
        else:
            raise RuntimeError(f"Chrome exited without writing {png}")
    finally:
        try:
            os.killpg(chrome.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        chrome.wait()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1] / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    if not CHROME or not shutil.which("flagsmith"):
        print("Needs Chrome (CHROME_PATH) and the Flagsmith CLI on PATH.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        refused = Path(tmp) / "refused.svg"
        subprocess.run([*UMPIRE, "review", "--fixture", "bad-peeking", "--no-report", "--svg", str(refused)],
                       env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

        port = free_port()
        mock = subprocess.Popen([*UMPIRE, "serve-fixture", "healthy", "--port", str(port)], env=ENV,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        approved = Path(tmp) / "approved.svg"
        try:
            for _ in range(50):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)
            live = {**ENV, "FLAGSMITH_API_URL": f"http://127.0.0.1:{port}",
                    f"FLAGSMITH_API_KEY_127_0_0_1_{port}": "mock.third-umpire-demo"}
            subprocess.run([*UMPIRE, "review", "-e", "bos7fYq2LkPz9mWcR4tXvH", "--no-report", "--svg", str(approved),
                            "--approve", "ship near_miss to 100% in Production"],
                           env=live, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        finally:
            mock.terminate()
            mock.wait()

        for svg, name in ((refused, "umpire-refused.png"), (approved, "umpire-approved.png")):
            rasterise(svg, out / name)
            print(out / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
