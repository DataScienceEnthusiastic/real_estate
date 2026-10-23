# Data Dictionary — Pune Real Estate Investment Intelligence Platform (v0.7.0)

This data platform collects, normalizes, validates, and models residential real estate data for Pune, Maharashtra, India. It combines project-level data (FlatNama), asking-price observations (listing portals), official registered transaction deeds (IGR Maharashtra / MahaRERA), transit infrastructure proximity, and macroeconomic parameters into a structured analytical architecture.

---

## 1. Feature Classification & Strategy Matrix

Data is structured into four explicit analytical tiers to prevent raw HTML clutter from contaminating statistical models:

| Tier | Category | Description | Analytical Purpose |
|---|---|---|---|
| **Tier 1** | **Essential** | Directly required for valuation, DCF cash flow, investment return calculations (IRR, NPV), entity resolution, and data integrity. | Acquisition cost, mortgage EMI, net operating income, rental yield, carpet area, possession dates, launch dates, RERA ID, prices, loan schedules. |
| **Tier 2** | **High-Value** | Improves comparable selection, risk assessment, location accessibility, delay risk, and hedonic prediction accuracy. | Concrete structure (RCC %), finishing %, delay in months, booking rate, inventory mix, transit/IT hub distances, infrastructure opening dates. |
| **Tier 3** | **Optional Enrichment** | Secondary context collected only when reliable, cost-effective, and analytically defensible. | Developer track record, complaint counts, verified architectural amenities, published area filters. |
| **Tier 4** | **Excluded / Downgraded** | Navigation clutter, synthetic FAQs, unverified claims, or unsupported default values. | Automatically synthesized FAQs, hardcoded `'Residential'` or `'On Schedule'` when source is silent, raw DOM scripts, and unverified subjective views. |

---

## 2. Core Relational Tables

### 2.1 Entity Master Tables

#### `sources`
- `source_id` (TEXT, PK): Canonical source identifier (`flatnama`, `maharera`, `igr_maharashtra`, `magicbricks`, `99acres`).
- `source_name` (TEXT): Display name.
- `source_type` (TEXT): `aggregator`, `statutory_registry`, `listing_portal`, `gis_layer`.
- `legal_access_type` (TEXT): `public_web`, `statutory_open_data`, `authorized_api`.
- `bulk_extraction_permitted` (BOOLEAN): Explicit terms-of-service compliance flag.
- `rate_limit_per_min` (INT): Polite crawl rate threshold.

#### `locations`
- `locality_id` (SERIAL, PK): Unique surrogate key.
- `city` (TEXT): `Pune`.
- `locality` (TEXT): Primary micro-market name (e.g. `Hinjawadi`, `Kharadi`, `Wakad`, `Kothrud`).
- `sub_locality` (TEXT): Specific sector or phase name.
- `pin_code` (VARCHAR(10)): Indian postal PIN code.
- `latitude` / `longitude` (NUMERIC(10, 7)): Centroid coordinates.
- `distance_to_hinjawadi_it_km` (NUMERIC(6, 2)): Road/Euclidean distance to Hinjawadi Rajiv Gandhi Infotech Park.
- `distance_to_kharadi_it_km` (NUMERIC(6, 2)): Distance to EON Free Zone / Kharadi IT Park.
- `distance_to_magarpatta_km` (NUMERIC(6, 2)): Distance to Magarpatta Cybercity.
- `distance_to_nearest_metro_km` (NUMERIC(6, 2)): Proximity to Pune Metro Line 1 / 2 / 3 station.

#### `projects`
- `project_key` (TEXT, PK): Unique slug (e.g. `pune-erandwane-rohan-garima-phase-1`).
- `project_name` (TEXT): Official marketing name.
- `rera_number` (TEXT): Official MahaRERA registration number (e.g. `P52100032629`).
- `phase_name` (TEXT): Wing or phase designation.
- `developer` (TEXT): Promoter / Builder legal entity name.
- `project_type` (TEXT): `Residential`, `Commercial`, `Mixed Use`, or `NULL` (unknown values remain `NULL`).
- `locality` (TEXT), `sub_locality` (TEXT), `city` (TEXT), `pin_code` (VARCHAR(10)).
- `launch_year` (INT), `launch_month` (TEXT), `possession_year` (INT), `possession_month` (TEXT).
- `promised_timeline_months` (INT): Statutory promised duration from registration to target possession.
- `possession_delay_months` (INT): Calculated delay beyond original registered possession date.
- `possession_extension_status` (TEXT): `Extended`, `On Schedule`, or `NULL` (never defaulted).
- `rcc_pct` (NUMERIC(5, 2)): Concrete structural completion (0.0 to 100.0%).
- `finishing_pct` (NUMERIC(5, 2)): Architectural finishing completion (0.0 to 100.0%).
- `total_units` (INT): Total registered inventory in phase.
- `units_booked` (INT): Units booked by buyers.
- `booking_pct` (NUMERIC(5, 2)): Sold percentage.
- `price_per_sqft_80pct` (NUMERIC(10, 2)): 80th-percentile rate benchmark from registered sales.
- `price_area_basis` (TEXT): Underlying area definition (`carpet_area`, `includes_balconies_and_terrace`).

---

### 2.2 Time-Dependent & Observation Tables

#### `project_snapshots`
- `project_key` (TEXT), `content_sha256` (TEXT), `parser_version` (VARCHAR(20)): Composite unique constraint `(project_key, content_sha256, parser_version)`. Enables parser reprocessing when parser logic is upgraded.
- `data` (JSONB): Complete structured parse tree.
- `fetched_at` (TIMESTAMPTZ): Provenance timestamp.

#### `project_sale_year_stats`
- `project_key` (TEXT), `sales_year` (INT): Composite PK.
- `price_per_sqft_80pct` (NUMERIC(10, 2)): Published 80th-percentile rate for that specific calendar year.
- `sales_count` (INT): Number of registered sales observed.
- `yoy_change_pct` (NUMERIC(6, 2)): Year-over-year percentage rate change.
- `yoy_direction` (TEXT): `up`, `down`, `stable`.
- `statistical_meaning` (TEXT): Explicit caveat defining the rate as an 80th-percentile aggregate, NOT an individual flat transaction price.

#### `project_progress_updates`
- `project_key` (TEXT), `update_label` (TEXT): Chronological construction milestone.
- `excavation_pct`, `rcc_pct`, `finishing_pct`, `units_booked`.
- `rcc_change`, `finishing_change`, `booking_change`: Delta changes between consecutive filings.

#### `project_size_price_bands`
- `project_key` (TEXT), `year_label` (TEXT), `raw_size_label` (TEXT): Flat size brackets (e.g. `700 – 800 sq ft`) and buyer price brackets (e.g. `₹70 – 90 lakh`).

---

### 2.3 Separate Transaction & Listing Datasets (Part 5 Compliance)

#### `property_listings` (Asking Prices)
- `listing_id` (TEXT, PK): Unique listing ID from portal.
- `source_id` (TEXT): `magicbricks`, `99acres`, `housing_com`.
- `project_key` (TEXT, FK): Linked project (if resolved).
- `property_type` (TEXT), `bhk_config` (TEXT).
- `carpet_area_sqft` (NUMERIC(8, 2)), `super_builtup_sqft` (NUMERIC(8, 2)).
- `asking_price_inr` (NUMERIC(14, 2)): Raw advertiser asking price.
- `floor_number` (INT), `total_floors` (INT), `furnishing_status` (TEXT).
- `listing_status` (TEXT): `active`, `delisted`, `expired` (a delisted asking price is never assumed to be a completed sale).

#### `registered_transactions` (Actual Deeds - IGR Maharashtra)
- `transaction_id` (TEXT, PK): Statutory index-II registration document identifier.
- `source_id` (TEXT): `igr_maharashtra`.
- `project_key` (TEXT, FK): Linked project.
- `registration_date` (DATE): Statutory deed registration date.
- `declared_consideration_inr` (NUMERIC(14, 2)): Actual financial consideration declared in deed.
- `ready_reckoner_valuation_inr` (NUMERIC(14, 2)): Government guidance circle valuation.
- `stamp_duty_paid_inr` (NUMERIC(12, 2)), `registration_fee_paid_inr` (NUMERIC(12, 2)).
- `carpet_area_sqft` (NUMERIC(8, 2)): Measured carpet area in square feet.
- `effective_price_per_sqft` (NUMERIC(10, 2)): `declared_consideration_inr / carpet_area_sqft`.

---

### 2.4 Infrastructure & Macroeconomic Tables

#### `infrastructure_projects`
- `infra_id` (TEXT, PK): Unique infrastructure project ID (e.g. `pune_metro_line_3`).
- `infra_name` (TEXT): e.g. *Pune Metro Line 3 (Hinjawadi to Shivajinagar)*.
- `infra_type` (TEXT): `metro`, `ring_road`, `flyover`, `airport`.
- `announced_date` (DATE), `target_completion_date` (DATE), `actual_operational_date` (DATE).
- `operational_status` (TEXT): `planned`, `under_construction`, `partially_operational`, `operational`.
- **Temporal Leakage Guard**: Historical backtests use `actual_operational_date` to prevent future infrastructure status from leaking into past price predictions.

#### `macroeconomic_indicators`
- `indicator_key` (TEXT), `effective_date` (DATE): Macroeconomic benchmark time-series.
- `home_loan_interest_rate_pct` (NUMERIC(5, 2)): Prevailing RBI repo-linked mortgage interest rate.
- `cpi_inflation_rate_pct` (NUMERIC(5, 2)): Consumer price inflation rate for real-return indexing.
- `pune_gdp_growth_rate_pct` (NUMERIC(5, 2)): Regional economic expansion rate.

---

### 2.5 Quality & Entity Resolution Tables

#### `entity_match_candidates`
- `match_id` (SERIAL, PK): Candidate linkage record.
- `entity_type` (TEXT): `project_to_external`, `listing_to_project`.
- `source_entity_ref` (TEXT), `target_entity_ref` (TEXT).
- `match_method` (TEXT): `exact_rera_id` (1.000), `exact_name_locality` (0.900), `fuzzy_token_similarity` (0.600–0.850).
- `confidence_score` (NUMERIC(5, 4)).
- `resolution_status` (TEXT): `auto_merged`, `verified_match`, `unresolved`, `rejected`. Ambiguous candidates remain `unresolved` until human verification.

#### `data_quality_issues`
- `issue_id` (SERIAL, PK).
- `source_id` (TEXT), `entity_key` (TEXT), `field_name` (TEXT).
- `issue_type` (TEXT): `range_violation`, `chronology_error`, `missing_critical_key`, `outlier_warning`, `unsupported_inferred_value`.
- `severity` (TEXT): `CRITICAL`, `WARNING`, `INFO`.
- `observed_value` (TEXT), `expected_rule` (TEXT).

---

## 3. Financial Modeling & Valuation Engine (Part 8)

The platform evaluates investments across **Hypotheses H1, H2, and H3**:

### 3.1 H1: Buy vs Capital Opportunity Analysis
- **Cash Outflows**:
  - `Purchase Price`: Base negotiated property price.
  - `Closing Costs`: Stamp Duty (6% in Pune: 5% Maharashtra + 1% Local Metro Cess), Registration Fee (1% capped statutory at ₹30,000), Brokerage (1%), Legal Due Diligence (₹35,000), Loan Processing (0.5%), GST (5% on under-construction; 0% on Ready-to-Move with Completion Certificate).
  - `Down Payment`: 20% equity down payment (80% Loan-to-Value).
- **Mortgage Debt Service**:
  - Monthly EMI computed via:
    $$EMI = P \cdot r \cdot \frac{(1 + r)^n}{(1 + r)^n - 1}$$
    where $P$ is principal, $r$ is monthly interest rate (8.5% / 12), and $n$ is tenure in months (240 months for 20 years).
- **Rental Operating Economics**:
  - `Gross Rent`: 3.2% annual gross yield in Pune residential markets.
  - `Operating Deductions`: 1-month annual vacancy allowance (8.33%), society maintenance charges (₹3/sqft/mo), municipal property taxes, property management (8%), landlord insurance.
  - `Rent Escalation`: 5.0% annual compounding rent escalation.
- **Taxation (Finance Act 2024)**:
  - Section 24(b): Up to ₹2,00,000 annual deduction for home loan interest paid.
  - Section 112: Long-Term Capital Gains (LTCG) taxed at flat **12.5%** without indexation on exits beyond 24 months.
- **Exit & Returns**:
  - Evaluated over **5, 10, and 15-year** investment horizons.
  - Net Resale Proceeds = Exit Value - Resale Brokerage (1.5%) - LTCG Tax (12.5%) - Outstanding Loan Principal.
  - `Nominal IRR`: Internal Rate of Return on net equity cash flows.
  - `Real IRR`: Inflation-adjusted return using Fisher equation:
    $$Real\ IRR = \frac{1 + Nominal\ IRR}{1 + Inflation\ Rate} - 1$$
  - Opportunity Cost Comparison: Benchmarked against **Nifty 50** equity index compounding (12.0% nominal) and **Bank Fixed Deposits** (7.0% pre-tax, 4.9% post-tax).

### 3.2 H2: Locality Investment Opportunity Scoring
Localities are ranked using a multi-factor composite score (0–100) to prevent ranking by price appreciation alone:
- **Price Growth Momentum (25%)**: 3-year historical CAGR from verified registered deeds.
- **Rental Yield Attractiveness (25%)**: Net rental yield relative to city baseline (3.2%).
- **Execution & Delay Risk (20%)**: Proportion of delayed projects and average delay months (penalized).
- **Pipeline Absorption (15%)**: Locality booking velocity (units booked / units registered).
- **Transit & Employment Proximity (15%)**: Proximity to IT hubs (Hinjawadi, Kharadi, Magarpatta) and Pune Metro Line 3.

### 3.3 H3: Project Value & Underpricing Scoring
Individual projects are scored relative to their micro-market peers:
- Compares subject project's 80th-percentile rate against locality benchmark rate.
- Discounts project value for severe construction delays (>12 months) or slow execution (finishing < 40% with possession due in < 12 months).

---

## 4. Analytical SQL Views

| View Name | Primary Function | Hypotheses Supported |
|---|---|---|
| `v_investment_h1_cashflows` | Pre-computes 5, 10, and 15-year total cash flows, closing costs, mortgage EMI, net operating income, and exit proceeds. | **H1** |
| `v_locality_h2_rankings` | Locality-level ranking combining price growth, rental yield, construction delay rates, absorption %, and transit proximity. | **H2** |
| `v_project_h3_value_scores` | Relative pricing, micro-market discounts, execution progress, and value opportunity score per project. | **H3** |
| `v_hedonic_h4_dataset` | Clean, leakage-free modeling dataset prepared for out-of-time train/test evaluation (Hedonic regression, Random Forests, XGBoost). | **H4** |
| `v_projects_master` | Unified master view with 60+ verified entity attributes and quality flags. | Master Data |
| `v_project_delays_and_progress` | Detailed possession extension timelines, delay in months, and RCC/finishing stages. | Execution Risk |
| `v_project_pricing_summary` | Annual price benchmarks, YoY growth, rate vs nearby projects, and volume. | Valuation |
| `v_project_inventory_summary` | Inventory distribution, sold counts, booking %, and BHK configurations. | Absorption |
| `v_project_faqs_overview` | Authentic source FAQs extracted from verified web pages. | Explanatory |

---

## 5. CSV Export Manifest (`exports/`)

When executing `python export_data.py --db --output-dir exports`, the platform exports 18 UTF-8 (with Excel BOM) spreadsheets:

1. `investment_h1_cashflows.csv`: Complete DCF acquisition, debt service, rental yield, and 5/10/15 year cash flow model.
2. `locality_h2_rankings.csv`: Locality investment opportunity scores, delays, and rental metrics.
3. `project_h3_value_scores.csv`: Project pricing vs peers, execution risks, and value opportunity scores.
4. `hedonic_h4_dataset.csv`: Out-of-time hedonic feature set with temporal leakage guards.
5. `projects_master.csv`: Wide master entity table with 60+ verified fields.
6. `delays_and_progress.csv`: Extension months, delay metrics, and construction stages.
7. `pricing_summary.csv`: 80th-percentile rates, YoY trends, and local premiums.
8. `inventory_summary.csv`: Total inventory, booked units, and configuration breakdowns.
9. `sale_prices.csv`: Historical year-by-year 80th-percentile rate records.
10. `progress_updates.csv`: Chronological excavation, RCC, and finishing milestone history.
11. `unit_mix.csv`: Normalized 1RK through 5+ BHK unit counts.
12. `size_price_bands.csv`: Size ranges and buyer price brackets.
13. `comparables.csv`: Specific peer projects.
14. `comparison_benchmarks.csv`: Benchmarks comparing project to similar peers.
15. `faqs.csv`: Verified source FAQs (possession, pricing, inventory).
16. `quality_audits.csv`: Extraction completeness percentage, warnings, and missing fields.
17. `financial_assumptions.csv`: Parameterized mortgage, tax, rental, and growth assumptions.
18. `locations.csv`: Locality catalog with IT corridor and metro station distances.
