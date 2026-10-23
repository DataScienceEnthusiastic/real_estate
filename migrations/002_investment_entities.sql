-- Migration 002: Decision-Driven Real Estate Entities
-- Adds normalized locations, infrastructure tracking, asking price listings,
-- official registered transactions, rental observations, individual flat units,
-- macroeconomic indicators, financial assumptions, entity matching, and data quality issues.

-- 1. Sources Catalog
CREATE TABLE IF NOT EXISTS sources (
    source_id VARCHAR(50) PRIMARY KEY,
    source_name VARCHAR(100) NOT NULL,
    source_type VARCHAR(50) NOT NULL, -- 'aggregator', 'official_rera', 'official_igr', 'listing_portal', 'macro_rbi', 'gis'
    base_url TEXT,
    rate_limit_delay_seconds NUMERIC(4,2) DEFAULT 2.50,
    compliance_notes TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO sources (source_id, source_name, source_type, base_url, compliance_notes) VALUES
('flatnama', 'FlatNama', 'aggregator', 'https://flatnama.com', 'Aggregated MahaRERA and registered sale summaries; 80th-percentile price benchmark.')
ON CONFLICT (source_id) DO NOTHING;

INSERT INTO sources (source_id, source_name, source_type, base_url, compliance_notes) VALUES
('maharera', 'MahaRERA Official Portal', 'official_rera', 'https://maharera.mahaonline.gov.in', 'Official statutory regulatory filings and project progress updates.')
ON CONFLICT (source_id) DO NOTHING;

INSERT INTO sources (source_id, source_name, source_type, base_url, compliance_notes) VALUES
('igr_maharashtra', 'Inspector General of Registration Maharashtra', 'official_igr', 'https://igrmaharashtra.gov.in', 'Official registered property sale deed records.')
ON CONFLICT (source_id) DO NOTHING;

-- 2. Normalized Locality & Geographic Context
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
    
    -- Distances to Key Economic Nodes (Calculated via GIS / OSRM)
    dist_hinjawadi_it_km NUMERIC(5,2),      -- Hinjawadi Rajiv Gandhi Infotech Park
    dist_kharadi_it_km NUMERIC(5,2),        -- EON Free Zone / Kharadi IT Cluster
    dist_magarpatta_km NUMERIC(5,2),        -- Magarpatta Cybercity
    dist_yerwada_it_km NUMERIC(5,2),        -- Commerzone / Yerwada
    dist_sb_road_km NUMERIC(5,2),           -- Senapati Bapat Road / Central Core
    dist_pune_station_km NUMERIC(5,2),      -- Pune Railway Station
    dist_airport_km NUMERIC(5,2),           -- Pune International Airport (Lohegaon)
    
    -- Infrastructure Availability
    metro_corridor_served TEXT,             -- e.g. 'Line 1 (Purple)', 'Line 2 (Aqua)', 'Line 3 (Hinjawadi-Shivajinagar)'
    metro_operational_status TEXT,          -- 'operational', 'under_construction', 'planned', 'none'
    flood_risk_level TEXT CHECK (flood_risk_level IN ('Low', 'Moderate', 'High', 'Severe', 'Unknown')) DEFAULT 'Unknown',
    environmental_notes TEXT,
    UNIQUE (locality_name, sub_locality, pin_code)
);
CREATE INDEX IF NOT EXISTS ix_locations_locality ON locations (locality_name);
CREATE INDEX IF NOT EXISTS ix_locations_pin ON locations (pin_code);

-- 3. Infrastructure Projects (Tracking Planned vs Actual Opening to Prevent Temporal Leakage)
CREATE TABLE IF NOT EXISTS infrastructure_projects (
    infra_id BIGSERIAL PRIMARY KEY,
    project_name TEXT NOT NULL,
    project_type TEXT NOT NULL,             -- 'metro', 'ring_road', 'flyover', 'airport', 'it_park'
    corridor_description TEXT,
    planned_completion_date DATE,
    actual_operational_date DATE,           -- Strict temporal anchor: models cannot assume operational before this date!
    current_status TEXT NOT NULL,           -- 'planned', 'under_construction', 'partially_operational', 'operational', 'delayed'
    impacted_localities JSONB DEFAULT '[]'::jsonb,
    source_evidence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed Known Pune Infrastructure Projects with Verified Operational Dates
INSERT INTO infrastructure_projects (project_name, project_type, planned_completion_date, actual_operational_date, current_status, impacted_localities) VALUES
('Pune Metro Line 1 (PCMC to Swargate - Purple)', 'metro', '2021-12-31', '2024-09-29', 'operational', '["PCMC", "Bhosari", "Khadki", "Shivajinagar", "Civil Court", "Swargate"]'::jsonb),
('Pune Metro Line 2 (Vanaz to Ramwadi - Aqua)', 'metro', '2022-06-30', '2024-03-06', 'operational', '["Kothrud", "Erandwane", "Deccan Gymkhana", "Pune Station", "Kalyani Nagar", "Yerwada", "Ramwadi"]'::jsonb),
('Pune Metro Line 3 (Hinjawadi to Shivajinagar)', 'metro', '2023-03-31', NULL, 'under_construction', '["Hinjawadi", "Wakad", "Balewadi", "Baner", "Aundh", "Shivajinagar"]'::jsonb),
('Chandani Chowk Multi-Level Flyover', 'flyover', '2021-08-31', '2023-08-12', 'operational', '["Kothrud", "Bavdhan", "Warje", "Pirangut"]'::jsonb)
ON CONFLICT DO NOTHING;

-- 4. Asking Prices Dataset (Listing Portals) - SEPARATE FROM REGISTERED TRANSACTIONS
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
    bhk_type TEXT,                          -- '1 BHK', '2 BHK', etc.
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
CREATE INDEX IF NOT EXISTS ix_property_listings_locality ON property_listings (locality_name);
CREATE INDEX IF NOT EXISTS ix_property_listings_project ON property_listings (project_key);
CREATE INDEX IF NOT EXISTS ix_property_listings_bhk ON property_listings (bhk_type);

-- 5. Registered Transactions Dataset (Official IGR Sale Deeds) - SEPARATE FROM ASKING PRICES
CREATE TABLE IF NOT EXISTS registered_transactions (
    transaction_id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(50) NOT NULL REFERENCES sources(source_id),
    official_document_ref TEXT NOT NULL,    -- SRO / Document Year / Document Number
    registration_date DATE NOT NULL,
    agreement_date DATE,
    project_key TEXT REFERENCES projects(project_key) ON DELETE SET NULL,
    location_id BIGINT REFERENCES locations(location_id) ON DELETE SET NULL,
    registration_office TEXT,               -- Sub-Registrar Office (e.g. Haveli 1-25)
    property_address TEXT,
    unit_flat_number TEXT,                  -- Kept strictly where legally accessible
    floor_number INTEGER,
    carpet_area_sqft NUMERIC(10,2) NOT NULL,
    declared_consideration_inr NUMERIC(16,2) NOT NULL, -- Actual declared deed sale price
    market_valuation_inr NUMERIC(16,2),     -- Ready Reckoner / Circle rate valuation
    stamp_duty_paid_inr NUMERIC(14,2),
    registration_fee_paid_inr NUMERIC(14,2),
    price_per_sqft_declared NUMERIC(14,2) GENERATED ALWAYS AS (declared_consideration_inr / NULLIF(carpet_area_sqft, 0)) STORED,
    document_type TEXT NOT NULL DEFAULT 'Conveyance Sale Deed',
    is_arm_length_transaction BOOLEAN DEFAULT TRUE,
    caveats TEXT,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (official_document_ref)
);
CREATE INDEX IF NOT EXISTS ix_reg_tx_date ON registered_transactions (registration_date);
CREATE INDEX IF NOT EXISTS ix_reg_tx_project ON registered_transactions (project_key);
CREATE INDEX IF NOT EXISTS ix_reg_tx_location ON registered_transactions (location_id);

-- 6. Rental Market Observations (For Accurate Yield Modeling)
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
    preferred_tenant TEXT,                 -- 'family', 'bachelors', 'company_lease', 'any'
    observed_date DATE NOT NULL DEFAULT CURRENT_DATE,
    observation_source_url TEXT,
    UNIQUE (source_id, locality_name, bhk_type, observed_date, monthly_rent_inr)
);
CREATE INDEX IF NOT EXISTS ix_rentals_locality ON rental_observations (locality_name, bhk_type);

-- 7. Individual Flat Physical Entities (For Granular Hedonic Models)
CREATE TABLE IF NOT EXISTS individual_properties (
    property_id BIGSERIAL PRIMARY KEY,
    project_key TEXT NOT NULL REFERENCES projects(project_key) ON DELETE CASCADE,
    building_or_wing TEXT,
    unit_flat_number TEXT,
    configuration_bhk TEXT NOT NULL,        -- '1 RK', '1 BHK', '2 BHK', etc.
    carpet_area_sqft NUMERIC(10,2) NOT NULL,
    balcony_area_sqft NUMERIC(10,2),
    terrace_area_sqft NUMERIC(10,2),
    floor_number INTEGER,
    total_floors INTEGER,
    facing_direction TEXT CHECK (facing_direction IN ('East', 'West', 'North', 'South', 'North-East', 'North-West', 'South-East', 'South-West', 'Unknown')),
    parking_allotted TEXT,                  -- 'covered', 'open', 'stilt', 'none'
    verification_source TEXT,               -- 'maharera_unit_plan', 'registered_deed', 'inspection'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_key, building_or_wing, unit_flat_number)
);

-- 8. Macroeconomic & Regulatory Assumptions
CREATE TABLE IF NOT EXISTS macroeconomic_indicators (
    metric_id BIGSERIAL PRIMARY KEY,
    effective_date DATE NOT NULL,
    rbi_repo_rate_pct NUMERIC(5,2) NOT NULL,
    sbi_home_loan_eblr_pct NUMERIC(5,2) NOT NULL,
    cpi_inflation_pct NUMERIC(5,2) NOT NULL,
    pune_stamp_duty_rate_pct NUMERIC(5,2) NOT NULL DEFAULT 6.00,  -- 5% state + 1% metro cess
    pune_registration_fee_pct NUMERIC(5,2) NOT NULL DEFAULT 1.00, -- 1% capped at ₹30,000
    pune_registration_fee_cap_inr NUMERIC(10,2) NOT NULL DEFAULT 30000.00,
    gst_under_construction_standard_pct NUMERIC(5,2) NOT NULL DEFAULT 5.00,
    gst_under_construction_affordable_pct NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    gst_ready_to_move_pct NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    ltcg_tax_rate_post_2024_pct NUMERIC(5,2) NOT NULL DEFAULT 12.50, -- Finance Act 2024
    notes TEXT,
    UNIQUE (effective_date)
);

INSERT INTO macroeconomic_indicators (effective_date, rbi_repo_rate_pct, sbi_home_loan_eblr_pct, cpi_inflation_pct, notes) VALUES
('2024-01-01', 6.50, 8.50, 5.10, 'RBI Pause at 6.50%; SBI EBLR at 8.50%; Budget 2024 LTCG at 12.5%')
ON CONFLICT DO NOTHING;

-- 9. Parameterized Financial Assumptions Templates
CREATE TABLE IF NOT EXISTS financial_assumptions (
    assumption_id VARCHAR(50) PRIMARY KEY,
    scenario_name VARCHAR(100) NOT NULL,    -- 'Base Case', 'Bear Case Conservative', 'Bull Case Aggressive'
    down_payment_pct NUMERIC(5,2) NOT NULL DEFAULT 20.00,
    loan_tenure_years INTEGER NOT NULL DEFAULT 20,
    loan_interest_rate_pct NUMERIC(5,2) NOT NULL DEFAULT 8.50,
    brokerage_purchase_pct NUMERIC(5,2) NOT NULL DEFAULT 1.00,
    brokerage_resale_pct NUMERIC(5,2) NOT NULL DEFAULT 2.00,
    legal_due_diligence_inr NUMERIC(10,2) NOT NULL DEFAULT 35000.00,
    vacancy_rate_pct NUMERIC(5,2) NOT NULL DEFAULT 8.33,          -- 1 month vacant per year
    annual_rent_growth_pct NUMERIC(5,2) NOT NULL DEFAULT 5.00,
    annual_appreciation_pct NUMERIC(5,2) NOT NULL DEFAULT 6.00,
    society_maintenance_sqft_pm NUMERIC(6,2) NOT NULL DEFAULT 3.50,
    annual_property_tax_pct NUMERIC(5,2) NOT NULL DEFAULT 0.20,
    discount_rate_wacc_pct NUMERIC(5,2) NOT NULL DEFAULT 9.00,
    opportunity_equity_cagr_pct NUMERIC(5,2) NOT NULL DEFAULT 11.50, -- Nifty 50 Index benchmark
    opportunity_debt_cagr_pct NUMERIC(5,2) NOT NULL DEFAULT 7.00     -- Fixed Deposit benchmark
);

INSERT INTO financial_assumptions (assumption_id, scenario_name, annual_appreciation_pct, annual_rent_growth_pct, vacancy_rate_pct, loan_interest_rate_pct) VALUES
('base_case', 'Base Case (Moderate)', 6.00, 5.00, 8.33, 8.50),
('bear_case', 'Bear Case (Conservative Stagnation)', 3.00, 2.50, 16.67, 9.50),
('bull_case', 'Bull Case (High Growth Corridor)', 9.00, 7.00, 4.00, 8.00)
ON CONFLICT (assumption_id) DO NOTHING;

-- 10. Entity Resolution & Deduplication Candidates
CREATE TABLE IF NOT EXISTS entity_match_candidates (
    match_id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,              -- 'project_to_listing', 'project_to_transaction', 'project_phase_to_parent'
    source_entity_ref TEXT NOT NULL,
    target_entity_ref TEXT NOT NULL,
    match_method TEXT NOT NULL,             -- 'exact_rera_id', 'exact_name_locality', 'fuzzy_token_similarity', 'gis_proximity'
    confidence_score NUMERIC(5,4) NOT NULL, -- 0.0000 to 1.0000
    resolution_status TEXT NOT NULL DEFAULT 'unresolved' CHECK (resolution_status IN ('unresolved', 'verified_match', 'rejected', 'auto_merged')),
    match_evidence JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    UNIQUE (entity_type, source_entity_ref, target_entity_ref)
);
CREATE INDEX IF NOT EXISTS ix_match_candidates_status ON entity_match_candidates (resolution_status, confidence_score DESC);

-- 11. Granular Data Quality Issues Table
CREATE TABLE IF NOT EXISTS data_quality_issues (
    issue_id BIGSERIAL PRIMARY KEY,
    source_id VARCHAR(50) NOT NULL REFERENCES sources(source_id),
    entity_key TEXT NOT NULL,
    field_name TEXT NOT NULL,
    issue_type TEXT NOT NULL,               -- 'range_violation', 'chronology_error', 'unsupported_inferred_value', 'missing_critical_key'
    severity TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'WARNING', 'INFO')),
    observed_value TEXT,
    expected_rule TEXT NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_resolved BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_dq_issues_severity ON data_quality_issues (severity, is_resolved);
