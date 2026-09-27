#!/usr/bin/env python3
"""Read-only audit for the studio-cms-editor donor.

This script does not deploy, publish, sync, install dependencies, or mutate the
repository. It inventories tracked source files, hashes harvest candidates, and
reports signals that need review before promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "plans" / "harvest-manifest.json"


def run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout.strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def candidate_files(manifest: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lane in manifest["lanes"].values():
        for rel in lane.get("files", []):
            if rel not in seen:
                seen.add(rel)
                out.append(rel)
    return out


def find_signals(path: Path, signals: Iterable[str]) -> list[dict]:
    if not path.exists() or path.suffix.lower() not in {
        ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".toml", ".css"
    }:
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    lower = text.lower()
    hits = []
    for signal in signals:
        count = lower.count(signal.lower())
        if count:
            hits.append({"signal": signal, "count": count})
    return hits


def build_report() -> dict:
    manifest = read_manifest()
    tracked = set(filter(None, run_git("ls-files").splitlines()))
    head = run_git("rev-parse", "HEAD")
    branch = run_git("branch", "--show-current")
    status = run_git("status", "--short")

    files = []
    for rel in candidate_files(manifest):
        path = ROOT / rel
        files.append(
            {
                "path": rel,
                "tracked": rel in tracked,
                "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() else None,
                "sha256": sha256(path) if path.exists() and path.is_file() else None,
                "review_signals": find_signals(
                    path, manifest.get("junk_or_review_signals", [])
                ),
            }
        )

    return {
        "schema": "studio-cms-editor.harvest-audit.v1",
        "repository_root": str(ROOT),
        "git": {
            "head": head,
            "branch": branch,
            "dirty": bool(status),
            "status": status.splitlines() if status else [],
        },
        "files": files,
        "safety": {
            "remote_mutations_performed": False,
            "deploy_performed": False,
            "publish_performed": False,
            "sync_performed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only JSON (default is a readable summary followed by JSON path hints).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Optional path to write the JSON report. Parent directories are created.",
    )
    args = parser.parse_args()

    report = build_report()

    if args.out:
        out = args.out.expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("Studio CMS Editor harvest audit")
    print(f"  branch: {report['git']['branch']}")
    print(f"  head:   {report['git']['head']}")
    print(f"  dirty:  {report['git']['dirty']}")
    print()
    for item in report["files"]:
        state = "OK" if item["exists"] and item["tracked"] else "MISSING"
        signals = ", ".join(
            f"{h['signal']}×{h['count']}" for h in item["review_signals"]
        ) or "none"
        print(f"[{state:7}] {item['path']:<32} review={signals}")

    print()
    print("No deploy, publish, sync, upload, or remote mutation was performed.")
    if args.out:
        print(f"Report written to: {args.out.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
