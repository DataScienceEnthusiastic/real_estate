# Data dictionary and interpretation rules

## Core table: `projects`

| Column | Meaning | Interpretation rule |
|---|---|---|
| `project_key` | Internal stable key; normally MahaRERA registration number | Separate RERA phases remain separate entities. |
| `rera_number` | Number shown on FlatNama project page | Verify against MahaRERA before investment decisions. |
| `project_name` | Page heading | May contain the locality in the display name; use as display text, not as a unique key. |
| `developer` | Developer string parsed from page copy | May be absent or have formatting differences. |
| `locality`, `pin_code` | Locality/PIN in the page description | Not a verified geocode or parcel boundary. |
| `maharera_status` | MahaRERA project status when parseable | Reported status, not a legal due-diligence conclusion. |
| `construction_stage` | FlatNama's display stage | Distinguishes early, mid-construction, nearing possession and ready-to-move labels. “Nearing possession” is not equivalent to an occupancy certificate. |
| `launch_date_text` | Month/year shown as launch | FlatNama defines launch as the MahaRERA registration month. |
| `possession_date_text` | Date registered with MahaRERA as shown by FlatNama | A registered target date, not a promise that handover has occurred. |
| `original_possession_date_text` | Original date only when explicitly parseable | Null is not evidence that no extension occurred. |
| `total_units` | Displayed total units | May include shops/offices/other units, not only residences. |
| `units_for_sale` | Units for sale if displayed or derivable from total less “not for sale” count | The derivation is flagged in the latest JSON object. |
| `units_booked` | Reported booked/sold count | It can reflect developer reporting and may be revised. |
| `booking_pct` | Booked divided by units for sale, when both numbers are available | This is a derived ratio; store the inputs too. It is not always comparable across project phases. |
| `building_count`, `land_acres` | Displayed building and project land figures | Project-level, not a unit characteristic. |
| `excavation_pct`, `rcc_pct`, `finishing_pct` | Progress figures when parseable | Developer-reported progress, and for multi-building projects may be an average. |
| `complaint_count` | Displayed MahaRERA complaints count if parseable | The page notes that this can include complaints filed by the builder against buyers; read case details separately. |
| `latest_sale_year` | Most recent sales-summary year parsed from a page | Not necessarily the page update date. |
| `price_per_sqft_80pct` | Latest displayed project price threshold | FlatNama describes this as the rate at or below which 80% of flats sold in the period went. It is not the mean/median, not the price for a specific flat and not an individual sale record. |
| `latest_sale_count` | Number of registered sales found for that summary | Coverage may be incomplete; preserve the count alongside each rate. |
| `map_url` | Google Maps link shown by the page, if present | Link only; the collector does not geocode a precise property centroid. |
| `raw_latest` | Latest structured extraction as JSONB | Includes fields not promoted to SQL columns. This is structured extraction, not the raw HTML page. |
| `first_seen_at`, `last_seen_at`, `last_scraped_at` | Collection timestamps | Last seen/scraped refers to this collector, not necessarily FlatNama's last update. |

## Versioned observations

- `project_snapshots.data` stores all extracted fields for a particular page-content hash, including source notes, image URL metadata, size/price bands, flat configuration, sales summaries and progress rows.
- `project_sale_year_stats` stores project-level year-by-year summaries. A record means “this project page displayed this year/rate/sales count”, not “this is a specific transaction”.
- `project_size_price_bands` stores the common size and price ranges shown on project pages. FlatNama states that sizes for its sold-price metric count carpet plus balcony plus terrace; these sizes should not be mixed silently with RERA carpet area from other sources.
- `project_unit_mix` stores visible configuration/count rows such as `2 BHK` and number of units.
- `project_progress_updates` stores dates/labels and visible excavation/RCC/final-finish/booking figures.
- `project_comparables` records visible similar-project row names and the original row data for additional parsing later.
- `source_pages` and `scrape_runs` support auditability and troubleshooting.

## Features not established by FlatNama pages

Do not expect this source to provide, for each individual unit, the exact registered deed consideration, unique flat number, exact carpet area, floor, orientation, balcony view, direct road frontage, noise level, structural condition, title encumbrances, asking-price history, final negotiated price, rental yield or buyer's all-in cost. Those need official deed matching, listing sources, maps, document reviews, site inspections and/or explicit data-sharing arrangements.
