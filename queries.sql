-- Useful queries for analyzing FlatNama PostgreSQL data

-- 1. Master project overview with location, timeline, and pricing
SELECT 
    project_name,
    rera_number,
    developer,
    locality,
    pin_code,
    construction_stage,
    launch_date_text,
    possession_date_text,
    possession_delay_months,
    rcc_pct,
    total_units,
    units_booked,
    booking_pct,
    latest_sale_year,
    price_per_sqft_80pct,
    latest_sale_count,
    rate_vs_nearby_projects_pct,
    project_url
FROM v_projects_master
ORDER BY locality NULLS LAST, project_name;

-- 2. Projects with possession delays and extended timelines
SELECT 
    project_name,
    locality,
    rera_number,
    launch_date_text,
    original_possession_date_text,
    possession_date_text,
    possession_delay_months,
    months_remaining_to_possession,
    rcc_pct,
    finishing_pct,
    construction_stage,
    complaint_count
FROM v_project_delays_and_progress
WHERE possession_delay_months > 0 OR possession_extension_status = 'Extended'
ORDER BY possession_delay_months DESC NULLS LAST;

-- 3. Price analysis: annual rate, YoY change, and nearby comparisons
SELECT 
    project_name,
    locality,
    latest_sale_year,
    rate_per_sqft_80pct,
    latest_sale_count,
    year_over_year_change_pct,
    year_over_year_direction,
    rate_vs_nearby_projects_pct,
    price_area_basis
FROM v_project_pricing_summary
ORDER BY rate_per_sqft_80pct DESC;

-- 4. Inventory and unit mix breakdown across projects
SELECT 
    project_name,
    locality,
    total_units,
    units_booked,
    booking_pct,
    units_1rk,
    units_1bhk,
    units_2bhk,
    units_3bhk,
    units_4bhk,
    units_5bhk_plus
FROM v_project_inventory_summary
WHERE total_units > 0
ORDER BY units_booked DESC;

-- 5. Similar project benchmark comparison
SELECT 
    p.project_name,
    p.locality,
    b.measure,
    b.this_project,
    b.similar_projects
FROM project_comparison_benchmarks b
JOIN projects p ON p.project_key = b.project_key
ORDER BY p.project_name, b.measure;

-- 6. Project FAQs and explanations
SELECT 
    project_name,
    topic,
    question,
    answer
FROM v_project_faqs_overview;

-- 7. Data quality and extraction audit scores
SELECT 
    p.project_name,
    p.rera_number,
    q.fields_present,
    q.fields_checked,
    q.completeness_pct,
    q.warnings
FROM project_quality_audits q
JOIN projects p ON p.project_key = q.project_key
ORDER BY q.completeness_pct ASC;

-- 8. Discovered projects coverage summary from area pages
SELECT 
    source_area_url,
    discovery_method,
    count(*) AS total_discovered,
    count(CASE WHEN selected_for_fetch THEN 1 END) AS selected,
    count(CASE WHEN fetch_status = 'parsed' THEN 1 END) AS parsed_ok,
    count(CASE WHEN fetch_status = 'error' THEN 1 END) AS errors
FROM discovered_project_urls
GROUP BY source_area_url, discovery_method;
