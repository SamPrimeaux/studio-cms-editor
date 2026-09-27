PRAGMA foreign_keys = ON;

-- Local CMS harvest schema.
-- Ownership is account -> site. There are intentionally NO tenant_id or workspace_id columns.
-- This database is a local working/harvest store, not a publication authority by itself.

CREATE TABLE IF NOT EXISTS cms_sites (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  slug TEXT NOT NULL,
  name TEXT NOT NULL,
  domain TEXT,
  status TEXT NOT NULL DEFAULT 'harvest',
  source_kind TEXT NOT NULL DEFAULT 'harvest',
  source_repo TEXT,
  source_ref TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, slug)
);

CREATE TABLE IF NOT EXISTS brand_profiles (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  profile_key TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'candidate',
  source_file TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, site_id, profile_key),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS brand_tokens (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  token_key TEXT NOT NULL,
  category TEXT NOT NULL,
  value_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'observed',
  confidence REAL NOT NULL DEFAULT 1.0,
  source_file TEXT,
  source_line INTEGER,
  source_kind TEXT NOT NULL DEFAULT 'css-variable',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE,
  FOREIGN KEY (account_id, profile_id) REFERENCES brand_profiles(account_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_brand_tokens_site
  ON brand_tokens(account_id, site_id, profile_id, category);

CREATE TABLE IF NOT EXISTS cms_routes (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  path TEXT NOT NULL,
  route_kind TEXT NOT NULL,
  title TEXT,
  source_file TEXT,
  source_symbol TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, site_id, path),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_layouts (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  route_id TEXT,
  layout_key TEXT NOT NULL,
  name TEXT NOT NULL,
  source_file TEXT,
  source_symbol TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',
  structure_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, site_id, layout_key),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE,
  FOREIGN KEY (account_id, route_id) REFERENCES cms_routes(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_sections (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  route_id TEXT,
  layout_id TEXT,
  section_key TEXT NOT NULL,
  name TEXT NOT NULL,
  section_type TEXT NOT NULL,
  zone TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  visible_default INTEGER NOT NULL DEFAULT 1,
  color_hint TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',
  authority TEXT NOT NULL DEFAULT 'harvest',
  source_file TEXT,
  source_line INTEGER,
  source_symbol TEXT,
  props_json TEXT NOT NULL DEFAULT '{}',
  style_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE,
  FOREIGN KEY (account_id, route_id) REFERENCES cms_routes(account_id, id) ON DELETE SET NULL,
  FOREIGN KEY (account_id, layout_id) REFERENCES cms_layouts(account_id, id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_cms_sections_route
  ON cms_sections(account_id, site_id, route_id, position);

CREATE TABLE IF NOT EXISTS cms_blocks (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  section_id TEXT,
  block_key TEXT NOT NULL,
  block_type TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate',
  source_file TEXT,
  source_line INTEGER,
  source_symbol TEXT,
  props_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE,
  FOREIGN KEY (account_id, section_id) REFERENCES cms_sections(account_id, id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS cms_components (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  component_key TEXT NOT NULL,
  name TEXT NOT NULL,
  component_kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'candidate',
  source_file TEXT,
  source_line INTEGER,
  source_symbol TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, site_id, component_key, source_file),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_navigation_systems (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  nav_key TEXT NOT NULL,
  name TEXT NOT NULL,
  location TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'candidate',
  source_file TEXT,
  source_symbol TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, site_id, nav_key),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_navigation_items (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  navigation_id TEXT NOT NULL,
  parent_id TEXT,
  position INTEGER NOT NULL,
  label TEXT NOT NULL,
  href TEXT NOT NULL,
  item_kind TEXT NOT NULL DEFAULT 'internal',
  status TEXT NOT NULL DEFAULT 'candidate',
  source_file TEXT,
  source_line INTEGER,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE,
  FOREIGN KEY (account_id, navigation_id) REFERENCES cms_navigation_systems(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_content_items (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  collection_key TEXT NOT NULL,
  item_key TEXT NOT NULL,
  item_type TEXT NOT NULL,
  title TEXT,
  slug TEXT,
  status TEXT NOT NULL DEFAULT 'sample',
  authority TEXT NOT NULL DEFAULT 'sample',
  source_file TEXT,
  source_line INTEGER,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, site_id, collection_key, item_key),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_content_fields (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  field_key TEXT NOT NULL,
  value_type TEXT NOT NULL,
  value_text TEXT,
  value_json TEXT,
  source_file TEXT,
  source_line INTEGER,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, item_id, field_key),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE,
  FOREIGN KEY (account_id, item_id) REFERENCES cms_content_items(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_assets (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  asset_key TEXT NOT NULL,
  asset_kind TEXT NOT NULL,
  uri TEXT,
  local_path TEXT,
  status TEXT NOT NULL DEFAULT 'candidate',
  authority TEXT NOT NULL DEFAULT 'reference',
  source_file TEXT,
  source_line INTEGER,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (account_id, id),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cms_assets_site
  ON cms_assets(account_id, site_id, asset_kind);

-- Local zero-risk editing lane. These tables are intentionally separate from published state.
CREATE TABLE IF NOT EXISTS cms_drafts (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  route_id TEXT,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'working',
  base_publication_id TEXT,
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_id, id),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE,
  FOREIGN KEY (account_id, route_id) REFERENCES cms_routes(account_id, id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS cms_change_sets (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  draft_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  source_kind TEXT NOT NULL DEFAULT 'human',
  actor_ref TEXT,
  patch_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'accepted',
  created_at TEXT NOT NULL,
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, draft_id, sequence),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE,
  FOREIGN KEY (account_id, draft_id) REFERENCES cms_drafts(account_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cms_publications (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'published',
  snapshot_json TEXT NOT NULL,
  source_draft_id TEXT,
  created_at TEXT NOT NULL,
  published_at TEXT,
  PRIMARY KEY (account_id, id),
  UNIQUE (account_id, site_id, revision),
  FOREIGN KEY (account_id, site_id) REFERENCES cms_sites(account_id, id) ON DELETE CASCADE
);

-- Provenance / harvest intelligence.
CREATE TABLE IF NOT EXISTS harvest_import_runs (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  source_repo TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  source_commit TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS harvest_source_files (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  lane TEXT NOT NULL,
  path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  source_commit TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (run_id) REFERENCES harvest_import_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_harvest_source_files_run
  ON harvest_source_files(run_id, lane);

CREATE TABLE IF NOT EXISTS harvest_findings (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  signal TEXT NOT NULL,
  message TEXT NOT NULL,
  source_file TEXT,
  source_line INTEGER,
  status TEXT NOT NULL DEFAULT 'review',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (run_id) REFERENCES harvest_import_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS harvest_candidates (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  site_id TEXT NOT NULL,
  candidate_kind TEXT NOT NULL,
  candidate_key TEXT NOT NULL,
  value_text TEXT,
  confidence REAL NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'review',
  source_file TEXT,
  source_line INTEGER,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (run_id) REFERENCES harvest_import_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_harvest_candidates_kind
  ON harvest_candidates(account_id, site_id, candidate_kind, status);
