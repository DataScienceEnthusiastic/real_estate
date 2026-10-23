# Data Dictionary — FlatNama Collector v0.6.0

This collector extracts an exhaustive set of project attributes across **16 structured data categories** from FlatNama. Data is stored in relational PostgreSQL tables with analytical views, and can be exported as Excel-friendly CSV files.

---

## The 16 Extraction Categories

### 1. Project Identity
- `project_name`: Displayed project and phase name.
- `rera_number`: Official MahaRERA registration number (e.g. `P52100032629`).
- `phase_name`: Extracted wing or phase name (e.g. `Phase 4`, `BUILDING-B3`, `C2 Wing`).
- `project_url`: Canonical FlatNama page URL.
- `developer`: Builder / Promoter company name.
- `project_type`: `Residential`, `Commercial`, or `Mixed Use`.
- `project_description`: Cleaned project overview / SEO meta description.
- `breadcrumbs`: Full hierarchy (`Pune` → `Locality` → `Project`).
- `maharera_status`: MahaRERA registration state (`Active`, `Completed`, `Expired`).

### 2. Geographic & Location Data
- `locality`: Primary area/locality name (e.g. `Erandwane`, `Deccan`).
- `sub_locality`: Specific neighbourhood where identified.
- `city` / `district`: `Pune`.
- `pin_code`: 6-digit postal code (e.g. `411004`).
- `map_url`: Google Maps search/location URL.
- `displayed_address`: Physical address string from the page.
- `area_page_url`: Canonical area catalog link.

### 3. Launch, Completion & Possession
- `launch_date_text`: Displayed launch date (e.g. `May 2023`).
- `launch_month` / `launch_year`: Structured month name and year.
- `possession_date_text`: Current registered possession target (e.g. `September 2026`).
- `possession_month` / `possession_year`: Structured target month and year.
- `original_possession_date_text`: First registered target date before any extension.
- `possession_extension_status`: `Extended`, `On Schedule`, or `Not Reported`.
- `possession_delay_months`: Total delay in months (from text or calculated).
- `possession_extension_note`: Descriptive extension statement.
- `promised_timeline_text`: Promised duration text (e.g. `56 months promised`).
- `promised_timeline_months`: Normalized total promised timeline in months.
- `months_elapsed_since_launch`: Number of calendar months elapsed since launch.
- `months_remaining_to_possession`: Months remaining until target possession.
- `ready_to_move_status`: Boolean indicator if stage is "Ready to move".

### 4. Construction & Physical Progress
- `building_count`: Total buildings/towers in this phase.
- `land_acres`: Plot area in acres.
- `excavation_pct`: Latest excavation progress percentage.
- `rcc_pct`: Latest concrete structure (RCC) completion percentage.
- `finishing_pct`: Latest internal/external final finishes completion percentage.
- `construction_stage`: `Ready to move`, `Nearing possession`, `Mid-construction`, `Early stage`.
- `structural_completion_status`: Boolean (`rcc_pct == 100%`).
- `finishing_completion_status`: Boolean (`finishing_pct == 100%`).
- `complaint_count`: Complaints reported on MahaRERA.
- `progress_updates`: Chronological milestone history with delta changes between updates.

### 5. Inventory & Flat Configuration
- `total_units`: Total registered units in the phase.
- `units_for_sale`: Units available for purchase.
- `units_booked`: Sold/booked units count.
- `not_for_sale_units`: Units retained or not offered for sale.
- `booking_pct`: Percentage of units booked.
- `booking_status`: `reported_count`, `all_booked`, `not_reported`, `unknown`.
- `recent_bookings_count`: Recently added bookings (e.g. `+ 4 booked recently`).
- **Configuration Breakdown**:
  - `units_1rk`: Number of 1 RK units.
  - `units_1bhk`: Number of 1 BHK units.
  - `units_2bhk`: Number of 2 BHK units.
  - `units_3bhk`: Number of 3 BHK units.
  - `units_4bhk`: Number of 4 BHK units.
  - `units_5bhk_plus`: Number of 5+ BHK units.
  - `units_other`: Unclassified / other units.
  - `total_residential_units`: Sum of residential configurations.

### 6. Actual Sold-Price Summaries
- `price_per_sqft_80pct`: 80th-percentile rate (80% of observed flats sold at or below this rate).
- `price_per_sqft_80pct_source`: `annual_year_by_year` or `headline_only`.
- `latest_sale_year`: Most recent calendar year with sales observations.
- `latest_sale_count`: Number of registered transactions observed in that year.
- `current_ytd_price`: Current calendar year-to-date rate (`YYYY so far`).
- `previous_year_price`: Rate for previous calendar year.
- `year_over_year_change_pct`: Percentage rate change vs previous year.
- `year_over_year_direction`: `up`, `down`, or `stable`.
- `rate_vs_nearby_projects_pct`: Percentage premium or discount compared to nearby projects.
- `price_area_basis`: Area convention (`includes balconies and terrace` or carpet area).
- `flat_sizes_sold_sqft`: Distinct individual flat sizes sold in recent years.
- `years_of_sales_data`: Count of years covered by historical sales data.

### 7. Size-Wise Pricing Bands
- Structured records in `project_size_price_bands`:
  - `year_label`: Applicable sales year.
  - `raw_size_label`: e.g. `700 – 800 sq ft`.
  - `min_size_sqft` / `max_size_sqft`: Numeric area bounds.
  - `raw_price_label`: e.g. `₹70 – 90 lakh` or `₹2.72 – 3.28 crore`.
  - `min_price_inr` / `max_price_inr`: Numeric INR price bounds.

### 8. Historical Project Updates
- Updates reported to MahaRERA in `project_progress_updates`:
  - `update_label`: Reporting period (e.g. `Jul 2026`).
  - `excavation_pct`, `rcc_pct`, `finishing_pct`, `units_booked`.
  - `rcc_change`: RCC progress increase since previous update.
  - `finishing_change`: Finishes progress increase since previous update.
  - `booking_change`: Net change in booked units between updates.

### 9. Similar-Project Comparisons
- Similar project group parameters:
  - `similar_projects_count`: Number of comparable peers in the benchmark group.
  - `similar_projects_pin`: Benchmark postal code.
- Peer projects in `project_comparables`:
  - `comparable_name`: Name of comparable project.
  - `launch_date_text`, `possession_date_text`, `rcc_pct`, `booking_text`.

### 10. Price & Market Benchmark Indicators
- Metric-by-metric benchmarks in `project_comparison_benchmarks`:
  - Promised timeline (launch to possession)
  - Possession date extended
  - Possession date (MahaRERA)
  - Concrete structure (RCC) complete
  - Share of units for sale that are booked
  - Complaints on MahaRERA

### 11. Frequently Asked Questions & Explanations
- Synthesized and extracted Q&As in `project_faqs`:
  - **Possession & Timeline**: Target date, extension months, promised schedule.
  - **Construction Status**: Current stage, RCC percentage, finishing percentage.
  - **Pricing & Sold Rates**: 80th-percentile rate, nearby comparison premium/discount.
  - **Inventory & Bookings**: Registered units, units booked, booking percentage.
  - **Developer & RERA Registration**: Builder name, RERA ID, status, complaint count.
  - **Methodology & Disclaimers**: Clarification of 80%-threshold definitions.

### 12. Area & Listing-Page Data
- Area catalog records in `area_page_snapshots`:
  - `area_name`, `area_url`, `pin_code`.
  - `listed_project_count`: Total residential projects in locality.
  - `visible_projects_count`: Default visible listing count.
  - `small_projects_hidden_count`: Count of small projects behind filter toggle.
  - `launched_last_6_months_count`: Recent launches in area.
  - `rcc_complete_count`: Projects with complete structure.
  - `possession_date_extended_count`: Projects with delayed possession.
  - `nearby_areas`: Links and names of adjacent localities.
  - Discovered project URLs in `discovered_project_urls`.

### 13. Pune Market Analytics
- Macro-level trends in `area_market_analytics`:
  - `area_name`, `trend_year`, `projects_launched`, `flats_launched`, `rcc_complete_flats`.

### 14. Related Projects & Navigation Links
- Related links in `project_related_links`:
  - `other_phase`: Links to other wings or phases of the same development.
  - `comparable_project`: Links to similar projects in the same micromarket.
  - `area_project_list`: Area catalog links.

### 15. Raw HTML & Technical Metadata
- Detailed DOM inventory in `page_data_inventory`:
  - Page title, meta tags, OpenGraph tags, canonical URL.
  - Section headings, all HTML tables, all unordered/ordered lists.
  - Key-value pairs, data attributes, image metadata with dimensions and alt text.

### 16. Provenance & Data Quality Fields
- Quality audit in `project_quality_audits`:
  - `parser_version`: Current parser release (`0.6.0`).
  - `fields_checked`: Total core fields audited.
  - `fields_present`: Count of populated fields.
  - `completeness_pct`: Field completeness percentage.
  - `warnings`: Detailed QA flags (layout shifts, price discrepancies, missing sections).

---

## Relational Database Tables

| Table | Description |
|---|---|
| `projects` | Master entity table with 60+ structured columns per registered phase. |
| `project_snapshots` | Versioned JSONB snapshot of every scrape run. |
| `project_unit_mix` | Normalized unit configurations (1RK, 1BHK, 2BHK, 3BHK, etc.). |
| `project_sale_year_stats` | Historical year-by-year 80th-percentile rates and sales count. |
| `project_size_price_bands` | Flat size bands and observed buyer price ranges in INR. |
| `project_progress_updates` | Historical milestones with excavation, RCC, finishes, bookings, and deltas. |
| `project_comparables` | Peer projects with launch, possession, RCC, and bookings. |
| `project_comparison_benchmarks` | Subject project vs similar project benchmarks on key metrics. |
| `project_related_links` | Links to other phases, comparable peers, and area pages. |
| `project_faqs` | Standard and verified Q&A explanatory content per project. |
| `project_quality_audits` | Extraction completeness score, field presence, and QA warnings. |
| `area_page_snapshots` | Area-level catalog counts, filters, and statistics. |
| `discovered_project_urls` | Manifest of all discovered candidate URLs with fetch statuses. |
| `area_market_analytics` | Area-by-year macro trends (launches, units, structural completion). |

---

## Analytical Views

- `v_projects_master`: Master overview view joining identity, location, timeline, construction, pricing, and quality score.
- `v_project_delays_and_progress`: Focus on promised timelines, possession date extensions, delay in months, and RCC/finishing stages.
- `v_project_pricing_summary`: Latest 80%-threshold rate, YoY price growth, nearby comparison premium, and sales volume.
- `v_project_inventory_summary`: Total units, booked units, booking percentage, and flat-type breakdown (1BHK..5BHK).
- `v_project_comparables_summary`: Project vs similar project benchmarks.
- `v_project_faqs_overview`: Questions and verified answers per project.

---

## Generated CSV Files (`exports/`)

When running `python export_data.py` or `python scraper.py --export-csv exports/`, the following UTF-8 (Excel-ready with BOM) CSVs are created:

1. `projects_master.csv`: Wide table containing 69 project-level columns.
2. `projects_complete.csv`: All-in-one consolidated spreadsheet with flattened unit mix, price history, and progress summaries.
3. `sale_prices.csv`: All historical annual price summaries.
4. `progress_updates.csv`: All construction milestones and progress deltas.
5. `unit_mix.csv`: Unit configurations by project.
6. `size_price_bands.csv`: Size ranges and buyer price brackets.
7. `comparables.csv`: Peer projects and comparable attributes.
8. `comparison_benchmarks.csv`: Benchmarks comparing project to similar peers.
9. `faqs.csv`: Structured FAQs covering possession, construction, pricing, and inventory.
10. `related_links.csv`: Other phases and navigation links.
11. `area_summaries.csv`: Locality-level project counts, small project counts, and filters.
12. `quality_audits.csv`: Extraction completeness percentage, warnings, and missing fields.
