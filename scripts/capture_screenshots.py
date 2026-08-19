#!/usr/bin/env python3
"""Capture idle + claim/PDF screenshots with Chrome headless."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:8765"


def wait_health(timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("server not healthy")


def shot(url: str, name: str) -> None:
    out = SHOTS / name
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--window-size=1280,1000",
        f"--screenshot={out}",
        url,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"wrote {out} ({out.stat().st_size} bytes)")


def main() -> None:
    try:
        wait_health(1.5)
        server = None
    except RuntimeError:
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "serve_app.py")],
            cwd=str(ROOT),
        )
        wait_health(20)

    shot(f"{BASE}/", "01-claims-desk-idle.png")
    shot(f"{BASE}/capture/claim?payer=acme-health&cpt=27447", "02-claim-result-and-pdf.png")
    shot(f"{BASE}/capture/claim?payer=northstar-mutual&cpt=70553", "03-imaging-claim-pdf.png")

    if server:
        server.terminate()
        server.wait(timeout=5)
    print("done", SHOTS)


if __name__ == "__main__":
    main()
