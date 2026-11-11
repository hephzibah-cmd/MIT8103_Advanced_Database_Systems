"""
==============================================================================
MIT 8103 Advanced Database Systems - Practical Database Portfolio
Case Study: ApexBank Digital (Fintech & Core Banking Platform)
Portfolio 1: PostgreSQL Schema Verification and Integrity Audit Runner
==============================================================================

Prerequisites:
    1. Docker Desktop is running.
    2. From the repository root:  docker compose up -d
    3. Install the driver:        pip install -r requirements.txt

Run:
    python portfolio-1-database-design/verify_schema.py

Environment:
    DATABASE_URL defaults to
    postgresql://apexbank:apexbank_dev@localhost:5432/apexbank
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import errors

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = BASE_DIR / "ddl_schema.sql"
SEED_FILE = BASE_DIR / "seed_data.sql"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://apexbank:apexbank_dev@localhost:5432/apexbank",
)

FAILURES = []


def record(passed, message):
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {message}")
    if not passed:
        FAILURES.append(message)
    return passed


def execute_script(conn, path):
    sql_text = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql_text)


def expect_failure(label, statements, expected_errors):
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE;")
            conn.rollback()
        record(False, f"{label}: statement unexpectedly succeeded")
    except expected_errors as exc:
        record(True, f"{label}: blocked ({type(exc).__name__})")
    except Exception as exc:  # noqa: BLE001 - report unexpected error types
        record(False, f"{label}: unexpected {type(exc).__name__}: {exc}")


def run_verification():
    print("=" * 78)
    print("APEXBANK DIGITAL CORE BANKING - PORTFOLIO 1 POSTGRESQL VERIFICATION")
    print("=" * 78)

    try:
        with psycopg.connect(DATABASE_URL) as probe:
            with probe.cursor() as cur:
                cur.execute("SELECT version();")
                print(f"[OK] Connected: {cur.fetchone()[0].split(',')[0]}")
    except psycopg.OperationalError as exc:
        print(f"[FAIL] Cannot connect to PostgreSQL: {exc}")
        print("       Start it with: docker compose up -d")
        sys.exit(1)

    conn = psycopg.connect(DATABASE_URL)
    conn.autocommit = True

    print("\n--- Executing PostgreSQL DDL Schema ---")
    execute_script(conn, SCHEMA_FILE)
    print(f"[OK] DDL executed from: {SCHEMA_FILE.name}")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]
    print(f"[OK] Created {len(tables)} relations: {', '.join(tables)}")

    print("\n--- Ingesting Seed Data ---")
    execute_script(conn, SEED_FILE)
    print(f"[OK] Seed data committed from: {SEED_FILE.name}")

    print("\n--- Table Population Audit ---")
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            print(f"  * {table.ljust(22)}: {cur.fetchone()[0]:4d} rows")

    print("\n--- Financial Ledger Invariant Verification ---")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                journal_id,
                SUM(CASE WHEN entry_type = 'DEBIT' THEN amount ELSE 0 END) AS total_debit,
                SUM(CASE WHEN entry_type = 'CREDIT' THEN amount ELSE 0 END) AS total_credit,
                COUNT(*) AS line_count
            FROM ledger_entries
            GROUP BY journal_id
            ORDER BY journal_id;
        """)
        ledgers = cur.fetchall()

        all_balanced = True
        for journal_id, debits, credits, line_count in ledgers:
            balanced = line_count >= 2 and debits == credits
            all_balanced = all_balanced and balanced
            record(
                balanced,
                f"Journal {journal_id}: debits={debits:,.2f}, "
                f"credits={credits:,.2f}, lines={line_count}",
            )

        cur.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN entry_type = 'DEBIT' THEN amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN entry_type = 'CREDIT' THEN amount ELSE 0 END), 0)
            FROM ledger_entries;
        """)
        total_debits, total_credits = cur.fetchone()
    record(
        total_debits == total_credits,
        f"Book totals: debits={total_debits:,.2f}, credits={total_credits:,.2f}",
    )
    record(all_balanced and len(ledgers) > 0, "All journals are balanced")

    print("\n--- Account Balance vs Latest Ledger Snapshot ---")
    with conn.cursor() as cur:
        cur.execute("""
            WITH latest AS (
                SELECT DISTINCT ON (account_id)
                    account_id,
                    balance_after
                FROM ledger_entries
                ORDER BY account_id, created_at DESC, ledger_entry_id DESC
            )
            SELECT a.account_id, a.current_balance, l.balance_after
            FROM accounts a
            JOIN latest l ON l.account_id = a.account_id
            WHERE a.current_balance <> l.balance_after;
        """)
        mismatches = cur.fetchall()
    record(
        not mismatches,
        f"Account balances match latest ledger snapshots ({len(mismatches)} mismatch(es))",
    )

    print("\n--- PCI DSS Card-Data Verification ---")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'cards'
              AND column_name IN ('encrypted_cvv', 'cvv', 'cvv2', 'pin_hash', 'pin_block');
        """)
        forbidden_columns = [row[0] for row in cur.fetchall()]
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'cards'
              AND column_name IN ('card_token', 'pan_hmac', 'masked_pan');
        """)
        safe_columns = {row[0] for row in cur.fetchall()}
        cur.execute("""
            SELECT COUNT(*)
            FROM cards
            WHERE length(regexp_replace(masked_pan, '[^0-9]', '', 'g')) > 10;
        """)
        full_pan_count = cur.fetchone()[0]
    record(not forbidden_columns, f"No CVV/PIN columns stored: {forbidden_columns or 'none'}")
    record(
        safe_columns == {"card_token", "pan_hmac", "masked_pan"},
        "Cards use token, keyed HMAC fingerprint, and masked PAN",
    )
    record(
        full_pan_count == 0,
        f"No full PAN stored in masked_pan, with or without separators ({full_pan_count} rows)",
    )

    print("\n--- Constraint Integrity Tests ---")
    overdraft_customer = "c0000001-0000-4000-8000-000000000001"
    source = "a0000001-0000-4000-8000-000000000001"
    destination = "a0000002-0000-4000-8000-000000000002"

    expect_failure(
        "Anti-overdraft check",
        [
            f"""
            INSERT INTO accounts
                (account_id, customer_id, account_type_id, currency_code,
                 account_number, current_balance, overdraft_limit)
            VALUES
                ('a9999999-0000-4000-8000-000000000099',
                 '{overdraft_customer}', 1, 'USD', '9999999999', -500.0000, 0.0000);
            """
        ],
        errors.CheckViolation,
    )
    expect_failure(
        "Referential integrity (orphan account)",
        [
            """
            INSERT INTO accounts
                (account_id, customer_id, account_type_id, currency_code, account_number)
            VALUES
                ('a9999998-0000-4000-8000-000000000098',
                 '99999999-0000-4000-8000-000000000099', 1, 'USD', '8888888888');
            """
        ],
        errors.ForeignKeyViolation,
    )
    expect_failure(
        "Idempotency key uniqueness",
        [
            f"""
            INSERT INTO transactions
                (transaction_id, transaction_reference, idempotency_key,
                 source_account_id, destination_account_id, currency_code, amount, channel)
            VALUES
                ('39999999-0000-4000-8000-000000000099', 'TXN-DUP-TEST',
                 'idem-key-889911-a', '{source}', '{destination}', 'USD', 1.0000,
                 'MOBILE_APP');
            """
        ],
        errors.UniqueViolation,
    )
    expect_failure(
        "Self-transfer prohibition",
        [
            f"""
            INSERT INTO transactions
                (transaction_id, transaction_reference, idempotency_key,
                 source_account_id, destination_account_id, currency_code, amount, channel)
            VALUES
                ('39999998-0000-4000-8000-000000000098', 'TXN-SELF-TEST',
                 'idem-self-test', '{source}', '{source}', 'USD', 1.0000,
                 'MOBILE_APP');
            """
        ],
        errors.CheckViolation,
    )
    expect_failure(
        "Full PAN rejection in masked_pan",
        [
            f"""
            INSERT INTO cards
                (card_id, account_id, masked_pan, card_token, pan_hmac, expiry_date)
            VALUES
                ('f9999999-0000-4000-8000-000000000099', '{source}',
                 '4111111111111111', 'tok_test_full_pan', repeat('a', 64),
                 '2030-01-01');
            """
        ],
        errors.CheckViolation,
    )
    expect_failure(
        "Separated full PAN rejection in masked_pan",
        [
            f"""
            INSERT INTO cards
                (card_id, account_id, masked_pan, card_token, pan_hmac, expiry_date)
            VALUES
                ('f9999998-0000-4000-8000-000000000098', '{source}',
                 '4111-1111-1111-1111', 'tok_test_full_pan_sep', repeat('b', 64),
                 '2030-01-01');
            """
        ],
        errors.CheckViolation,
    )
    expect_failure(
        "Transaction currency must match account currency",
        [
            f"""
            INSERT INTO transactions
                (transaction_id, transaction_reference, idempotency_key,
                 source_account_id, destination_account_id, currency_code, amount, channel)
            VALUES
                ('39999997-0000-4000-8000-000000000097', 'TXN-CCY-TEST',
                 'idem-ccy-test', '{source}',
                 'a0000003-0000-4000-8000-000000000003', 'USD', 1.0000,
                 'MOBILE_APP');
            """
        ],
        errors.RaiseException,
    )
    expect_failure(
        "Verified KYC requires verified_at",
        [
            f"""
            INSERT INTO kyc_verifications
                (kyc_id, customer_id, document_type, id_number,
                 verification_status, verified_at)
            VALUES
                ('d9999999-0000-4000-8000-000000000099',
                 '{overdraft_customer}', 'DRIVERS_LICENSE', 'DL-TEST-NO-DATE',
                 'VERIFIED', NULL);
            """
        ],
        errors.CheckViolation,
    )
    expect_failure(
        "Closed account requires closed_at",
        [
            f"""
            INSERT INTO accounts
                (account_id, customer_id, account_type_id, currency_code,
                 account_number, current_balance, account_status, closed_at)
            VALUES
                ('a9999997-0000-4000-8000-000000000097',
                 '{overdraft_customer}', 1, 'USD', '7777777777', 0.0000,
                 'CLOSED', NULL);
            """
        ],
        errors.CheckViolation,
    )
    expect_failure(
        "Settled transaction requires completed_at",
        [
            f"""
            INSERT INTO transactions
                (transaction_id, transaction_reference, idempotency_key,
                 source_account_id, destination_account_id, currency_code,
                 amount, channel, status, completed_at)
            VALUES
                ('39999996-0000-4000-8000-000000000096', 'TXN-STATUS-TEST',
                 'idem-status-test', '{source}', '{destination}', 'USD',
                 1.0000, 'MOBILE_APP', 'SETTLED', NULL);
            """
        ],
        errors.CheckViolation,
    )
    expect_failure(
        "Settled transaction requires a journal",
        [
            f"""
            INSERT INTO transactions
                (transaction_id, transaction_reference, idempotency_key,
                 source_account_id, destination_account_id, currency_code,
                 amount, channel, status, completed_at)
            VALUES
                ('39999995-0000-4000-8000-000000000095', 'TXN-NO-JOURNAL-TEST',
                 'idem-no-journal-test', '{source}', '{destination}', 'USD',
                 1.0000, 'MOBILE_APP', 'SETTLED', CURRENT_TIMESTAMP);
            """
        ],
        errors.CheckViolation,
    )
    expect_failure(
        "Closed account must have zero balance",
        [
            f"""
            INSERT INTO accounts
                (account_id, customer_id, account_type_id, currency_code,
                 account_number, current_balance, account_status, closed_at)
            VALUES
                ('a9999996-0000-4000-8000-000000000096',
                 '{overdraft_customer}', 1, 'USD', '6666666666', 25.0000,
                 'CLOSED', CURRENT_TIMESTAMP);
            """
        ],
        errors.CheckViolation,
    )

    print("\n--- Append-Only Financial History Tests ---")
    expect_failure(
        "UPDATE ledger_entries",
        ["UPDATE ledger_entries SET amount = amount + 1.0000;"],
        errors.RaiseException,
    )
    expect_failure(
        "DELETE ledger_entries",
        ["DELETE FROM ledger_entries;"],
        errors.RaiseException,
    )
    expect_failure(
        "UPDATE journal_entries",
        ["UPDATE journal_entries SET narrative = 'tampered';"],
        errors.RaiseException,
    )
    expect_failure(
        "DELETE journal_entries",
        ["DELETE FROM journal_entries;"],
        errors.RaiseException,
    )
    expect_failure(
        "UPDATE audit_logs",
        ["UPDATE audit_logs SET action = 'tampered';"],
        errors.RaiseException,
    )
    expect_failure(
        "DELETE audit_logs",
        ["DELETE FROM audit_logs;"],
        errors.RaiseException,
    )

    try:
        with psycopg.connect(DATABASE_URL) as conn2:
            with conn2.cursor() as cur:
                cur.execute("""
                    INSERT INTO customers
                        (customer_id, first_name, last_name, email, phone_number, password_hash)
                    VALUES
                        ('c9999999-0000-4000-8000-000000000099', 'Erasure', 'Test',
                         'erasure.test@example.com', '+2340000000099', 'test_hash');
                """)
                cur.execute("""
                    INSERT INTO audit_logs
                        (audit_id, customer_id, actor_reference, action, target_table,
                         target_record_id, ip_address)
                    VALUES
                        ('49999999-0000-4000-8000-000000000099',
                         'c9999999-0000-4000-8000-000000000099',
                         'customer:c9999999-0000-4000-8000-000000000099',
                         'CUSTOMER_LOGIN', 'customers',
                         'c9999999-0000-4000-8000-000000000099', '127.0.0.1');
                """)
                cur.execute(
                    "DELETE FROM customers WHERE customer_id = 'c9999999-0000-4000-8000-000000000099';"
                )
                cur.execute("""
                    SELECT customer_id, actor_reference FROM audit_logs
                    WHERE audit_id = '49999999-0000-4000-8000-000000000099';
                """)
                linked_customer, actor = cur.fetchone()
            conn2.rollback()
        record(
            linked_customer is None and actor.startswith("customer:c9999999"),
            "Customer deletion nulls audit_logs.customer_id; actor_reference preserved",
        )
    except Exception as exc:  # noqa: BLE001
        record(False, f"Audit ON DELETE SET NULL path failed unexpectedly: {exc}")

    print("\n--- Deferred Double-Entry Trigger Tests ---")
    expect_failure(
        "Incorrect balance_after rejected at posting time",
        [
            """
            INSERT INTO journal_entries
                (journal_id, entry_reference, narrative, event_type)
            VALUES
                ('19999996-0000-4000-8000-000000000096', 'JRN-TEST-BAL-MISMATCH',
                 'Balance mismatch test journal', 'P2P_TRANSFER');
            """,
            f"""
            INSERT INTO ledger_entries
                (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after)
            VALUES
                ('29999995-0000-4000-8000-000000000095',
                 '19999996-0000-4000-8000-000000000096', '{source}',
                 'DEBIT', 100.0000, 1.0000);
            """,
        ],
        errors.RaiseException,
    )
    expect_failure(
        "Unbalanced journal rejected at commit",
        [
            """
            INSERT INTO journal_entries
                (journal_id, entry_reference, narrative, event_type)
            VALUES
                ('19999999-0000-4000-8000-000000000099', 'JRN-TEST-UNBAL',
                 'Unbalanced test journal', 'P2P_TRANSFER');
            """,
            f"""
            INSERT INTO ledger_entries
                (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after)
            VALUES
                ('29999999-0000-4000-8000-000000000099',
                 '19999999-0000-4000-8000-000000000099', '{source}',
                 'DEBIT', 100.0000, 14400.5000);
            """,
            f"""
            INSERT INTO ledger_entries
                (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after)
            VALUES
                ('29999998-0000-4000-8000-000000000098',
                 '19999999-0000-4000-8000-000000000099', '{destination}',
                 'CREDIT', 90.0000, 8340.0000);
            """,
        ],
        errors.RaiseException,
    )
    expect_failure(
        "Empty journal rejected at commit",
        [
            """
            INSERT INTO journal_entries
                (journal_id, entry_reference, narrative, event_type)
            VALUES
                ('19999998-0000-4000-8000-000000000098', 'JRN-TEST-EMPTY',
                 'Empty test journal', 'FEE_CHARGE');
            """
        ],
        errors.RaiseException,
    )
    expect_failure(
        "Mixed-currency journal rejected at commit",
        [
            """
            INSERT INTO journal_entries
                (journal_id, entry_reference, narrative, event_type)
            VALUES
                ('19999995-0000-4000-8000-000000000095', 'JRN-TEST-MIXED-CCY',
                 'Mixed-currency test journal', 'P2P_TRANSFER');
            """,
            f"""
            INSERT INTO ledger_entries
                (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after)
            VALUES
                ('29999994-0000-4000-8000-000000000094',
                 '19999995-0000-4000-8000-000000000095', '{source}',
                 'DEBIT', 100.0000, 14400.5000);
            """,
            """
            INSERT INTO ledger_entries
                (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after)
            VALUES
                ('29999993-0000-4000-8000-000000000093',
                 '19999995-0000-4000-8000-000000000095',
                 'a0000003-0000-4000-8000-000000000003',
                 'CREDIT', 100.0000, 750100.0000);
            """,
        ],
        errors.RaiseException,
    )

    try:
        with psycopg.connect(DATABASE_URL) as conn2:
            with conn2.cursor() as cur:
                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s;",
                    (source,),
                )
                source_before = cur.fetchone()[0]
                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s;",
                    (destination,),
                )
                destination_before = cur.fetchone()[0]

                amount = Decimal("100.0000")
                source_after = source_before - amount
                destination_after = destination_before + amount

                cur.execute("""
                    INSERT INTO journal_entries
                        (journal_id, entry_reference, narrative, event_type)
                    VALUES
                        ('19999997-0000-4000-8000-000000000097', 'JRN-TEST-BAL',
                         'Balanced test journal', 'DEPOSIT');
                """)
                cur.execute(
                    """
                    INSERT INTO ledger_entries
                        (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after)
                    VALUES
                        ('29999997-0000-4000-8000-000000000097',
                         '19999997-0000-4000-8000-000000000097', %s,
                         'DEBIT', %s, %s);
                    """,
                    (source, amount, source_after),
                )
                cur.execute(
                    """
                    INSERT INTO ledger_entries
                        (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after)
                    VALUES
                        ('29999996-0000-4000-8000-000000000096',
                         '19999997-0000-4000-8000-000000000097', %s,
                         'CREDIT', %s, %s);
                    """,
                    (destination, amount, destination_after),
                )
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE;")

                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s;",
                    (source,),
                )
                actual_source = cur.fetchone()[0]
                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s;",
                    (destination,),
                )
                actual_destination = cur.fetchone()[0]

                if actual_source != source_after or actual_destination != destination_after:
                    raise AssertionError(
                        "Ledger posting did not update account balances correctly: "
                        f"source {actual_source} != {source_after}, "
                        f"destination {actual_destination} != {destination_after}"
                    )
            conn2.rollback()
        record(True, "Balanced journal accepted; posting updated account balances")
    except Exception as exc:  # noqa: BLE001
        record(False, f"Balanced posting failed unexpectedly: {exc}")

    print("\n--- Schema Object Audit ---")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT trigger_name
            FROM information_schema.triggers
            WHERE trigger_schema = 'public'
            ORDER BY trigger_name;
        """)
        triggers = sorted({row[0] for row in cur.fetchall()})
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'cards'
              AND column_name = 'encrypted_cvv';
        """)
        cvv_columns = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'audit_logs'
              AND column_name = 'actor_reference';
        """)
        actor_columns = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(*)
            FROM audit_logs
            WHERE actor_reference IS NULL OR btrim(actor_reference) = '';
        """)
        missing_actors = cur.fetchone()[0]
    expected_triggers = {
        "trg_journal_append_only",
        "trg_ledger_append_only",
        "trg_audit_append_only",
        "trg_ledger_balanced",
        "trg_journal_has_lines",
        "trg_ledger_apply_balance",
        "trg_transaction_currency_guard",
        "trg_customers_updated_at",
    }
    record(
        expected_triggers.issubset(set(triggers)),
        f"Integrity triggers present: {', '.join(triggers)}",
    )
    record(cvv_columns == 0, "encrypted_cvv column is absent from cards")
    record(actor_columns == 1, "audit_logs retains an immutable actor_reference")
    record(missing_actors == 0, f"All audit rows have an actor reference ({missing_actors} missing)")

    conn.close()

    print("\n" + "=" * 78)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} CHECK(S) FAILED")
        for failure in FAILURES:
            print(f"  - {failure}")
        print("=" * 78)
        sys.exit(1)

    print("RESULT: ALL PORTFOLIO 1 POSTGRESQL CHECKS PASSED")
    print("=" * 78)


if __name__ == "__main__":
    run_verification()
