-- Comprehensive schema for FlatNama research collector
-- Stores structured project identity, location, possession, construction,
-- inventory, price summaries, size bands, milestones, benchmarks, FAQs,
-- area catalogues, and data quality audits.

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
    page_type TEXT NOT NULL CHECK (page_type IN ('area', 'project', 'analytics', 'unknown')),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_status INTEGER,
    content_sha256 TEXT,
    parse_status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    UNIQUE (run_id, canonical_url)
);
CREATE INDEX IF NOT EXISTS ix_source_pages_url_time ON source_pages (canonical_url, fetched_at DESC);

-- Area-level summaries (catalogue counts, filters and nearby areas)
CREATE TABLE IF NOT EXISTS area_page_snapshots (
    area_snapshot_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES scrape_runs(run_id) ON DELETE CASCADE,
    source_page_id BIGINT REFERENCES source_pages(source_page_id) ON DELETE SET NULL,
    area_url TEXT NOT NULL,
    area_name TEXT,
    pin_code CHAR(6),
    listed_project_count INTEGER,
    visible_projects_count INTEGER,
    small_projects_hidden_count INTEGER,
    launched_last_6_months_count INTEGER,
    rcc_complete_count INTEGER,
    possession_date_extended_count INTEGER,
    content_sha256 TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data JSONB NOT NULL,
    UNIQUE (area_url, content_sha256)
);
CREATE INDEX IF NOT EXISTS ix_area_page_snapshots_url_time ON area_page_snapshots (area_url, observed_at DESC);

-- Coverage manifest: every project URL discovered from each area page
CREATE TABLE IF NOT EXISTS discovered_project_urls (
    discovered_url_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES scrape_runs(run_id) ON DELETE CASCADE,
    source_area_url TEXT NOT NULL,
    project_url TEXT NOT NULL,
    discovery_method TEXT NOT NULL,
    selected_for_fetch BOOLEAN NOT NULL DEFAULT FALSE,
    fetch_status TEXT,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, source_area_url, project_url)
);
CREATE INDEX IF NOT EXISTS ix_discovered_project_urls_run ON discovered_project_urls (run_id, selected_for_fetch);
CREATE INDEX IF NOT EXISTS ix_discovered_project_urls_url ON discovered_project_urls (project_url, discovered_at DESC);

-- Master table for projects: one row per registered project/phase
CREATE TABLE IF NOT EXISTS projects (
    project_key TEXT PRIMARY KEY,
    rera_number TEXT,
    project_name TEXT NOT NULL,
    phase_name TEXT,
    developer TEXT,
    project_type TEXT DEFAULT 'Residential',
    project_description TEXT,
    locality TEXT,
    sub_locality TEXT,
    city TEXT DEFAULT 'Pune',
    district TEXT DEFAULT 'Pune',
    pin_code CHAR(6),
    project_url TEXT NOT NULL,
    area_page_url TEXT,
    map_url TEXT,
    displayed_address TEXT,
    
    -- Launch, possession & timeline metrics
    maharera_status TEXT,
    construction_stage TEXT,
    launch_date_text TEXT,
    launch_month TEXT,
    launch_year INTEGER,
    possession_date_text TEXT,
    possession_month TEXT,
    possession_year INTEGER,
    original_possession_date_text TEXT,
    possession_extension_status TEXT,
    possession_extension_months INTEGER,
    possession_extension_note TEXT,
    promised_timeline_text TEXT,
    promised_timeline_months INTEGER,
    months_elapsed_since_launch INTEGER,
    months_remaining_to_possession INTEGER,
    ready_to_move_status BOOLEAN DEFAULT FALSE,
    structural_completion_status BOOLEAN DEFAULT FALSE,
    finishing_completion_status BOOLEAN DEFAULT FALSE,

    -- Construction physical attributes
    building_count INTEGER,
    land_acres NUMERIC(12,4),
    excavation_pct NUMERIC(5,2),
    rcc_pct NUMERIC(5,2),
    finishing_pct NUMERIC(5,2),
    complaint_count INTEGER DEFAULT 0,

    -- Inventory and bookings
    total_units INTEGER,
    units_for_sale INTEGER,
    units_booked INTEGER,
    not_for_sale_units INTEGER,
    reported_booking_denominator INTEGER,
    recent_bookings_count INTEGER,
    booking_pct NUMERIC(6,2),
    booking_status TEXT,
    units_1rk INTEGER DEFAULT 0,
    units_1bhk INTEGER DEFAULT 0,
    units_2bhk INTEGER DEFAULT 0,
    units_3bhk INTEGER DEFAULT 0,
    units_4bhk INTEGER DEFAULT 0,
    units_5bhk_plus INTEGER DEFAULT 0,
    units_other INTEGER DEFAULT 0,
    total_residential_units INTEGER DEFAULT 0,

    -- Sold-price summaries & market comparisons
    latest_sale_year INTEGER,
    price_per_sqft_80pct NUMERIC(14,2),
    price_per_sqft_80pct_source TEXT,
    latest_sale_count INTEGER,
    current_ytd_price NUMERIC(14,2),
    previous_year_price NUMERIC(14,2),
    headline_price_per_sqft_80pct NUMERIC(14,2),
    headline_price_year_label TEXT,
    headline_price_sale_count INTEGER,
    year_over_year_change_pct NUMERIC(6,2),
    year_over_year_direction TEXT,
    year_over_year_comparison_year INTEGER,
    rate_vs_nearby_projects_pct NUMERIC(6,2),
    price_area_basis TEXT,
    years_of_sales_data INTEGER DEFAULT 0,

    -- Similar projects context
    similar_projects_count INTEGER,
    similar_projects_pin CHAR(6),

    -- Metadata, audit & provenance
    breadcrumbs JSONB DEFAULT '[]'::jsonb,
    source_notes JSONB DEFAULT '{}'::jsonb,
    quality_score NUMERIC(5,2),
    quality_warnings JSONB DEFAULT '[]'::jsonb,
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
CREATE INDEX IF NOT EXISTS ix_projects_developer ON projects (developer);
CREATE INDEX IF NOT EXISTS ix_projects_stage ON projects (construction_stage);
CREATE INDEX IF NOT EXISTS ix_projects_price ON projects (price_per_sqft_80pct);
CREATE INDEX IF NOT EXISTS ix_projects_possession ON projects (possession_date_text);

-- Versioned project snapshot
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

-- Unit mix breakdown
CREATE TABLE IF NOT EXISTS project_unit_mix (
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    flat_type TEXT NOT NULL,
    unit_count INTEGER,
    PRIMARY KEY (snapshot_id, flat_type)
);

-- Year-by-year 80th-percentile price stats
CREATE TABLE IF NOT EXISTS project_sale_year_stats (
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    sales_year INTEGER NOT NULL,
    year_label TEXT,
    price_per_sqft_80pct NUMERIC(14,2),
    sale_count INTEGER,
    year_over_year_delta_text TEXT,
    raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, sales_year, year_label)
);

-- Size-price bands
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

-- Historical construction and booking milestones
CREATE TABLE IF NOT EXISTS project_progress_updates (
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    update_label TEXT NOT NULL,
    excavation_pct NUMERIC(5,2),
    rcc_pct NUMERIC(5,2),
    finishing_pct NUMERIC(5,2),
    units_booked INTEGER,
    rcc_change NUMERIC(5,2),
    finishing_change NUMERIC(5,2),
    booking_change INTEGER,
    raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, update_label)
);

-- Comparable peer projects
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

-- Comparison benchmark measures
CREATE TABLE IF NOT EXISTS project_comparison_benchmarks (
    benchmark_id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    measure TEXT NOT NULL,
    this_project TEXT,
    similar_projects TEXT,
    raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (snapshot_id, measure)
);

-- Related links: other phases, similar projects, maps
CREATE TABLE IF NOT EXISTS project_related_links (
    link_id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    category TEXT NOT NULL,
    label TEXT NOT NULL,
    url TEXT NOT NULL,
    UNIQUE (snapshot_id, category, url)
);

-- Explanatory content & frequently asked questions
CREATE TABLE IF NOT EXISTS project_faqs (
    faq_id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    UNIQUE (snapshot_id, question)
);

-- Data quality and extraction audits
CREATE TABLE IF NOT EXISTS project_quality_audits (
    audit_id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    parser_version TEXT NOT NULL,
    fields_checked INTEGER NOT NULL,
    fields_present INTEGER NOT NULL,
    completeness_pct NUMERIC(5,2) NOT NULL,
    warnings JSONB DEFAULT '[]'::jsonb,
    audit_details JSONB NOT NULL,
    audited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snapshot_id)
);

-- Pune market analytics trends
CREATE TABLE IF NOT EXISTS area_market_analytics (
    analytics_id BIGSERIAL PRIMARY KEY,
    area_name TEXT NOT NULL,
    pin_code CHAR(6),
    trend_year INTEGER NOT NULL,
    projects_launched INTEGER,
    flats_launched INTEGER,
    rcc_complete_flats INTEGER,
    config_breakdown JSONB DEFAULT '{}'::jsonb,
    source_url TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (area_name, trend_year)
);

-- =====================================================================
-- ANALYTICAL VIEWS FOR EASY INSPECTION
-- =====================================================================

-- 1. Master Overview View
CREATE OR REPLACE VIEW v_projects_master AS
SELECT 
    project_key,
    rera_number,
    project_name,
    phase_name,
    developer,
    locality,
    pin_code,
    construction_stage,
    maharera_status,
    launch_date_text,
    possession_date_text,
    possession_extension_status,
    possession_delay_months,
    months_elapsed_since_launch,
    months_remaining_to_possession,
    building_count,
    land_acres,
    rcc_pct,
    finishing_pct,
    total_units,
    units_booked,
    booking_pct,
    latest_sale_year,
    price_per_sqft_80pct,
    latest_sale_count,
    year_over_year_change_pct,
    rate_vs_nearby_projects_pct,
    complaint_count,
    quality_score,
    project_url,
    last_scraped_at
FROM projects
ORDER BY locality NULLS LAST, project_name;

-- 2. Delays and Construction Progress
CREATE OR REPLACE VIEW v_project_delays_and_progress AS
SELECT 
    project_name,
    locality,
    rera_number,
    construction_stage,
    launch_date_text,
    promised_timeline_text,
    original_possession_date_text,
    possession_date_text,
    possession_extension_status,
    possession_delay_months,
    months_remaining_to_possession,
    excavation_pct,
    rcc_pct,
    finishing_pct,
    structural_completion_status,
    ready_to_move_status,
    complaint_count
FROM projects
ORDER BY possession_delay_months DESC NULLS LAST, locality;

-- 3. Pricing and Market Position
CREATE OR REPLACE VIEW v_project_pricing_summary AS
SELECT 
    project_name,
    locality,
    developer,
    latest_sale_year,
    price_per_sqft_80pct AS rate_per_sqft_80pct,
    latest_sale_count,
    current_ytd_price,
    previous_year_price,
    year_over_year_change_pct,
    year_over_year_direction,
    rate_vs_nearby_projects_pct,
    price_area_basis,
    years_of_sales_data,
    project_url
FROM projects
WHERE price_per_sqft_80pct IS NOT NULL
ORDER BY locality, price_per_sqft_80pct DESC;

-- 4. Inventory and Booking Status
CREATE OR REPLACE VIEW v_project_inventory_summary AS
SELECT 
    project_name,
    locality,
    total_units,
    units_for_sale,
    units_booked,
    booking_pct,
    booking_status,
    recent_bookings_count,
    units_1rk,
    units_1bhk,
    units_2bhk,
    units_3bhk,
    units_4bhk,
    units_5bhk_plus,
    units_other,
    total_residential_units
FROM projects
ORDER BY total_units DESC NULLS LAST;

-- 5. Annual Sale Stats (Backward Compatible)
CREATE OR REPLACE VIEW latest_project_sale_stats AS
SELECT DISTINCT ON (s.project_key, ys.sales_year)
       s.project_key, p.project_name, p.locality, ys.sales_year,
       ys.price_per_sqft_80pct, ys.sale_count, ys.year_over_year_delta_text, s.observed_at
FROM project_sale_year_stats ys
JOIN project_snapshots s ON s.snapshot_id = ys.snapshot_id
JOIN projects p ON p.project_key = s.project_key
ORDER BY s.project_key, ys.sales_year, s.observed_at DESC;

-- 6. FAQs Overview
CREATE OR REPLACE VIEW v_project_faqs_overview AS
SELECT 
    p.project_name,
    p.locality,
    f.topic,
    f.question,
    f.answer
FROM project_faqs f
JOIN projects p ON p.project_key = f.project_key
ORDER BY p.project_name, f.topic;
