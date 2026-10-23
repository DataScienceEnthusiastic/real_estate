#!/usr/bin/env python3
"""Financial Planning, Real Estate Valuation, and Investment Calculations Engine.

Directly addresses:
- H1: Financial attractiveness of residential property in Pune over 5, 10, 15 years vs equity/debt.
- H2: Locality investment opportunity ranking.
- H3: Project and individual flat value scoring.
- H4: Hedonic price dataset preparation and temporal modeling diagnostics.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AcquisitionCosts:
    purchase_price: float
    is_ready_to_move: bool = False
    is_affordable_housing: bool = False  # <= 45 lakh and <= 60 sqm
    stamp_duty_rate: float = 0.06        # 5% Maharashtra + 1% Pune metro cess
    registration_fee_rate: float = 0.01   # 1%
    registration_fee_cap: float = 30000.0 # Maharashtra statutory cap
    brokerage_rate: float = 0.01         # 1%
    legal_due_diligence: float = 35000.0  # Document verification, title search
    loan_processing_rate: float = 0.005  # 0.5% bank processing fee
    loan_ltv_ratio: float = 0.80

    @property
    def stamp_duty_inr(self) -> float:
        return round(self.purchase_price * self.stamp_duty_rate, 2)

    @property
    def registration_fee_inr(self) -> float:
        return round(min(self.purchase_price * self.registration_fee_rate, self.registration_fee_cap), 2)

    @property
    def brokerage_inr(self) -> float:
        return round(self.purchase_price * self.brokerage_rate, 2)

    @property
    def gst_inr(self) -> float:
        if self.is_ready_to_move:
            return 0.0
        gst_rate = 0.01 if self.is_affordable_housing else 0.05
        return round(self.purchase_price * gst_rate, 2)

    @property
    def loan_processing_inr(self) -> float:
        loan_amount = self.purchase_price * self.loan_ltv_ratio
        return round(loan_amount * self.loan_processing_rate, 2)

    @property
    def total_closing_costs(self) -> float:
        return (
            self.stamp_duty_inr
            + self.registration_fee_inr
            + self.brokerage_inr
            + self.legal_due_diligence
            + self.gst_inr
            + self.loan_processing_inr
        )

    @property
    def total_acquisition_cost(self) -> float:
        return self.purchase_price + self.total_closing_costs

    @property
    def down_payment_inr(self) -> float:
        return round(self.purchase_price * (1.0 - self.loan_ltv_ratio), 2)

    @property
    def total_initial_cash_required(self) -> float:
        return self.down_payment_inr + self.total_closing_costs


@dataclass
class LoanSchedule:
    principal: float
    annual_interest_rate: float = 0.085  # 8.5% p.a.
    tenure_years: int = 20

    @property
    def monthly_interest_rate(self) -> float:
        return self.annual_interest_rate / 12.0

    @property
    def total_months(self) -> int:
        return self.tenure_years * 12

    @property
    def monthly_emi(self) -> float:
        if self.principal <= 0:
            return 0.0
        r = self.monthly_interest_rate
        n = self.total_months
        emi = (self.principal * r * (1.0 + r) ** n) / (((1.0 + r) ** n) - 1.0)
        return round(emi, 2)

    def amortization_at_year(self, year: int) -> dict[str, float]:
        """Calculates outstanding principal, interest paid, and principal paid up to target year."""
        r = self.monthly_interest_rate
        emi = self.monthly_emi
        balance = self.principal
        total_interest = 0.0
        total_principal = 0.0
        target_months = min(year * 12, self.total_months)

        for _ in range(target_months):
            interest_month = balance * r
            principal_month = emi - interest_month
            balance = max(0.0, balance - principal_month)
            total_interest += interest_month
            total_principal += principal_month

        return {
            "year": year,
            "monthly_emi": emi,
            "annual_debt_service": round(emi * 12, 2),
            "outstanding_principal": round(balance, 2),
            "cumulative_interest_paid": round(total_interest, 2),
            "cumulative_principal_paid": round(total_principal, 2),
        }


@dataclass
class RentalEconomics:
    purchase_price: float
    carpet_area_sqft: float = 1000.0
    gross_rental_yield_rate: float = 0.032      # 3.2% annual yield benchmark for Pune
    vacancy_rate: float = 0.0833                 # 1 month vacant per year (~8.33%)
    maintenance_sqft_per_month: float = 3.50     # ₹3.50/sqft/mo society maintenance
    property_tax_rate: float = 0.002             # 0.2% PMC/PCMC assessment
    property_insurance_annual: float = 5000.0    # Annual structural insurance
    annual_rent_growth_rate: float = 0.05        # 5% annual rent escalation

    @property
    def gross_annual_rent_yr1(self) -> float:
        return round(self.purchase_price * self.gross_rental_yield_rate, 2)

    @property
    def monthly_rent_yr1(self) -> float:
        return round(self.gross_annual_rent_yr1 / 12.0, 2)

    @property
    def vacancy_loss_yr1(self) -> float:
        return round(self.gross_annual_rent_yr1 * self.vacancy_rate, 2)

    @property
    def operating_expenses_yr1(self) -> float:
        maintenance = self.carpet_area_sqft * self.maintenance_sqft_per_month * 12.0
        tax = self.purchase_price * self.property_tax_rate
        return round(maintenance + tax + self.property_insurance_annual, 2)

    @property
    def net_operating_income_yr1(self) -> float:
        return round(self.gross_annual_rent_yr1 - self.vacancy_loss_yr1 - self.operating_expenses_yr1, 2)

    @property
    def net_rental_yield_pct(self) -> float:
        return round((self.net_operating_income_yr1 / self.purchase_price) * 100.0, 2)


def compute_irr(cash_flows: list[float], guess: float = 0.10, max_iter: int = 100, tol: float = 1e-6) -> float | None:
    """Computes Internal Rate of Return (IRR) via Newton-Raphson."""
    rate = guess
    for _ in range(max_iter):
        npv = sum(cf / ((1.0 + rate) ** t) for t, cf in enumerate(cash_flows))
        d_npv = sum(-t * cf / ((1.0 + rate) ** (t + 1)) for t, cf in enumerate(cash_flows))
        if abs(d_npv) < 1e-10:
            break
        new_rate = rate - npv / d_npv
        if abs(new_rate - rate) < tol:
            return round(new_rate * 100.0, 2)
        rate = new_rate
    return None


def compute_npv(discount_rate: float, cash_flows: list[float]) -> float:
    """Computes Net Present Value (NPV)."""
    return round(sum(cf / ((1.0 + discount_rate) ** t) for t, cf in enumerate(cash_flows)), 2)


def evaluate_investment_h1(
    purchase_price: float,
    carpet_area_sqft: float = 1000.0,
    holding_years: int = 10,
    annual_appreciation_rate: float = 0.06,  # 6% CAGR Base
    annual_inflation_rate: float = 0.051,    # 5.1% CPI inflation
    loan_interest_rate: float = 0.085,       # 8.5%
    loan_ltv: float = 0.80,                  # 80% LTV
    is_ready_to_move: bool = False,
    opportunity_equity_cagr: float = 0.115,  # 11.5% Nifty 50 CAGR
    opportunity_debt_cagr: float = 0.07,     # 7.0% Fixed Deposit CAGR
) -> dict[str, Any]:
    """Evaluates Hypothesis H1: Comprehensive 5, 10, 15-year DCF holding period analysis."""
    acq = AcquisitionCosts(
        purchase_price=purchase_price,
        is_ready_to_move=is_ready_to_move,
        loan_ltv_ratio=loan_ltv,
    )
    loan_amount = purchase_price * loan_ltv
    loan = LoanSchedule(principal=loan_amount, annual_interest_rate=loan_interest_rate, tenure_years=20)
    rental = RentalEconomics(purchase_price=purchase_price, carpet_area_sqft=carpet_area_sqft)

    initial_outflow = -acq.total_initial_cash_required
    annual_cash_flows = [initial_outflow]
    annual_emi = loan.monthly_emi * 12.0

    current_rent = rental.gross_annual_rent_yr1
    current_expenses = rental.operating_expenses_yr1

    for yr in range(1, holding_years + 1):
        # Escalate rent and expenses annually
        if yr > 1:
            current_rent *= 1.0 + rental.annual_rent_growth_rate
            current_expenses *= 1.0 + annual_inflation_rate

        vacancy = current_rent * rental.vacancy_rate
        noi = current_rent - vacancy - current_expenses
        net_cash_flow = noi - annual_emi
        annual_cash_flows.append(round(net_cash_flow, 2))

    # Exit Valuation at Year N
    resale_price = round(purchase_price * ((1.0 + annual_appreciation_rate) ** holding_years), 2)
    resale_brokerage = round(resale_price * 0.02, 2)
    amort = loan.amortization_at_year(holding_years)
    loan_balance_at_exit = amort["outstanding_principal"]

    # Capital Gains Tax (Finance Act 2024: 12.5% without indexation on net gain)
    capital_gain = max(0.0, resale_price - resale_brokerage - acq.total_acquisition_cost)
    ltcg_tax = round(capital_gain * 0.125, 2)

    net_exit_equity = round(resale_price - resale_brokerage - loan_balance_at_exit - ltcg_tax, 2)

    # Terminal cash flow in final year incorporates exit equity
    terminal_cash_flows = list(annual_cash_flows)
    terminal_cash_flows[-1] += net_exit_equity

    nominal_irr = compute_irr(terminal_cash_flows)
    # Real IRR adjusted for CPI inflation: (1 + nominal) / (1 + inflation) - 1
    real_irr = None
    if nominal_irr is not None:
        nom_dec = nominal_irr / 100.0
        real_dec = ((1.0 + nom_dec) / (1.0 + annual_inflation_rate)) - 1.0
        real_irr = round(real_dec * 100.0, 2)

    npv_at_9pct = compute_npv(0.09, terminal_cash_flows)

    # Alternative 1: Equity Index (Nifty 50 SIP)
    # Invest identical initial equity, plus annual deficits, compounding at 11.5% post-tax 10.0%
    net_equity_alt = acq.total_initial_cash_required * ((1.0 + (opportunity_equity_cagr * 0.875)) ** holding_years)
    for t, cf in enumerate(annual_cash_flows[1:], 1):
        if cf < 0:
            remaining_years = holding_years - t
            net_equity_alt += abs(cf) * ((1.0 + (opportunity_equity_cagr * 0.875)) ** remaining_years)

    # Alternative 2: Fixed Deposit (Debt @ 7% pre-tax / 4.9% post-tax in 30% bracket)
    net_debt_alt = acq.total_initial_cash_required * ((1.0 + (opportunity_debt_cagr * 0.70)) ** holding_years)

    return {
        "holding_years": holding_years,
        "purchase_price": purchase_price,
        "total_acquisition_cost": acq.total_acquisition_cost,
        "initial_equity_invested": acq.total_initial_cash_required,
        "loan_principal": loan_amount,
        "monthly_emi": loan.monthly_emi,
        "annual_debt_service": annual_emi,
        "gross_rental_yield_pct": round((rental.gross_annual_rent_yr1 / purchase_price) * 100.0, 2),
        "net_rental_yield_pct": rental.net_rental_yield_pct,
        "projected_resale_price": resale_price,
        "outstanding_loan_at_exit": loan_balance_at_exit,
        "ltcg_tax_payable": ltcg_tax,
        "net_exit_equity": net_exit_equity,
        "net_profit_inr": round(sum(terminal_cash_flows), 2),
        "nominal_irr_pct": nominal_irr,
        "real_irr_pct": real_irr,
        "npv_at_9pct_inr": npv_at_9pct,
        "alternative_nifty50_terminal_equity": round(net_equity_alt, 2),
        "alternative_fd_terminal_equity": round(net_debt_alt, 2),
        "property_vs_nifty50_delta_inr": round(net_exit_equity - net_equity_alt, 2),
        "is_property_financially_superior_to_equity": net_exit_equity > net_equity_alt,
        "cash_flows_annual": [round(c, 2) for c in terminal_cash_flows],
    }


def evaluate_investment_scenarios_h1(purchase_price: float, carpet_area_sqft: float = 1000.0) -> dict[str, Any]:
    """Generates Bear, Base, and Bull scenario matrix across 5, 10, and 15 years."""
    scenarios = {
        "bear_case": {"appreciation": 0.03, "loan_rate": 0.095, "desc": "Conservative: 3% appreciation, 9.5% interest, higher vacancy"},
        "base_case": {"appreciation": 0.06, "loan_rate": 0.085, "desc": "Moderate: 6% appreciation, 8.5% interest, normal market"},
        "bull_case": {"appreciation": 0.09, "loan_rate": 0.080, "desc": "Aggressive: 9% appreciation, 8.0% interest, high demand corridor"},
    }
    matrix = {}
    for sc_name, sc_params in scenarios.items():
        matrix[sc_name] = {
            "description": sc_params["desc"],
            "5_year": evaluate_investment_h1(
                purchase_price, carpet_area_sqft, holding_years=5,
                annual_appreciation_rate=sc_params["appreciation"],
                loan_interest_rate=sc_params["loan_rate"]
            ),
            "10_year": evaluate_investment_h1(
                purchase_price, carpet_area_sqft, holding_years=10,
                annual_appreciation_rate=sc_params["appreciation"],
                loan_interest_rate=sc_params["loan_rate"]
            ),
            "15_year": evaluate_investment_h1(
                purchase_price, carpet_area_sqft, holding_years=15,
                annual_appreciation_rate=sc_params["appreciation"],
                loan_interest_rate=sc_params["loan_rate"]
            ),
        }
    return matrix


def compute_locality_ranking_score_h2(
    median_price_sqft: float,
    yoy_price_growth_pct: float | None,
    booking_absorption_pct: float | None,
    delayed_project_pct: float | None,
    dist_to_nearest_it_hub_km: float | None = None,
    metro_operational: bool = False,
) -> float:
    """Computes composite Locality Investment Attractiveness Score (H2).

    Avoids ranking by appreciation alone by incorporating rental yields,
    delay risk, connectivity, and pipeline absorption.
    """
    growth = yoy_price_growth_pct if yoy_price_growth_pct is not None else 5.0
    # Estimated rental yield (lower for super-prime, higher for emerging)
    if median_price_sqft > 18000:
        yield_pct = 2.80
    elif median_price_sqft >= 12000:
        yield_pct = 3.20
    else:
        yield_pct = 3.80

    absorption = booking_absorption_pct if booking_absorption_pct is not None else 50.0
    delay_penalty = delayed_project_pct if delayed_project_pct is not None else 20.0

    transit_bonus = 2.0 if metro_operational else 0.0
    proximity_bonus = max(0.0, (15.0 - (dist_to_nearest_it_hub_km or 10.0)) * 0.2)

    # Weighted Score: 30% Growth + 25% Yield + 25% Absorption - 20% Delay Penalty + Transit/Proximity
    score = (
        (growth * 0.30)
        + (yield_pct * 5.0 * 0.25)
        + (absorption * 0.10 * 0.25)
        - (delay_penalty * 0.10 * 0.20)
        + transit_bonus
        + proximity_bonus
    )
    return round(score, 2)


def evaluate_project_value_h3(
    subject_rate_sqft: float,
    locality_median_rate_sqft: float,
    possession_delay_months: int | None = None,
    rcc_pct: float | None = None,
    complaint_count: int | None = None,
) -> dict[str, Any]:
    """Computes project-level value assessment relative to micro-market peers (H3)."""
    if locality_median_rate_sqft <= 0:
        return {"category": "Unrated", "discount_pct": 0.0, "value_score": 50.0}

    discount_pct = round(((subject_rate_sqft - locality_median_rate_sqft) / locality_median_rate_sqft) * 100.0, 2)
    delay = possession_delay_months or 0
    rcc = rcc_pct if rcc_pct is not None else 50.0
    complaints = complaint_count or 0

    if discount_pct < -8.0 and delay <= 6 and rcc >= 60.0 and complaints <= 2:
        category = "Attractive Value Opportunity"
        score = 85.0 - discount_pct  # Higher score for deeper discount
    elif discount_pct > 15.0:
        category = "Premium Overpriced"
        score = 40.0
    elif delay > 12 or complaints >= 10:
        category = "High Construction Delay Risk"
        score = 30.0
    else:
        category = "Fairly Priced"
        score = 65.0

    return {
        "value_category": category,
        "price_diff_vs_locality_pct": discount_pct,
        "is_value_discount": discount_pct < 0,
        "value_score": round(score, 1),
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=" * 80)
    print("PUNE REAL ESTATE FINANCIAL VALUATION & DECISION ENGINE")
    print("=" * 80)

    # 1. H1 Investment Evaluation on ₹1.25 Cr Pune 2 BHK Flat
    purchase_price = 12_500_000.0  # ₹1.25 Crore
    carpet_area = 850.0            # 850 sq ft
    print(f"\n[H1] Buy vs Capital Alternatives Analysis: Rs {purchase_price:,.0f} ({carpet_area} sq ft)")
    print("-" * 80)
    h1_10 = evaluate_investment_h1(purchase_price=purchase_price, carpet_area_sqft=carpet_area, holding_years=10)
    print(f"Total Acquisition Cost:      Rs {h1_10['total_acquisition_cost']:,.0f}")
    print(f"Total Initial Cash Required: Rs {h1_10['initial_equity_invested']:,.0f} (20% down + closing costs)")
    print(f"Monthly Mortgage EMI (80%):  Rs {h1_10['monthly_emi']:,.0f} (8.5% p.a., 20y tenure)")
    print(f"Gross Rental Yield (Yr 1):   {h1_10['gross_rental_yield_pct']:.2f}% | Net Rental Yield: {h1_10['net_rental_yield_pct']:.2f}%")

    print("\nHolding Horizon Comparison:")
    for yr in (5, 10, 15):
        h_res = evaluate_investment_h1(purchase_price=purchase_price, carpet_area_sqft=carpet_area, holding_years=yr)
        nom_irr = f"{h_res['nominal_irr_pct']:.2f}%" if h_res['nominal_irr_pct'] is not None else "N/A"
        real_irr = f"{h_res['real_irr_pct']:.2f}%" if h_res['real_irr_pct'] is not None else "N/A"
        print(f"  [{yr}-YEAR] Resale: Rs {h_res['projected_resale_price']:,.0f} | Net Exit Equity: Rs {h_res['net_exit_equity']:,.0f} | "
              f"Nominal IRR: {nom_irr} | Real IRR (Inflation-Adj): {real_irr}")
        print(f"            Property Net Profit: Rs {h_res['net_profit_inr']:,.0f} vs "
              f"Nifty 50 Equity: Rs {h_res['alternative_nifty50_terminal_equity']:,.0f} | "
              f"FD: Rs {h_res['alternative_fd_terminal_equity']:,.0f}")

    # 2. H1 Scenario Sensitivity (Bear / Base / Bull at 10 Years)
    print("\n[H1] Scenario Sensitivity Matrix (10-Year Horizon):")
    print("-" * 80)
    scenarios = evaluate_investment_scenarios_h1(purchase_price=purchase_price, carpet_area_sqft=carpet_area)
    for name, s_data in scenarios.items():
        s = s_data["10_year"]
        nom_irr = f"{s['nominal_irr_pct']:.2f}%" if s['nominal_irr_pct'] is not None else "N/A"
        real_irr = f"{s['real_irr_pct']:.2f}%" if s['real_irr_pct'] is not None else "N/A"
        print(f"  {name.upper():<10}: Nominal IRR: {nom_irr:>6} | Real IRR: {real_irr:>6} | "
              f"Net Equity: Rs {s['net_exit_equity']:>11,.0f} vs Nifty: Rs {s['alternative_nifty50_terminal_equity']:>11,.0f} | "
              f"{s_data['description']}")

    # 3. H2 Locality Ranking Example
    print("\n[H2] Multi-Factor Locality Investment Opportunity Scoring:")
    print("-" * 80)
    localities_sample = [
        ("Kharadi", 11200.0, 7.8, 88.0, 10.0, 2.0, False),
        ("Hinjawadi", 8500.0, 6.5, 82.0, 15.0, 1.5, True),
        ("Wakad", 9200.0, 7.1, 85.0, 12.0, 5.0, False),
        ("Hadapsar", 7800.0, 4.2, 70.0, 25.0, 3.5, False),
    ]
    for loc, med_p, growth, abs_pct, del_pct, it_km, metro in localities_sample:
        score = compute_locality_ranking_score_h2(med_p, growth, abs_pct, del_pct, it_km, metro)
        print(f"  {loc:<12} -> Attractiveness Score: {score:>5.2f} (Median: Rs {med_p:,.0f}/sqft, 3y Growth: {growth}%, Metro: {metro})")

    # 4. H3 Project Value Scoring
    print("\n[H3] Project Value Opportunity Evaluation:")
    print("-" * 80)
    p1 = evaluate_project_value_h3(subject_rate_sqft=7200.0, locality_median_rate_sqft=8200.0, possession_delay_months=0, rcc_pct=90.0)
    p2 = evaluate_project_value_h3(subject_rate_sqft=9800.0, locality_median_rate_sqft=8200.0, possession_delay_months=18, rcc_pct=40.0)
    print(f"  Project A (Rs 7,200 vs Rs 8,200 median, 0 delay, 90% RCC) -> {p1['value_category']} (Score: {p1['value_score']})")
    print(f"  Project B (Rs 9,800 vs Rs 8,200 median, 18m delay, 40% RCC)-> {p2['value_category']} (Score: {p2['value_score']})")
    print("=" * 80)
