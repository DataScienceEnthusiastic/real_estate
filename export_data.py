#!/usr/bin/env python3
"""Export scraped FlatNama data to comprehensive CSV files.

Supports exporting directly from:
  1. A structured JSON report (e.g. reports/deccan_sample_v3.json)
  2. A live PostgreSQL database (via DATABASE_URL in .env)

Generates cleanly formatted, Excel-friendly CSVs (using UTF-8 with BOM)
for easy viewing and analysis across spreadsheets, Pandas, and BI tools.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Safe field extractor for dictionary access
def get_val(d: dict[str, Any], key: str, default: Any = "") -> Any:
    val = d.get(key)
    return default if val is None else val


def export_from_json(json_path: Path, output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    projects: list[dict[str, Any]] = data.get("projects", [])
    area_discovery: list[dict[str, Any]] = data.get("area_discovery", [])

    counts: dict[str, int] = {}

    # 1. projects_master.csv
    master_rows = []
    for p in projects:
        quality = p.get("extraction_quality", {})
        warnings = quality.get("warnings", [])
        inv = p.get("page_data_inventory", {})

        row = {
            "project_key": p.get("rera_number") or p.get("project_url", ""),
            "project_name": get_val(p, "project_name"),
            "rera_number": get_val(p, "rera_number"),
            "phase_name": get_val(p, "phase_name"),
            "developer": get_val(p, "developer"),
            "project_type": get_val(p, "project_type", "Residential"),
            "locality": get_val(p, "locality"),
            "sub_locality": get_val(p, "sub_locality"),
            "city": get_val(p, "city", "Pune"),
            "district": get_val(p, "district", "Pune"),
            "pin_code": get_val(p, "pin_code"),
            "construction_stage": get_val(p, "construction_stage"),
            "maharera_status": get_val(p, "maharera_status"),
            "launch_date_text": get_val(p, "launch_date_text"),
            "launch_month": get_val(p, "launch_month"),
            "launch_year": get_val(p, "launch_year"),
            "possession_date_text": get_val(p, "possession_date_text"),
            "possession_month": get_val(p, "possession_month"),
            "possession_year": get_val(p, "possession_year"),
            "original_possession_date_text": get_val(p, "original_possession_date_text"),
            "possession_extension_status": get_val(p, "possession_extension_status"),
            "possession_extension_months": get_val(p, "possession_extension_months"),
            "possession_extension_note": get_val(p, "possession_extension_note"),
            "promised_timeline_text": get_val(p, "promised_timeline_text"),
            "promised_timeline_months": get_val(p, "promised_timeline_months"),
            "months_elapsed_since_launch": get_val(p, "months_elapsed_since_launch"),
            "months_remaining_to_possession": get_val(p, "months_remaining_to_possession"),
            "ready_to_move_status": get_val(p, "ready_to_move_status", False),
            "structural_completion_status": get_val(p, "structural_completion_status", False),
            "finishing_completion_status": get_val(p, "finishing_completion_status", False),
            "building_count": get_val(p, "building_count"),
            "land_acres": get_val(p, "land_acres"),
            "excavation_pct": get_val(p, "excavation_pct"),
            "rcc_pct": get_val(p, "rcc_pct"),
            "finishing_pct": get_val(p, "finishing_pct"),
            "complaint_count": get_val(p, "complaint_count", 0),
            "total_units": get_val(p, "total_units"),
            "units_for_sale": get_val(p, "units_for_sale"),
            "units_booked": get_val(p, "units_booked"),
            "not_for_sale_units": get_val(p, "not_for_sale_units"),
            "recent_bookings_count": get_val(p, "recent_bookings_count"),
            "booking_pct": get_val(p, "booking_pct"),
            "booking_status": get_val(p, "booking_status"),
            "units_1rk": get_val(p, "units_1rk", 0),
            "units_1bhk": get_val(p, "units_1bhk", 0),
            "units_2bhk": get_val(p, "units_2bhk", 0),
            "units_3bhk": get_val(p, "units_3bhk", 0),
            "units_4bhk": get_val(p, "units_4bhk", 0),
            "units_5bhk_plus": get_val(p, "units_5bhk_plus", 0),
            "units_other": get_val(p, "units_other", 0),
            "total_residential_units": get_val(p, "total_residential_units", 0),
            "latest_sale_year": get_val(p, "latest_sale_year"),
            "price_per_sqft_80pct": get_val(p, "price_per_sqft_80pct"),
            "price_per_sqft_80pct_source": get_val(p, "price_per_sqft_80pct_source"),
            "latest_sale_count": get_val(p, "latest_sale_count"),
            "current_ytd_price": get_val(p, "current_ytd_price"),
            "previous_year_price": get_val(p, "previous_year_price"),
            "year_over_year_change_pct": get_val(p, "year_over_year_change_pct"),
            "year_over_year_direction": get_val(p, "year_over_year_direction"),
            "rate_vs_nearby_projects_pct": get_val(p, "rate_vs_nearby_projects_pct"),
            "price_area_basis": get_val(p, "price_area_basis"),
            "years_of_sales_data": len(p.get("sale_year_stats", [])),
            "similar_projects_count": get_val(p, "similar_projects_count"),
            "similar_projects_pin": get_val(p, "similar_projects_pin"),
            "quality_score": quality.get("completeness_pct", round(quality.get("fields_present", 0) / max(1, quality.get("fields_checked", 1)) * 100, 1)),
            "quality_warnings_count": len(warnings),
            "quality_warnings": "; ".join(warnings) if warnings else "",
            "map_url": get_val(p, "map_url"),
            "project_url": get_val(p, "project_url"),
        }
        master_rows.append(row)

    _write_csv(output_dir / "projects_master.csv", master_rows)
    counts["projects_master.csv"] = len(master_rows)

    # 2. sale_prices.csv
    price_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        p_name = p.get("project_name", "")
        for s in p.get("sale_year_stats", []):
            price_rows.append({
                "project_key": key,
                "project_name": p_name,
                "sales_year": s.get("sales_year"),
                "year_label": s.get("year_label"),
                "price_per_sqft_80pct": s.get("price_per_sqft_80pct"),
                "sale_count": s.get("sale_count"),
                "year_over_year_delta_text": s.get("year_over_year_delta_text", ""),
                "is_current_ytd": "so far" in str(s.get("year_label", "")).lower(),
            })
    _write_csv(output_dir / "sale_prices.csv", price_rows)
    counts["sale_prices.csv"] = len(price_rows)

    # 3. progress_updates.csv
    update_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        p_name = p.get("project_name", "")
        for u in p.get("progress_updates", []):
            update_rows.append({
                "project_key": key,
                "project_name": p_name,
                "update_label": u.get("update_label"),
                "excavation_pct": u.get("excavation_pct"),
                "rcc_pct": u.get("rcc_pct"),
                "finishing_pct": u.get("finishing_pct"),
                "units_booked": u.get("units_booked"),
                "rcc_change": u.get("rcc_change", ""),
                "finishing_change": u.get("finishing_change", ""),
                "booking_change": u.get("booking_change", ""),
            })
    _write_csv(output_dir / "progress_updates.csv", update_rows)
    counts["progress_updates.csv"] = len(update_rows)

    # 4. unit_mix.csv
    unit_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        p_name = p.get("project_name", "")
        for m in p.get("flat_type_mix", []):
            unit_rows.append({
                "project_key": key,
                "project_name": p_name,
                "flat_type": m.get("flat_type"),
                "unit_count": m.get("unit_count"),
            })
    _write_csv(output_dir / "unit_mix.csv", unit_rows)
    counts["unit_mix.csv"] = len(unit_rows)

    # 5. size_price_bands.csv
    band_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        p_name = p.get("project_name", "")
        for b in p.get("size_price_bands", []):
            band_rows.append({
                "project_key": key,
                "project_name": p_name,
                "year_label": b.get("year_label"),
                "raw_size_label": b.get("raw_size_label"),
                "min_size_sqft": b.get("min_size_sqft"),
                "max_size_sqft": b.get("max_size_sqft"),
                "raw_price_label": b.get("raw_price_label"),
                "min_price_inr": b.get("min_price_inr"),
                "max_price_inr": b.get("max_price_inr"),
            })
    _write_csv(output_dir / "size_price_bands.csv", band_rows)
    counts["size_price_bands.csv"] = len(band_rows)

    # 6. comparables.csv
    comp_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        p_name = p.get("project_name", "")
        for c in p.get("comparables", []):
            comp_rows.append({
                "project_key": key,
                "project_name": p_name,
                "comparable_name": c.get("comparable_name"),
                "launch_date_text": c.get("launch_date_text"),
                "possession_date_text": c.get("possession_date_text"),
                "rcc_pct": c.get("rcc_pct"),
                "booking_text": c.get("booking_text"),
            })
    _write_csv(output_dir / "comparables.csv", comp_rows)
    counts["comparables.csv"] = len(comp_rows)

    # 7. comparison_benchmarks.csv
    benchmark_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        p_name = p.get("project_name", "")
        for bm in p.get("comparison_summary", []):
            benchmark_rows.append({
                "project_key": key,
                "project_name": p_name,
                "measure": bm.get("measure"),
                "this_project": bm.get("this_project"),
                "similar_projects_benchmark": bm.get("similar_projects"),
            })
    _write_csv(output_dir / "comparison_benchmarks.csv", benchmark_rows)
    counts["comparison_benchmarks.csv"] = len(benchmark_rows)

    # 8. faqs.csv
    faq_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        p_name = p.get("project_name", "")
        for q in p.get("faqs", []):
            faq_rows.append({
                "project_key": key,
                "project_name": p_name,
                "topic": q.get("topic"),
                "question": q.get("question"),
                "answer": q.get("answer"),
            })
    _write_csv(output_dir / "faqs.csv", faq_rows)
    counts["faqs.csv"] = len(faq_rows)

    # 9. related_links.csv
    link_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        p_name = p.get("project_name", "")
        for l in p.get("related_project_links", []):
            link_rows.append({
                "project_key": key,
                "project_name": p_name,
                "category": l.get("category"),
                "label": l.get("label"),
                "url": l.get("url"),
            })
    _write_csv(output_dir / "related_links.csv", link_rows)
    counts["related_links.csv"] = len(link_rows)

    # 10. area_summaries.csv
    area_rows = []
    for ad in area_discovery:
        summary = ad.get("area_summary", {})
        area_rows.append({
            "area_name": summary.get("area_name"),
            "area_url": ad.get("area_url"),
            "pin_code": summary.get("pin_code"),
            "listed_project_count": summary.get("listed_project_count"),
            "visible_projects_count": summary.get("visible_projects_count_from_hidden_toggle"),
            "small_projects_hidden_count": summary.get("small_projects_hidden_count"),
            "launched_last_6_months_count": summary.get("launched_last_6_months_count"),
            "rcc_complete_count": summary.get("rcc_complete_count"),
            "possession_date_extended_count": summary.get("possession_date_extended_count"),
            "project_links_discovered": ad.get("project_links_discovered"),
            "discovery_method": ad.get("discovery_method"),
            "nearby_areas": "; ".join(x.get("name", "") for x in summary.get("nearby_areas", [])),
        })
    _write_csv(output_dir / "area_summaries.csv", area_rows)
    counts["area_summaries.csv"] = len(area_rows)

    # 11. quality_audits.csv
    audit_rows = []
    for p in projects:
        key = p.get("rera_number") or p.get("project_url", "")
        quality = p.get("extraction_quality", {})
        audit_rows.append({
            "project_key": key,
            "project_name": p.get("project_name"),
            "parser_version": quality.get("parser_version"),
            "fields_checked": quality.get("fields_checked"),
            "fields_present": quality.get("fields_present"),
            "completeness_pct": quality.get("completeness_pct", round(quality.get("fields_present", 0) / max(1, quality.get("fields_checked", 1)) * 100, 1)),
            "warnings_count": len(quality.get("warnings", [])),
            "warnings": "; ".join(quality.get("warnings", [])),
            "visible_text_chars": quality.get("visible_text_char_count"),
            "page_sections_count": quality.get("page_section_count"),
            "annual_price_rows": quality.get("annual_price_rows"),
            "unit_mix_rows": quality.get("unit_mix_rows"),
            "progress_update_rows": quality.get("construction_update_rows"),
        })
    _write_csv(output_dir / "quality_audits.csv", audit_rows)
    counts["quality_audits.csv"] = len(audit_rows)

    # 12. projects_complete.csv (Single consolidated view with flattened arrays)
    complete_rows = []
    for p, m_row in zip(projects, master_rows):
        c_row = dict(m_row)
        # Summarize unit mix: "2 BHK: 60 | 3 BHK: 52"
        mix_str = " | ".join(f"{item.get('flat_type')}: {item.get('unit_count')}" for item in p.get("flat_type_mix", []))
        c_row["unit_mix_summary"] = mix_str
        # Summarize price history: "2024: ₹23,200 (20 sales) | 2025: ₹22,700 (42 sales)"
        price_str = " | ".join(f"{item.get('year_label')}: ₹{item.get('price_per_sqft_80pct'):,.0f} ({item.get('sale_count')} sales)" for item in p.get("sale_year_stats", []) if item.get("price_per_sqft_80pct"))
        c_row["price_history_summary"] = price_str
        # Summarize sizes: "700–800 sq ft (₹70–90 lakh)"
        sizes_str = " | ".join(f"{item.get('raw_size_label')} ({item.get('raw_price_label')})" for item in p.get("size_price_bands", []))
        c_row["size_price_summary"] = sizes_str
        # Summarize progress: "Dec 2025: RCC 100%, Finishes 40%"
        progress_str = " | ".join(f"{item.get('update_label')}: RCC {item.get('rcc_pct')}%, Finishes {item.get('finishing_pct')}%" for item in p.get("progress_updates", []))
        c_row["latest_progress_summary"] = progress_str
        complete_rows.append(c_row)
    _write_csv(output_dir / "projects_complete.csv", complete_rows)
    counts["projects_complete.csv"] = len(complete_rows)

    return counts


def export_from_db(dsn: str, output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    import psycopg
    from psycopg.rows import dict_row

    counts: dict[str, int] = {}
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Query each view / table
            queries = {
                "projects_master.csv": "SELECT * FROM v_projects_master",
                "delays_and_progress.csv": "SELECT * FROM v_project_delays_and_progress",
                "pricing_summary.csv": "SELECT * FROM v_project_pricing_summary",
                "inventory_summary.csv": "SELECT * FROM v_project_inventory_summary",
                "sale_prices.csv": "SELECT * FROM project_sale_year_stats ORDER BY sales_year DESC",
                "progress_updates.csv": "SELECT * FROM project_progress_updates",
                "unit_mix.csv": "SELECT * FROM project_unit_mix",
                "size_price_bands.csv": "SELECT * FROM project_size_price_bands",
                "comparables.csv": "SELECT * FROM project_comparables",
                "comparison_benchmarks.csv": "SELECT * FROM project_comparison_benchmarks",
                "faqs.csv": "SELECT * FROM v_project_faqs_overview",
                "quality_audits.csv": "SELECT * FROM project_quality_audits",
            }

            for filename, query in queries.items():
                try:
                    cur.execute(query)
                    rows = cur.fetchall()
                    if rows:
                        _write_csv(output_dir / filename, [dict(r) for r in rows])
                    else:
                        _write_csv(output_dir / filename, [])
                    counts[filename] = len(rows)
                except Exception as e:
                    print(f"Warning: could not export {filename}: {e}", file=sys.stderr)

    return counts


def _write_csv(file_path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        # Create empty file
        file_path.write_text("", encoding="utf-8-sig")
        return

    # Collect union of all keys preserving first seen order
    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                fieldnames.append(k)

    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Format dictionaries/lists to json strings for clean spreadsheet display
            clean_row = {}
            for k, v in row.items():
                if isinstance(v, (dict, list)):
                    clean_row[k] = json.dumps(v, ensure_ascii=False)
                else:
                    clean_row[k] = v
            writer.writerow(clean_row)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Export FlatNama data to comprehensive CSV files.")
    parser.add_argument("--json", type=Path, help="Path to input JSON report file (e.g. reports/deccan_sample_v3.json)")
    parser.add_argument("--db", action="store_true", help="Export directly from PostgreSQL database (using DATABASE_URL)")
    parser.add_argument("--output-dir", type=Path, default=Path("exports"), help="Directory to save CSV files (default: exports/)")
    args = parser.parse_args()

    if not args.json and not args.db:
        # Default: check for recent JSON report or db
        sample_report = Path("reports/deccan_sample_v3.json")
        if sample_report.exists():
            args.json = sample_report
        else:
            args.db = True

    if args.json:
        if not args.json.exists():
            print(f"Error: JSON file not found: {args.json}", file=sys.stderr)
            return 1
        print(f"Exporting from JSON report: {args.json} to {args.output_dir}/")
        counts = export_from_json(args.json, args.output_dir)
    elif args.db:
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            print("Error: DATABASE_URL not found in .env", file=sys.stderr)
            return 1
        print(f"Exporting from PostgreSQL to {args.output_dir}/")
        counts = export_from_db(dsn, args.output_dir)

    print("\nExport completed successfully! Generated CSV files:")
    for fname, count in counts.items():
        print(f"  - {fname}: {count} records")

    return 0


if __name__ == "__main__":
    sys.exit(main())
