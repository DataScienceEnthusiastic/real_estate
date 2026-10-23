#!/usr/bin/env python3
"""Import parsed project reports (JSON) into PostgreSQL.

Allows importing offline or pre-collected research samples into PostgreSQL
without re-fetching from the network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv
import psycopg

from scraper import Store, PARSER_VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOG = logging.getLogger("report-importer")


def import_json_report(json_path: Path, dsn: str) -> int:
    load_dotenv()
    if not json_path.exists():
        raise FileNotFoundError(f"JSON report file not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    projects = payload.get("projects", [])
    if not projects:
        LOG.warning("No projects found in JSON report: %s", json_path)
        return 0

    store = Store(dsn)
    try:
        run_id = uuid.uuid4()
        store.start_run(run_id, mode="json-report-import", seed_count=len(projects), notes=f"Imported from {json_path.name}")

        imported = 0
        for p in projects:
            url = p.get("project_url") or "https://flatnama.com/pune/imported/"
            content_bytes = json.dumps(p, sort_keys=True).encode("utf-8")
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            source_page_id = store.add_source_page(
                run_id=run_id,
                url=url,
                page_type="project",
                status=200,
                content_hash=content_hash,
                parse_status="ok",
            )
            store.conn.commit()

            key, is_new = store.save_project(source_page_id, p, content_hash)
            imported += 1
            LOG.info("Imported project [%s] (new_snapshot=%s)", key, is_new)

        store.finish_run(run_id, area_pages=0, project_pages=imported, succeeded=imported, failed=0)
        LOG.info("Successfully imported %d projects into PostgreSQL.", imported)
        return imported
    finally:
        store.conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import JSON research reports into PostgreSQL.")
    parser.add_argument("report", type=Path, help="Path to JSON report file (e.g. reports/deccan_sample_v3.json)")
    parser.add_argument("--dsn", help="PostgreSQL DSN (defaults to DATABASE_URL in .env)")
    args = parser.parse_args()

    load_dotenv()
    dsn = args.dsn or os.getenv("DATABASE_URL")
    if not dsn:
        LOG.error("DATABASE_URL is not set.")
        return 1

    try:
        count = import_json_report(args.report, dsn)
        print(f"Import completed: {count} projects processed.")
        return 0
    except Exception as exc:
        LOG.error("Import failed: %s", exc)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
