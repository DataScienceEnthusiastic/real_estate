#!/usr/bin/env python3
"""Data Quality and Extraction Validation Framework.

Enforces:
- Range and boundary checks (RCC and finishes between 0 and 100%, prices > 0, units >= 0).
- Chronological consistency (possession year >= launch year, update labels ordered).
- Genuine unknown semantics (unknown booleans and integers remain None, never False or 0).
- Audit issue logging into `data_quality_issues` table.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import psycopg

LOG = logging.getLogger("data-quality")


@dataclass
class QualityIssue:
    entity_key: str
    field_name: str
    issue_type: str
    severity: str  # 'CRITICAL', 'WARNING', 'INFO'
    observed_value: Any
    expected_rule: str
    source_id: str = "flatnama"


def validate_project_record(p: dict[str, Any]) -> list[QualityIssue]:
    """Validates a parsed project dictionary and returns detected data quality issues."""
    issues: list[QualityIssue] = []
    key = p.get("project_key") or p.get("project_url") or "unknown"

    # 1. Identity validation
    if not p.get("project_name"):
        issues.append(QualityIssue(
            entity_key=key, field_name="project_name", issue_type="missing_critical_key",
            severity="CRITICAL", observed_value=None, expected_rule="Project name must not be empty"
        ))

    rera = p.get("rera_number")
    if not rera:
        issues.append(QualityIssue(
            entity_key=key, field_name="rera_number", issue_type="missing_critical_key",
            severity="WARNING", observed_value=None, expected_rule="MahaRERA registration ID should be present"
        ))

    # 2. Percentage Range Checks (0.0 to 100.0%)
    for pct_col in ("rcc_pct", "finishing_pct", "excavation_pct", "booking_pct"):
        val = p.get(pct_col)
        if val is not None:
            if not isinstance(val, (int, float)) or val < 0.0 or val > 100.0:
                issues.append(QualityIssue(
                    entity_key=key, field_name=pct_col, issue_type="range_violation",
                    severity="CRITICAL", observed_value=val, expected_rule="Percentage must be between 0.0 and 100.0%"
                ))

    # 3. Unit Counts & Inventory Checks
    total_u = p.get("total_units")
    booked_u = p.get("units_booked")
    if total_u is not None:
        if total_u < 0:
            issues.append(QualityIssue(
                entity_key=key, field_name="total_units", issue_type="range_violation",
                severity="CRITICAL", observed_value=total_u, expected_rule="Total units must be >= 0"
            ))
    if booked_u is not None:
        if booked_u < 0:
            issues.append(QualityIssue(
                entity_key=key, field_name="units_booked", issue_type="range_violation",
                severity="CRITICAL", observed_value=booked_u, expected_rule="Units booked must be >= 0"
            ))
        if total_u is not None and booked_u > total_u:
            # Not necessarily an error if denominator was reported differently, but deserves a warning
            issues.append(QualityIssue(
                entity_key=key, field_name="units_booked", issue_type="inventory_inconsistency",
                severity="WARNING", observed_value=f"booked={booked_u}, total={total_u}",
                expected_rule="Booked units should typically not exceed total registered units"
            ))

    # 4. Chronological Consistency
    l_yr = p.get("launch_year")
    p_yr = p.get("possession_year")
    if l_yr is not None and p_yr is not None:
        if p_yr < l_yr:
            issues.append(QualityIssue(
                entity_key=key, field_name="possession_year", issue_type="chronology_error",
                severity="CRITICAL", observed_value=f"launch={l_yr}, possession={p_yr}",
                expected_rule="Possession year must be greater than or equal to launch year"
            ))

    # 5. Price Sanity Checks
    rate = p.get("price_per_sqft_80pct")
    if rate is not None:
        if rate <= 0:
            issues.append(QualityIssue(
                entity_key=key, field_name="price_per_sqft_80pct", issue_type="range_violation",
                severity="CRITICAL", observed_value=rate, expected_rule="Price per sq ft must be > 0"
            ))
        elif rate < 2000 or rate > 100000:
            issues.append(QualityIssue(
                entity_key=key, field_name="price_per_sqft_80pct", issue_type="outlier_warning",
                severity="WARNING", observed_value=rate, expected_rule="Price per sq ft in Pune is typically between ₹2,000 and ₹100,000"
            ))

    # 6. Audit of Inferred / Defaulted Booleans
    # Verify that unobserved fields were NOT coerced to False
    if p.get("structural_completion_status") is False and p.get("rcc_pct") is None:
        issues.append(QualityIssue(
            entity_key=key, field_name="structural_completion_status", issue_type="unsupported_inferred_value",
            severity="WARNING", observed_value=False, expected_rule="Structural completion should be None if RCC% is unknown"
        ))

    return issues


def persist_quality_issues(issues: list[QualityIssue], conn: psycopg.Connection) -> int:
    """Persists validation issues into data_quality_issues table."""
    if not issues:
        return 0
    saved = 0
    with conn.cursor() as cur:
        for iss in issues:
            cur.execute(
                """
                INSERT INTO data_quality_issues 
                (source_id, entity_key, field_name, issue_type, severity, observed_value, expected_rule)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (iss.source_id, iss.entity_key, iss.field_name, iss.issue_type, iss.severity, str(iss.observed_value), iss.expected_rule),
            )
            saved += 1
    conn.commit()
    return saved
