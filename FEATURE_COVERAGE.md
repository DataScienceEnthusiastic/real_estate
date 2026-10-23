# Source feature coverage matrix

This matrix prevents a common modeling mistake: treating features that FlatNama does not publish as scraper failures.

| Feature family | FlatNama supports | Scraper status | Additional source needed? |
|---|---|---|---|
| Project name, registration ID, developer, locality/PIN | Commonly shown | Parsed | Verify against MahaRERA |
| Launch and possession dates, status | Commonly shown | Parsed when wording matches | Verify against MahaRERA |
| Total units, BHK/RK mix, bookings | Often shown; layouts vary | Parsed with QA checks; may be null if unreported | MahaRERA for verification |
| Building count and project land area | Often shown | Parsed when text is present | Source documents for verification |
| Dated excavation/RCC/final-finish progress | Commonly shown in a table | Parsed from table rows | Official MahaRERA filings for verification |
| Annual price-per-sq-ft 80%-threshold + sale count | Shown for many, not all projects | Parsed from table/list/card layouts | IGR docs to verify the underlying observations |
| Common flat-size/price bands | Shown for some projects | Parsed when both a size and price band are visible | IGR transaction-level linkage for true comparables |
| Similar-project comparisons | Shown for some projects | Parsed where tables are recognized | Validate metric definitions |
| Balcony view, orientation, floor-level outlook | Not established by project summary | Not collected | Unit photos and site inspection |
| Exact unit carpet area and specific flat identifier | Not reliably given for each unit | Not collected | Unit documents / approved plans |
| Direct road frontage, road width and access rights | Not reliably given per property | Not collected | Parcel maps, development plans, inspection and legal review |
| Asking price, price-change history, negotiation gap | Not the purpose of FlatNama | Not collected | Listing snapshots, seller/broker evidence, verified closing evidence |
| Exact individual registered sale deed price | FlatNama displays aggregate project-level summaries | Not collected as one row per transaction | Authorized IGR document search and transaction matching |
| Society maintenance, leakage, noise, structural condition | Not provided as unit-specific measured fields | Not collected | Site inspection / owner records / professional assessment |
