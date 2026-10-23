import os
import unittest
import psycopg
from dotenv import load_dotenv

from pathlib import Path
from migrate import apply_migrations
from import_report import import_json_report
from export_data import export_from_db

load_dotenv()
DB_URL = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")


@unittest.skipUnless(DB_URL, "PostgreSQL database URL not configured in environment")
class DatabaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Verify connection
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                res = cur.fetchone()
                assert res[0] == 1

    def test_01_migrations_apply_idempotently(self):
        applied = apply_migrations(DB_URL)
        # Applying migrations again on an up-to-date DB should return 0 new migrations
        self.assertEqual(len(applied), 0)

    def test_02_views_are_queryable(self):
        views_to_test = [
            "v_projects_master",
            "v_project_delays_and_progress",
            "v_project_pricing_summary",
            "v_project_inventory_summary",
            "v_investment_h1_cashflows",
            "v_locality_h2_rankings",
            "v_project_h3_value_scores",
            "v_hedonic_h4_dataset",
        ]
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                for v in views_to_test:
                    cur.execute(f"SELECT COUNT(*) FROM {v};")
                    count = cur.fetchone()[0]
                    self.assertGreaterEqual(count, 0, f"View {v} query failed")

    def test_03_repeat_import_idempotency(self):
        sample_path = "reports/deccan_sample_v3.json"
        if not os.path.exists(sample_path):
            self.skipTest("Sample report not present")

        # Import once
        count1 = import_json_report(Path(sample_path), DB_URL)
        # Import second time
        count2 = import_json_report(Path(sample_path), DB_URL)
        self.assertEqual(count1, count2)

        # Check that projects count didn't duplicate
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(DISTINCT project_key), COUNT(*) FROM projects;")
                distinct_cnt, total_cnt = cur.fetchone()
                self.assertEqual(distinct_cnt, total_cnt, "Projects table has duplicate project_key records!")

    def test_04_export_script_produces_files(self):
        counts = export_from_db(DB_URL, Path("exports"))
        self.assertGreater(len(counts), 10)
        for filename in counts:
            filepath = Path("exports") / filename
            self.assertTrue(filepath.exists(), f"Exported file {filepath} not found")
            self.assertGreater(filepath.stat().st_size, 0, f"Exported file {filepath} is empty")


if __name__ == "__main__":
    unittest.main()
