"""
MIT 8103 Advanced Database Systems - Portfolio 3
ApexBank Digital PostgreSQL Transactions & Concurrency Control

This runner builds a dedicated PostgreSQL concurrency database from the
Portfolio 1 DDL and seed, executes ACID transaction scripts and multithreaded
concurrency experiments against the real P1 schema (triggers, deferred
constraints, chk_account_solvency, idempotency uniqueness, append-only
ledger/journal), and writes evidence files for the portfolio.

Usage (from repository root):
    python portfolio-3-transactions-concurrency/concurrency_runner.py

Environment:
    P3_DATABASE_URL   DSN for the concurrency database
                      (default: postgresql://apexbank:apexbank_dev@localhost:5432/apexbank_concurrency)
"""

import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

BASE_DIR = Path(__file__).resolve().parent
P1_DIR = BASE_DIR.parent / "portfolio-1-database-design"
DDL_FILE = P1_DIR / "ddl_schema.sql"
SEED_FILE = P1_DIR / "seed_data.sql"
TRANSACTIONS_SQL = BASE_DIR / "transactions.sql"

DEFAULT_DSN = "postgresql://apexbank:apexbank_dev@localhost:5432/apexbank_concurrency"
CONCURRENCY_DSN = os.getenv("P3_DATABASE_URL", DEFAULT_DSN)
CONCURRENCY_DB = conninfo_to_dict(CONCURRENCY_DSN).get("dbname", "apexbank_concurrency")
MAINTENANCE_DSN = make_conninfo(**{**conninfo_to_dict(CONCURRENCY_DSN), "dbname": "postgres"})

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def execute_script(conn, path):
    text = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(text)


def ensure_concurrency_database():
    with psycopg.connect(MAINTENANCE_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (CONCURRENCY_DB,))
            if cur.fetchone() is None:
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(CONCURRENCY_DB))
                )
                print(f"[OK] Created PostgreSQL concurrency database: {CONCURRENCY_DB}")
            else:
                print(f"[OK] Reusing PostgreSQL concurrency database: {CONCURRENCY_DB}")


def load_p1_schema_and_seed(conn):
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    execute_script(conn, DDL_FILE)
    execute_script(conn, SEED_FILE)
    print("[OK] Loaded Portfolio 1 DDL and seed into concurrency database")


def run_acid_transactions(conn):
    """Execute the three ACID transaction scripts from transactions.sql against
    the live P1 schema. The file already contains proper BEGIN / COMMIT /
    ROLLBACK boundaries, so it is split into transaction blocks and each block
    is executed as one unit. This lets P1's deferred constraint triggers
    (journal balance, has-lines) fire at the correct COMMIT boundaries while
    still reporting per-transaction outcomes."""
    text = TRANSACTIONS_SQL.read_text(encoding="utf-8")

    # Split into transaction blocks on COMMIT;/ROLLBACK; line boundaries.
    blocks = []
    current = []
    for line in text.split("\n"):
        current.append(line)
        if line.strip() in ("COMMIT;", "ROLLBACK;"):
            blocks.append("\n".join(current))
            current = []
    remainder = "\n".join(current).strip()
    if remainder:
        blocks.append(remainder)

    results = []
    for block_idx, block in enumerate(blocks):
        if not block.strip():
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(block)
            # Extract a short label from the first comment line in the block
            label = ""
            for line in block.split("\n"):
                if line.strip().startswith("-- TRANSACTION"):
                    label = line.strip().replace("-- ", "")
                    break
            if not label:
                label = f"block {block_idx + 1}"
            results.append((block_idx, "OK", label))
        except psycopg.Error as exc:
            label = f"block {block_idx + 1}"
            results.append((block_idx, f"BLOCKED: {type(exc).__name__}", f"{label}: {str(exc)[:80]}"))
    return results


def main():
    print("=" * 70)
    print("PORTFOLIO 3: TRANSACTIONS & CONCURRENCY CONTROL RUNNER")
    print("=" * 70)
    print(f"Target database: {CONCURRENCY_DB}")
    print(f"P1 schema: {DDL_FILE}")
    print(f"P1 seed:   {SEED_FILE}")
    print()

    ensure_concurrency_database()

    with psycopg.connect(CONCURRENCY_DSN, autocommit=True) as conn:
        load_p1_schema_and_seed(conn)

        print()
        print("-" * 70)
        print("Running ACID transaction scripts (transactions.sql)")
        print("-" * 70)
        txn_results = run_acid_transactions(conn)
        for idx, status, preview in txn_results:
            print(f"  [{status:10s}] {preview}")

    print()
    print("Running multithreaded concurrency simulation ...")
    print()

    # Import and run the simulation module (it connects via psycopg itself)
    sys.path.insert(0, str(BASE_DIR))
    import concurrency_simulation as sim

    sim.run_all(conn_dsn=CONCURRENCY_DSN)

    print()
    print("=" * 70)
    print("PORTFOLIO 3 RUN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
