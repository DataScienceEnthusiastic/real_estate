import unittest
from financial_model import (
    AcquisitionCosts,
    LoanSchedule,
    RentalEconomics,
    compute_irr,
    compute_npv,
    evaluate_investment_h1,
    evaluate_investment_scenarios_h1,
    compute_locality_ranking_score_h2,
    evaluate_project_value_h3,
)


class FinancialModelTests(unittest.TestCase):
    def test_acquisition_costs_calculation(self):
        acq = AcquisitionCosts(purchase_price=10_000_000.0, is_ready_to_move=False)
        self.assertEqual(acq.stamp_duty_inr, 600_000.0)         # 6%
        self.assertEqual(acq.registration_fee_inr, 30_000.0)    # Capped at ₹30,000
        self.assertEqual(acq.brokerage_inr, 100_000.0)          # 1%
        self.assertEqual(acq.gst_inr, 500_000.0)                # 5% for under construction
        self.assertEqual(acq.down_payment_inr, 2_000_000.0)     # 20%
        self.assertAlmostEqual(acq.total_acquisition_cost, 11_305_000.0)

    def test_ready_to_move_gst_exemption(self):
        acq = AcquisitionCosts(purchase_price=10_000_000.0, is_ready_to_move=True)
        self.assertEqual(acq.gst_inr, 0.0)

    def test_loan_amortization_schedule(self):
        loan = LoanSchedule(principal=8_000_000.0, annual_interest_rate=0.085, tenure_years=20)
        # Standard EMI for ₹80L @ 8.5% 20y is approx ₹69,425.86
        self.assertAlmostEqual(loan.monthly_emi, 69425.86, places=1)
        amort10 = loan.amortization_at_year(10)
        # Outstanding principal should be lower than initial principal
        self.assertLess(amort10["outstanding_principal"], 8_000_000.0)
        self.assertGreater(amort10["cumulative_principal_paid"], 2_000_000.0)
        self.assertGreater(amort10["cumulative_interest_paid"], 4_000_000.0)

    def test_rental_economics_and_yields(self):
        rent = RentalEconomics(purchase_price=10_000_000.0, carpet_area_sqft=1000.0)
        self.assertEqual(rent.gross_annual_rent_yr1, 320_000.0)  # 3.2%
        self.assertAlmostEqual(rent.vacancy_loss_yr1, 26_656.0, places=0)
        self.assertGreater(rent.net_operating_income_yr1, 200_000.0)
        self.assertLess(rent.net_rental_yield_pct, 3.20)

    def test_irr_and_npv_computation(self):
        # Initial outflow -100, followed by +40, +40, +40
        cfs = [-100.0, 40.0, 40.0, 40.0]
        irr = compute_irr(cfs)
        self.assertIsNotNone(irr)
        self.assertAlmostEqual(irr, 9.70, places=1)
        npv = compute_npv(0.097, cfs)
        self.assertAlmostEqual(npv, 0.0, places=0)

    def test_h1_investment_evaluation(self):
        res = evaluate_investment_h1(
            purchase_price=10_000_000.0,
            holding_years=10,
            annual_appreciation_rate=0.06,
            annual_inflation_rate=0.051,
        )
        self.assertIn("nominal_irr_pct", res)
        self.assertIn("real_irr_pct", res)
        self.assertIn("npv_at_9pct_inr", res)
        self.assertIn("alternative_nifty50_terminal_equity", res)
        # Real IRR must be less than Nominal IRR by approximately the inflation rate
        self.assertLess(res["real_irr_pct"], res["nominal_irr_pct"])

    def test_h1_scenarios_matrix(self):
        scenarios = evaluate_investment_scenarios_h1(purchase_price=10_000_000.0)
        self.assertIn("bear_case", scenarios)
        self.assertIn("base_case", scenarios)
        self.assertIn("bull_case", scenarios)
        # Bull case IRR should exceed Bear case IRR
        bull_irr = scenarios["bull_case"]["10_year"]["nominal_irr_pct"]
        bear_irr = scenarios["bear_case"]["10_year"]["nominal_irr_pct"]
        self.assertGreater(bull_irr, bear_irr)

    def test_h2_locality_ranking(self):
        score_high = compute_locality_ranking_score_h2(
            median_price_sqft=18000,
            yoy_price_growth_pct=8.5,
            booking_absorption_pct=80.0,
            delayed_project_pct=5.0,
            dist_to_nearest_it_hub_km=5.0,
            metro_operational=True,
        )
        score_low = compute_locality_ranking_score_h2(
            median_price_sqft=12000,
            yoy_price_growth_pct=1.0,
            booking_absorption_pct=25.0,
            delayed_project_pct=40.0,
            dist_to_nearest_it_hub_km=25.0,
            metro_operational=False,
        )
        self.assertGreater(score_high, score_low)

    def test_h3_project_value_evaluation(self):
        # 12% discount to locality with zero delay and 80% RCC
        res_good = evaluate_project_value_h3(
            subject_rate_sqft=17600,
            locality_median_rate_sqft=20000,
            possession_delay_months=0,
            rcc_pct=80.0,
            complaint_count=0,
        )
        self.assertEqual(res_good["value_category"], "Attractive Value Opportunity")
        self.assertTrue(res_good["is_value_discount"])

        # 25% premium to locality
        res_over = evaluate_project_value_h3(
            subject_rate_sqft=25000,
            locality_median_rate_sqft=20000,
        )
        self.assertEqual(res_over["value_category"], "Premium Overpriced")


if __name__ == "__main__":
    unittest.main()
