import unittest
from scraper import parse_area_page, parse_project_page, project_links_from_html, is_project_url

FIXTURE = '''
<!doctype html><html><head><meta property="og:image" content="https://flatnama.com/media/example.webp"></head><body>
<nav><a href="/pune/">Pune</a></nav>
<div class="breadcrumbs"><a href="/pune/areas/">All areas</a><a href="/pune/test-locality/">Test Locality</a></div>
<h1>Example Towers Phase 1, Test Locality</h1>
<div>Ready to move</div>
<div>by Example Developers Pvt Ltd. Test Locality, Pune 411111.</div>
<div>Launched May 2022</div>
<div>Possession date (MahaRERA) December 2025</div>
<div>Concrete structure (RCC) 100%</div>
<div>Units booked 70 of 80 units booked</div>
<div>1 building · 1.5 acres</div>
<div>Price per sq ft (incl. balconies and terrace) ₹12,500 2025 · 10 sales</div>
<div>Project facts</div>
<table><tr><td>1 BHK</td><td>10</td></tr><tr><td>2 BHK</td><td>50</td></tr><tr><td>3 BHK</td><td>20</td></tr><tr><td>Total units</td><td>80</td></tr></table>
<h3>Flat sizes and prices</h3><p>Based on flats sold in 2025.</p>
<table><tr><th>Flat size</th><th>What most buyers paid</th></tr><tr><td>700 – 800 sq ft</td><td>₹70 – 90 lakh</td></tr></table>
<h3>Price per sq ft, year by year</h3>
<table><tr><th>Year</th><th>Rate</th><th>Sales</th></tr><tr><td>2024</td><td>₹11,900 per sq ft</td><td>8 sales</td></tr><tr><td>2025</td><td>₹12,500 per sq ft</td><td>10 sales</td></tr></table>
<h3>Updates reported to MahaRERA</h3>
<table><tr><th>Update</th><th>Excavation</th><th>Structure (RCC)</th><th>Final finishes</th><th>Units booked</th></tr><tr><td>Dec 2024</td><td>100%</td><td>80%</td><td>40%</td><td>60</td></tr><tr><td>Jun 2025</td><td>100%</td><td>100%</td><td>100%</td><td>70</td></tr></table>
<div>Example Towers Phase 1 (MahaRERA P52100012345) is a residential project by Example Developers in Test Locality, Pune 411111. Its MahaRERA status is Active.</div>
<a href="https://www.google.com/maps/search/?api=1&query=Test+Locality" aria-label="View on Google Maps">View on Google Maps</a>
</body></html>
'''

LIST_STYLE_FIXTURE = '''
<!doctype html><html><body>
<h1>Venkatesh Erandwane Central Building B3</h1>
<div>by Shree Venkatesh Buildcon Pvt Ltd. Erandwane, Pune 411004.</div>
<h3>Price per sq ft, year by year</h3>
<p>80% of the flats sold in each year went for this price or less.</p>
<ul>
  <li>2024₹23,200per sq ft 20 registered sales found</li>
  <li>2025₹22,700per sq ft 42 registered sales found down 2% on 2024</li>
  <li>2026 so far₹23,800per sq ft 19 registered sales found up 5% on 2025</li>
</ul>
<h3>Other phases of this project</h3><p>Not part of the annual price section.</p>
<h3>About this project</h3><p>MahaRERA P52100032629.</p>
</body></html>
'''

class ParserTests(unittest.TestCase):
    def test_project_url_identification(self):
        self.assertTrue(is_project_url("https://flatnama.com/pune/p52100012345-example-towers/"))
        self.assertTrue(is_project_url("https://flatnama.com/pune/pr1261012600653-pristine-example/"))
        self.assertFalse(is_project_url("https://flatnama.com/pune/deccan/"))

    def test_project_page_extracts_core_fields(self):
        d = parse_project_page("https://flatnama.com/pune/p52100012345-example-towers/", FIXTURE)
        self.assertEqual(d["rera_number"], "P52100012345")
        self.assertIn("Example Towers", d["project_name"])
        self.assertEqual(d["developer"], "Example Developers Pvt Ltd")
        self.assertEqual(d["locality"], "Test Locality")
        self.assertEqual(d["pin_code"], "411111")
        self.assertEqual(d["possession_date_text"], "December 2025")
        self.assertEqual(d["maharera_status"], "Active")
        self.assertEqual(d["total_units"], 80)
        self.assertEqual(d["building_count"], 1)
        self.assertAlmostEqual(d["land_acres"], 1.5)
        self.assertEqual(d["latest_sale_year"], 2025)
        self.assertEqual(d["price_per_sqft_80pct"], 12500.0)
        self.assertEqual(d["latest_sale_count"], 10)
        self.assertTrue(any(x["flat_type"] == "2 BHK" and x["unit_count"] == 50 for x in d["flat_type_mix"]))
        self.assertTrue(any(x["sales_year"] == 2024 and x["sale_count"] == 8 for x in d["sale_year_stats"]))
        self.assertTrue(any(x["min_size_sqft"] == 700 and x["max_size_sqft"] == 800 for x in d["size_price_bands"]))
        self.assertTrue(any(x["update_label"] == "Jun 2025" and x["rcc_pct"] == 100 for x in d["progress_updates"]))
        self.assertIsNotNone(d["map_url"])

    def test_annual_price_summaries_rendered_as_list_are_extracted(self):
        d = parse_project_page("https://flatnama.com/pune/p52100032629-venkatesh-erandwane-central-building-b3/", LIST_STYLE_FIXTURE)
        values = {(x["sales_year"], x["price_per_sqft_80pct"], x["sale_count"]) for x in d["sale_year_stats"]}
        self.assertEqual(values, {(2024, 23200.0, 20), (2025, 22700.0, 42), (2026, 23800.0, 19)})
        self.assertEqual(d["latest_sale_year"], 2026)
        self.assertEqual(d["latest_sale_count"], 19)

    def test_current_card_layout_extracts_prices_inventory_size_and_progress(self):
        html = """<!doctype html><html><head><title>Venkatesh B3</title></head><body>
        <h1>Venkatesh Erandwane Central - BUILDING-B3 - Phase 4</h1>
        <p>by SHREE VENKATESH BUILDCON PVT LTD. Erandwane, Pune 411004.</p>
        <p>Launched January 2022 56 months promised</p>
        <p>Possession date (MahaRERA) September 2026</p>
        <p>Concrete structure (RCC) 100%</p>
        <p>Units booked 74 of 114 65% booked, out of 114 units</p>
        <p>Price per sq ft (incl. balconies and terrace) ₹23,800 80% of flats sold in 2026 went for this price or less 2026 so far · 19 registered sales found Rate about 10% higher than nearby projects up 5% on 2025</p>
        <p>1 building · 1 acres</p>
        <h3>Flat types</h3><ul><li>2 1 RK</li><li>60 2 BHK</li><li>52 3 BHK</li><li>114 Total units</li></ul>
        <h3>Flat sizes sold here (2023–26)</h3><ul><li>1,370 sq ft</li><li>1,620 sq ft</li></ul>
        <h3>What buyers paid here</h3><h4>Flat sizes and prices</h4>
        <table><tr><th>Flat size</th><th>What most buyers paid</th></tr><tr><td>1,370 sq ft</td><td>₹2.72 – 3.28 crore</td></tr></table>
        <h3>Price per sq ft, year by year</h3><p>80% of the flats sold in each year went for this price or less.</p>
        <ul><li>2024₹23,200per sq ft 20 registered sales found</li><li>2025₹22,700per sq ft 42 registered sales found down 2% on 2024</li><li>2026 so far₹23,800per sq ft 19 registered sales found up 5% on 2025</li></ul>
        <h3>Updates reported to MahaRERA</h3><table><tr><th>Update</th><th>Excavation</th><th>Structure (RCC)</th><th>Final finishes</th><th>Units booked</th></tr>
        <tr><td>Jul 2026</td><td>100%</td><td>100%</td><td>58%</td><td>74</td></tr><tr><td>Dec 2025</td><td>100%</td><td>100%</td><td>44%</td><td>74</td></tr></table>
        <p>Venkatesh Erandwane Central (MahaRERA P52100032629) is a residential project by SHREE VENKATESH BUILDCON PVT LTD in Erandwane, Pune 411004. It has 114 units.</p>
        </body></html>"""
        d = parse_project_page("https://flatnama.com/pune/p52100032629-venkatesh-erandwane-central-building-b3/", html)
        values = {(x["sales_year"], x["price_per_sqft_80pct"], x["sale_count"]) for x in d["sale_year_stats"]}
        self.assertEqual(values, {(2024, 23200.0, 20), (2025, 22700.0, 42), (2026, 23800.0, 19)})
        self.assertEqual(d["total_units"], 114)
        self.assertEqual(d["units_booked"], 74)
        self.assertEqual(d["flat_type_mix"], [
            {"flat_type": "1 RK", "unit_count": 2},
            {"flat_type": "2 BHK", "unit_count": 60},
            {"flat_type": "3 BHK", "unit_count": 52},
        ])
        self.assertEqual(d["flat_sizes_sold_sqft"], [1370.0, 1620.0])
        self.assertEqual(len(d["size_price_bands"]), 1)
        self.assertEqual(d["size_price_bands"][0]["min_price_inr"], 27_200_000.0)
        self.assertEqual(d["headline_price_per_sqft_80pct"], 23800.0)
        self.assertEqual(d["headline_price_year_label"], "2026 so far")
        self.assertEqual(d["headline_price_sale_count"], 19)
        self.assertEqual(d["price_per_sqft_80pct_source"], "annual_year_by_year")
        self.assertEqual(d["rate_vs_nearby_projects_pct"], 10.0)
        self.assertEqual(d["year_over_year_change_pct"], 5.0)
        self.assertEqual(d["year_over_year_comparison_year"], 2025)
        self.assertEqual(d["extraction_quality"]["warnings"], [])

    def test_headline_price_is_preserved_when_history_is_not_published(self):
        html = """<html><body><h1>Headline-Only Project</h1>
        <p>Price per sq ft (incl. balconies and terrace) ₹21,200 80% of flats sold in 2026 went for this price or less 2026 so far · 12 registered sales found</p>
        <p>Project details</p></body></html>"""
        d = parse_project_page("https://flatnama.com/pune/p52100012345-headline-only/", html)
        self.assertEqual(d["price_per_sqft_80pct"], 21200.0)
        self.assertEqual(d["price_per_sqft_80pct_source"], "headline_only")
        self.assertEqual(d["latest_sale_year"], 2026)
        self.assertEqual(d["latest_sale_count"], 12)
        self.assertIn("headline_price_found_but_year_by_year_rows_not_extracted_or_not_published", d["extraction_quality"]["warnings"])

    def test_area_page_summary_and_hidden_project_counts_are_parsed(self):
        html = """<html><head><title>New Projects in Dhayari</title></head><body>
        <h1>New projects in Dhayari</h1>
        <p>105 new residential projects in Dhayari (PIN 411041). 10 were launched in the last 6 months, 39 have their structure (RCC) complete, and 22 have had their possession date extended.</p>
        <p>52 projects · 53 small projects hidden</p>
        <button>Show small projects</button>
        <h3>Nearby areas</h3><a href="/pune/ambegaon/">Ambegaon</a><a href="/pune/warje/">Warje</a>
        </body></html>"""
        d = parse_area_page("https://flatnama.com/pune/dhayari/", html)
        self.assertEqual(d["area_name"], "Dhayari")
        self.assertEqual(d["pin_code"], "411041")
        self.assertEqual(d["listed_project_count"], 105)
        self.assertEqual(d["launched_last_6_months_count"], 10)
        self.assertEqual(d["rcc_complete_count"], 39)
        self.assertEqual(d["possession_date_extended_count"], 22)
        self.assertEqual(d["visible_projects_count_from_hidden_toggle"], 52)
        self.assertEqual(d["small_projects_hidden_count"], 53)
        self.assertEqual([x["name"] for x in d["nearby_areas"]], ["Ambegaon", "Warje"])

    def test_area_link_discovery_prefers_project_cards_over_related_links(self):
        html = """<div class="project-card">
          <h2><a href="/pune/p52100012345-project-a/">Project A</a></h2>
          <p>2 BHK, Erandwane</p><p>Possession date (MahaRERA) December 2027</p>
          <p>Concrete structure (RCC) 80% · Units booked 20 of 40</p>
        </div>
        <div class="other-phases"><a href="/pune/p52100088888-project-b/">Related phase only</a></div>"""
        from scraper import project_link_discovery_details
        links, method = project_link_discovery_details(html, "https://flatnama.com/pune/deccan/")
        self.assertEqual(links, ["https://flatnama.com/pune/p52100012345-project-a/"])
        self.assertEqual(method, "project_card_heuristic")

    def test_area_page_link_discovery_is_host_scoped(self):
        html = '''<a href="/pune/p52100012345-example-towers/">Project A</a>
                  <a href="https://example.com/pune/p52100088888-not-flatnama/">external</a>
                  <a href="/pune/deccan/">area</a>'''
        links = project_links_from_html(html, "https://flatnama.com/pune/deccan/")
        self.assertEqual(links, ["https://flatnama.com/pune/p52100012345-example-towers/"])

    def test_extended_timeline_phase_and_unit_breakdown(self):
        d = parse_project_page("https://flatnama.com/pune/p52100012345-example-towers/", FIXTURE)
        self.assertEqual(d["phase_name"], "Phase 1")
        self.assertEqual(d["project_type"], "Residential")
        self.assertEqual(d["launch_month"], "May")
        self.assertEqual(d["launch_year"], 2022)
        self.assertEqual(d["possession_month"], "December")
        self.assertEqual(d["possession_year"], 2025)
        self.assertEqual(d["ready_to_move_status"], True)
        self.assertEqual(d["structural_completion_status"], True)
        self.assertEqual(d["units_1bhk"], 10)
        self.assertEqual(d["units_2bhk"], 50)
        self.assertEqual(d["units_3bhk"], 20)
        self.assertEqual(d["total_residential_units"], 80)
        # Verify genuine FAQs only (not synthetically fabricated when absent)
        self.assertEqual(d["faqs"], [])

    def test_genuine_source_faqs_extracted_when_present(self):
        from bs4 import BeautifulSoup
        from scraper import extract_source_faqs
        html = """<div class="faq-section">
            <details class="faq-item"><summary>What are the society maintenance charges?</summary><p>Maintenance is ₹3.50 per sq ft monthly.</p></details>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        faqs = extract_source_faqs(soup)
        self.assertEqual(len(faqs), 1)
        self.assertIn("maintenance", faqs[0]["question"].lower())
        self.assertFalse(faqs[0]["is_synthesized"])

    def test_progress_deltas_computation(self):
        from scraper import compute_progress_deltas
        updates = [
            {"update_label": "Jul 2026", "excavation_pct": 100.0, "rcc_pct": 100.0, "finishing_pct": 58.0, "units_booked": 74},
            {"update_label": "Dec 2025", "excavation_pct": 100.0, "rcc_pct": 100.0, "finishing_pct": 44.0, "units_booked": 70},
        ]
        deltas = compute_progress_deltas(updates)
        self.assertEqual(deltas[0]["update_label"], "Jul 2026")
        self.assertEqual(deltas[0]["rcc_change"], 0.0)
        self.assertEqual(deltas[0]["finishing_change"], 14.0)
        self.assertEqual(deltas[0]["booking_change"], 4)
        self.assertIsNone(deltas[1]["rcc_change"])

    def test_csv_export_from_parsed_data(self):
        import tempfile
        import json
        from pathlib import Path
        from export_data import export_from_json
        d = parse_project_page("https://flatnama.com/pune/p52100012345-example-towers/", FIXTURE)
        sample = {
            "parser_version": "0.6.0",
            "run_id": "test-run",
            "status": "complete",
            "projects": [d],
            "area_discovery": []
        }
        with tempfile.TemporaryDirectory() as td:
            json_file = Path(td) / "sample.json"
            json_file.write_text(json.dumps(sample), encoding="utf-8")
            out_dir = Path(td) / "csvs"
            counts = export_from_json(json_file, out_dir)
            self.assertEqual(counts["projects_master.csv"], 1)
            self.assertTrue((out_dir / "projects_master.csv").exists())
            self.assertTrue((out_dir / "faqs.csv").exists())
            self.assertTrue((out_dir / "projects_complete.csv").exists())

if __name__ == "__main__":
    unittest.main()

