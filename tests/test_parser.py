import unittest
from scraper import parse_project_page, project_links_from_html, is_project_url

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

    def test_area_page_link_discovery_is_host_scoped(self):
        html = '''<a href="/pune/p52100012345-example-towers/">Project A</a>
                  <a href="https://example.com/pune/p52100088888-not-flatnama/">external</a>
                  <a href="/pune/deccan/">area</a>'''
        links = project_links_from_html(html, "https://flatnama.com/pune/deccan/")
        self.assertEqual(links, ["https://flatnama.com/pune/p52100012345-example-towers/"])

if __name__ == "__main__":
    unittest.main()
