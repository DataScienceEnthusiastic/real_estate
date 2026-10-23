import unittest
from entity_resolution import (
    normalize_text,
    token_similarity,
    match_project_to_external_record,
    MatchCandidate,
)


class EntityResolutionTests(unittest.TestCase):
    def test_normalize_text(self):
        raw = "VTP Realty Pvt. Ltd. (Bellissimo), Pune!"
        normalized = normalize_text(raw)
        self.assertNotIn("pvt", normalized)
        self.assertNotIn("ltd", normalized)
        self.assertNotIn("!", normalized)
        self.assertIn("vtp", normalized)
        self.assertIn("bellissimo", normalized)
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text(""), "")

    def test_token_similarity_jaccard(self):
        s1 = "Rohan Abhilasha Phase 1"
        s2 = "Rohan Abhilasha Phase 2"
        sim = token_similarity(s1, s2)
        # 3 shared tokens ('rohan', 'abhilasha', 'phase') out of 5 total unique tokens ('1', '2') => 3/5 = 0.6
        self.assertAlmostEqual(sim, 0.6, places=2)

        s3 = "Godrej Properties Megapolis"
        s4 = "Kolte Patil Life Republic"
        self.assertEqual(token_similarity(s3, s4), 0.0)

    def test_tier1_exact_rera_id_match(self):
        cand = match_project_to_external_record(
            project_key="pune-kharadi-vtp-cygnus",
            project_rera="P52100021234",
            project_name="VTP Cygnus Phase 1",
            developer="VTP Realty",
            locality="Kharadi",
            external_record={
                "ref_id": "igr_doc_998811",
                "rera_number": "p52100021234",  # Case insensitive
                "project_name": "Cygnus Luxury",
                "locality": "Kharadi",
            },
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand.method, "exact_rera_id")
        self.assertEqual(cand.confidence, 1.0)
        self.assertEqual(cand.status, "auto_merged")

    def test_tier2_exact_name_and_locality_match(self):
        cand = match_project_to_external_record(
            project_key="pune-hinjawadi-megapolis",
            project_rera=None,
            project_name="Megapolis Mystic",
            developer="Pegasus",
            locality="Hinjawadi",
            external_record={
                "ref_id": "listing_44221",
                "project_name": "Megapolis Mystic Pvt Ltd",
                "locality": "Hinjawadi",
            },
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand.method, "exact_name_locality")
        self.assertEqual(cand.confidence, 0.90)
        self.assertEqual(cand.status, "verified_match")

    def test_tier3_fuzzy_token_similarity_unresolved_match(self):
        cand = match_project_to_external_record(
            project_key="pune-baner-panchshil-towers",
            project_rera=None,
            project_name="Panchshil Towers Tower A",
            developer="Panchshil",
            locality="Baner",
            external_record={
                "ref_id": "listing_8877",
                "project_name": "Panchshil Towers Residential A",
                "locality": "Baner",
            },
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand.method, "fuzzy_token_similarity")
        self.assertGreaterEqual(cand.confidence, 0.60)
        self.assertEqual(cand.status, "unresolved")

    def test_non_matching_different_locality(self):
        cand = match_project_to_external_record(
            project_key="pune-wakad-project-x",
            project_rera="P52100099999",
            project_name="Pride Purple Park",
            developer="Pride Purple",
            locality="Wakad",
            external_record={
                "ref_id": "listing_123",
                "rera_number": "P52100011111",
                "project_name": "Pride Purple Park",
                "locality": "Hadapsar",  # Different locality & RERA
            },
        )
        self.assertIsNone(cand)


if __name__ == "__main__":
    unittest.main()
