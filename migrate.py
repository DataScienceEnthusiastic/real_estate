#!/usr/bin/env python3
"""Database Migration Runner for Real Estate Investment Intelligence Platform.

Tracks applied migrations in `schema_migrations` and applies ordered SQL files
from the `migrations/` directory within ACID transactions.
"""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import psycopg
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
LOG = logging.getLogger("db-migrator")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_connection(dsn: str | None = None) -> psycopg.Connection:
    load_dotenv()
    db_url = dsn or os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is not set and no DSN was provided.")
    return psycopg.connect(db_url)


def ensure_migration_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                description TEXT
            );
            """
        )
    conn.commit()


def get_applied_migrations(conn: psycopg.Connection) -> set[str]:
    ensure_migration_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
        return {row[0] for row in cur.fetchall()}


def apply_migrations(dsn: str | None = None, dry_run: bool = False) -> list[str]:
    conn = get_connection(dsn)
    applied = get_applied_migrations(conn)
    applied_this_run: list[str] = []

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        LOG.warning("No SQL migration files found in %s", MIGRATIONS_DIR)
        return []

    for file_path in sql_files:
        version = file_path.stem
        if version in applied:
            LOG.info("Migration [%s] already applied. Skipping.", version)
            continue

        LOG.info("Applying migration [%s] from %s...", version, file_path.name)
        sql_content = file_path.read_text(encoding="utf-8")

        if dry_run:
            LOG.info("[DRY-RUN] Would apply migration: %s", version)
            applied_this_run.append(version)
            continue

        try:
            with conn.cursor() as cur:
                cur.execute(sql_content)
                cur.execute(
                    "INSERT INTO schema_migrations (version, description) VALUES (%s, %s);",
                    (version, file_path.name),
                )
            conn.commit()
            LOG.info("Successfully applied migration [%s].", version)
            applied_this_run.append(version)
        except Exception as exc:
            LOG.error("Failed to apply migration [%s]: %s", version, exc)
            conn.rollback()
            raise

    conn.close()
    return applied_this_run


def show_status(dsn: str | None = None) -> None:
    conn = get_connection(dsn)
    applied = get_applied_migrations(conn)
    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    print("\n--- DATABASE MIGRATION STATUS ---")
    for file_path in sql_files:
        version = file_path.stem
        status = "[APPLIED]" if version in applied else "[PENDING]"
        print(f"  {status} {version} ({file_path.name})")
    print("---------------------------------\n")
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Database migration runner for real_estate.")
    parser.add_argument("--dsn", help="PostgreSQL connection string (defaults to DATABASE_URL in .env)")
    parser.add_argument("--status", action="store_true", help="Show current migration status without applying")
    parser.add_argument("--dry-run", action="store_true", help="Check pending migrations without applying")
    args = parser.parse_args()

    try:
        if args.status:
            show_status(args.dsn)
            return 0

        applied = apply_migrations(args.dsn, dry_run=args.dry_run)
        if applied:
            LOG.info("Applied %d migration(s).", len(applied))
        else:
            LOG.info("Database schema is up to date. No pending migrations.")
        return 0
    except Exception as exc:
        LOG.error("Migration error: %s", exc)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
