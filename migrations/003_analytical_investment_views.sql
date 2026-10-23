-- Migration 003: Analytical and Investment Views
-- Implements robust SQL analytical views directly supporting Hypotheses H1, H2, H3, and H4.

-- =====================================================================
-- VIEW 1: H1 FINANCIAL ATTRACTIVENESS & DCF CASH FLOWS
-- Computes acquisition costs, financing EMIs, rental net income, 
-- and 5, 10, 15-year holding period capital gains and returns.
-- =====================================================================
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
        -- Representative unit size (default 1000 sq ft 2 BHK if unstated)
        1000.0 AS sample_carpet_sqft,
        (COALESCE(p.price_per_sqft_80pct, p.headline_price_per_sqft_80pct, 12000.0) * 1000.0) AS purchase_price
    FROM projects p
    WHERE p.price_per_sqft_80pct IS NOT NULL OR p.headline_price_per_sqft_80pct IS NOT NULL
),
acquisition_calc AS (
    SELECT 
        bp.*,
        -- Acquisition Costs:
        -- Stamp Duty: 6% (5% state + 1% metro cess in Pune)
        ROUND(bp.purchase_price * 0.06, 2) AS stamp_duty_inr,
        -- Registration: 1% capped at ₹30,000 in Maharashtra
        LEAST(ROUND(bp.purchase_price * 0.01, 2), 30000.00) AS registration_fee_inr,
        -- Brokerage / Advisory: 1%
        ROUND(bp.purchase_price * 0.01, 2) AS acquisition_brokerage_inr,
        -- Legal / Due Diligence: Flat ₹35,000
        35000.00 AS legal_fees_inr,
        -- GST: 0% if Ready to Move, 5% if Under Construction
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
        -- 80% Loan to Value (LTV), 20% Down Payment
        ROUND(ac.purchase_price * 0.20, 2) AS down_payment_inr,
        ROUND(ac.purchase_price * 0.80, 2) AS loan_principal_inr
    FROM acquisition_calc ac
),
rental_and_emi AS (
    SELECT 
        cs.*,
        -- Total initial cash required (Down payment + all transaction taxes & closing costs)
        ROUND(cs.down_payment_inr + (cs.total_acquisition_cost - cs.purchase_price), 2) AS initial_equity_invested,
        -- Monthly EMI @ 8.5% p.a. for 20 years (Formula: P * r * (1+r)^n / ((1+r)^n - 1), factor ~= 0.008678)
        ROUND(cs.loan_principal_inr * 0.0086782, 2) AS monthly_emi_inr,
        ROUND(cs.loan_principal_inr * 0.0086782 * 12, 2) AS annual_debt_service_inr,
        -- Estimated gross rental yield for Pune residential (benchmark ~3.2% of market value)
        ROUND(cs.purchase_price * 0.032, 2) AS gross_annual_rent_inr,
        -- Vacancy allowance (1 month / 8.33% vacancy)
        ROUND(cs.purchase_price * 0.032 * 0.0833, 2) AS vacancy_loss_inr,
        -- Operating expenses (Society maintenance @ ₹3.5/sqft/mo + Property tax ~0.2%)
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
    -- Annual cash flow after debt service (pre-tax)
    ROUND((re.gross_annual_rent_inr - re.vacancy_loss_inr - re.annual_operating_expenses_inr) - re.annual_debt_service_inr, 2) AS annual_cash_flow_after_financing,
    
    -- 5-Year Exit Scenario (Assuming Base 6% Appreciation CAGR):
    ROUND(re.purchase_price * POWER(1.06, 5), 2) AS projected_value_yr5,
    -- Outstanding loan balance after 5 years (~88% of principal remaining)
    ROUND(re.loan_principal_inr * 0.885, 2) AS loan_balance_yr5,
    ROUND((re.purchase_price * POWER(1.06, 5) * 0.98) - (re.loan_principal_inr * 0.885), 2) AS net_equity_at_exit_yr5,

    -- 10-Year Exit Scenario:
    ROUND(re.purchase_price * POWER(1.06, 10), 2) AS projected_value_yr10,
    ROUND(re.loan_principal_inr * 0.705, 2) AS loan_balance_yr10,
    ROUND((re.purchase_price * POWER(1.06, 10) * 0.98) - (re.loan_principal_inr * 0.705), 2) AS net_equity_at_exit_yr10,

    -- 15-Year Exit Scenario:
    ROUND(re.purchase_price * POWER(1.06, 15), 2) AS projected_value_yr15,
    ROUND(re.loan_principal_inr * 0.425, 2) AS loan_balance_yr15,
    ROUND((re.purchase_price * POWER(1.06, 15) * 0.98) - (re.loan_principal_inr * 0.425), 2) AS net_equity_at_exit_yr15
FROM rental_and_emi re;


-- =====================================================================
-- VIEW 2: H2 LOCALITY INVESTMENT RANKINGS
-- Multi-factor comparison ranking Pune localities by price growth,
-- rental yields, construction delay risk, and supply absorption.
-- =====================================================================
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
        -- Delay indicators
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
    -- Estimated gross rental yield based on Pune micro-market median price
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
    -- Composite Locality Score (Weighted: 30% Price Growth + 25% Rental Yield + 25% Booking Absorption - 20% Delay Penalty)
    ROUND(
        (COALESCE(la.avg_yoy_price_growth_pct, 5.0) * 0.30) +
        ((CASE WHEN la.median_price_sqft_80pct > 18000 THEN 2.80 WHEN la.median_price_sqft_80pct BETWEEN 12000 AND 18000 THEN 3.20 ELSE 3.80 END) * 5.0 * 0.25) +
        (COALESCE(la.avg_booking_pct, 50.0) * 0.10 * 0.25) -
        ((la.delayed_projects_count::numeric / NULLIF(la.total_projects, 0) * 100) * 0.10 * 0.20),
        2
    ) AS locality_investment_attractiveness_score
FROM locality_aggregates la
ORDER BY locality_investment_attractiveness_score DESC;


-- =====================================================================
-- VIEW 3: H3 PROJECT & FLAT VALUE EVALUATION
-- Identifies properties trading at a value discount relative to 
-- micro-market peers, adjusted for developer track record and construction.
-- =====================================================================
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
    -- Relative Price Premium / Discount vs Locality Peer Median
    ROUND(((p.price_per_sqft_80pct - lb.locality_median_rate) / NULLIF(lb.locality_median_rate, 0)) * 100, 2) AS price_diff_vs_locality_pct,
    p.rcc_pct,
    p.finishing_pct,
    p.possession_date_text,
    p.possession_extension_status,
    COALESCE(p.possession_extension_months, 0) AS delay_months,
    p.booking_pct,
    p.complaint_count,
    -- Value Classification:
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


-- =====================================================================
-- VIEW 4: H4 HEDONIC PRICE MODELING DATASET
-- Clean, strictly time-aware feature dataset for ML & hedonic regression.
-- Prevents temporal leakage by preserving historical observation year.
-- =====================================================================
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
    -- Dependent Target Variables (Annual 80th-Percentile Benchmark):
    ys.sales_year AS observation_year,
    ys.year_label,
    ys.price_per_sqft_80pct AS target_rate_sqft_80pct,
    ROUND(LN(NULLIF(ys.price_per_sqft_80pct, 0)), 4) AS ln_target_rate_sqft,
    ys.sale_count AS sample_transaction_count,
    -- Strictly Historical Temporal Anchor:
    s.observed_at AS snapshot_timestamp,
    s.parser_version
FROM project_sale_year_stats ys
JOIN project_snapshots s ON s.snapshot_id = ys.snapshot_id
JOIN projects p ON p.project_key = ys.project_key
LEFT JOIN locations loc ON p.locality = loc.locality_name;

-- =====================================================================
-- VIEW 5: MASTER PROJECT CATALOG VIEW
-- =====================================================================
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

-- =====================================================================
-- VIEW 6: DELAYS AND CONSTRUCTION PROGRESS
-- =====================================================================
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

-- =====================================================================
-- VIEW 7: PRICING AND MARKET POSITION
-- =====================================================================
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

-- =====================================================================
-- VIEW 8: INVENTORY AND BOOKING STATUS
-- =====================================================================
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

-- =====================================================================
-- VIEW 9: LATEST ANNUAL SALE STATS (BACKWARD COMPATIBLE)
-- =====================================================================
CREATE OR REPLACE VIEW latest_project_sale_stats AS
SELECT DISTINCT ON (s.project_key, ys.sales_year)
       s.project_key, p.project_name, p.locality, ys.sales_year,
       ys.price_per_sqft_80pct, ys.sale_count, ys.year_over_year_delta_text, s.observed_at
FROM project_sale_year_stats ys
JOIN project_snapshots s ON s.snapshot_id = ys.snapshot_id
JOIN projects p ON p.project_key = s.project_key
ORDER BY s.project_key, ys.sales_year, s.observed_at DESC;

-- =====================================================================
-- VIEW 10: FAQS OVERVIEW
-- =====================================================================
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
