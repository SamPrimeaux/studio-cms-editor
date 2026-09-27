#!/usr/bin/env python3
"""One-shot curated export for studio-cms-editor.

Default behavior:
  1. copy curated donor source by lane,
  2. preserve source files verbatim,
  3. write provenance/history/receipt metadata.

Optional --stage-sdk copies the finished export only into:
  <sdk>/apps/_incoming/studio-cms-editor-harvest

It never writes into active AgentSam SDK packages and never runs deploy/sync/
publish/npm/wrangler commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "plans" / "harvest-manifest.json"
DEFAULT_OUT = ROOT.parent / "studio-cms-editor-harvest-export"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def safe_remove_export(path: Path) -> None:
    path = path.resolve()
    forbidden = {ROOT.resolve(), ROOT.parent.resolve(), Path.home().resolve(), Path("/")}
    if path in forbidden:
        raise RuntimeError(f"refusing to remove unsafe path: {path}")
    marker = path / ".studio-cms-harvest-export"
    if path.exists() and not marker.exists():
        raise RuntimeError(
            f"refusing to replace unrecognized directory: {path}\n"
            "Choose another --out path or remove it manually after inspection."
        )
    if path.exists():
        shutil.rmtree(path)


def copy_lane_files(export_root: Path, lane_name: str, lane: dict) -> list[dict]:
    target = export_root / "lanes" / lane_name
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for rel in lane.get("files", []):
        src = ROOT / rel
        if not src.exists() or not src.is_file():
            copied.append({"path": rel, "status": "missing"})
            continue
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(
            {
                "path": rel,
                "status": "copied",
                "bytes": src.stat().st_size,
                "sha256": sha256(src),
            }
        )
    return copied


def write_candidate_notes(export_root: Path) -> None:
    candidates = export_root / "candidates"
    candidates.mkdir(parents=True, exist_ok=True)

    (candidates / "README.md").write_text(
        """# Candidate promotion map

Nothing in this directory is runtime authority.

- cms-editor-primitives -> review against apps/client-cms-editor
- theme-inneranimals-site -> normalize public routes/components/data into a section/block-oriented theme package
- openai-identity -> use chatgpt-auth.ts only as transport/reference evidence
- runtime-reference -> historical execution/deployment context only

Promotion into an active AgentSam package must be an explicit later change.
""",
        encoding="utf-8",
    )

    for name, body in {
        "cms-editor-primitives": (
            "Preserve the editor interaction model, canvas/selection behavior, "
            "inspector concepts, templates/components/media UX, and keyboard workflows. "
            "Do not preserve fake persistence or seeded customer/demo data as authority."
        ),
        "theme-inneranimals-site": (
            "Preserve all public routes, Storefront component behavior, data shape, and CSS. "
            "Normalize later into tokens, sections, blocks, and content bindings. "
            "Installing/previewing must not publish or sync."
        ),
        "openai-identity": (
            "Map hosted ChatGPT identity into AgentSam NormalizedExternalIdentity. "
            "Do not infer OpenAI inference permission from sign-in."
        ),
        "runtime-reference": (
            "Keep Vite/Vinext/Worker/Wrangler files for provenance only. "
            "Do not auto-copy production bindings or deploy scripts."
        ),
    }.items():
        d = candidates / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "NOTES.md").write_text(body + "\n", encoding="utf-8")


def write_history(export_root: Path, manifest: dict) -> None:
    paths = []
    seen = set()
    for lane in manifest["lanes"].values():
        for rel in lane.get("files", []):
            if rel not in seen:
                seen.add(rel)
                paths.append(rel)

    cmd = ["log", "--date=short", "--pretty=format:%h %ad %s", "--", *paths]
    history = git(*cmd)
    (export_root / "PROVENANCE_HISTORY.txt").write_text(
        history + ("\n" if history else ""), encoding="utf-8"
    )


def validate_sdk(path: Path) -> Path:
    sdk = path.expanduser().resolve()
    checks = [
        sdk / "package.json",
        sdk / "apps",
        sdk / "apps" / "client-cms-editor",
    ]
    missing = [str(p) for p in checks if not p.exists()]
    if missing:
        raise RuntimeError(
            "target does not look like agentsam-sdk; missing:\n  " + "\n  ".join(missing)
        )
    return sdk


def stage_into_sdk(export_root: Path, sdk_path: Path, replace: bool) -> Path:
    sdk = validate_sdk(sdk_path)
    dest = sdk / "apps" / "_incoming" / "studio-cms-editor-harvest"
    marker = dest / ".studio-cms-harvest-staging"

    if dest.exists():
        if not replace:
            raise RuntimeError(
                f"SDK staging target already exists: {dest}\n"
                "Re-run with --replace-sdk-staging only after reviewing it."
            )
        if not marker.exists():
            raise RuntimeError(f"refusing to replace unrecognized SDK directory: {dest}")
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(export_root, dest)
    marker.write_text(
        "staged donor only; not runtime authority; no implicit sync/deploy/publish\n",
        encoding="utf-8",
    )
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--replace-export",
        action="store_true",
        help="Replace an existing export only if it contains the harvest marker.",
    )
    parser.add_argument(
        "--sdk",
        type=Path,
        help="Path to agentsam-sdk. Used only together with --stage-sdk.",
    )
    parser.add_argument(
        "--stage-sdk",
        action="store_true",
        help="Explicitly copy export into agentsam-sdk/apps/_incoming only.",
    )
    parser.add_argument(
        "--replace-sdk-staging",
        action="store_true",
        help="Replace prior recognized _incoming staging export.",
    )
    args = parser.parse_args()

    if args.stage_sdk and not args.sdk:
        parser.error("--stage-sdk requires --sdk /path/to/agentsam-sdk")

    export_root = args.out.expanduser().resolve()
    if export_root.exists():
        if not args.replace_export:
            raise RuntimeError(
                f"export already exists: {export_root}\n"
                "Use --replace-export only after reviewing the existing export."
            )
        safe_remove_export(export_root)

    manifest = load_manifest()
    export_root.mkdir(parents=True)
    (export_root / ".studio-cms-harvest-export").write_text(
        "recognized studio-cms-editor harvest export\n", encoding="utf-8"
    )

    copied_by_lane = {}
    for lane_name, lane in manifest["lanes"].items():
        copied_by_lane[lane_name] = copy_lane_files(export_root, lane_name, lane)

    write_candidate_notes(export_root)
    write_history(export_root, manifest)

    plans_dir = export_root / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    for plan in sorted((ROOT / "plans").glob("*")):
        if plan.is_file():
            shutil.copy2(plan, plans_dir / plan.name)

    receipt = {
        "schema": "studio-cms-editor.harvest-receipt.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "repository": git("config", "--get", "remote.origin.url"),
            "branch": git("branch", "--show-current"),
            "commit": git("rev-parse", "HEAD"),
            "dirty_status": git("status", "--short").splitlines(),
        },
        "output": str(export_root),
        "lanes": copied_by_lane,
        "side_effects": {
            "network_deploy": False,
            "site_sync": False,
            "cms_publish": False,
            "asset_upload": False,
            "database_write": False,
            "active_sdk_package_write": False
        },
    }
    (export_root / "HARVEST_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Harvest export created: {export_root}")
    print("No deploy, publish, sync, upload, database write, or active SDK package mutation occurred.")

    if args.stage_sdk:
        dest = stage_into_sdk(export_root, args.sdk, args.replace_sdk_staging)
        print(f"SDK donor staging created: {dest}")
        print("Staging is under apps/_incoming only; no active package was changed.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
