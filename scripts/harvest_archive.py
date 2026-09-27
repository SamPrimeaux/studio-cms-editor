#!/usr/bin/env python3
"""Safe local intake/repackager for historical website/theme archives.

Accepts directories plus .zip, .tar, .tar.gz/.tgz, .gz, and Git .bundle files.
Everything is quarantined locally, fingerprinted, classified, and repackaged
without deploy/publish/sync/upload side effects.

Examples:
  python3 scripts/harvest_archive.py ~/Downloads/theme.zip
  python3 scripts/harvest_archive.py old.bundle backup.tar.gz theme.zip
  python3 scripts/harvest_archive.py theme.zip --out ../studio-cms-editor-harvest-export --replace
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT.parent / "studio-cms-editor-harvest-export"
SHOPIFY_DIRS = ("layout", "sections", "snippets", "templates", "config", "locales", "assets")
JUNK_PARTS = {
    "node_modules", ".next", "dist", "build", ".cache", ".parcel-cache",
    ".wrangler", ".vinext", "__pycache__", ".DS_Store",
}
CODE_EXTS = {
    ".html", ".htm", ".liquid", ".css", ".scss", ".sass", ".less", ".js", ".jsx",
    ".ts", ".tsx", ".json", ".md", ".txt", ".xml", ".svg", ".yml", ".yaml", ".toml",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".svg", ".ico", ".heic"}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_id(prefix, *parts):
    raw = "|".join(str(x) for x in parts)
    return prefix + "_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def safe_slug(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    return value or "archive"


def is_junk(rel):
    return any(part in JUNK_PARTS for part in PurePosixPath(rel).parts)


def safe_rel(name):
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in ("..", "") for part in p.parts):
        raise RuntimeError("unsafe archive path: " + name)
    return p


def classify_input(path):
    if path.is_dir():
        return "directory"
    low = path.name.lower()
    if low.endswith(".bundle"):
        return "git-bundle"
    if low.endswith(".tar.gz") or low.endswith(".tgz"):
        return "tar.gz"
    if low.endswith(".tar"):
        return "tar"
    if low.endswith(".zip"):
        return "zip"
    if low.endswith(".gz"):
        return "gz"
    return "file"


def ensure_limits(count, total, max_files, max_bytes):
    if count > max_files:
        raise RuntimeError(f"archive file-count limit exceeded: {count} > {max_files}")
    if total > max_bytes:
        raise RuntimeError(f"archive unpacked-size limit exceeded: {total} > {max_bytes}")


def copy_directory(src, dest, include_build_junk, max_files, max_bytes):
    copied, skipped, total = [], [], 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src).as_posix()
        if not include_build_junk and is_junk(rel):
            skipped.append({"path": rel, "reason": "build-junk"})
            continue
        if path.is_symlink():
            skipped.append({"path": rel, "reason": "symlink"})
            continue
        if path.is_dir():
            continue
        total += path.stat().st_size
        ensure_limits(len(copied) + 1, total, max_files, max_bytes)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append(rel)
    return copied, skipped, total


def extract_zip(src, dest, include_build_junk, max_files, max_bytes):
    copied, skipped, total = [], [], 0
    with zipfile.ZipFile(src) as zf:
        members = zf.infolist()
        declared = sum(info.file_size for info in members if not info.is_dir())
        ensure_limits(len(members), declared, max_files, max_bytes)
        for info in members:
            rel = safe_rel(info.filename)
            rels = rel.as_posix()
            if info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                skipped.append({"path": rels, "reason": "symlink"})
                continue
            if not include_build_junk and is_junk(rels):
                skipped.append({"path": rels, "reason": "build-junk"})
                continue
            total += info.file_size
            ensure_limits(len(copied) + 1, total, max_files, max_bytes)
            target = dest.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as rf, target.open("wb") as wf:
                shutil.copyfileobj(rf, wf)
            copied.append(rels)
    return copied, skipped, total


def extract_tar(src, dest, include_build_junk, max_files, max_bytes):
    copied, skipped, total = [], [], 0
    with tarfile.open(src, "r:*") as tf:
        members = tf.getmembers()
        declared = sum(m.size for m in members if m.isfile())
        ensure_limits(len(members), declared, max_files, max_bytes)
        for member in members:
            rel = safe_rel(member.name)
            rels = rel.as_posix()
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                skipped.append({"path": rels, "reason": "link"})
                continue
            if not member.isfile():
                skipped.append({"path": rels, "reason": "special-file"})
                continue
            if not include_build_junk and is_junk(rels):
                skipped.append({"path": rels, "reason": "build-junk"})
                continue
            total += member.size
            ensure_limits(len(copied) + 1, total, max_files, max_bytes)
            target = dest.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            rf = tf.extractfile(member)
            if rf is None:
                skipped.append({"path": rels, "reason": "unreadable"})
                continue
            with rf, target.open("wb") as wf:
                shutil.copyfileobj(rf, wf)
            copied.append(rels)
    return copied, skipped, total


def extract_gz(src, dest, max_bytes):
    name = src.name[:-3] or "payload"
    target = dest / safe_slug(name)
    total = 0
    with gzip.open(src, "rb") as rf, target.open("wb") as wf:
        while True:
            chunk = rf.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError("gzip unpacked-size limit exceeded")
            wf.write(chunk)
    return [target.name], [], total


def extract_bundle(src, dest):
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git is required for .bundle intake")
    verify = subprocess.run(
        [git, "bundle", "verify", str(src)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if verify.returncode != 0:
        raise RuntimeError("not a valid Git bundle: " + (verify.stderr or verify.stdout).strip())
    repo = dest / "repo"
    subprocess.run(
        [git, "clone", "-q", str(src), str(repo)],
        check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return repo, {
        "verify_stdout": verify.stdout[-6000:],
        "verify_stderr": verify.stderr[-6000:],
    }


def find_shopify_root(source):
    candidates = []
    roots = [source]
    for depth1 in source.iterdir() if source.exists() else []:
        if depth1.is_dir():
            roots.append(depth1)
            for depth2 in depth1.iterdir():
                if depth2.is_dir():
                    roots.append(depth2)
    for root in roots:
        present = [name for name in SHOPIFY_DIRS if (root / name).is_dir()]
        score = len(present)
        markers = {
            "theme_liquid": (root / "layout" / "theme.liquid").is_file(),
            "settings_schema": (root / "config" / "settings_schema.json").is_file(),
            "settings_data": (root / "config" / "settings_data.json").is_file(),
        }
        if score or any(markers.values()):
            candidates.append((score + sum(markers.values()) * 2, root, present, markers))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    score, root, present, markers = candidates[0]
    if score < 4 and not (markers["theme_liquid"] and markers["settings_schema"]):
        return None
    return {"root": root, "score": score, "present": present, "markers": markers}


def inventory(source):
    extensions, categories, files, total = {}, {}, [], 0
    html_candidates, liquid_candidates = [], []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(source).as_posix()
        size = path.stat().st_size
        total += size
        ext = path.suffix.lower()
        extensions[ext or "<none>"] = extensions.get(ext or "<none>", 0) + 1
        if ext in IMAGE_EXTS:
            cat = "image"
        elif ext in CODE_EXTS:
            cat = "code-content"
        else:
            cat = "other"
        categories[cat] = categories.get(cat, 0) + 1
        row = {"path": rel, "bytes": size, "sha256": sha256(path), "category": cat}
        files.append(row)
        if ext in (".html", ".htm"):
            html_candidates.append(rel)
        if ext == ".liquid":
            liquid_candidates.append(rel)
    return {
        "file_count": len(files),
        "bytes": total,
        "extensions": dict(sorted(extensions.items())),
        "categories": categories,
        "html_candidates": html_candidates,
        "liquid_candidates": liquid_candidates,
        "files": files,
    }


def write_zip_from_root(root, out_file, include_paths=None):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if include_paths:
            paths = []
            for name in include_paths:
                base = root / name
                if base.exists():
                    paths.extend(p for p in base.rglob("*") if p.is_file() and not p.is_symlink())
        else:
            paths = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
        for path in sorted(paths):
            zf.write(path, path.relative_to(root).as_posix())
    return out_file


def write_tar_gz(root, out_file):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_file, "w:gz", compresslevel=6) as tf:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            tf.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
    return out_file


def write_git_bundle(repo, out_file):
    git = shutil.which("git")
    if not git or not (repo / ".git").exists():
        return None
    subprocess.run(
        [git, "bundle", "create", str(out_file), "--all"],
        cwd=repo, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    return out_file


def write_salvage_zip(source, paths, out_file):
    if not paths:
        return None
    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel in sorted(set(paths)):
            path = source / rel
            if path.is_file():
                zf.write(path, rel)
    return out_file


def package_row(path, kind):
    return {
        "kind": kind,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def ensure_archive_tables(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS archive_ingests (
      id TEXT PRIMARY KEY,
      account_id TEXT NOT NULL,
      site_id TEXT NOT NULL,
      source_path TEXT NOT NULL,
      source_kind TEXT NOT NULL,
      source_sha256 TEXT,
      quarantine_path TEXT NOT NULL,
      classification TEXT NOT NULL,
      created_at TEXT NOT NULL,
      manifest_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS archive_files (
      id TEXT PRIMARY KEY,
      ingest_id TEXT NOT NULL,
      relative_path TEXT NOT NULL,
      bytes INTEGER NOT NULL,
      sha256 TEXT NOT NULL,
      category TEXT NOT NULL,
      FOREIGN KEY (ingest_id) REFERENCES archive_ingests(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS archive_outputs (
      id TEXT PRIMARY KEY,
      ingest_id TEXT NOT NULL,
      output_kind TEXT NOT NULL,
      path TEXT NOT NULL,
      bytes INTEGER NOT NULL,
      sha256 TEXT NOT NULL,
      FOREIGN KEY (ingest_id) REFERENCES archive_ingests(id) ON DELETE CASCADE
    );
    """)


def write_db(db_path, account, site, manifest):
    if not db_path or not db_path.exists():
        return
    db = sqlite3.connect(db_path)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        ensure_archive_tables(db)
        ingest = manifest["ingest_id"]
        db.execute(
            "INSERT OR REPLACE INTO archive_ingests(id,account_id,site_id,source_path,source_kind,source_sha256,quarantine_path,classification,created_at,manifest_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                ingest, account, site, manifest["input"]["path"], manifest["input"]["kind"],
                manifest["input"].get("sha256"), manifest["quarantine"], manifest["classification"],
                manifest["created_at"], json.dumps(manifest)
            ),
        )
        for row in manifest["inventory"]["files"]:
            db.execute(
                "INSERT OR REPLACE INTO archive_files(id,ingest_id,relative_path,bytes,sha256,category) VALUES(?,?,?,?,?,?)",
                (
                    stable_id("afile", ingest, row["path"]), ingest, row["path"],
                    row["bytes"], row["sha256"], row["category"]
                ),
            )
        for row in manifest["outputs"]:
            db.execute(
                "INSERT OR REPLACE INTO archive_outputs(id,ingest_id,output_kind,path,bytes,sha256) VALUES(?,?,?,?,?,?)",
                (
                    stable_id("aout", ingest, row["kind"], row["path"]), ingest, row["kind"],
                    row["path"], row["bytes"], row["sha256"]
                ),
            )
        db.commit()
    finally:
        db.close()


def process_one(path, out, args):
    path = path.expanduser().resolve()
    if not path.exists():
        raise RuntimeError("input does not exist: " + str(path))
    kind = classify_input(path)
    source_hash = sha256(path) if path.is_file() else stable_id("dir", path, path.stat().st_mtime_ns)
    stem = safe_slug(path.name)
    ingest_id = stable_id("ingest", str(path), source_hash)
    root = out / "intake" / (stem + "-" + ingest_id[-8:])
    if root.exists():
        if not args.replace:
            raise RuntimeError("intake already exists; use --replace: " + str(root))
        shutil.rmtree(root)
    quarantine = root / "source"
    packages = root / "packages"
    quarantine.mkdir(parents=True)
    packages.mkdir(parents=True)
    max_bytes = args.max_unpacked_mb * 1024 * 1024

    bundle_meta = None
    repo_root = None
    if kind == "directory":
        copied, skipped, total = copy_directory(
            path, quarantine, args.include_build_junk, args.max_files, max_bytes
        )
        if (path / ".git").exists():
            repo_root = path
    elif kind == "zip":
        copied, skipped, total = extract_zip(
            path, quarantine, args.include_build_junk, args.max_files, max_bytes
        )
    elif kind in ("tar", "tar.gz"):
        copied, skipped, total = extract_tar(
            path, quarantine, args.include_build_junk, args.max_files, max_bytes
        )
    elif kind == "gz":
        copied, skipped, total = extract_gz(path, quarantine, max_bytes)
    elif kind == "git-bundle":
        repo_root, bundle_meta = extract_bundle(path, quarantine)
        copied = [p.relative_to(quarantine).as_posix() for p in repo_root.rglob("*") if p.is_file()]
        skipped, total = [], sum(p.stat().st_size for p in repo_root.rglob("*") if p.is_file())
    else:
        target = quarantine / path.name
        shutil.copy2(path, target)
        copied, skipped, total = [path.name], [], target.stat().st_size

    inv = inventory(quarantine)
    shopify = find_shopify_root(quarantine)
    classification = "shopify-theme" if shopify else ("git-repository" if repo_root else "website-source")
    outputs = []

    archive_tar = write_tar_gz(quarantine, packages / "normalized-source.tar.gz")
    outputs.append(package_row(archive_tar, "normalized-tar.gz"))

    if args.emit_zip:
        portable_zip = write_zip_from_root(quarantine, packages / "normalized-source.zip")
        outputs.append(package_row(portable_zip, "normalized-zip"))

    if shopify:
        theme_zip = write_zip_from_root(
            shopify["root"], packages / "shopify-theme.zip", SHOPIFY_DIRS
        )
        outputs.append(package_row(theme_zip, "shopify-theme-zip"))

    salvage_paths = list(inv["html_candidates"])
    # Liquid files outside a detected Shopify root are useful donor material too.
    if shopify:
        theme_prefix = shopify["root"].relative_to(quarantine).as_posix()
        for rel in inv["liquid_candidates"]:
            if theme_prefix != "." and not rel.startswith(theme_prefix.rstrip("/") + "/"):
                salvage_paths.append(rel)
    salvage = write_salvage_zip(quarantine, salvage_paths, packages / "custom-html-liquid-salvage.zip")
    if salvage:
        outputs.append(package_row(salvage, "custom-html-liquid-salvage"))

    if repo_root:
        rebundle = write_git_bundle(repo_root, packages / "repository.bundle")
        if rebundle:
            outputs.append(package_row(rebundle, "git-bundle"))

    source_bytes = path.stat().st_size if path.is_file() else inv["bytes"]
    manifest = {
        "schema": "studio-cms-editor.archive-intake.v1",
        "ingest_id": ingest_id,
        "created_at": utcnow(),
        "input": {
            "path": str(path),
            "kind": kind,
            "bytes": source_bytes,
            "sha256": sha256(path) if path.is_file() else None,
        },
        "quarantine": str(quarantine),
        "classification": classification,
        "shopify": None if not shopify else {
            "root": str(shopify["root"]),
            "root_relative": shopify["root"].relative_to(quarantine).as_posix(),
            "score": shopify["score"],
            "core_directories_present": shopify["present"],
            "markers": shopify["markers"],
        },
        "extraction": {
            "copied_entries": len(copied),
            "skipped_entries": skipped,
            "unpacked_bytes": total,
            "limits": {"max_files": args.max_files, "max_unpacked_mb": args.max_unpacked_mb},
        },
        "inventory": inv,
        "bundle": bundle_meta,
        "outputs": outputs,
        "storage_guidance": {
            "raw_source": "Keep original archive outside automated repacks if legal/business retention requires exact bytes.",
            "r2_default": "Prefer normalized-source.tar.gz for compact archival storage; store manifest separately for search/indexing.",
            "shopify": "Use shopify-theme.zip only when classification is shopify-theme; core theme folders are at archive root.",
            "git": "Prefer repository.bundle for Git history rather than zipping .git.",
            "images": "Do not duplicate large image binaries into multiple packages unless a portability/export use case requires it.",
        },
        "side_effects": {
            "network": False,
            "deploy": False,
            "publish": False,
            "sync": False,
            "r2_upload": False,
            "remote_db_write": False,
        },
    }
    manifest_path = root / "ARCHIVE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("inputs", nargs="+", type=Path, help="Drag/drop paths: folder, .zip, .tar, .tar.gz/.tgz, .gz, or Git .bundle")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--db", type=Path, help="Optional local CMS SQLite. Defaults to <out>/local/inneranimals-cms.sqlite if present.")
    ap.add_argument("--account-id", default=os.getenv("IAM_ACCOUNT_ID") or os.getenv("AGENTSAM_ACCOUNT_ID") or "acct_local")
    ap.add_argument("--site-id", default="site_inneranimals")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--emit-zip", action="store_true", help="Also emit normalized-source.zip. tar.gz remains the compact default.")
    ap.add_argument("--include-build-junk", action="store_true", help="Include node_modules/build/cache directories in quarantine/repackages.")
    ap.add_argument("--max-files", type=int, default=50000)
    ap.add_argument("--max-unpacked-mb", type=int, default=2048)
    args = ap.parse_args()

    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    db_path = args.db.expanduser().resolve() if args.db else out / "local" / "inneranimals-cms.sqlite"

    manifests = []
    for path in args.inputs:
        manifest = process_one(path, out, args)
        write_db(db_path if db_path.exists() else None, args.account_id, args.site_id, manifest)
        manifests.append(manifest)
        print(f"[OK] {path} -> {manifest['classification']}")
        for item in manifest["outputs"]:
            print(f"     {item['kind']}: {item['path']} ({item['bytes']} bytes)")

    index = {
        "schema": "studio-cms-editor.archive-intake-index.v1",
        "created_at": utcnow(),
        "count": len(manifests),
        "ingests": [
            {
                "ingest_id": m["ingest_id"],
                "input": m["input"],
                "classification": m["classification"],
                "manifest": str(Path(m["quarantine"]).parent / "ARCHIVE_MANIFEST.json"),
                "outputs": m["outputs"],
            }
            for m in manifests
        ],
    }
    index_path = out / "intake" / "ARCHIVE_INDEX.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    print("Archive index:", index_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, zipfile.BadZipFile, tarfile.TarError, subprocess.CalledProcessError, sqlite3.Error) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
