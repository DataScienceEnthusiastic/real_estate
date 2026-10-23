# Repository Audit Report: Real Estate Investment Intelligence Platform

**Date:** 2026-10-24  
**Auditor:** Senior Data Engineer, Real Estate Data Scientist, Applied Economist & PostgreSQL Architect  
**Branch:** `feature/investment-intelligence-platform`  
**Repository:** `https://github.com/DataScienceEnthusiastic/real_estate`

---

## 1. Executive Summary

This repository initially operated as a research collector scraping project-level data from FlatNama (`flatnama.com`) into PostgreSQL. While it successfully extracts many project cards, tables, and annual price statistics, our comprehensive audit reveals several structural flaws, methodological conflations, and default-assignment risks that would compromise quantitative real estate valuation and financial investment modeling.

This audit details the current state, catalogs existing bugs and anti-patterns, classifies analytical features into four tiers, and specifies the architecture to upgrade the system into an evidence-backed real estate investment intelligence platform.

---

## 2. Inventory of Current Features & Structural Findings

| Component | Status | Finding / Defect | Required Correction |
|---|---|---|---|
| **`projects` Schema Defaults** | **Defective** | Columns `project_type DEFAULT 'Residential'`, `ready_to_move_status DEFAULT FALSE`, `structural_completion_status DEFAULT FALSE`, and `complaint_count DEFAULT 0` silently substitute assumed values when the source is silent. | Alter schema and parser: genuine unknowns must remain `NULL`. Never substitute `False` or `0` for unobserved facts. |
| **Possession Timeline Logic** | **Defective** | `possession_extension_status` defaulted to `"On Schedule"` whenever a possession date was present and no extension note was detected. | Demote to `"Not Reported"` or `"Unspecified"`. Do not infer that a project is on schedule merely because a possession date exists. |
| **Synthetic FAQs** | **Anti-Pattern** | `generate_project_faqs()` synthetically synthesized question-answer text out of extracted data and stored them as primary data in `project_faqs`. | Remove synthetic FAQ generation from primary analytical dataset. Only store real, source-published FAQs (`is_synthesized = FALSE`). |
| **Snapshot Reprocessing** | **Architectural Bug** | `project_snapshots` enforces `UNIQUE (project_key, content_sha256)`. When a newer parser version runs against previously scraped HTML, `ON CONFLICT DO NOTHING` silently aborts reprocessing, leaving obsolete analytical rows intact. | Update constraint to `UNIQUE (project_key, content_sha256, parser_version)` or provide explicit snapshot upgrade handling that refreshes analytical tables. |
| **Price Semantics Distinction** | **Methodological Risk** | FlatNama publishes an **annual 80th-percentile benchmark** of registered sales, not individual transaction deed prices. There is no separate table for actual registered deed transactions (IGR) or asking-price listings. | Create distinct tables: `project_price_observations` (for FlatNama benchmarks), `property_listings` (for asking prices), and `registered_transactions` (for official IGR deed records). |
| **Individual Flat Features** | **Missing** | Current schema models project-level aggregates only. Downstream hedonic modeling and unit valuation require unit-level records (carpet area, floor, orientation, parking). | Introduce `individual_properties` entity cleanly separated from project aggregates. |
| **Financial Engine** | **Missing** | No cash flow modeling, loan amortization, rental economics, or scenario DCF analysis exists to answer H1 (financial attractiveness over 5, 10, 15 years vs equity/debt). | Implement `financial_model.py` supporting 5/10/15 year DCF, IRR, NPV, Cash-on-Cash, tax deductions (Sec 24b, 80C, LTCG), and sensitivity analysis. |
| **Locality & Macro Data** | **Missing** | Localities lack coordinates, distances to major Pune IT hubs (Hinjawadi, Kharadi, Magarpatta), transit lines (Metro lines 1, 2, 3), and macro rates (repo rate, inflation). | Implement `locations` and `macroeconomic_indicators` tables with GIS distance calculations. |
| **Database Migrations** | **Missing** | Schema updates rely solely on raw `CREATE TABLE IF NOT EXISTS` in `schema.sql`, without version tracking or safe backfills. | Implement a formal migration framework (`migrations/` directory + `schema_migrations` tracking table + `migrate.py`). |
| **Entity Resolution** | **Missing** | No formal framework to resolve entities across sources (RERA ID, name similarity, address matching). | Implement `entity_match_candidates` table and resolution pipeline. |

---

## 3. Decision-Driven Feature Classification (Parts 3 & 13)

### Tier 1: Essential (Core Valuation & Financial Decisions)
- **Project Identity**: MahaRERA registration number (primary legal key), project name, developer/promoter name, project phase/wing name.
- **Location**: Locality, PIN code, geographic coordinates, distance to key employment clusters.
- **Timeline & Risk**: Registered launch date, original registered possession date, current registered possession date, verified extension months, elapsed months, remaining months.
- **Physical Progress**: Excavation %, RCC/structural %, final finishes %, reported progress date.
- **Inventory & Absorption**: Total registered units, units booked, units available, configuration breakdown (1 RK, 1-5 BHK), booking percentage.
- **Price Benchmarks**: Reporting year, 80th-percentile rate per sq ft, sales count, YoY percentage change (strictly linked to previous observation), area basis.
- **Financial Inputs**: Purchase price, stamp duty (6% + 1% metro cess), registration fee (1% capped at ₹30k), GST (0% or 5%), loan interest rate, loan tenure, gross rent, vacancy allowance, society maintenance.

### Tier 2: High-Value (Risk Assessment & Comparable Selection)
- Size-wise price bands (min/max price for carpet area ranges).
- Historical progress deltas ($\Delta \text{RCC}$, $\Delta \text{Finishing}$, $\Delta \text{Bookings}$).
- Developer delivery track record (historical delay index across previous projects).
- Neighborhood comparative pricing (% premium/discount vs micro-market peers).
- Proximity to transit (Pune Metro stations, ring road).

### Tier 3: Optional Enrichment
- Sibling phases and parent development links.
- Area catalogue summary statistics (total projects launched in area).
- External RERA verification links.

### Tier 4: Exclude from Primary Analytical Dataset
- **Synthetic FAQs** (discarded from analytical processing).
- **DOM clutter & raw HTML dumps** (buttons, generic navigation tags, client-side tracking attributes).
- **Assumed / Defaulted booleans and strings** when source is silent (`'Residential'`, `False`, `0`).

---

## 4. Implementation Plan

1. **Database Schema & Migrations (`migrations/` & `migrate.py`)**:
   - Migration 001: Baseline schema with snapshot reprocessing fix and removal of invalid defaults.
   - Migration 002: Decision-driven entities (`locations`, `individual_properties`, `property_listings`, `registered_transactions`, `macroeconomic_indicators`, `entity_match_candidates`, `financial_assumptions`).
   - Migration 003: Analytical and investment views supporting Hypotheses H1, H2, H3, and H4.
2. **Parser Upgrades (`scraper.py`)**:
   - Remove bogus default assignments (`project_type`, `ready_to_move`, `complaint_count`, `possession_extension_status`). Genuine unknowns remain `None`/`NULL`.
   - Remove synthetic FAQ generation.
   - Ensure snapshot reprocessing updates structured tables when parser version increments.
3. **Financial & Investment Calculations Engine (`financial_model.py`)**:
   - Comprehensive DCF model evaluating H1 (5, 10, 15-year holding periods, loan amortization, rental yields, tax rules, alternative equity/debt comparisons, Bear/Base/Bull scenarios).
   - Locality ranking model evaluating H2.
   - Project value scoring evaluating H3.
   - Hedonic dataset preparation and temporal validation evaluating H4.
4. **Entity Resolution (`entity_resolution.py`)**:
   - Exact RERA matching, normalized text matching, and candidate logging.
5. **Data Quality Framework (`data_quality.py`)**:
   - Validation rules, range checks, temporal sequence audits, provenance tracking.
6. **CSV Export System Upgrade (`export_data.py`)**:
   - Include financial models, locality rankings, and valuation exports.
7. **Comprehensive Automated Tests**:
   - Parser regression tests, financial model tests, migration tests, and repeatable import verification.
