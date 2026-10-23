import unittest
from data_quality import validate_project_record, QualityIssue


class DataQualityTests(unittest.TestCase):
    def test_clean_record_passes_without_critical_issues(self):
        clean_p = {
            "project_key": "pune-wakad-clean-residency",
            "project_name": "Clean Residency",
            "rera_number": "P52100012345",
            "launch_year": 2021,
            "possession_year": 2024,
            "total_units": 200,
            "units_booked": 150,
            "rcc_pct": 85.0,
            "finishing_pct": 40.0,
            "price_per_sqft_80pct": 8200.0,
        }
        issues = validate_project_record(clean_p)
        critical = [i for i in issues if i.severity == "CRITICAL"]
        self.assertEqual(len(critical), 0)

    def test_missing_project_name_critical(self):
        p = {"project_key": "pune-test-1", "project_name": "", "rera_number": "P52100012345"}
        issues = validate_project_record(p)
        names = [i.field_name for i in issues if i.severity == "CRITICAL"]
        self.assertIn("project_name", names)

    def test_percentage_range_violation(self):
        p = {
            "project_key": "pune-test-2",
            "project_name": "Test Towers",
            "rcc_pct": 105.0,  # Invalid: > 100%
            "finishing_pct": -5.0,  # Invalid: < 0%
        }
        issues = validate_project_record(p)
        violated_fields = [i.field_name for i in issues if i.issue_type == "range_violation"]
        self.assertIn("rcc_pct", violated_fields)
        self.assertIn("finishing_pct", violated_fields)

    def test_chronology_error(self):
        p = {
            "project_key": "pune-test-3",
            "project_name": "Time Travel Heights",
            "launch_year": 2025,
            "possession_year": 2020,  # Impossible: possession before launch
        }
        issues = validate_project_record(p)
        chron_issues = [i for i in issues if i.issue_type == "chronology_error"]
        self.assertEqual(len(chron_issues), 1)
        self.assertEqual(chron_issues[0].severity, "CRITICAL")

    def test_price_sanity_and_outlier(self):
        p_zero = {
            "project_key": "pune-test-4",
            "project_name": "Zero Price Apartments",
            "price_per_sqft_80pct": 0.0,
        }
        issues_zero = validate_project_record(p_zero)
        self.assertTrue(any(i.field_name == "price_per_sqft_80pct" and i.severity == "CRITICAL" for i in issues_zero))

        p_outlier = {
            "project_key": "pune-test-5",
            "project_name": "Ultra Luxury Castle",
            "price_per_sqft_80pct": 250_000.0,  # Warning outlier (> 100,000)
        }
        issues_outlier = validate_project_record(p_outlier)
        self.assertTrue(any(i.issue_type == "outlier_warning" and i.severity == "WARNING" for i in issues_outlier))

    def test_unsupported_inferred_boolean_flagged(self):
        p = {
            "project_key": "pune-test-6",
            "project_name": "Defaulted Boolean Project",
            "rcc_pct": None,
            "structural_completion_status": False,  # Should have been None when rcc_pct is None
        }
        issues = validate_project_record(p)
        inferred = [i for i in issues if i.issue_type == "unsupported_inferred_value"]
        self.assertEqual(len(inferred), 1)


if __name__ == "__main__":
    unittest.main()
