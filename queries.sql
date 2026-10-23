-- 1. Latest project records
SELECT project_name, rera_number, developer, locality, pin_code,
       launch_date_text, possession_date_text, construction_stage,
       total_units, units_booked, booking_pct, rcc_pct,
       latest_sale_year, price_per_sqft_80pct, latest_sale_count,
       project_url
FROM projects
ORDER BY locality NULLS LAST, project_name;

-- 2. Price summary history (these are summaries, not individual transactions)
SELECT p.project_name, p.locality, ys.sales_year, ys.year_label,
       ys.price_per_sqft_80pct, ys.sale_count, s.observed_at
FROM project_sale_year_stats ys
JOIN project_snapshots s USING (snapshot_id)
JOIN projects p USING (project_key)
ORDER BY p.locality, p.project_name, ys.sales_year;

-- 3. Projects with latest progress updates
SELECT p.project_name, p.locality, u.update_label,
       u.excavation_pct, u.rcc_pct, u.finishing_pct, u.units_booked,
       s.observed_at
FROM project_progress_updates u
JOIN project_snapshots s USING (snapshot_id)
JOIN projects p USING (project_key)
ORDER BY p.project_name, s.observed_at DESC, u.update_label DESC;

-- 4. Spot incomplete parses and scraping errors
SELECT requested_url, page_type, http_status, parse_status, error_message, fetched_at
FROM source_pages
WHERE parse_status <> 'ok' OR error_message IS NOT NULL
ORDER BY fetched_at DESC;

-- 5. Check project-level data completeness
SELECT count(*) AS projects,
       count(rera_number) AS with_rera_number,
       count(locality) AS with_locality,
       count(possession_date_text) AS with_possession_date,
       count(total_units) AS with_total_units,
       count(price_per_sqft_80pct) AS with_price_summary
FROM projects;
