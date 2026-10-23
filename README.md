# FlatNama → PostgreSQL & CSV Collector (v0.6.0)

An advanced, polite research collector for extracting structured real estate data from [FlatNama](https://flatnama.com) into **PostgreSQL** and **CSV spreadsheets**.

It captures an exhaustive set of project features across **16 structured data categories**, computes exact timeline/possession metrics and construction progress deltas, generates project FAQs, creates relational tables with analytical views, and exports clean Excel-ready CSV files.

---

## The 16 Extraction Categories

1. **Project Identity**: Project name, MahaRERA ID, phase/wing name, canonical URL, developer, category/type (Residential/Commercial/Mixed), description, breadcrumbs, registration status.
2. **Geographic & Location Data**: Area/locality, sub-locality, city, district, 6-digit PIN code, Google Maps link, displayed address, area catalogue URL.
3. **Launch, Completion & Possession**: Launch month & year, promised timeline in months, registered possession target, original possession target, possession extension status (`Extended` / `On Schedule`), delay in months, months elapsed since launch, months remaining, ready-to-move status.
4. **Construction & Physical Progress**: Buildings count, land area in acres, excavation %, RCC %, final finishes %, construction stage, structural completion status, finishing completion status, complaints count, chronological progress updates with delta changes.
5. **Inventory & Flat Configuration**: Total registered units, units for sale, units booked, not for sale units, booking %, booking status, recent bookings count, and flat mix breakdown (`1 RK`, `1 BHK`, `2 BHK`, `3 BHK`, `4 BHK`, `5+ BHK`, `Other`).
6. **Actual Sold-Price Summaries**: 80th-percentile rate per sq ft, latest sales year, transaction count, current year-to-date rate (`YYYY so far`), previous year rate, YoY change %, YoY direction (`up`/`down`/`stable`), rate vs nearby projects premium/discount %, price area basis.
7. **Size-Wise Pricing Bands**: Flat size ranges (sq ft), observed buyer price brackets (INR Lakh/Crore), min/max size and price bounds.
8. **Historical Project Updates**: Detailed milestone table with excavation, RCC, finishes, bookings, and delta change calculations between consecutive updates.
9. **Similar-Project Comparisons**: Benchmark group size, benchmark PIN code, and individual comparable projects with launch, possession, RCC, and bookings.
10. **Price & Market Benchmark Indicators**: Key measure comparisons (promised timeline, possession extensions, possession date, RCC complete %, share of units booked, complaints).
11. **Frequently Asked Questions & Explanatory Content**: Synthesized and extracted Q&As covering possession dates, construction status, pricing, inventory, developer background, and 80%-threshold definitions.
12. **Area & Listing-Page Data**: Area name, PIN code, total listed projects, visible projects, small projects hidden behind filters, recent 6-month launches, RCC complete count, extended possession count, nearby areas.
13. **Pune Market Analytics**: Area-by-year macro trends (launches, units, structural completion).
14. **Related Projects & Navigation**: Other phases of the same development, comparable project links, area navigation links, map links.
15. **Raw HTML & Technical Metadata**: Technical DOM inventory (meta tags, OpenGraph tags, canonical URL, headings, tables, lists, key-values, links, images metadata).
16. **Provenance & Data Quality**: Parser version, field presence score, completeness percentage, and detailed QA audit warnings.

---

## Quickstart

### 1. Environment Setup

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

Verify your [.env](file:///u:/Projects_/real_estate/.env) has your contact email in `FLATNAMA_USER_AGENT` and your database credentials in `DATABASE_URL`.

### 2. Start PostgreSQL (Docker)

```powershell
docker compose up -d db
```

Tables, indexes, and analytical views will initialize automatically via [schema.sql](file:///u:/Projects_/real_estate/schema.sql).

### 3. Run Parser Unit Tests

```powershell
python -m unittest discover -s tests -v
```

---

## Running the Scraper

### Sample Run with QA Report and CSV Export

```powershell
python scraper.py --input seed_urls.txt --discover-project-links --max-project-pages 10 --report-json reports\deccan_sample_v3.json --export-csv exports
```

To run without writing to PostgreSQL (dry run):
```powershell
python scraper.py --input seed_urls.txt --discover-project-links --max-project-pages 10 --dry-run --report-json reports\deccan_sample_v3.json --export-csv exports
```

---

## Exporting CSV Spreadsheets

You can export the entire scraped dataset at any time using [export_data.py](file:///u:/Projects_/real_estate/export_data.py):

```powershell
# Export from a JSON report file
python export_data.py --json reports\deccan_sample_v3.json --output-dir exports

# Or export directly from live PostgreSQL database
python export_data.py --db --output-dir exports
```

### Generated CSV Files in `exports/`:
- `projects_master.csv`: Wide master table with 69 structured columns per project.
- `projects_complete.csv`: Single all-in-one spreadsheet with flattened unit mix, price history, and progress summaries.
- `sale_prices.csv`: All year-by-year 80th-percentile price records and sales counts.
- `progress_updates.csv`: All historical construction milestones with progress deltas.
- `unit_mix.csv`: Unit configurations (`1 RK` through `5+ BHK`).
- `size_price_bands.csv`: Size ranges and buyer price brackets.
- `comparables.csv`: Specific comparable projects.
- `comparison_benchmarks.csv`: Benchmarks comparing project to similar peers.
- `faqs.csv`: Project-specific FAQs and explanatory notes.
- `related_links.csv`: Other phases and navigation links.
- `area_summaries.csv`: Area catalog counts, hidden project counts, and filters.
- `quality_audits.csv`: Extraction completeness scores, warnings, and missing fields.

All CSVs are encoded in **UTF-8 with BOM** (`utf-8-sig`) so that symbols like `₹` and special formatting open seamlessly in Microsoft Excel, Google Sheets, and Pandas.

---

## PostgreSQL Views & Queries

The database provides pre-built analytical views for immediate inspection:
- `v_projects_master`: High-level master overview of all projects.
- `v_project_delays_and_progress`: Focus on timelines, delays in months, and structural stages.
- `v_project_pricing_summary`: Latest 80%-threshold rate, YoY price growth, and market comparisons.
- `v_project_inventory_summary`: Inventory breakdown, units booked, and flat types.
- `v_project_comparables_summary`: Project vs similar project benchmarks.
- `v_project_faqs_overview`: Questions and verified answers per project.

Ready-to-run SQL queries are provided in [queries.sql](file:///u:/Projects_/real_estate/queries.sql).
