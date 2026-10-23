-- Cumulative Canonical Schema for Pune Real Estate Investment Intelligence Platform
-- Enforces data integrity, snapshot version reprocessing, separate listings/transactions,
-- financial modeling readiness, and analytical views for Hypotheses H1, H2, H3, and H4.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    description TEXT
);

-- 1. Scrape & Collection Runs
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

-- 2. Area Summaries
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
    UNIQUE (area_url, content_sha256, parser_version)
);
CREATE INDEX IF NOT EXISTS ix_area_page_snapshots_url_time ON area_page_snapshots (area_url, observed_at DESC);

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

-- 3. Master Projects Table
CREATE TABLE IF NOT EXISTS projects (
    project_key TEXT PRIMARY KEY,
    rera_number TEXT,
    project_name TEXT NOT NULL,
    phase_name TEXT,
    developer TEXT,
    project_type TEXT,                      -- Nullable: No automatic 'Residential' default
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
    
    -- Timeline
    maharera_status TEXT,
    construction_stage TEXT,
    launch_date_text TEXT,
    launch_month TEXT,
    launch_year INTEGER,
    possession_date_text TEXT,
    possession_month TEXT,
    possession_year INTEGER,
    original_possession_date_text TEXT,
    possession_extension_status TEXT,      -- Nullable: No automatic 'On Schedule' default
    possession_extension_months INTEGER,
    possession_extension_note TEXT,
    promised_timeline_text TEXT,
    promised_timeline_months INTEGER,
    months_elapsed_since_launch INTEGER,
    months_remaining_to_possession INTEGER,
    ready_to_move_status BOOLEAN,          -- Nullable: No automatic FALSE default
    structural_completion_status BOOLEAN,  -- Nullable: No automatic FALSE default
    finishing_completion_status BOOLEAN,   -- Nullable: No automatic FALSE default

    -- Physical attributes
    building_count INTEGER,
    land_acres NUMERIC(12,4),
    excavation_pct NUMERIC(5,2),
    rcc_pct NUMERIC(5,2),
    finishing_pct NUMERIC(5,2),
    complaint_count INTEGER,               -- Nullable: No automatic 0 default

    -- Inventory
    total_units INTEGER,
    units_for_sale INTEGER,
    units_booked INTEGER,
    not_for_sale_units INTEGER,
    reported_booking_denominator INTEGER,
    recent_bookings_count INTEGER,
    booking_pct NUMERIC(6,2),
    booking_status TEXT,
    units_1rk INTEGER,
    units_1bhk INTEGER,
    units_2bhk INTEGER,
    units_3bhk INTEGER,
    units_4bhk INTEGER,
    units_5bhk_plus INTEGER,
    units_other INTEGER,
    total_residential_units INTEGER,

    -- Sold-price summaries (80th-percentile benchmark)
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

    -- Similar projects
    similar_projects_count INTEGER,
    similar_projects_pin CHAR(6),

    -- Provenance & Metadata
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
CREATE INDEX IF NOT EXISTS ix_projects_stage ON projects (construction_stage);
CREATE INDEX IF NOT EXISTS ix_projects_price ON projects (price_per_sqft_80pct);

-- 4. Versioned Project Snapshots (Reprocessing Support via parser_version in unique key)
CREATE TABLE IF NOT EXISTS project_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    source_page_id BIGINT REFERENCES source_pages(source_page_id) ON DELETE SET NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_sha256 TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    data JSONB NOT NULL,
    UNIQUE (project_key, content_sha256, parser_version)
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
    rcc_change NUMERIC(5,2),
    finishing_change NUMERIC(5,2),
    booking_change INTEGER,
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

CREATE TABLE IF NOT EXISTS project_related_links (
    link_id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    category TEXT NOT NULL,
    label TEXT NOT NULL,
    url TEXT NOT NULL,
    UNIQUE (snapshot_id, category, url)
);

CREATE TABLE IF NOT EXISTS project_faqs (
    faq_id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES project_snapshots(snapshot_id) ON DELETE CASCADE,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    is_synthesized BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (snapshot_id, question)
);

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

-- 5. Decision-Driven Investment Entities
CREATE TABLE IF NOT EXISTS sources (
    source_id VARCHAR(50) PRIMARY KEY,
    source_name VARCHAR(100) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    base_url TEXT,
    rate_limit_delay_seconds NUMERIC(4,2) DEFAULT 2.50,
    compliance_notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS locations (
    location_id BIGSERIAL PRIMARY KEY,
    locality_name TEXT NOT NULL,
    sub_locality TEXT,
    pin_code CHAR(6),
    city TEXT NOT NULL DEFAULT 'Pune',
    district TEXT NOT NULL DEFAULT 'Pune',
    jurisdiction TEXT CHECK (jurisdiction IN ('PMC', 'PCMC', 'PMRDA', 'Cantonment', 'Other')),
    centroid_lat NUMERIC(9,6),
    centroid_lon NUMERIC(9,6),
    dist_hinjawadi_it_km NUMERIC(5,2),
    dist_kharadi_it_km NUMERIC(5,2),
    dist_magarpatta_km NUMERIC(5,2),
    dist_yerwada_it_km NUMERIC(5,2),
    dist_sb_road_km NUMERIC(5,2),
    dist_pune_station_km NUMERIC(5,2),
    dist_airport_km NUMERIC(5,2),
    metro_corridor_served TEXT,
    metro_operational_status TEXT,
    flood_risk_level TEXT CHECK (flood_risk_level IN ('Low', 'Moderate', 'High', 'Severe', 'Unknown')) DEFAULT 'Unknown',
    environmental_notes TEXT,
    UNIQUE (locality_name, sub_locality, pin_code)
);

CREATE TABLE IF NOT EXISTS infrastructure_projects (
    infra_id BIGSERIAL PRIMARY KEY,
    project_name TEXT NOT NULL,
    project_type TEXT NOT NULL,
    corridor_description TEXT,
    planned_completion_date DATE,
    actual_operational_date DATE,
    current_status TEXT NOT NULL,
    impacted_localities JSONB DEFAULT '[]'::jsonb,
    source_evidence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Asking Prices (Listings) Dataset - SEPARATE FROM REGISTERED SALES
CREATE TABLE IF NOT EXISTS property_listings (
    listing_id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(50) NOT NULL REFERENCES sources(source_id),
    source_listing_ref TEXT NOT NULL,
    source_url TEXT,
    project_key TEXT REFERENCES projects(project_key) ON DELETE SET NULL,
    location_id BIGINT REFERENCES locations(location_id) ON DELETE SET NULL,
    locality_name TEXT NOT NULL,
    title TEXT,
    listing_type TEXT NOT NULL CHECK (listing_type IN ('new_developer_sale', 'resale', 'assignment', 'unknown')),
    property_type TEXT DEFAULT 'Apartment',
    bhk_type TEXT,
    carpet_area_sqft NUMERIC(10,2) NOT NULL,
    builtup_area_sqft NUMERIC(10,2),
    floor_number INTEGER,
    total_floors INTEGER,
    asking_price_inr NUMERIC(14,2) NOT NULL,
    asking_price_per_sqft NUMERIC(12,2) GENERATED ALWAYS AS (asking_price_inr / NULLIF(carpet_area_sqft, 0)) STORED,
    maintenance_monthly_inr NUMERIC(10,2),
    furnishing_status TEXT CHECK (furnishing_status IN ('unfurnished', 'semi-furnished', 'fully-furnished', 'unknown')),
    parking_count INTEGER,
    possession_status TEXT CHECK (possession_status IN ('ready_to_move', 'under_construction', 'resale_immediate', 'unknown')),
    first_listed_date DATE,
    delisted_date DATE,
    listing_status TEXT NOT NULL DEFAULT 'active' CHECK (listing_status IN ('active', 'delisted_likely_sold', 'delisted_withdrawn', 'price_reduced')),
    last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_listing_data JSONB DEFAULT '{}'::jsonb,
    UNIQUE (source_id, source_listing_ref)
);

-- Official Registered Transactions (IGR Deeds) - SEPARATE FROM ASKING PRICES
CREATE TABLE IF NOT EXISTS registered_transactions (
    transaction_id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(50) NOT NULL REFERENCES sources(source_id),
    official_document_ref TEXT NOT NULL,
    registration_date DATE NOT NULL,
    agreement_date DATE,
    project_key TEXT REFERENCES projects(project_key) ON DELETE SET NULL,
    location_id BIGINT REFERENCES locations(location_id) ON DELETE SET NULL,
    registration_office TEXT,
    property_address TEXT,
    unit_flat_number TEXT,
    floor_number INTEGER,
    carpet_area_sqft NUMERIC(10,2) NOT NULL,
    declared_consideration_inr NUMERIC(16,2) NOT NULL,
    market_valuation_inr NUMERIC(16,2),
    stamp_duty_paid_inr NUMERIC(14,2),
    registration_fee_paid_inr NUMERIC(14,2),
    price_per_sqft_declared NUMERIC(14,2) GENERATED ALWAYS AS (declared_consideration_inr / NULLIF(carpet_area_sqft, 0)) STORED,
    document_type TEXT NOT NULL DEFAULT 'Conveyance Sale Deed',
    is_arm_length_transaction BOOLEAN DEFAULT TRUE,
    caveats TEXT,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (official_document_ref)
);

CREATE TABLE IF NOT EXISTS rental_observations (
    rental_id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(50) NOT NULL REFERENCES sources(source_id),
    project_key TEXT REFERENCES projects(project_key) ON DELETE SET NULL,
    location_id BIGINT REFERENCES locations(location_id) ON DELETE SET NULL,
    locality_name TEXT NOT NULL,
    bhk_type TEXT NOT NULL,
    carpet_area_sqft NUMERIC(10,2),
    monthly_rent_inr NUMERIC(12,2) NOT NULL,
    security_deposit_inr NUMERIC(12,2),
    maintenance_included BOOLEAN DEFAULT FALSE,
    furnishing_status TEXT,
    preferred_tenant TEXT,
    observed_date DATE NOT NULL DEFAULT CURRENT_DATE,
    observation_source_url TEXT,
    UNIQUE (source_id, locality_name, bhk_type, observed_date, monthly_rent_inr)
);

CREATE TABLE IF NOT EXISTS individual_properties (
    property_id BIGSERIAL PRIMARY KEY,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    building_or_wing TEXT,
    unit_flat_number TEXT,
    configuration_bhk TEXT NOT NULL,
    carpet_area_sqft NUMERIC(10,2) NOT NULL,
    balcony_area_sqft NUMERIC(10,2),
    terrace_area_sqft NUMERIC(10,2),
    floor_number INTEGER,
    total_floors INTEGER,
    facing_direction TEXT CHECK (facing_direction IN ('East', 'West', 'North', 'South', 'North-East', 'North-West', 'South-East', 'South-West', 'Unknown')),
    parking_allotted TEXT,
    verification_source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_key, building_or_wing, unit_flat_number)
);

CREATE TABLE IF NOT EXISTS macroeconomic_indicators (
    metric_id BIGSERIAL PRIMARY KEY,
    effective_date DATE NOT NULL,
    rbi_repo_rate_pct NUMERIC(5,2) NOT NULL,
    sbi_home_loan_eblr_pct NUMERIC(5,2) NOT NULL,
    cpi_inflation_pct NUMERIC(5,2) NOT NULL,
    pune_stamp_duty_rate_pct NUMERIC(5,2) NOT NULL DEFAULT 6.00,
    pune_registration_fee_pct NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    pune_registration_fee_cap_inr NUMERIC(10,2) NOT NULL DEFAULT 30000.00,
    gst_under_construction_standard_pct NUMERIC(5,2) NOT NULL DEFAULT 5.00,
    gst_under_construction_affordable_pct NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    gst_ready_to_move_pct NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    ltcg_tax_rate_post_2024_pct NUMERIC(5,2) NOT NULL DEFAULT 12.50,
    notes TEXT,
    UNIQUE (effective_date)
);

CREATE TABLE IF NOT EXISTS financial_assumptions (
    assumption_id VARCHAR(50) PRIMARY KEY,
    scenario_name VARCHAR(100) NOT NULL,
    down_payment_pct NUMERIC(5,2) NOT NULL DEFAULT 20.00,
    loan_tenure_years INTEGER NOT NULL DEFAULT 20,
    loan_interest_rate_pct NUMERIC(5,2) NOT NULL DEFAULT 8.50,
    brokerage_purchase_pct NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    brokerage_resale_pct NUMERIC(5,2) NOT NULL DEFAULT 2.00,
    legal_due_diligence_inr NUMERIC(10,2) NOT NULL DEFAULT 35000.00,
    vacancy_rate_pct NUMERIC(5,2) NOT NULL DEFAULT 8.33,
    annual_rent_growth_pct NUMERIC(5,2) NOT NULL DEFAULT 5.00,
    annual_appreciation_pct NUMERIC(5,2) NOT NULL DEFAULT 6.00,
    society_maintenance_sqft_pm NUMERIC(6,2) NOT NULL DEFAULT 3.50,
    annual_property_tax_pct NUMERIC(5,2) NOT NULL DEFAULT 0.20,
    discount_rate_wacc_pct NUMERIC(5,2) NOT NULL DEFAULT 9.00,
    opportunity_equity_cagr_pct NUMERIC(5,2) NOT NULL DEFAULT 11.50,
    opportunity_debt_cagr_pct NUMERIC(5,2) NOT NULL DEFAULT 7.00
);

CREATE TABLE IF NOT EXISTS entity_match_candidates (
    match_id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    source_entity_ref TEXT NOT NULL,
    target_entity_ref TEXT NOT NULL,
    match_method TEXT NOT NULL,
    confidence_score NUMERIC(5,4) NOT NULL,
    resolution_status TEXT NOT NULL DEFAULT 'unresolved' CHECK (resolution_status IN ('unresolved', 'verified_match', 'rejected', 'auto_merged')),
    match_evidence JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    UNIQUE (entity_type, source_entity_ref, target_entity_ref)
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    issue_id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(50) NOT NULL REFERENCES sources(source_id),
    entity_key TEXT NOT NULL,
    field_name TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'WARNING', 'INFO')),
    observed_value TEXT,
    expected_rule TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_resolved BOOLEAN NOT NULL DEFAULT FALSE
);

-- =====================================================================
-- ANALYTICAL VIEWS
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
    possession_extension_months,
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
    possession_extension_months,
    months_remaining_to_possession,
    excavation_pct,
    rcc_pct,
    finishing_pct,
    structural_completion_status,
    ready_to_move_status,
    complaint_count
FROM projects
ORDER BY possession_extension_months DESC NULLS LAST, locality;

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
    f.answer,
    f.is_synthesized
FROM project_faqs f
JOIN projects p ON p.project_key = f.project_key
ORDER BY p.project_name, f.topic;

-- 7. H1 Financial Attractiveness & DCF Cash Flows View
CREATE OR REPLACE VIEW v_investment_h1_cashflows AS
WITH base_properties AS (
    SELECT 
        p.project_key,
        p.project_name,
        p.developer,
        p.locality,
        p.pin_code,
        p.construction_stage,
        COALESCE(p.price_per_sqft_80pct, p.headline_price_per_sqft_80pct, 12000.0) AS rate_sqft,
        1000.0 AS sample_carpet_sqft,
        (COALESCE(p.price_per_sqft_80pct, p.headline_price_per_sqft_80pct, 12000.0) * 1000.0) AS purchase_price
    FROM projects p
    WHERE p.price_per_sqft_80pct IS NOT NULL OR p.headline_price_per_sqft_80pct IS NOT NULL
),
acquisition_calc AS (
    SELECT 
        bp.*,
        ROUND(bp.purchase_price * 0.06, 2) AS stamp_duty_inr,
        LEAST(ROUND(bp.purchase_price * 0.01, 2), 30000.00) AS registration_fee_inr,
        ROUND(bp.purchase_price * 0.01, 2) AS acquisition_brokerage_inr,
        35000.00 AS legal_fees_inr,
        CASE 
            WHEN bp.construction_stage = 'Ready to move' THEN 0.00 
            ELSE ROUND(bp.purchase_price * 0.05, 2) 
        END AS gst_inr
    FROM base_properties bp
),
cost_summary AS (
    SELECT 
        ac.*,
        (ac.purchase_price + ac.stamp_duty_inr + ac.registration_fee_inr + ac.acquisition_brokerage_inr + ac.legal_fees_inr + ac.gst_inr) AS total_acquisition_cost,
        ROUND(ac.purchase_price * 0.20, 2) AS down_payment_inr,
        ROUND(ac.purchase_price * 0.80, 2) AS loan_principal_inr
    FROM acquisition_calc ac
),
rental_and_emi AS (
    SELECT 
        cs.*,
        ROUND(cs.down_payment_inr + (cs.total_acquisition_cost - cs.purchase_price), 2) AS initial_equity_invested,
        ROUND(cs.loan_principal_inr * 0.0086782, 2) AS monthly_emi_inr,
        ROUND(cs.loan_principal_inr * 0.0086782 * 12, 2) AS annual_debt_service_inr,
        ROUND(cs.purchase_price * 0.032, 2) AS gross_annual_rent_inr,
        ROUND(cs.purchase_price * 0.032 * 0.0833, 2) AS vacancy_loss_inr,
        ROUND((cs.sample_carpet_sqft * 3.5 * 12) + (cs.purchase_price * 0.002), 2) AS annual_operating_expenses_inr
    FROM cost_summary cs
)
SELECT 
    re.project_key,
    re.project_name,
    re.developer,
    re.locality,
    re.pin_code,
    re.rate_sqft,
    re.sample_carpet_sqft,
    re.purchase_price,
    re.total_acquisition_cost,
    re.initial_equity_invested,
    re.loan_principal_inr,
    re.monthly_emi_inr,
    re.annual_debt_service_inr,
    re.gross_annual_rent_inr,
    (re.gross_annual_rent_inr - re.vacancy_loss_inr - re.annual_operating_expenses_inr) AS net_operating_income_inr,
    ROUND(((re.gross_annual_rent_inr - re.vacancy_loss_inr - re.annual_operating_expenses_inr) / NULLIF(re.total_acquisition_cost, 0)) * 100, 2) AS net_rental_yield_pct,
    ROUND((re.gross_annual_rent_inr - re.vacancy_loss_inr - re.annual_operating_expenses_inr) - re.annual_debt_service_inr, 2) AS annual_cash_flow_after_financing,
    ROUND(re.purchase_price * POWER(1.06, 5), 2) AS projected_value_yr5,
    ROUND(re.loan_principal_inr * 0.885, 2) AS loan_balance_yr5,
    ROUND((re.purchase_price * POWER(1.06, 5) * 0.98) - (re.loan_principal_inr * 0.885), 2) AS net_equity_at_exit_yr5,
    ROUND(re.purchase_price * POWER(1.06, 10), 2) AS projected_value_yr10,
    ROUND(re.loan_principal_inr * 0.705, 2) AS loan_balance_yr10,
    ROUND((re.purchase_price * POWER(1.06, 10) * 0.98) - (re.loan_principal_inr * 0.705), 2) AS net_equity_at_exit_yr10,
    ROUND(re.purchase_price * POWER(1.06, 15), 2) AS projected_value_yr15,
    ROUND(re.loan_principal_inr * 0.425, 2) AS loan_balance_yr15,
    ROUND((re.purchase_price * POWER(1.06, 15) * 0.98) - (re.loan_principal_inr * 0.425), 2) AS net_equity_at_exit_yr15
FROM rental_and_emi re;

-- 8. H2 Locality Rankings View
CREATE OR REPLACE VIEW v_locality_h2_rankings AS
WITH locality_aggregates AS (
    SELECT 
        p.locality,
        COUNT(DISTINCT p.project_key) AS total_projects,
        COUNT(DISTINCT p.rera_number) AS active_rera_registrations,
        ROUND(AVG(p.price_per_sqft_80pct), 2) AS avg_price_sqft_80pct,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p.price_per_sqft_80pct)::numeric, 2) AS median_price_sqft_80pct,
        ROUND(AVG(p.year_over_year_change_pct), 2) AS avg_yoy_price_growth_pct,
        SUM(COALESCE(p.total_units, 0)) AS total_units_in_pipeline,
        SUM(COALESCE(p.units_booked, 0)) AS total_units_booked,
        ROUND(AVG(p.booking_pct), 2) AS avg_booking_pct,
        COUNT(CASE WHEN p.possession_extension_status = 'Extended' OR p.possession_extension_months > 0 THEN 1 END) AS delayed_projects_count,
        ROUND(AVG(COALESCE(p.possession_extension_months, 0)), 1) AS avg_delay_months,
        ROUND(AVG(p.rcc_pct), 1) AS avg_rcc_progress_pct
    FROM projects p
    WHERE p.locality IS NOT NULL
    GROUP BY p.locality
    HAVING COUNT(p.project_key) >= 1
)
SELECT 
    la.locality,
    la.total_projects,
    la.median_price_sqft_80pct,
    la.avg_yoy_price_growth_pct,
    ROUND((CASE 
        WHEN la.median_price_sqft_80pct > 18000 THEN 2.80
        WHEN la.median_price_sqft_80pct BETWEEN 12000 AND 18000 THEN 3.20
        ELSE 3.80 
    END), 2) AS estimated_gross_rental_yield_pct,
    la.total_units_in_pipeline,
    la.avg_booking_pct,
    ROUND((la.delayed_projects_count::numeric / NULLIF(la.total_projects, 0)) * 100, 1) AS delay_incidence_pct,
    la.avg_delay_months,
    la.avg_rcc_progress_pct,
    ROUND(
        (COALESCE(la.avg_yoy_price_growth_pct, 5.0) * 0.30) +
        ((CASE WHEN la.median_price_sqft_80pct > 18000 THEN 2.80 WHEN la.median_price_sqft_80pct BETWEEN 12000 AND 18000 THEN 3.20 ELSE 3.80 END) * 5.0 * 0.25) +
        (COALESCE(la.avg_booking_pct, 50.0) * 0.10 * 0.25) -
        ((la.delayed_projects_count::numeric / NULLIF(la.total_projects, 0) * 100) * 0.10 * 0.20),
        2
    ) AS locality_investment_attractiveness_score
FROM locality_aggregates la
ORDER BY locality_investment_attractiveness_score DESC;

-- 9. H3 Project Value Scores View
CREATE OR REPLACE VIEW v_project_h3_value_scores AS
WITH locality_benchmarks AS (
    SELECT 
        locality,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_per_sqft_80pct)::numeric AS locality_median_rate
    FROM projects
    WHERE price_per_sqft_80pct IS NOT NULL AND locality IS NOT NULL
    GROUP BY locality
)
SELECT 
    p.project_key,
    p.rera_number,
    p.project_name,
    p.phase_name,
    p.developer,
    p.locality,
    p.pin_code,
    p.construction_stage,
    p.price_per_sqft_80pct AS subject_rate_sqft,
    lb.locality_median_rate,
    ROUND(((p.price_per_sqft_80pct - lb.locality_median_rate) / NULLIF(lb.locality_median_rate, 0)) * 100, 2) AS price_diff_vs_locality_pct,
    p.rcc_pct,
    p.finishing_pct,
    p.possession_date_text,
    p.possession_extension_status,
    COALESCE(p.possession_extension_months, 0) AS delay_months,
    p.booking_pct,
    p.complaint_count,
    CASE 
        WHEN p.price_per_sqft_80pct < (lb.locality_median_rate * 0.92) 
             AND (p.possession_extension_months IS NULL OR p.possession_extension_months <= 6)
             AND (p.rcc_pct IS NULL OR p.rcc_pct >= 60.0) THEN 'Attractive Value Opportunity'
        WHEN p.price_per_sqft_80pct > (lb.locality_median_rate * 1.15) THEN 'Premium Overpriced'
        WHEN p.possession_extension_months > 12 THEN 'High Construction Delay Risk'
        ELSE 'Fairly Priced'
    END AS value_investment_category
FROM projects p
LEFT JOIN locality_benchmarks lb ON p.locality = lb.locality
ORDER BY price_diff_vs_locality_pct ASC NULLS LAST;

-- 10. H4 Hedonic Modeling Dataset View
CREATE OR REPLACE VIEW v_hedonic_h4_dataset AS
SELECT 
    p.project_key,
    p.rera_number,
    p.project_name,
    p.locality,
    p.pin_code,
    loc.centroid_lat,
    loc.centroid_lon,
    loc.dist_hinjawadi_it_km,
    loc.dist_kharadi_it_km,
    loc.dist_magarpatta_km,
    loc.dist_pune_station_km,
    loc.metro_corridor_served,
    p.construction_stage,
    p.building_count,
    p.land_acres,
    p.rcc_pct,
    p.finishing_pct,
    p.total_units,
    p.booking_pct,
    p.units_1bhk,
    p.units_2bhk,
    p.units_3bhk,
    p.units_4bhk,
    ys.sales_year AS observation_year,
    ys.year_label,
    ys.price_per_sqft_80pct AS target_rate_sqft_80pct,
    ROUND(LN(NULLIF(ys.price_per_sqft_80pct, 0)), 4) AS ln_target_rate_sqft,
    ys.sale_count AS sample_transaction_count,
    s.observed_at AS snapshot_timestamp,
    s.parser_version
FROM project_sale_year_stats ys
JOIN project_snapshots s ON s.snapshot_id = ys.snapshot_id
JOIN projects p ON p.project_key = ys.project_key
LEFT JOIN locations loc ON p.locality = loc.locality_name;
