#!/usr/bin/env python3
"""Launch the existing studio-cms-editor locally without deploying anything."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_NODE = (22, 13, 0)


def require(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise RuntimeError(f"required executable not found: {name}")
    return value


def node_version() -> tuple[int, int, int]:
    raw = subprocess.check_output(["node", "--version"], text=True).strip().lstrip("v")
    parts = raw.split(".")
    return tuple(int(x) for x in parts[:3])  # type: ignore[return-value]


def find_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no available local preview port found")


def wait_for(url: str, process: subprocess.Popen, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.5)
    return False


def normalize_route(value: str) -> str:
    value = value.strip() or "/studio"
    return value if value.startswith("/") else f"/{value}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument(
        "--route",
        default="/studio",
        help="Route to open after boot. Default: /studio. Use / for the storefront.",
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Run npm ci first. Never runs automatically.",
    )
    args = parser.parse_args()

    require("node")
    require("npm")
    version = node_version()
    if version < MIN_NODE:
        raise RuntimeError(
            f"Node {MIN_NODE[0]}.{MIN_NODE[1]}+ required; found {'.'.join(map(str, version))}"
        )

    if args.install:
        subprocess.run(
            ["npm", "ci", "--no-audit", "--no-fund"],
            cwd=ROOT,
            check=True,
        )

    if not (ROOT / "node_modules").exists():
        raise RuntimeError(
            "node_modules is missing. Re-run once with --install to perform npm ci."
        )

    port = find_port(args.port)
    route = normalize_route(args.route)
    base = f"http://127.0.0.1:{port}"
    url = base + route

    env = os.environ.copy()
    env["WRANGLER_LOG_PATH"] = str(ROOT / ".wrangler" / "wrangler.log")

    cmd = [
        "npm", "run", "dev", "--",
        "--host", "127.0.0.1",
        "--port", str(port),
        "--strictPort",
    ]

    print(f"Starting local preview: {url}")
    print(f"  CMS Studio: {base}/studio")
    print(f"  Storefront: {base}/")
    print(f"  Shop:       {base}/shop")
    print("This command does not deploy or publish anything.")
    process = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )

    def stop(*_args):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    if wait_for(url, process):
        print(f"Preview ready: {url}")
        if not args.no_browser:
            webbrowser.open(url)
    else:
        print("Preview did not become ready before the process exited/timeout.", file=sys.stderr)

    try:
        return process.wait()
    finally:
        stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
