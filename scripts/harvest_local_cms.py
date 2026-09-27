#!/usr/bin/env python3
"""Build a local account-scoped CMS SQLite scaffold from studio-cms-editor.

Local only: no deploy, publish, sync, R2/D1/KV write, or asset download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "plans" / "local-cms-harvest-schema.sql"
MANIFEST = ROOT / "plans" / "harvest-manifest.json"
DEFAULT_OUT = ROOT.parent / "studio-cms-editor-harvest-export"

ROUTES = {
    "app/page.tsx": ("/", "HomePage"),
    "app/shop/page.tsx": ("/shop", "ShopPage"),
    "app/collections/[slug]/page.tsx": ("/collections/[slug]", "Page"),
    "app/product/[slug]/page.tsx": ("/product/[slug]", "ProductPage"),
    "app/journal/page.tsx": ("/journal", "JournalPage"),
    "app/journal/[slug]/page.tsx": ("/journal/[slug]", "Page"),
    "app/story/page.tsx": ("/story", "StoryPage"),
}

SIGNALS = {
    "localStorage": ("local-state", "info", "Useful for preview/recovery; do not assume canonical authority."),
    "setTimeout": ("simulation", "info", "Timer-driven behavior may be simulated persistence/progress."),
    "2 others editing": ("fake-presence", "warning", "Hardcoded collaboration presence needs a real realtime source."),
    "Connected": ("fake-state", "info", "Connection state needs a provider/runtime receipt."),
    "uploaded": ("fake-upload", "info", "Upload language needs real asset persistence."),
    "publishing": ("fake-publish", "warning", "Publish UI needs an immutable publication receipt."),
    "wrangler deploy": ("deployment-coupling", "warning", "Deploy commands are reference-only and explicit."),
    "deploy:prod": ("deployment-coupling", "warning", "Production deploy must never become an implicit SDK lifecycle action."),
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).stdout.strip()


def stable_id(prefix, *parts):
    raw = "|".join(str(x) for x in parts)
    return prefix + "_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def line_at(text, offset):
    return text.count("\n", 0, offset) + 1


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def classify_token(name, value):
    s = (name + " " + value).lower()
    if "#" in value or "rgb" in value or any(x in s for x in ("color", "background", "accent", "surface", "border", "acid", "line", "text-")):
        return "color"
    if "font" in s:
        return "typography"
    if "radius" in s or name.startswith("--r-"):
        return "radius"
    if "ease" in s or "dur" in s or "motion" in s:
        return "motion"
    if any(x in s for x in ("space", "gap", "padding", "margin")):
        return "spacing"
    return "other"


def split_top(text):
    out, start, depth, quote, escape = [], 0, 0, None, False
    for i, ch in enumerate(text):
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def parse_value(raw):
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        return [parse_value(x) for x in split_top(raw[1:-1])]
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return float(raw) if "." in raw else int(raw)
    return raw


def parse_object(raw):
    result = {}
    for part in split_top(raw):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip().strip("'").strip('"')
        if re.fullmatch(r"[A-Za-z_$][\w$]*", key):
            result[key] = parse_value(value)
    return result


def extract_array(text, name):
    m = re.search(r"export\s+const\s+" + re.escape(name) + r"[^=]*=\s*\[", text)
    if not m:
        return []
    start = text.find("[", m.end() - 1)
    depth, quote, escape, end = 0, None, False, None
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return []
    block = text[start + 1:end]
    rows = []
    for obj in re.finditer(r"\{([^{}]*)\}", block, re.S):
        rows.append((parse_object(obj.group(1)), line_at(text, start + 1 + obj.start())))
    return rows


def insert_brand(conn, account, site, run_id):
    profiles = [
        ("inneranimals-public", "Inner Animals Public Theme", "public-theme", "app/storefront.css", "candidate"),
        ("cms-shell", "CMS Editor Shell", "editor-chrome", "app/globals.css", "reference"),
    ]
    for pkey, name, role, rel, status in profiles:
        pid = stable_id("brand", account, site, pkey)
        conn.execute(
            "INSERT INTO cms_brand_profiles(account_id,id,site_id,profile_key,name,role,source_file,status) VALUES(?,?,?,?,?,?,?,?)",
            (account, pid, site, pkey, name, role, rel, status),
        )
        text = read(rel)
        for match in re.finditer(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;}{]+)", text):
            token, value = match.group(1), match.group(2).strip()
            conn.execute(
                "INSERT OR IGNORE INTO cms_brand_tokens(account_id,id,site_id,profile_id,token_key,category,value_text,confidence,status,source_file,source_line) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account, stable_id("token", account, site, pkey, token), site, pid, token,
                    classify_token(token, value), value, 1.0,
                    "observed" if role == "public-theme" else "reference",
                    rel, line_at(text, match.start())
                ),
            )

    public_text = read("app/storefront.css") + "\n" + read("app/components/Storefront.tsx")
    counts = {}
    for match in re.finditer(r"#[0-9A-Fa-f]{3,8}\b", public_text):
        color = match.group(0).lower()
        counts[color] = counts.get(color, 0) + 1
    for color, count in counts.items():
        if count >= 2:
            conn.execute(
                "INSERT INTO harvest_candidates(id,run_id,account_id,site_id,candidate_kind,candidate_key,value_text,confidence,status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    stable_id("cand", run_id, "color", color), run_id, account, site,
                    "brand-color", color, color, 0.65, "review",
                    json.dumps({"occurrences": count})
                ),
            )


def insert_routes_sections(conn, account, site):
    store = read("app/components/Storefront.tsx")
    for rel, (path, symbol) in ROUTES.items():
        rid = stable_id("route", account, site, path)
        lid = stable_id("layout", account, site, path)
        conn.execute(
            "INSERT INTO cms_routes(account_id,id,site_id,path,route_kind,title,source_file,source_symbol,status) VALUES(?,?,?,?,?,?,?,?,?)",
            (account, rid, site, path, "public", "Home" if path == "/" else path, rel, symbol, "candidate"),
        )
        conn.execute(
            "INSERT INTO cms_layouts(account_id,id,site_id,route_id,layout_key,name,source_file,source_symbol,status) VALUES(?,?,?,?,?,?,?,?,?)",
            (account, lid, site, rid, "public:" + path, "Layout " + path, rel, symbol, "candidate"),
        )

        source = store if symbol in ("HomePage", "ShopPage", "ProductPage", "JournalPage", "StoryPage") else read(rel)
        scope = source
        if source is store:
            start = source.find("export function " + symbol)
            next_start = source.find("\nexport function ", start + 10)
            scope = source[start: next_start if next_start > 0 else len(source)]
        for pos, match in enumerate(re.finditer(r"<section\b([^>]*)>", scope)):
            attrs = match.group(1)
            cm = re.search(r'className\s*=\s*["\']([^"\']+)', attrs)
            name = cm.group(1) if cm else "section-" + str(pos + 1)
            key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            conn.execute(
                "INSERT OR IGNORE INTO cms_sections(account_id,id,site_id,route_id,layout_id,section_key,name,section_type,zone,position,authority,status,source_file,source_line,source_symbol) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account, stable_id("section", account, site, path, pos, key), site, rid, lid,
                    key, name, "section", "BODY", pos, "harvest", "candidate",
                    "app/components/Storefront.tsx" if source is store else rel,
                    line_at(source, match.start()), symbol
                ),
            )

    conn.execute(
        "INSERT INTO cms_routes(account_id,id,site_id,path,route_kind,title,source_file,source_symbol,status) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            account, stable_id("route", account, site, "/studio"), site, "/studio",
            "editor", "CMS Studio", "app/studio/page.tsx", "Studio", "reference"
        ),
    )


def insert_navigation(conn, account, site):
    text = read("app/components/Storefront.tsx")
    for nav_key, symbol, location in (
        ("public-primary", "StoreHeader", "header"),
        ("public-footer", "StoreFooter", "footer"),
    ):
        start = text.find("export function " + symbol)
        if start < 0:
            continue
        next_start = text.find("\nexport function ", start + 10)
        scope = text[start: next_start if next_start > 0 else len(text)]
        nav_id = stable_id("nav", account, site, nav_key)
        conn.execute(
            "INSERT INTO cms_navigation(account_id,id,site_id,nav_key,name,location,source_file,source_symbol,status) VALUES(?,?,?,?,?,?,?,?,?)",
            (account, nav_id, site, nav_key, symbol, location, "app/components/Storefront.tsx", symbol, "candidate"),
        )
        link_re = re.compile(r'<(?:Link|a)\b[^>]*href=["\']([^"\']+)["\'][^>]*>([^<{][^<{}]*)</(?:Link|a)>')
        for pos, match in enumerate(link_re.finditer(scope)):
            label = re.sub(r"\s+", " ", match.group(2)).strip()
            if not label:
                continue
            href = match.group(1)
            conn.execute(
                "INSERT INTO cms_navigation_items(account_id,id,site_id,navigation_id,position,label,href,item_kind,source_file,source_line,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account, stable_id("navitem", account, nav_id, pos, label, href), site, nav_id,
                    pos, label, href, "external" if href.startswith("http") else "internal",
                    "app/components/Storefront.tsx", line_at(text, start + match.start()), "candidate"
                ),
            )


def insert_content_assets(conn, account, site):
    rel = "app/storefront-data.ts"
    text = read(rel)
    for collection, item_type in (("products", "product"), ("archetypes", "archetype"), ("journal", "article")):
        for pos, (data, line) in enumerate(extract_array(text, collection)):
            key = str(data.get("slug") or data.get("name") or (collection + "-" + str(pos + 1)))
            conn.execute(
                "INSERT INTO cms_content_items(account_id,id,site_id,collection_key,item_key,item_type,title,slug,authority,status,source_file,source_line,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account, stable_id("content", account, site, collection, key), site, collection, key,
                    item_type, data.get("title") or data.get("name"), data.get("slug"),
                    "sample", "sample", rel, line, json.dumps(data, ensure_ascii=False)
                ),
            )

    seen = set()
    for source_rel in [rel, "app/components/Storefront.tsx", *ROUTES.keys()]:
        source = read(source_rel)
        for match in re.finditer(r"https?://[^\s\"'<>)}]+", source):
            uri = match.group(0).rstrip(",;")
            if uri in seen:
                continue
            seen.add(uri)
            kind = "image" if "images.unsplash.com" in uri or re.search(r"\.(png|jpe?g|webp|svg)(\?|$)", uri, re.I) else "external-url"
            conn.execute(
                "INSERT INTO cms_assets(account_id,id,site_id,asset_key,asset_kind,uri,authority,status,source_file,source_line) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    account, stable_id("asset", account, site, uri), site, stable_id("assetkey", uri),
                    kind, uri, "reference", "candidate", source_rel, line_at(source, match.start())
                ),
            )


def record_provenance(conn, account, site, run_id, commit):
    manifest = json.loads(MANIFEST.read_text())
    for lane_name, lane in manifest["lanes"].items():
        for rel in lane.get("files", []):
            path = ROOT / rel
            if not path.is_file():
                continue
            conn.execute(
                "INSERT OR IGNORE INTO harvest_sources(id,run_id,lane,path,sha256,bytes,source_commit) VALUES(?,?,?,?,?,?,?)",
                (
                    stable_id("source", run_id, lane_name, rel), run_id, lane_name, rel,
                    sha256(path), path.stat().st_size, commit
                ),
            )
            if path.suffix.lower() not in {".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".toml", ".css"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for signal, (category, severity, message) in SIGNALS.items():
                for match in re.finditer(re.escape(signal), text, re.I):
                    line = line_at(text, match.start())
                    conn.execute(
                        "INSERT OR IGNORE INTO harvest_findings(id,run_id,account_id,site_id,category,severity,signal,message,source_file,source_line,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            stable_id("finding", run_id, rel, signal, line), run_id, account, site,
                            category, severity, signal, message, rel, line, "review"
                        ),
                    )


def build_db(db_path, account, site, site_name, domain):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    commit = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    repo = git("config", "--get", "remote.origin.url")
    run_id = stable_id("harvest", account, site, commit, utcnow())

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA.read_text())
        stamp = utcnow()
        conn.execute(
            "INSERT INTO cms_sites(account_id,id,slug,name,domain,status,source_repo,source_ref,created_at,updated_at) VALUES(?,?,?,?,?,'harvest',?,?,?,?)",
            (account, site, "inneranimals", site_name, domain, repo, branch, stamp, stamp),
        )
        conn.execute(
            "INSERT INTO harvest_runs(id,account_id,site_id,source_repo,source_ref,source_commit,created_at) VALUES(?,?,?,?,?,?,?)",
            (run_id, account, site, repo, branch, commit, stamp),
        )
        record_provenance(conn, account, site, run_id, commit)
        insert_brand(conn, account, site, run_id)
        insert_routes_sections(conn, account, site)
        insert_navigation(conn, account, site)
        insert_content_assets(conn, account, site)
        conn.commit()

        tables = [
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        ]
        counts = {
            table: conn.execute('SELECT COUNT(*) n FROM "' + table + '"').fetchone()["n"]
            for table in tables
        }
        return {
            "schema": "studio-cms-editor.local-cms.v1",
            "db_path": str(db_path),
            "account_id": account,
            "site_id": site,
            "source_commit": commit,
            "source_ref": branch,
            "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "tables": counts,
            "ownership": "account -> site; no tenant/workspace layer",
        }
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--replace-export", action="store_true")
    ap.add_argument("--reuse-export", action="store_true")
    ap.add_argument("--db", type=Path)
    ap.add_argument("--replace-db", action="store_true")
    ap.add_argument("--account-id")
    ap.add_argument("--site-id", default="site_inneranimals")
    ap.add_argument("--site-name", default="Inner Animals")
    ap.add_argument("--domain", default="inneranimals.com")
    args = ap.parse_args()

    out = args.out.expanduser().resolve()
    marker = out / ".studio-cms-harvest-export"
    if args.reuse_export:
        if not marker.exists():
            raise RuntimeError("recognized harvest export not found: " + str(out))
    else:
        cmd = [sys.executable, str(ROOT / "scripts" / "harvest_all.py"), "--out", str(out)]
        if args.replace_export:
            cmd.append("--replace-export")
        subprocess.run(cmd, cwd=ROOT, check=True)

    db = args.db.expanduser().resolve() if args.db else out / "local" / "inneranimals-cms.sqlite"
    if db.exists() and not args.replace_db:
        raise RuntimeError("SQLite file exists; pass --replace-db after review: " + str(db))

    account = args.account_id or os.getenv("IAM_ACCOUNT_ID") or os.getenv("AGENTSAM_ACCOUNT_ID") or "acct_local"
    summary = build_db(db, account, args.site_id, args.site_name, args.domain or None)
    summary_path = db.parent / "LOCAL_SQLITE_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print("Local CMS SQLite:", db)
    print("Summary:", summary_path)
    print(summary["ownership"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, sqlite3.Error) as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(2)
