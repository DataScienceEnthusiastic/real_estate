# Pune Real Estate Investment Intelligence Platform (v0.7.0)

An evidence-backed real estate investment data and decision platform for **Pune, Maharashtra, India**. 

The platform collects data from FlatNama, listing portals, and official statutory sources (MahaRERA / IGR Maharashtra) into **PostgreSQL**, applies transactional migrations, validates data quality, performs entity resolution, and runs financial planning calculations (DCF, IRR, NPV, mortgage amortization, scenario analysis) to address core investment hypotheses.

---

## 1. Investment Hypotheses Supported

- **H1: Financial Attractiveness of Residential Property in Pune**: Evaluates whether purchasing residential property in Pune is financially justified vs capital alternatives (Nifty 50 equity index compounding @ 12% and Bank Fixed Deposits @ 7%). Computes nominal and inflation-adjusted (real) IRR, exit equity, and net cash flows over 5, 10, and 15-year holding horizons under Bear, Base, and Bull scenarios, accounting for Finance Act 2024 LTCG tax (flat 12.5% under Section 112) and Section 24(b) interest deductions.
- **H2: Locality Investment Ranking**: Ranks Pune micro-markets using a multi-factor score (0–100) combining 3-year registered price growth, net rental yields, project delay and execution risk, pipeline absorption rates, and transit proximity to IT corridors (Hinjawadi, Kharadi, Magarpatta) and Pune Metro Line 3.
- **H3: Project and Individual Flat Value Evaluation**: Identifies properties whose asking or registered rates offer attractive value relative to micro-market peer benchmarks, while adjusting for developer delay history and finishing progress.
- **H4: Explainable Hedonic Price Modeling Dataset**: Prepares a leak-free modeling dataset for regression and machine learning (e.g. XGBoost, Random Forest) using strict out-of-time splits and historical infrastructure opening dates to prevent temporal lookahead bias.

---

## 2. Architecture & Design Principles

1. **Strict Entity Separation**: Asking prices (`property_listings`), statutory registered deeds (`registered_transactions`), and project-level annual benchmarks (`project_sale_year_stats`) are stored in distinct tables. FlatNama's 80th-percentile project benchmark is never labeled as an individual flat transaction price.
2. **Honest Missing-Data Semantics**: Unknown fields remain `NULL`. The platform never injects default values (e.g. `Residential`, `Active`, `On Schedule`, `0`, or `False`) when the source is silent.
3. **No Synthetic Content**: Replaced synthetic FAQ generators with an authentic schema.org and HTML accordion FAQ extractor.
4. **Reprocessable Snapshots**: Snapshot uniqueness constraint is enforced as `UNIQUE (project_key, content_sha256, parser_version)`. Bumping the parser version re-processes existing HTML snapshots without manual database truncation.
5. **Versioned Database Migrations**: Schema updates are managed via versioned SQL migrations (`migrations/001_initial_baseline.sql`, `002_investment_entities.sql`, `003_analytical_investment_views.sql`) tracked in `schema_migrations`.

---

## 3. Quickstart

### 3.1 Setup Environment

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

Verify your `.env` configuration contains your database credentials:
```env
FLATNAMA_USER_AGENT=researcher/0.1 (contact: your_email@example.com)
DATABASE_URL=postgresql://uday:1234@localhost:5432/pune_property
```

### 3.2 Run Database Migrations

Apply all versioned database migrations idempotently:
```powershell
python migrate.py
```

### 3.3 Import Research Data (Offline / Pre-collected)

Import existing research reports (such as `reports/deccan_sample_v3.json`) directly into PostgreSQL without making network requests:
```powershell
python import_report.py reports\deccan_sample_v3.json
```

### 3.4 Run Scraper Collection

Run the polite FlatNama collector:
```powershell
# Scrape sample projects and generate a QA report
python scraper.py --input seed_urls.txt --discover-project-links --max-project-pages 10 --report-json reports\deccan_sample_v3.json --export-csv exports

# Or run in dry-run mode (skips database writes)
python scraper.py --input seed_urls.txt --discover-project-links --max-project-pages 5 --dry-run
```

### 3.5 Run the Financial & Investment Valuation Engine

Run the financial model CLI to evaluate investment scenarios:
```powershell
python financial_model.py
```
This prints the 5, 10, and 15-year DCF cash flow schedules, debt amortization, nominal vs real IRR, and Bear/Base/Bull scenario comparisons.

### 3.6 Export CSV Spreadsheets

Export all 18 analytical tables and views into Excel-ready UTF-8 (with BOM) CSV files:
```powershell
python export_data.py --db --output-dir exports
```

---

## 4. Test Suite Execution

Run the complete automated test suite (37 unit, regression, and database integration tests):

```powershell
.\.venv\Scripts\python.exe -m unittest discover tests -v
```

### Verified Test Modules:
- `tests/test_parser.py`: 12 tests verifying multi-row annual price extraction, year-over-year text matching, layout shifts, missing values, and authentic FAQ extraction.
- `tests/test_financial_model.py`: 11 tests verifying acquisition closing costs, monthly EMI schedules, rental yields, IRR/NPV, and H1/H2/H3 scoring.
- `tests/test_entity_resolution.py`: 4 tests verifying multi-tiered record matching (exact RERA ID, exact name & locality, fuzzy Jaccard similarity, and unresolved preservation).
- `tests/test_data_quality.py`: 6 tests verifying range bounds, chronological consistency (possession >= launch), price boundaries, and unobserved boolean audits.
- `tests/test_integration.py`: 4 tests verifying database connectivity, migration idempotency, view queries, repeat-import idempotency, and CSV exports.

---

## 5. Analytical SQL Views

| View Name | Primary Function | Hypotheses |
|---|---|---|
| `v_investment_h1_cashflows` | Pre-computes 5, 10, 15-year cash flows, mortgage EMI, net operating income, and exit equity. | **H1** |
| `v_locality_h2_rankings` | Locality-level ranking combining price growth, rental yield, delay rates, absorption %, and transit proximity. | **H2** |
| `v_project_h3_value_scores` | Relative pricing, micro-market discounts, execution progress, and value opportunity score per project. | **H3** |
| `v_hedonic_h4_dataset` | Clean, leakage-free modeling dataset prepared for out-of-time train/test evaluation. | **H4** |
| `v_projects_master` | Master view with 60+ verified entity attributes and quality flags. | Master Data |
| `v_project_delays_and_progress` | Detailed possession extension timelines, delay in months, and RCC/finishing stages. | Execution Risk |
| `v_project_pricing_summary` | Annual price benchmarks, YoY growth, rate vs nearby projects, and volume. | Valuation |
| `v_project_inventory_summary` | Inventory distribution, sold counts, booking %, and BHK configurations. | Absorption |

---

## 6. Generated CSV Files (`exports/`)

Running `python export_data.py --db --output-dir exports` creates:
1. `investment_h1_cashflows.csv`
2. `locality_h2_rankings.csv`
3. `project_h3_value_scores.csv`
4. `hedonic_h4_dataset.csv`
5. `projects_master.csv`
6. `delays_and_progress.csv`
7. `pricing_summary.csv`
8. `inventory_summary.csv`
9. `sale_prices.csv`
10. `progress_updates.csv`
11. `unit_mix.csv`
12. `size_price_bands.csv`
13. `comparables.csv`
14. `comparison_benchmarks.csv`
15. `faqs.csv`
16. `quality_audits.csv`
17. `financial_assumptions.csv`
18. `locations.csv`
