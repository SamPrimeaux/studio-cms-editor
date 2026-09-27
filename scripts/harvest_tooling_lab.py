#!/usr/bin/env python3
"""Harvest plus deterministic acceptance tests for AgentSam tooling.

Default safe profile has no network.
Optional --scrape-url performs a public read and writes results only to the local fixture.
Never deploys, publishes, syncs, uploads to R2, or writes remote Vectorize.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "studio-cms-editor-harvest-export"


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def redact(text):
    patterns = [
        (r"sk-[A-Za-z0-9_-]{10,}", "sk-[REDACTED]"),
        (r"aak_[A-Za-z0-9_-]{8,}", "aak_[REDACTED]"),
        (r"(?i)(api[_-]?key|token|secret|password)(\s*[=:]\s*)[^\s,;]+", r"\1\2[REDACTED]"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text[-12000:]


def build_harvest(out, replace_export, replace_db, account, site):
    marker = out / ".studio-cms-harvest-export"
    cmd = [
        sys.executable, str(ROOT / "scripts" / "harvest_local_cms.py"),
        "--out", str(out), "--account-id", account, "--site-id", site,
    ]
    if replace_export:
        cmd.append("--replace-export")
    elif marker.exists():
        cmd.append("--reuse-export")
    if replace_db:
        cmd.append("--replace-db")
    subprocess.run(cmd, cwd=ROOT, check=True)
    return out / "local" / "inneranimals-cms.sqlite"


class Lab:
    def __init__(self, out, sdk, db, account, site, profile, dry_run):
        self.out = out
        self.sdk = sdk
        self.db = db
        self.account = account
        self.site = site
        self.profile = profile
        self.dry_run = dry_run
        self.tooling = out / "tooling"
        self.fixture = self.tooling / "fixture"
        self.receipts = self.tooling / "receipts"
        self.run_id = "probe_" + uuid.uuid4().hex[:16]
        self.steps = []

    def prepare(self):
        if self.fixture.exists():
            shutil.rmtree(self.fixture)
        self.fixture.mkdir(parents=True)
        for lane in ("theme_layout_donor", "cms_editor_donor"):
            source = self.out / "lanes" / lane
            if source.exists():
                shutil.copytree(source, self.fixture / lane, dirs_exist_ok=True)

        brand_input = self.fixture / "brand-input"
        brand_input.mkdir()
        for rel in ("public/favicon.svg", "app/storefront.css", "app/storefront-data.ts"):
            source = ROOT / rel
            if source.exists():
                shutil.copy2(source, brand_input / source.name)

        tiny_png = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
            "AAAAC0lEQVR42mP8/x8AAusB9WlC7uoAAAAASUVORK5CYII="
        )
        (brand_input / "optimizer-fixture.png").write_bytes(base64.b64decode(tiny_png))

        (self.fixture / "README.md").write_text(
            "# AgentSam acceptance fixture\nGenerated from studio-cms-editor harvest. Disposable local test material.\n"
        )
        subprocess.run(["git", "init", "-q"], cwd=self.fixture, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@agentsam.local"], cwd=self.fixture, check=True)
        subprocess.run(["git", "config", "user.name", "AgentSam Fixture"], cwd=self.fixture, check=True)
        subprocess.run(["git", "add", "."], cwd=self.fixture, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture: harvested donor"], cwd=self.fixture, check=True)

    def start_db(self):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "INSERT INTO tooling_probe_runs(id,account_id,site_id,profile,sdk_root,fixture_root,started_at) VALUES(?,?,?,?,?,?,?)",
                (self.run_id, self.account, self.site, self.profile, str(self.sdk), str(self.fixture), utcnow()),
            )
            conn.commit()
        finally:
            conn.close()

    def finish_db(self, ok):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "UPDATE tooling_probe_runs SET finished_at=?, ok=? WHERE id=?",
                (utcnow(), 1 if ok else 0, self.run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def save_step_db(self, step):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO tooling_probe_steps(id,probe_run_id,step_key,category,command_json,cwd,mutability,network_mode,started_at,finished_at,exit_code,ok,stdout_text,stderr_text) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    step["id"], self.run_id, step["key"], step["category"],
                    json.dumps(step["command"]), step["cwd"], step["mutability"], step["network"],
                    step["started_at"], step["finished_at"], step["exit_code"],
                    1 if step["ok"] else 0, step["stdout"], step["stderr"]
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def run(self, key, category, command, cwd, mutability, network, required=True, env=None):
        started = utcnow()
        if self.dry_run:
            code, stdout, stderr = 0, "DRY RUN", ""
        else:
            proc = subprocess.run(
                command, cwd=cwd, env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            code, stdout, stderr = proc.returncode, redact(proc.stdout), redact(proc.stderr)

        step = {
            "id": "step_" + uuid.uuid4().hex[:16],
            "key": key,
            "category": category,
            "command": command,
            "cwd": str(cwd),
            "mutability": mutability,
            "network": network,
            "required": required,
            "started_at": started,
            "finished_at": utcnow(),
            "exit_code": code,
            "ok": code == 0,
            "stdout": stdout,
            "stderr": stderr,
        }
        self.steps.append(step)
        self.receipts.mkdir(parents=True, exist_ok=True)
        (self.receipts / (str(len(self.steps)).zfill(2) + "-" + key + ".json")).write_text(
            json.dumps(step, indent=2) + "\n"
        )
        self.save_step_db(step)

        label = "OK" if code == 0 else ("WARN" if not required else "FAIL")
        print("[" + label + "]", key)
        return code == 0 or not required


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk", type=Path, default=Path.home() / "agentsam-sdk")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--profile", choices=("safe", "local-full"), default="safe")
    ap.add_argument("--replace-export", action="store_true")
    ap.add_argument("--replace-db", action="store_true")
    ap.add_argument("--account-id", default=os.getenv("IAM_ACCOUNT_ID") or os.getenv("AGENTSAM_ACCOUNT_ID") or "acct_local")
    ap.add_argument("--site-id", default="site_inneranimals")
    ap.add_argument("--scrape-url")
    ap.add_argument("--optimize-scrape-images", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sdk = args.sdk.expanduser().resolve()
    out = args.out.expanduser().resolve()
    if not (sdk / "bin" / "agentsam").exists():
        raise RuntimeError("AgentSam SDK not found: " + str(sdk))

    db = build_harvest(out, args.replace_export, args.replace_db, args.account_id, args.site_id)
    lab = Lab(out, sdk, db, args.account_id, args.site_id, args.profile, args.dry_run)
    lab.prepare()
    lab.start_db()

    node = shutil.which("node") or "node"
    py = shutil.which("python3") or sys.executable
    agentsam = str(sdk / "bin" / "agentsam")
    brand = str(sdk / "packages" / "agentsam-brand" / "bin" / "agentsam-brand.mjs")
    scrape_pkg = sdk / "packages" / "agentsam-site-scrape"

    ok = True
    try:
        ok &= lab.run("agentsam-help", "cli", [node, agentsam, "--help"], sdk, "read-only", "none")
        ok &= lab.run(
            "site-scrape-unit", "scrape",
            [py, "-m", "unittest", "discover", "-s", "tests", "-v"],
            scrape_pkg, "read-only", "none"
        )
        ok &= lab.run("brand-processors", "brand", [node, brand, "processors", "--json"], lab.fixture, "read-only", "none")
        ok &= lab.run("brand-roles", "brand", [node, brand, "roles", "--json"], lab.fixture, "read-only", "none")
        ok &= lab.run("brand-templates", "brand", [node, brand, "templates", "--json"], lab.fixture, "read-only", "none")

        ok &= lab.run(
            "autorag-setup-fixture", "knowledge",
            [
                node, agentsam, "autorag", "setup", "--cwd", str(lab.fixture),
                "--yes", "--kind", "mixed", "--provider", "fixture",
                "--backend", "local_exact", "--semantic"
            ],
            sdk, "fixture-local-write", "none"
        )
        ok &= lab.run(
            "autorag-probe-fixture", "knowledge",
            [
                node, agentsam, "autorag", "probe", "--cwd", str(lab.fixture),
                "--semantic", "--query",
                "Inner Animals navigation brand tokens products journal CMS sections"
            ],
            sdk, "fixture-local-write", "none"
        )
        ok &= lab.run(
            "index-plan", "knowledge",
            [node, agentsam, "index", "plan", "--cwd", str(lab.fixture), "--json"],
            sdk, "read-only", "none"
        )

        if args.profile == "local-full":
            ok &= lab.run(
                "brand-ingest", "brand",
                [
                    node, brand, "ingest", str(lab.fixture / "brand-input"),
                    "--brand", "inneranimals-harvest",
                    "--title", "Inner Animals Harvest",
                    "--cwd", str(lab.fixture), "--json", "--no-interactive"
                ],
                sdk, "fixture-local-write", "none"
            )
            pack = lab.fixture / ".agentsam" / "brand" / "packs" / "inneranimals-harvest"
            ok &= lab.run(
                "brand-build", "brand",
                [
                    node, brand, "build", "--from", str(pack),
                    "--cwd", str(lab.fixture),
                    "--out", str(lab.fixture / "brand-dist"),
                    "--no-zip", "--json", "--no-interactive"
                ],
                sdk, "fixture-local-write", "none", required=False
            )

        if args.scrape_url:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(scrape_pkg)
            cmd = [
                py, "-m", "agentsam_site_scrape", args.scrape_url,
                "--out", str(lab.fixture / "site-scrape"),
                "--max-pages", "12", "--yes"
            ]
            if not args.optimize_scrape_images:
                cmd.append("--no-optimize")
            ok &= lab.run(
                "site-scrape-public", "scrape", cmd, sdk,
                "fixture-local-write", "public-read", env=env
            )
    finally:
        lab.finish_db(bool(ok))

    receipt = {
        "schema": "studio-cms-editor.tooling-lab.v1",
        "run_id": lab.run_id,
        "profile": args.profile,
        "ok": bool(ok),
        "sdk_root": str(sdk),
        "fixture_root": str(lab.fixture),
        "cms_db": str(db),
        "steps": lab.steps,
        "safety": {
            "deploy": False,
            "publish": False,
            "site_sync": False,
            "r2_upload": False,
            "vectorize_remote_write": False,
            "cloudflare_images_upload": False,
            "network_scrape": bool(args.scrape_url),
        },
    }
    lab.tooling.mkdir(parents=True, exist_ok=True)
    receipt_path = lab.tooling / "TOOLING_LAB_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Tooling lab receipt:", receipt_path)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, sqlite3.Error) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
