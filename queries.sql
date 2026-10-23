-- Analytical SQL Queries for Real Estate Investment Intelligence Platform
-- Addressing Business & Investment Hypotheses H1, H2, H3, and H4.

-- =====================================================================
-- 1. HYPOTHESIS H1: Financial Attractiveness & Holding Period DCF Analysis
-- Evaluates acquisition cost, debt service, net yields, exit equity, and Nifty 50 comparison.
-- =====================================================================
SELECT 
    project_name,
    locality,
    rate_sqft,
    purchase_price,
    total_acquisition_cost,
    initial_equity_invested,
    monthly_emi_inr,
    net_operating_income_inr,
    net_rental_yield_pct,
    annual_cash_flow_after_financing,
    projected_value_yr5,
    net_equity_at_exit_yr5,
    projected_value_yr10,
    net_equity_at_exit_yr10,
    projected_value_yr15,
    net_equity_at_exit_yr15
FROM v_investment_h1_cashflows
ORDER BY net_rental_yield_pct DESC;


-- =====================================================================
-- 2. HYPOTHESIS H2: Locality Investment Opportunity Rankings
-- Multi-factor scoring incorporating price growth, rental yields, delay risk, and absorption.
-- =====================================================================
SELECT 
    locality,
    total_projects,
    median_price_sqft_80pct,
    avg_yoy_price_growth_pct,
    estimated_gross_rental_yield_pct,
    total_units_in_pipeline,
    avg_booking_pct,
    delay_incidence_pct,
    avg_delay_months,
    avg_rcc_progress_pct,
    locality_investment_attractiveness_score
FROM v_locality_h2_rankings
ORDER BY locality_investment_attractiveness_score DESC;


-- =====================================================================
-- 3. HYPOTHESIS H3: Project & Flat Value Opportunity Identification
-- Identifies properties trading at a value discount vs peers with low delay and high progress.
-- =====================================================================
SELECT 
    project_name,
    locality,
    subject_rate_sqft,
    locality_median_rate,
    price_diff_vs_locality_pct,
    rcc_pct,
    possession_extension_status,
    delay_months,
    booking_pct,
    value_investment_category
FROM v_project_h3_value_scores
ORDER BY price_diff_vs_locality_pct ASC;


-- =====================================================================
-- 4. HYPOTHESIS H4: Hedonic Price Modeling Dataset (Strictly Time-Aware)
-- Clean feature matrix with spatial distance metrics and observation years to prevent leakage.
-- =====================================================================
SELECT 
    project_name,
    locality,
    observation_year,
    target_rate_sqft_80pct,
    ln_target_rate_sqft,
    sample_transaction_count,
    dist_hinjawadi_it_km,
    dist_kharadi_it_km,
    dist_magarpatta_km,
    metro_corridor_served,
    construction_stage,
    rcc_pct,
    booking_pct,
    snapshot_timestamp
FROM v_hedonic_h4_dataset
ORDER BY locality, observation_year DESC;


-- =====================================================================
-- 5. Construction Risk: Projects with Extended Possession Timelines
-- =====================================================================
SELECT 
    project_name,
    locality,
    rera_number,
    launch_date_text,
    original_possession_date_text,
    possession_date_text,
    possession_extension_status,
    possession_extension_months,
    months_remaining_to_possession,
    rcc_pct,
    finishing_pct,
    construction_stage,
    complaint_count
FROM v_project_delays_and_progress
WHERE possession_extension_months > 0 OR possession_extension_status = 'Extended'
ORDER BY possession_extension_months DESC NULLS LAST;


-- =====================================================================
-- 6. Inventory Absorption: Bookings Velocity and Available Pipeline
-- =====================================================================
SELECT 
    project_name,
    locality,
    total_units,
    units_booked,
    units_for_sale,
    booking_pct,
    units_1rk,
    units_1bhk,
    units_2bhk,
    units_3bhk,
    units_4bhk,
    units_5bhk_plus
FROM v_project_inventory_summary
WHERE total_units > 0
ORDER BY total_units DESC;


-- =====================================================================
-- 7. Time-Series Milestones: Progress Update Deltas
-- =====================================================================
SELECT 
    project_key,
    update_label,
    rcc_pct,
    rcc_change,
    finishing_pct,
    finishing_change,
    units_booked,
    booking_change
FROM project_progress_updates
ORDER BY project_key, update_label DESC;


-- =====================================================================
-- 8. Data Quality Audits & Provenance Tracking
-- =====================================================================
SELECT 
    p.project_name,
    p.rera_number,
    q.parser_version,
    q.fields_present,
    q.fields_checked,
    q.completeness_pct,
    q.warnings
FROM project_quality_audits q
JOIN projects p ON p.project_key = q.project_key
ORDER BY q.completeness_pct ASC;
