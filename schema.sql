CREATE TABLE IF NOT EXISTS scrape_runs (
    run_id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    mode TEXT NOT NULL,
    seed_count INTEGER NOT NULL DEFAULT 0,
    area_pages_seen INTEGER NOT NULL DEFAULT 0,
    project_pages_seen INTEGER NOT NULL DEFAULT 0,
    pages_succeeded INTEGER NOT NULL DEFAULT 0,
    pages_failed INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS source_pages (
    source_page_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES scrape_runs(run_id) ON DELETE CASCADE,
    requested_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    page_type TEXT NOT NULL CHECK (page_type IN ('area', 'project', 'unknown')),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_status INTEGER,
    content_sha256 TEXT,
    parse_status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    UNIQUE (run_id, canonical_url)
);
CREATE INDEX IF NOT EXISTS ix_source_pages_url_time ON source_pages (canonical_url, fetched_at DESC);

-- One row per registered project/phase when a MahaRERA number is available.
-- This is the latest parsed state; project_snapshots preserves prior observations.
CREATE TABLE IF NOT EXISTS projects (
    project_key TEXT PRIMARY KEY,
    rera_number TEXT,
    project_name TEXT NOT NULL,
    developer TEXT,
    locality TEXT,
    pin_code CHAR(6),
    project_url TEXT NOT NULL,
    maharera_status TEXT,
    construction_stage TEXT,
    launch_date_text TEXT,
    possession_date_text TEXT,
    original_possession_date_text TEXT,
    total_units INTEGER,
    units_for_sale INTEGER,
    units_booked INTEGER,
    booking_pct NUMERIC(6,2),
    building_count INTEGER,
    land_acres NUMERIC(12,4),
    excavation_pct NUMERIC(5,2),
    rcc_pct NUMERIC(5,2),
    finishing_pct NUMERIC(5,2),
    complaint_count INTEGER,
    latest_sale_year INTEGER,
    price_per_sqft_80pct NUMERIC(14,2),
    latest_sale_count INTEGER,
    map_url TEXT,
    last_content_sha256 TEXT,
    raw_latest JSONB,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (rera_number)
);
CREATE INDEX IF NOT EXISTS ix_projects_locality ON projects (locality);
CREATE INDEX IF NOT EXISTS ix_projects_pin ON projects (pin_code);
CREATE INDEX IF NOT EXISTS ix_projects_rera ON projects (rera_number);
CREATE INDEX IF NOT EXISTS ix_projects_possession ON projects (possession_date_text);

-- Field-rich, versioned JSON snapshot of each page's structured extraction.
-- Raw HTML is deliberately not stored by default; this avoids turning the DB into a mirror of the website.
CREATE TABLE IF NOT EXISTS project_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    source_page_id BIGINT REFERENCES source_pages(source_page_id) ON DELETE SET NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_sha256 TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    data JSONB NOT NULL,
    UNIQUE (project_key, content_sha256)
);
CREATE INDEX IF NOT EXISTS ix_project_snapshots_project_time ON project_snapshots (project_key, observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_project_snapshots_data ON project_snapshots USING GIN (data);

CREATE TABLE IF NOT EXISTS project_unit_mix (
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    flat_type TEXT NOT NULL,
    unit_count INTEGER,
    PRIMARY KEY (snapshot_id, flat_type)
);

-- These are project/year summaries shown by FlatNama, NOT individual sale transactions.
CREATE TABLE IF NOT EXISTS project_sale_year_stats (
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    sales_year INTEGER NOT NULL,
    year_label TEXT,
    price_per_sqft_80pct NUMERIC(14,2),
    sale_count INTEGER,
    raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, sales_year, year_label)
);

CREATE TABLE IF NOT EXISTS project_size_price_bands (
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    year_label TEXT,
    min_size_sqft NUMERIC(12,2),
    max_size_sqft NUMERIC(12,2),
    min_price_inr NUMERIC(16,2),
    max_price_inr NUMERIC(16,2),
    raw_size_label TEXT,
    raw_price_label TEXT,
    PRIMARY KEY (snapshot_id, raw_size_label, raw_price_label)
);

CREATE TABLE IF NOT EXISTS project_progress_updates (
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    update_label TEXT NOT NULL,
    excavation_pct NUMERIC(5,2),
    rcc_pct NUMERIC(5,2),
    finishing_pct NUMERIC(5,2),
    units_booked INTEGER,
    raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, update_label)
);

CREATE TABLE IF NOT EXISTS project_comparables (
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    comparable_name TEXT NOT NULL,
    launch_date_text TEXT,
    possession_date_text TEXT,
    rcc_pct NUMERIC(5,2),
    booking_text TEXT,
    raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, comparable_name)
);

CREATE OR REPLACE VIEW latest_project_sale_stats AS
SELECT DISTINCT ON (s.project_key, ys.sales_year)
       s.project_key, p.project_name, p.locality, ys.sales_year,
       ys.price_per_sqft_80pct, ys.sale_count, s.observed_at
FROM project_sale_year_stats ys
JOIN project_snapshots s ON s.snapshot_id = ys.snapshot_id
JOIN projects p ON p.project_key = s.project_key
ORDER BY s.project_key, ys.sales_year, s.observed_at DESC;
