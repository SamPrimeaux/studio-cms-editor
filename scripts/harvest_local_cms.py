#!/usr/bin/env python3
"""Curate studio-cms-editor into a local SQLite CMS/brand/theme working scaffold.

This is a LOCAL harvest tool. It:
  1. runs the curated file export,
  2. creates a separate SQLite database,
  3. extracts brand tokens, routes/layouts, navigation, structured sample content,
     assets, components, section candidates, and provenance,
  4. creates empty draft/change-set/publication tables for future local editing,
  5. optionally stages the finished export under agentsam-sdk/apps/_incoming.

It NEVER deploys, publishes, syncs, uploads, writes D1/R2/KV, or modifies an
active AgentSam SDK package.
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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCHEMA_PATH = ROOT / "plans" / "local-cms-harvest-schema.sql"
MANIFEST_PATH = ROOT / "plans" / "harvest-manifest.json"
DEFAULT_OUT = ROOT.parent / "studio-cms-editor-harvest-export"

sys.path.insert(0, str(SCRIPTS))
import harvest_all  # noqa: E402

PUBLIC_ROUTES = {
    "app/page.tsx": "/",
    "app/shop/page.tsx": "/shop",
    "app/collections/[slug]/page.tsx": "/collections/[slug]",
    "app/product/[slug]/page.tsx": "/product/[slug]",
    "app/journal/page.tsx": "/journal",
    "app/journal/[slug]/page.tsx": "/journal/[slug]",
    "app/story/page.tsx": "/story",
}
SIGNALS = {
    "localStorage": ("prototype-state", "warning", "Browser-local state is useful for preview/recovery but must not become canonical CMS authority."),
    "setTimeout": ("simulation", "info", "Timer-driven behavior may be simulated UX rather than persisted state."),
    "2 others editing": ("fake-presence", "warning", "Collaboration/presence copy appears hardcoded and must not imply real realtime state."),
    "Connected": ("fake-state", "info", "Connection state requires verification before promotion."),
    "uploaded": ("fake-upload", "info", "Upload language requires verification against real asset persistence."),
    "publishing": ("fake-publish", "warning", "Publishing UX requires verification against a real immutable publication flow."),
    "wrangler deploy": ("deployment-coupling", "warning", "Deployment command is reference-only and must remain explicit."),
    "deploy:prod": ("deployment-coupling", "warning", "Production deployment script must not become an implicit SDK lifecycle action."),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def line_for(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def route_id(account_id: str, site_id: str, path: str) -> str:
    return stable_id("route", account_id, site_id, path)


def layout_id(account_id: str, site_id: str, key: str) -> str:
    return stable_id("layout", account_id, site_id, key)


def classify_token(name: str, value: str) -> str:
    n = name.lower()
    v = value.lower()
    if (
        any(x in n for x in ("color", "bg", "border", "accent", "text", "surface", "acid", "line"))
        or re.search(r"#(?:[0-9a-f]{3,8})\b|rgba?\(|hsla?\(", v)
    ):
        return "color"
    if "font" in n:
        return "typography"
    if n.startswith("--r-") or "radius" in n:
        return "radius"
    if any(x in n for x in ("dur", "ease", "motion")):
        return "motion"
    if any(x in n for x in ("space", "gap", "pad", "margin")):
        return "spacing"
    return "other"


def split_top_level(value: str, delimiter: str = ",") -> list[str]:
    out: list[str] = []
    start = 0
    quote: str | None = None
    escape = False
    depth = 0
    openers = {"[", "{", "("}
    closers = {"]", "}", ")"}
    for i, ch in enumerate(value):
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'", chr(96)):
            quote = ch
        elif ch in openers:
            depth += 1
        elif ch in closers:
            depth = max(0, depth - 1)
        elif ch == delimiter and depth == 0:
            out.append(value[start:i].strip())
            start = i + 1
    tail = value[start:].strip()
    if tail:
        out.append(tail)
    return out


def parse_js_value(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        return [parse_js_value(x) for x in split_top_level(raw[1:-1])]
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw in ("null", "undefined"):
        return None
    if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
        return float(raw) if "." in raw else int(raw)
    return raw


def parse_object_fields(raw: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for piece in split_top_level(raw):
        if ":" not in piece:
            continue
        key, value = piece.split(":", 1)
        key = key.strip().strip("\"'")
        if re.fullmatch(r"[A-Za-z_$][\w$]*", key):
            result[key] = parse_js_value(value)
    return result


def find_balanced(text: str, start: int, opener: str = "{", closer: str = "}") -> tuple[str, int]:
    if start < 0 or start >= len(text) or text[start] != opener:
        raise ValueError("balanced scan must start on opener")
    depth = 0
    quote: str | None = None
    escape = False
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
        if ch in ('"', "'", chr(96)):
            quote = ch
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
    raise ValueError("unbalanced source")


def top_level_objects(block: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    depth = 0
    quote: str | None = None
    escape = False
    start: int | None = None
    for i, ch in enumerate(block):
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'", chr(96)):
            quote = ch
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                out.append((block[start + 1 : i], start))
                start = None
    return out


def extract_function_body(text: str, name: str) -> tuple[str, int] | None:
    match = re.search(rf"(?:export\s+)?function\s+{re.escape(name)}\b", text)
    if not match:
        return None
    brace = text.find("{", match.end())
    if brace < 0:
        return None
    body, _ = find_balanced(text, brace)
    return body, brace + 1


def extract_array_objects(text: str, name: str) -> list[tuple[dict[str, Any], int]]:
    match = re.search(rf"export\s+const\s+{re.escape(name)}[^=]*=\s*\[", text)
    if not match:
        return []
    open_idx = text.find("[", match.end() - 1)
    depth = 0
    quote: str | None = None
    escape = False
    close_idx = None
    for i in range(open_idx, len(text)):
        ch = text[i]
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'", chr(96)):
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                close_idx = i
                break
    if close_idx is None:
        return []
    block = text[open_idx + 1 : close_idx]
    return [
        (parse_object_fields(raw), line_for(text, open_idx + 1 + rel))
        for raw, rel in top_level_objects(block)
    ]


def route_symbol(source: str) -> str:
    match = re.search(r'import\s*{\s*([^}]+)\s*}\s*from\s*["\'][^"\']*Storefront', source)
    if match:
        names = [x.strip() for x in match.group(1).split(",")]
        preferred = [x for x in names if x not in ("StoreHeader", "StoreFooter")]
        if preferred:
            return preferred[0]
    return "Page"


def jsx_sections(text: str, source_symbol: str | None = None) -> list[tuple[str, str, int]]:
    scope = text
    base = 0
    if source_symbol:
        found = extract_function_body(text, source_symbol)
        if found:
            scope, base = found
    out = []
    for idx, match in enumerate(re.finditer(r"<section\b([^>]*)>", scope), start=1):
        attrs = match.group(1)
        class_match = re.search(r'className\s*=\s*["\']([^"\']+)["\']', attrs)
        class_name = class_match.group(1).strip() if class_match else f"section-{idx}"
        key = re.sub(r"[^a-z0-9]+", "-", class_name.lower()).strip("-") or f"section-{idx}"
        out.append((key, class_name, line_for(text, base + match.start())))
    return out


def user_facing_text_candidates(text: str) -> list[tuple[str, int]]:
    seen: set[str] = set()
    out = []
    for match in re.finditer(r">([^<>{}\n][^<>{}]*)<", text):
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        if len(value) < 3 or value in seen:
            continue
        if re.fullmatch(r"[A-Za-z0-9_-]+", value) and len(value) < 6:
            continue
        seen.add(value)
        out.append((value, line_for(text, match.start(1))))
    return out


def nav_links(function_body: str, full_text: str, body_offset: int) -> list[tuple[str, str, int]]:
    out = []
    pattern = re.compile(
        r'<(?:Link|a)\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>'
        r'([^<{][^<{}]*)</(?:Link|a)>'
    )
    for match in pattern.finditer(function_body):
        label = re.sub(r"\s+", " ", match.group(2)).strip()
        if label:
            out.append((label, match.group(1), line_for(full_text, body_offset + match.start())))
    return out


def insert_site_and_profiles(
    conn: sqlite3.Connection,
    account_id: str,
    site_id: str,
    site_slug: str,
    site_name: str,
    domain: str | None,
    repo: str,
    ref: str,
) -> dict[str, str]:
    stamp = now()
    conn.execute(
        """
        INSERT INTO cms_sites
        (account_id,id,slug,name,domain,status,source_kind,source_repo,source_ref,
         metadata_json,created_at,updated_at)
        VALUES (?,?,?,?,?,'harvest','harvest',?,?,?, ?,?)
        """,
        (account_id, site_id, site_slug, site_name, domain, repo, ref, "{}", stamp, stamp),
    )
    profiles = {
        "public": stable_id("brand", account_id, site_id, "inneranimals-public"),
        "editor": stable_id("brand", account_id, site_id, "cms-shell"),
    }
    conn.execute(
        """
        INSERT INTO brand_profiles
        (account_id,id,site_id,profile_key,name,role,status,source_file,metadata_json)
        VALUES (?,?,?,?,?,'public-theme','candidate','app/storefront.css','{}')
        """,
        (account_id, profiles["public"], site_id, "inneranimals-public", "Inner Animals Public Theme"),
    )
    conn.execute(
        """
        INSERT INTO brand_profiles
        (account_id,id,site_id,profile_key,name,role,status,source_file,metadata_json)
        VALUES (?,?,?,?,?,'editor-chrome','reference','app/globals.css','{}')
        """,
        (account_id, profiles["editor"], site_id, "cms-shell", "CMS Editor Shell"),
    )
    return profiles


def extract_brand(
    conn: sqlite3.Connection,
    account_id: str,
    site_id: str,
    profiles: dict[str, str],
    run_id: str,
) -> None:
    css_sources = [
        ("app/storefront.css", profiles["public"], "observed"),
        ("app/globals.css", profiles["editor"], "reference"),
    ]
    var_re = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;}{]+)")
    for rel, profile_id, status in css_sources:
        text = read(rel)
        for match in var_re.finditer(text):
            key, value = match.group(1), match.group(2).strip()
            conn.execute(
                """
                INSERT OR IGNORE INTO brand_tokens
                (account_id,id,site_id,profile_id,token_key,category,value_text,
                 status,confidence,source_file,source_line,source_kind,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,1.0,?,?,'css-variable','{}')
                """,
                (
                    account_id,
                    stable_id("token", account_id, site_id, profile_id, key, rel, line_for(text, match.start())),
                    site_id,
                    profile_id,
                    key,
                    classify_token(key, value),
                    value,
                    status,
                    rel,
                    line_for(text, match.start()),
                ),
            )

    public_sources = ["app/storefront.css", "app/components/Storefront.tsx", *PUBLIC_ROUTES.keys()]
    occurrences: list[tuple[str, str, int]] = []
    counter: Counter[str] = Counter()
    for rel in public_sources:
        text = read(rel)
        for match in re.finditer(r"#[0-9A-Fa-f]{3,8}\b", text):
            color = match.group(0).lower()
            counter[color] += 1
            occurrences.append((color, rel, line_for(text, match.start())))
    for color, count in counter.items():
        if count < 2:
            continue
        first = next(x for x in occurrences if x[0] == color)
        conn.execute(
            """
            INSERT INTO harvest_candidates
            (id,run_id,account_id,site_id,candidate_kind,candidate_key,value_text,
             confidence,status,source_file,source_line,metadata_json)
            VALUES (?,?,?,?, 'brand-color', ?, ?, 0.65, 'review', ?, ?, ?)
            """,
            (
                stable_id("cand", run_id, "color", color),
                run_id,
                account_id,
                site_id,
                f"observed-color:{color}",
                color,
                first[1],
                first[2],
                jdump({"occurrences": count}),
            ),
        )


def create_routes_layouts_sections(
    conn: sqlite3.Connection,
    account_id: str,
    site_id: str,
) -> None:
    store = read("app/components/Storefront.tsx")
    for rel, path in PUBLIC_ROUTES.items():
        source = read(rel)
        symbol = route_symbol(source)
        rid = route_id(account_id, site_id, path)
        lid = layout_id(account_id, site_id, f"public:{path}")
        conn.execute(
            """
            INSERT INTO cms_routes
            (account_id,id,site_id,path,route_kind,title,source_file,source_symbol,status,metadata_json)
            VALUES (?,?,?,?, 'public', ?, ?, ?, 'candidate','{}')
            """,
            (account_id, rid, site_id, path, path if path != "/" else "Home", rel, symbol),
        )
        conn.execute(
            """
            INSERT INTO cms_layouts
            (account_id,id,site_id,route_id,layout_key,name,source_file,source_symbol,status,structure_json)
            VALUES (?,?,?,?,?,?,?,?,'candidate','{}')
            """,
            (account_id, lid, site_id, rid, f"public:{path}", f"Layout {path}", rel, symbol),
        )
        if symbol != "Page" and extract_function_body(store, symbol):
            section_source, section_symbol, section_file = store, symbol, "app/components/Storefront.tsx"
        else:
            section_source, section_symbol, section_file = source, None, rel
        for pos, (key, name, line) in enumerate(jsx_sections(section_source, section_symbol)):
            conn.execute(
                """
                INSERT OR IGNORE INTO cms_sections
                (account_id,id,site_id,route_id,layout_id,section_key,name,section_type,zone,
                 position,visible_default,status,authority,source_file,source_line,source_symbol,
                 props_json,style_json)
                VALUES (?,?,?,?,?,?,?,?,'BODY',?,1,'candidate','harvest',?,?,?,'{}','{}')
                """,
                (
                    account_id,
                    stable_id("section", account_id, site_id, path, key, pos),
                    site_id,
                    rid,
                    lid,
                    key,
                    name,
                    "section",
                    pos,
                    section_file,
                    line,
                    section_symbol or "Page",
                ),
            )

    editor_path = "/studio"
    erid = route_id(account_id, site_id, editor_path)
    elid = layout_id(account_id, site_id, "editor:studio")
    conn.execute(
        """
        INSERT INTO cms_routes
        (account_id,id,site_id,path,route_kind,title,source_file,source_symbol,status,metadata_json)
        VALUES (?,?,?,?,'editor','CMS Studio','app/studio/page.tsx','Studio','reference','{}')
        """,
        (account_id, erid, site_id, editor_path),
    )
    conn.execute(
        """
        INSERT INTO cms_layouts
        (account_id,id,site_id,route_id,layout_key,name,source_file,source_symbol,status,structure_json)
        VALUES (?,?,?,?,'editor:studio','CMS Studio Prototype','app/studio/page.tsx',
                'Studio','reference','{}')
        """,
        (account_id, elid, site_id, erid),
    )

    studio = read("app/studio/page.tsx")
    match = re.search(r"const\s+makeSections\s*=.*?=>\s*\[", studio, re.S)
    if not match:
        return
    open_idx = studio.find("[", match.end() - 1)
    close_idx = studio.find("];", open_idx)
    if close_idx < 0:
        return
    block = studio[open_idx + 1 : close_idx]
    for pos, (raw, rel_off) in enumerate(top_level_objects(block)):
        sid = re.search(r'id:\s*"([^"]+)"', raw)
        name = re.search(r'name:\s*"([^"]+)"', raw)
        typ = re.search(r'type:\s*"([^"]+)"', raw)
        zone = re.search(r'zone:\s*"([^"]+)"', raw)
        visible = re.search(r'visible:\s*(true|false)', raw)
        color = re.search(r'color:\s*"([^"]+)"', raw)
        fields_match = re.search(r"fields\s*:\s*\{", raw)
        fields: dict[str, Any] = {}
        if fields_match:
            brace = raw.find("{", fields_match.start())
            try:
                fields_raw, _ = find_balanced(raw, brace)
                fields = parse_object_fields(fields_raw)
            except ValueError:
                pass
        key = sid.group(1) if sid else f"seed-{pos + 1}"
        conn.execute(
            """
            INSERT OR IGNORE INTO cms_sections
            (account_id,id,site_id,route_id,layout_id,section_key,name,section_type,zone,
             position,visible_default,color_hint,status,authority,source_file,source_line,
             source_symbol,props_json,style_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'reference','prototype',?,?,?,?, '{}')
            """,
            (
                account_id,
                stable_id("section", account_id, site_id, "studio-seed", key),
                site_id,
                erid,
                elid,
                key,
                name.group(1) if name else key,
                typ.group(1) if typ else "Section",
                zone.group(1) if zone else None,
                pos,
                1 if not visible or visible.group(1) == "true" else 0,
                color.group(1) if color else None,
                "app/studio/page.tsx",
                line_for(studio, open_idx + 1 + rel_off),
                "makeSections",
                jdump(fields),
            ),
        )


def extract_navigation(conn: sqlite3.Connection, account_id: str, site_id: str) -> None:
    store = read("app/components/Storefront.tsx")
    definitions = [
        ("public-primary", "Public Primary Navigation", "header", "StoreHeader"),
        ("public-footer", "Public Footer Navigation", "footer", "StoreFooter"),
    ]
    for key, name, location, symbol in definitions:
        found = extract_function_body(store, symbol)
        if not found:
            continue
        body, offset = found
        nav_id = stable_id("nav", account_id, site_id, key)
        conn.execute(
            """
            INSERT INTO cms_navigation_systems
            (account_id,id,site_id,nav_key,name,location,status,source_file,source_symbol,metadata_json)
            VALUES (?,?,?,?,?,?,'candidate','app/components/Storefront.tsx',?,'{}')
            """,
            (account_id, nav_id, site_id, key, name, location, symbol),
        )
        for pos, (label, href, line) in enumerate(nav_links(body, store, offset)):
            conn.execute(
                """
                INSERT INTO cms_navigation_items
                (account_id,id,site_id,navigation_id,parent_id,position,label,href,item_kind,
                 status,source_file,source_line,metadata_json)
                VALUES (?,?,?,?,NULL,?,?,?,?,'candidate','app/components/Storefront.tsx',?,'{}')
                """,
                (
                    account_id,
                    stable_id("navitem", account_id, nav_id, pos, label, href),
                    site_id,
                    nav_id,
                    pos,
                    label,
                    href,
                    "external" if href.startswith("http") else "internal",
                    line,
                ),
            )


def extract_structured_content(conn: sqlite3.Connection, account_id: str, site_id: str) -> None:
    rel = "app/storefront-data.ts"
    text = read(rel)
    for collection, item_type in [("products", "product"), ("archetypes", "archetype"), ("journal", "article")]:
        for pos, (fields, line) in enumerate(extract_array_objects(text, collection)):
            item_key = str(fields.get("slug") or fields.get("name") or f"{collection}-{pos + 1}")
            title = fields.get("title") or fields.get("name")
            slug = fields.get("slug")
            item_id = stable_id("content", account_id, site_id, collection, item_key)
            conn.execute(
                """
                INSERT INTO cms_content_items
                (account_id,id,site_id,collection_key,item_key,item_type,title,slug,status,
                 authority,source_file,source_line,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,'sample','sample',?,?,?)
                """,
                (account_id, item_id, site_id, collection, item_key, item_type, title, slug, rel, line, jdump({"position": pos})),
            )
            for field_key, value in fields.items():
                if isinstance(value, (dict, list)):
                    value_type, value_text, value_json = "json", None, jdump(value)
                elif isinstance(value, bool):
                    value_type, value_text, value_json = "boolean", ("true" if value else "false"), None
                elif isinstance(value, (int, float)):
                    value_type, value_text, value_json = "number", str(value), None
                elif value is None:
                    value_type, value_text, value_json = "null", None, None
                else:
                    value_type, value_text, value_json = "text", str(value), None
                conn.execute(
                    """
                    INSERT INTO cms_content_fields
                    (account_id,id,site_id,item_id,field_key,value_type,value_text,value_json,
                     source_file,source_line,metadata_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,'{}')
                    """,
                    (
                        account_id,
                        stable_id("field", account_id, item_id, field_key),
                        site_id,
                        item_id,
                        field_key,
                        value_type,
                        value_text,
                        value_json,
                        rel,
                        line,
                    ),
                )


def extract_components_and_candidates(
    conn: sqlite3.Connection,
    account_id: str,
    site_id: str,
    run_id: str,
) -> None:
    store_rel = "app/components/Storefront.tsx"
    store = read(store_rel)
    for match in re.finditer(r"export function\s+([A-Za-z0-9_]+)", store):
        name = match.group(1)
        conn.execute(
            """
            INSERT OR IGNORE INTO cms_components
            (account_id,id,site_id,component_key,name,component_kind,status,source_file,
             source_line,source_symbol,metadata_json)
            VALUES (?,?,?,?,?,'storefront','candidate',?,?,?,'{}')
            """,
            (
                account_id,
                stable_id("component", account_id, site_id, store_rel, name),
                site_id,
                name.lower(),
                name,
                store_rel,
                line_for(store, match.start()),
                name,
            ),
        )

    studio_rel = "app/studio/page.tsx"
    studio = read(studio_rel)
    components_match = re.search(r"const\s+components\s*=\s*\[(.*?)\];", studio, re.S)
    if components_match:
        for pos, value in enumerate(re.findall(r'"([^"]+)"', components_match.group(1))):
            conn.execute(
                """
                INSERT OR IGNORE INTO cms_components
                (account_id,id,site_id,component_key,name,component_kind,status,source_file,
                 source_line,source_symbol,metadata_json)
                VALUES (?,?,?,?,?,'editor-library','reference',?,?,'components',?)
                """,
                (
                    account_id,
                    stable_id("component", account_id, site_id, studio_rel, value),
                    site_id,
                    re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-"),
                    value,
                    studio_rel,
                    line_for(studio, components_match.start()),
                    jdump({"position": pos}),
                ),
            )

    templates_match = re.search(r"const\s+templateCards\s*=\s*\[(.*?)\];", studio, re.S)
    if templates_match:
        for pos, value in enumerate(re.findall(r'"([^"]+)"', templates_match.group(1))):
            conn.execute(
                """
                INSERT INTO harvest_candidates
                (id,run_id,account_id,site_id,candidate_kind,candidate_key,value_text,
                 confidence,status,source_file,source_line,metadata_json)
                VALUES (?,?,?,?, 'template', ?, ?, 0.75, 'review', ?, ?, ?)
                """,
                (
                    stable_id("cand", run_id, "template", value),
                    run_id,
                    account_id,
                    site_id,
                    re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-"),
                    value,
                    studio_rel,
                    line_for(studio, templates_match.start()),
                    jdump({"position": pos}),
                ),
            )

    for rel in [store_rel, *PUBLIC_ROUTES.keys()]:
        text = read(rel)
        for value, line in user_facing_text_candidates(text):
            conn.execute(
                """
                INSERT OR IGNORE INTO harvest_candidates
                (id,run_id,account_id,site_id,candidate_kind,candidate_key,value_text,
                 confidence,status,source_file,source_line,metadata_json)
                VALUES (?,?,?,?, 'content-text', ?, ?, 0.70, 'review', ?, ?,'{}')
                """,
                (
                    stable_id("cand", run_id, "text", rel, line, value),
                    run_id,
                    account_id,
                    site_id,
                    stable_id("text", rel, line, value),
                    value,
                    rel,
                    line,
                ),
            )


def extract_assets(conn: sqlite3.Connection, account_id: str, site_id: str) -> None:
    rels = ["app/storefront-data.ts", "app/components/Storefront.tsx", "app/storefront.css", *PUBLIC_ROUTES.keys()]
    seen: set[tuple[str, str]] = set()
    for rel in rels:
        text = read(rel)
        for match in re.finditer(r"""https?://[^\s"'<>)}]+""", text):
            uri = match.group(0).rstrip(";,")
            key = (rel, uri)
            if key in seen:
                continue
            seen.add(key)
            kind = "image" if (
                "images.unsplash.com" in uri
                or re.search(r"\.(?:png|jpe?g|webp|avif|svg)(?:\?|$)", uri, re.I)
            ) else "external-url"
            conn.execute(
                """
                INSERT OR IGNORE INTO cms_assets
                (account_id,id,site_id,asset_key,asset_kind,uri,local_path,status,
                 authority,source_file,source_line,metadata_json)
                VALUES (?,?,?,?,?,?,NULL,'candidate','reference',?,?,'{}')
                """,
                (
                    account_id,
                    stable_id("asset", account_id, site_id, uri),
                    site_id,
                    stable_id("assetkey", uri),
                    kind,
                    uri,
                    rel,
                    line_for(text, match.start()),
                ),
            )

    favicon = ROOT / "public" / "favicon.svg"
    if favicon.exists():
        conn.execute(
            """
            INSERT OR IGNORE INTO cms_assets
            (account_id,id,site_id,asset_key,asset_kind,uri,local_path,status,
             authority,source_file,source_line,metadata_json)
            VALUES (?,?,?,'favicon','icon',NULL,?,'candidate','reference',
                    'public/favicon.svg',1,?)
            """,
            (
                account_id,
                stable_id("asset", account_id, site_id, "public/favicon.svg"),
                site_id,
                "public/favicon.svg",
                jdump({"sha256": sha256(favicon), "bytes": favicon.stat().st_size}),
            ),
        )


def record_provenance_and_findings(
    conn: sqlite3.Connection,
    account_id: str,
    site_id: str,
    run_id: str,
    manifest: dict[str, Any],
    commit: str,
) -> None:
    seen: set[tuple[str, str]] = set()
    for lane_name, lane in manifest["lanes"].items():
        for rel in lane.get("files", []):
            path = ROOT / rel
            if not path.exists() or not path.is_file():
                continue
            pair = (lane_name, rel)
            if pair not in seen:
                seen.add(pair)
                conn.execute(
                    """
                    INSERT INTO harvest_source_files
                    (id,run_id,lane,path,sha256,bytes,source_commit,metadata_json)
                    VALUES (?,?,?,?,?,?,?,'{}')
                    """,
                    (
                        stable_id("src", run_id, lane_name, rel),
                        run_id,
                        lane_name,
                        rel,
                        sha256(path),
                        path.stat().st_size,
                        commit,
                    ),
                )
            if path.suffix.lower() not in {".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".toml", ".css"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for signal, (category, severity, message) in SIGNALS.items():
                start = 0
                while True:
                    idx = text.lower().find(signal.lower(), start)
                    if idx < 0:
                        break
                    line = line_for(text, idx)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO harvest_findings
                        (id,run_id,account_id,site_id,category,severity,signal,message,
                         source_file,source_line,status,metadata_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,'review','{}')
                        """,
                        (
                            stable_id("finding", run_id, rel, signal, line),
                            run_id,
                            account_id,
                            site_id,
                            category,
                            severity,
                            signal,
                            message,
                            rel,
                            line,
                        ),
                    )
                    start = idx + len(signal)


def build_database(
    db_path: Path,
    account_id: str,
    site_id: str,
    site_slug: str,
    site_name: str,
    domain: str | None,
) -> dict[str, Any]:
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    commit = git("rev-parse", "HEAD")
    branch = git("branch", "--show-current")
    repo = git("config", "--get", "remote.origin.url")
    run_id = stable_id("harvest", account_id, site_id, commit, now())

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(schema)
        conn.execute("BEGIN")
        profiles = insert_site_and_profiles(conn, account_id, site_id, site_slug, site_name, domain, repo, branch)
        conn.execute(
            """
            INSERT INTO harvest_import_runs
            (id,account_id,site_id,source_repo,source_ref,source_commit,manifest_json,created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (run_id, account_id, site_id, repo, branch, commit, jdump(manifest), now()),
        )
        record_provenance_and_findings(conn, account_id, site_id, run_id, manifest, commit)
        extract_brand(conn, account_id, site_id, profiles, run_id)
        create_routes_layouts_sections(conn, account_id, site_id)
        extract_navigation(conn, account_id, site_id)
        extract_structured_content(conn, account_id, site_id)
        extract_components_and_candidates(conn, account_id, site_id, run_id)
        extract_assets(conn, account_id, site_id)

        draft_id = stable_id("draft", account_id, site_id, "harvest-working")
        stamp = now()
        conn.execute(
            """
            INSERT INTO cms_drafts
            (account_id,id,site_id,route_id,name,status,base_publication_id,
             snapshot_json,created_at,updated_at)
            VALUES (?,?,?,NULL,'Harvest working draft','working',NULL,?,?,?)
            """,
            (
                account_id,
                draft_id,
                site_id,
                jdump(
                    {
                        "schema": "agentsam.cms.local-draft.v1",
                        "mode": "normalized-tables",
                        "source": "harvest",
                        "site_id": site_id,
                        "base_publication": None,
                    }
                ),
                stamp,
                stamp,
            ),
        )
        conn.commit()

        tables = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            table: conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
            for table in tables
        }
        return {
            "schema": "studio-cms-editor.local-sqlite-harvest.v1",
            "db_path": str(db_path),
            "account_id": account_id,
            "site_id": site_id,
            "source_repo": repo,
            "source_ref": branch,
            "source_commit": commit,
            "run_id": run_id,
            "tables": counts,
            "ownership": "account -> site (no tenant/workspace layer)",
            "side_effects": {
                "network_deploy": False,
                "site_sync": False,
                "cms_publish": False,
                "asset_download": False,
                "asset_upload": False,
                "database_remote_write": False,
            },
        }
    finally:
        conn.close()


def ensure_export(out: Path, replace: bool, reuse: bool) -> None:
    marker = out / ".studio-cms-harvest-export"
    if reuse:
        if not marker.exists():
            raise RuntimeError(f"--reuse-export requires an existing recognized export: {out}")
        return
    cmd = [sys.executable, str(SCRIPTS / "harvest_all.py"), "--out", str(out)]
    if replace:
        cmd.append("--replace-export")
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--replace-export", action="store_true")
    parser.add_argument("--reuse-export", action="store_true")
    parser.add_argument("--db", type=Path, help="SQLite output path. Default: <out>/local/inneranimals-cms.sqlite")
    parser.add_argument("--replace-db", action="store_true")
    parser.add_argument("--account-id")
    parser.add_argument("--site-id", default="site_inneranimals")
    parser.add_argument("--site-slug", default="inneranimals")
    parser.add_argument("--site-name", default="Inner Animals")
    parser.add_argument("--domain", default="inneranimals.com")
    parser.add_argument("--sdk", type=Path)
    parser.add_argument("--stage-sdk", action="store_true")
    parser.add_argument("--replace-sdk-staging", action="store_true")
    args = parser.parse_args()

    if args.replace_export and args.reuse_export:
        parser.error("--replace-export and --reuse-export are mutually exclusive")
    if args.stage_sdk and not args.sdk:
        parser.error("--stage-sdk requires --sdk /path/to/agentsam-sdk")

    out = args.out.expanduser().resolve()
    ensure_export(out, args.replace_export, args.reuse_export)

    db_path = args.db.expanduser().resolve() if args.db else out / "local" / "inneranimals-cms.sqlite"
    if db_path.exists() and not args.replace_db:
        raise RuntimeError(f"SQLite output already exists: {db_path}\nUse --replace-db after reviewing it.")

    account_id = (
        args.account_id
        or os.environ.get("IAM_ACCOUNT_ID")
        or os.environ.get("AGENTSAM_ACCOUNT_ID")
        or "acct_local"
    )
    summary = build_database(
        db_path=db_path,
        account_id=account_id,
        site_id=args.site_id,
        site_slug=args.site_slug,
        site_name=args.site_name,
        domain=args.domain or None,
    )
    summary_path = db_path.parent / "LOCAL_SQLITE_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Local CMS SQLite created: {db_path}")
    print(f"Summary: {summary_path}")
    print(f"Ownership: {summary['ownership']}")
    print("No deploy, sync, publish, asset upload/download, or remote DB write occurred.")

    if args.stage_sdk:
        dest = harvest_all.stage_into_sdk(out, args.sdk, args.replace_sdk_staging)
        print(f"SDK donor staging created: {dest}")
        print("Only apps/_incoming was written; no active SDK package was changed.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
