"""
MIT 8103 Advanced Database Systems - Portfolio 3
ApexBank Digital PostgreSQL Transactions & Concurrency Control

This runner builds a dedicated PostgreSQL concurrency database from the
Portfolio 1 DDL and seed, executes ACID transaction scripts (COMMIT, ROLLBACK, SAVEPOINT) and multithreaded
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
    """Execute the ACID transaction scripts from transactions.sql against
    the live P1 schema. The file already contains proper BEGIN / COMMIT /
    ROLLBACK boundaries, so it is split into transaction blocks and each block
    is executed as one unit. This lets P1's deferred constraint triggers
    (journal balance, has-lines) fire at the correct COMMIT boundaries while
    still reporting per-transaction outcomes.

    A block that raises (e.g. UniqueViolation, CheckViolation) stops at the
    failing statement, so its trailing ROLLBACK never reaches the server; the
    runner issues that ROLLBACK itself, exactly as an application would."""
    text = TRANSACTIONS_SQL.read_text(encoding="utf-8")

    # Split into transaction blocks on COMMIT;/ROLLBACK; line boundaries
    # (ROLLBACK TO SAVEPOINT does not end a block).
    blocks = []
    current = []
    for line in text.split("\n"):
        current.append(line)
        if line.strip() in ("COMMIT;", "ROLLBACK;"):
            blocks.append("\n".join(current))
            current = []

    results = []
    for block in blocks:
        label = next(
            (ln.strip().replace("-- ", "") for ln in block.split("\n")
             if ln.strip().startswith("-- TRANSACTION")),
            "unlabelled block",
        )
        ends_with = "COMMIT" if block.rstrip().endswith("COMMIT;") else "ROLLBACK"
        try:
            with conn.cursor() as cur:
                cur.execute(block)
            results.append((f"OK -> {ends_with}", label, ""))
        except psycopg.Error as exc:
            with conn.cursor() as cur:
                cur.execute("ROLLBACK;")
            first_line = str(exc).splitlines()[0]
            results.append(
                (f"{type(exc).__name__} -> ROLLBACK", label, first_line)
            )
    return results


ACID_VERIFICATION = [
    ("Amina a0000001 balance (T1 -302.00, T5 +50.00)",
     "SELECT current_balance FROM accounts WHERE account_id = 'a0000001-0000-4000-8000-000000000001'",
     "14248.5000"),
    ("Chidi a0000002 balance (T1 +300.00, T5 -50.00, cashback undone)",
     "SELECT current_balance FROM accounts WHERE account_id = 'a0000002-0000-4000-8000-000000000002'",
     "8500.0000"),
    ("Treasury a0000008 balance (T1 +2.00, cashback undone)",
     "SELECT current_balance FROM accounts WHERE account_id = 'a0000008-0000-4000-8000-000000000008'",
     "18454.0500"),
    ("David a0000004 balance (T2, T4 rolled back)",
     "SELECT current_balance FROM accounts WHERE account_id = 'a0000004-0000-4000-8000-000000000004'",
     "45000.0000"),
    ("T1 journal committed",
     "SELECT COUNT(*) FROM journal_entries WHERE journal_id = '50000001-0000-4000-8000-000000000001'",
     "1"),
    ("T3 duplicate idempotency key rows",
     "SELECT COUNT(*) FROM transactions WHERE idempotency_key = 'idem-key-889911-a'",
     "1"),
    ("T4 journal header discarded with failed lines",
     "SELECT COUNT(*) FROM journal_entries WHERE journal_id = '50000004-0000-4000-8000-000000000004'",
     "0"),
    ("T5 main journal kept",
     "SELECT COUNT(*) FROM journal_entries WHERE journal_id = '50000005-0000-4000-8000-000000000005'",
     "1"),
    ("T5 cashback journal undone by ROLLBACK TO SAVEPOINT",
     "SELECT COUNT(*) FROM journal_entries WHERE journal_id = '50000006-0000-4000-8000-000000000006'",
     "0"),
]


def verify_acid_outcomes(conn, log):
    failures = 0
    with conn.cursor() as cur:
        for label, query, expected in ACID_VERIFICATION:
            cur.execute(query)
            actual = str(cur.fetchone()[0])
            ok = actual == expected
            failures += 0 if ok else 1
            log(f"  [{'PASS' if ok else 'FAIL'}] {label}: {actual} (expected {expected})")
    return failures


def main():
    print("=" * 70)
    print("PORTFOLIO 3: TRANSACTIONS & CONCURRENCY CONTROL RUNNER")
    print("=" * 70)
    print(f"Target database: {CONCURRENCY_DB}")
    print(f"P1 schema: {DDL_FILE}")
    print(f"P1 seed:   {SEED_FILE}")
    print()

    ensure_concurrency_database()

    # The simulation module owns the evidence log; ACID results are written to
    # it too so concurrency_test_evidence.txt covers COMMIT/ROLLBACK/SAVEPOINT.
    sys.path.insert(0, str(BASE_DIR))
    import concurrency_simulation as sim

    with psycopg.connect(CONCURRENCY_DSN, autocommit=True) as conn:
        load_p1_schema_and_seed(conn)

        print()
        sim.log("=" * 72)
        sim.log("ACID TRANSACTION SCRIPTS (transactions.sql): COMMIT / ROLLBACK / SAVEPOINT")
        sim.log("=" * 72)
        for status, label, detail in run_acid_transactions(conn):
            sim.log(f"  [{status}] {label}")
            if detail:
                sim.log(f"      server error: {detail}")
        sim.log()
        sim.log("Post-script verification:")
        acid_failures = verify_acid_outcomes(conn, sim.log)
        sim.log()

    print("Running multithreaded concurrency simulation ...")
    print()
    sim_failures = sim.run_all(conn_dsn=CONCURRENCY_DSN)

    print()
    print("=" * 70)
    print("PORTFOLIO 3 RUN COMPLETE")
    print("=" * 70)
    if acid_failures or sim_failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
