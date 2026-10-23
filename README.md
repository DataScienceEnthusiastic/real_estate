# FlatNama → PostgreSQL research collector

A small, versioned collector for **research-sized, permission-respecting samples** of FlatNama project pages. It extracts structured project details, annual sold-price summaries, size/price bands, construction updates and comparison rows, then stores them in PostgreSQL with source URLs, hashes, crawl logs and historical snapshots.

## Important scope and data-quality limits

FlatNama's [Terms of Use](https://flatnama.com/terms-and-privacy/) say that pages may be linked, shared and quoted with attribution, welcome well-behaved crawlers, ask visitors not to overload the site, and state: **“Please don’t copy the site as a whole.”** This tool therefore has small default limits and does not automatically spider the entire Pune catalogue. Obtain explicit written permission from FlatNama before expanded or whole-catalog collection. The `--authorized-bulk` guard is an extra safety check, not permission itself.

FlatNama's own [guide](https://flatnama.com/guides/) says project information reflects developer reports to MahaRERA and may be incomplete or incorrect, and that government sale records obtained by FlatNama may not include every sale. This project preserves those caveats.

**Important:** FlatNama usually shows *project-level annual price summaries*, such as a price threshold that 80% of observed flats sold at or below, plus a sale count and common flat-size/price band. These are **not unit-level transaction records**. The scraper does not invent exact transaction prices, individual floor plans, balcony views, road frontage or unit-level facts that the source page does not expose. Those features require other sources and/or direct inspection.

Raw HTML and images are **not** stored. The database stores structured extractions, a content hash, URL and selected image URL metadata only. It does not bypass CAPTCHA, authentication, robots.txt, 403/429 responses or other access controls.

## What is collected

- Project identity: displayed name, MahaRERA identifier, developer, locality, PIN code, canonical URL and map link (when exposed).
- Dates and status: launch date text, registered possession date text, status/stage shown, original possession date when parseable.
- Inventory: total units, mix of RK/BHK/other units, reported units for sale/booked and derived booked percentage when the page exposes enough information, building count, land area and complaint count.
- Build progress: excavation, RCC structure and final-finishes percentages, plus visible dated MahaRERA progress rows.
- Price summaries: annual year labels, displayed price-per-sq-ft threshold, count of observed registrations, and size/price bands where available.
- Comparisons: comparable-project names and raw row labels when table structure permits extraction.
- Provenance: source URL, fetch time, HTTP status, SHA-256 content hash, parser version, each crawl run, and versioned JSON snapshots.

The HTML layout can change. Null means “not confidently parsed”; it does not mean zero. Review a small sample of values against the rendered pages before treating the parsed data as analytically ready.

## Setup

Requirements: Python 3.11+ and Docker Desktop (or a PostgreSQL 15+ server).

1. Unzip this folder and open a terminal in it.
2. Create a `.env` file by copying `.env.example`. Set `FLATNAMA_USER_AGENT` to a descriptive name and a real contact channel.
3. Start PostgreSQL:

   ```bash
   docker compose up -d db
   ```

   The first start creates the schema from `schema.sql`. If you have an existing database, the scraper also applies the schema when it connects.

4. Create a virtual environment and install Python dependencies:

   **Windows PowerShell**
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

   **macOS/Linux**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

5. In `.env`, replace `your-email@example.com` with a valid contact address and verify `DATABASE_URL` matches your PostgreSQL login.

## Run a small sample

`seed_urls.txt` contains one area page and one project page as examples. The default run only processes explicit area pages and explicit project pages; it does not follow other links unless you opt in.

```bash
python scraper.py --input seed_urls.txt --dry-run
python scraper.py --input seed_urls.txt
```

To discover project links from a small set of area pages and collect at most 25 project pages in that run:

```bash
python scraper.py --input seed_urls.txt --discover-project-links --max-area-pages 5 --max-project-pages 25
```

The collector waits at least 2.5 seconds between HTTP requests by default. It checks robots.txt first. If the request is forbidden, rate-limited, challenged, or robots.txt disallows access, it stops rather than trying to work around the restriction. It does not use proxy rotation, browser stealth, CAPTCHA solving or concurrent request bursts.

### Expanded / bulk runs

Do not run an entire-catalogue scrape just because the links are publicly visible. FlatNama's Terms of Use say not to copy the site as a whole. Request written permission or a data-sharing arrangement from the site operators first. Once permission is granted, set `FLATNAMA_BULK_PERMISSION_CONFIRMED=1` in `.env` and pass `--authorized-bulk`; the code still follows robots.txt, throttling and stop-on-403/429 rules.

## Inspect the database

Connect with `psql` or a GUI such as DBeaver. Useful tables:

- `projects`: latest normalized project-level view.
- `project_snapshots`: full structured extraction per changed page (JSONB; historical view).
- `project_sale_year_stats`: annual price/sales-count summaries shown by FlatNama; not individual deed records.
- `project_size_price_bands`: common size/price ranges described on project pages.
- `project_unit_mix`: reported unit counts by configuration.
- `project_progress_updates`: dated progress history when it is visible in a parseable table.
- `project_comparables`: visible peer rows.
- `source_pages`, `scrape_runs`: provenance, status, hashes and errors.

Example queries are in `queries.sql`.

## Updating safely

- Re-run the same seed list periodically. `projects` upserts the latest values; `project_snapshots` stores new snapshots only when page content changes.
- Review `source_pages.parse_status`, null rates and snapshots after each run.
- If parsing degrades, save a manually supplied local HTML fixture from a page you are authorized to retain and write a parser test against it. Do not defeat access controls to obtain fixtures.
- Keep the source URL and observed timestamp with every feature. Cite FlatNama in downstream research, and clearly distinguish data “reported by FlatNama” from “verified against the original MahaRERA/IGR record.”

## Known limitations in v0.1

- CSS/HTML structure has not been validated against a live fetch in the authoring environment; internet DNS access was unavailable during package creation. This version has been syntax-checked, but you should run `--dry-run` and inspect the first records on your own machine before a longer collection.
- Date/status fields intentionally remain strings because source wording can vary; normalize to dates only after validation.
- Project-level statistics are not flat-level sales records. No row should be represented as a specific deed-level transaction without original transaction evidence.
- The current parser is heuristic and needs fixture-backed tests before production investment analysis.
