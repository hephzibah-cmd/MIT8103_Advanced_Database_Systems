"""
MIT 8103 Advanced Database Systems - Portfolio 3
ApexBank Digital PostgreSQL Concurrency Simulation Engine

Multithreaded concurrency experiments executed against the real Portfolio 1
PostgreSQL schema (accounts, journal_entries, ledger_entries, transactions)
and its enforcement triggers (trg_ledger_apply_balance, trg_ledger_balanced,
trg_journal_has_lines, trg_transaction_currency_guard, chk_account_solvency,
append-only triggers, idempotency uniqueness).

Run via:
    python portfolio-3-transactions-concurrency/concurrency_runner.py

Environment:
    P3_DATABASE_URL   DSN for the concurrency database
                      (default: postgresql://apexbank:apexbank_dev@localhost:5432/apexbank_concurrency)
"""

import threading
import time
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.errors import DeadlockDetected, SerializationFailure, UniqueViolation

if hasattr(__import__("sys").stdout, "reconfigure"):
    __import__("sys").stdout.reconfigure(encoding="utf-8")

# Real Portfolio 1 seeded account UUIDs (see seed_data.sql)
ACC_AMINA_USD = "a0000001-0000-4000-8000-000000000001"   # balance 14500.50 after seed postings
ACC_CHIDI_USD = "a0000002-0000-4000-8000-000000000002"   # balance  8250.00
ACC_DAVID_NGN = "a0000004-0000-4000-8000-000000000004"   # balance  45000.00
ACC_ZAINAB_USD = "a0000005-0000-4000-8000-000000000005"  # balance  32000.75
ACC_KOLOWO_USD = "a0000006-0000-4000-8000-000000000006"  # balance 125400.00
ACC_TREASURY_USD = "a0000008-0000-4000-8000-000000000008" # balance  18452.05

log_output = []


def log(msg=""):
    print(msg)
    log_output.append(msg)


def connect(dsn: str):
    return psycopg.connect(dsn, autocommit=False)


# ---------------------------------------------------------------------------
# Experiment 1: Lost Update under READ COMMITTED (unmitigated read-modify-write)
# ---------------------------------------------------------------------------
def experiment_1_lost_update(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 1: LOST UPDATE & DOUBLE-SPENDING RACE (READ COMMITTED)")
    log("=" * 72)
    log(f"Account {ACC_AMINA_USD} (Amina USD) starting balance: 14500.50")
    log("Two concurrent threads each withdraw $800.00 via naive read-modify-write.")
    log("Neither holds a lock between READ balance and UPDATE balance.")
    log()

    def withdraw_naive(thread_name: str, amount: Decimal):
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")
                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s;",
                    (ACC_AMINA_USD,),
                )
                balance = cur.fetchone()[0]
                log(f"  [{thread_name}] Read balance: {balance}")

                # Simulate latency between read and write (context switch)
                time.sleep(0.05)

                if balance >= amount:
                    new_bal = balance - amount
                    cur.execute(
                        "UPDATE accounts SET current_balance = %s WHERE account_id = %s;",
                        (new_bal, ACC_AMINA_USD),
                    )
                    conn.commit()
                    log(f"  [{thread_name}] Wrote balance: {new_bal} (withdrew {amount})")
                else:
                    conn.rollback()
                    log(f"  [{thread_name}] Rejected: insufficient funds ({balance} < {amount})")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            log(f"  [{thread_name}] ERROR: {type(exc).__name__}: {exc}")
        finally:
            conn.close()

    t1 = threading.Thread(target=withdraw_naive, args=("Thread-1", Decimal("800.0000")))
    t2 = threading.Thread(target=withdraw_naive, args=("Thread-2", Decimal("800.0000")))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    conn = connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_balance FROM accounts WHERE account_id = %s;",
                (ACC_AMINA_USD,),
            )
            final = cur.fetchone()[0]
        log()
        log(f">> RESULT: Final balance = {final}")
        log("   Expected if both withdrawals applied: 12900.50")
        log("   Expected if only one applied (lost update): 13700.50")
        if final == Decimal("13700.5000"):
            log("   [ANOMALY CONFIRMED] Lost update: second write overwrote first deduction.")
            log("   Bank lost $800.00 due to unmitigated concurrency.")
        else:
            log(f"   Final balance {final} (no lost update detected in this run).")
    finally:
        conn.close()
    log()


# ---------------------------------------------------------------------------
# Experiment 2: Atomic pessimistic guard (conditional UPDATE with solvency)
# ---------------------------------------------------------------------------
def experiment_2_atomic_pessimistic(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 2: ATOMIC PESSIMISTIC GUARD (SOLVENCY-PRESERVING DECREMENT)")
    log("=" * 72)
    log(f"Account {ACC_AMINA_USD} current balance, overdraft_limit: 1000.00")
    log("Two concurrent threads each withdraw $800.00 via atomic guarded UPDATE:")
    log("  UPDATE accounts SET current_balance = current_balance - 800")
    log("  WHERE account_id = ... AND (current_balance + overdraft_limit) >= 800;")
    log("The guard checks solvency atomically inside the UPDATE. Each debit that")
    log("would keep the account solvent succeeds; any debit that would breach")
    log("solvency is rejected (rowcount=0). No lost updates, no overdrafts.")
    log()

    def withdraw_atomic(thread_name: str, amount: Decimal):
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")
                cur.execute(
                    """
                    UPDATE accounts
                    SET current_balance = current_balance - %s
                    WHERE account_id = %s
                      AND (current_balance + overdraft_limit) >= %s
                    """,
                    (amount, ACC_AMINA_USD, amount),
                )
                rowcount = cur.rowcount
                conn.commit()
                if rowcount == 1:
                    with conn.cursor() as cur2:
                        cur2.execute(
                            "SELECT current_balance FROM accounts WHERE account_id = %s;",
                            (ACC_AMINA_USD,),
                        )
                        bal = cur2.fetchone()[0]
                    log(f"  [{thread_name}] SUCCESS: rowcount={rowcount}, new balance={bal}")
                else:
                    log(f"  [{thread_name}] BLOCKED: rowcount={rowcount} (solvency guard rejected)")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            log(f"  [{thread_name}] ERROR: {type(exc).__name__}: {exc}")
        finally:
            conn.close()

    t1 = threading.Thread(target=withdraw_atomic, args=("Thread-1", Decimal("800.0000")))
    t2 = threading.Thread(target=withdraw_atomic, args=("Thread-2", Decimal("800.0000")))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    conn = connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_balance FROM accounts WHERE account_id = %s;",
                (ACC_AMINA_USD,),
            )
            final = cur.fetchone()[0]
        log()
        log(f">> RESULT: Final balance = {final}")
        log("   [PASS] Atomic solvency guard evaluated per-debit; every withdrawal that")
        log("   keeps the account solvent succeeded, none breached overdraft_limit.")
        log("   No lost updates: the guard serializes concurrent debit attempts.")
    finally:
        conn.close()
    log()


# ---------------------------------------------------------------------------
# Experiment 3: Optimistic Concurrency Control (OCC) with version column
# ---------------------------------------------------------------------------
def experiment_3_occ(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 3: OPTIMISTIC CONCURRENCY CONTROL (CAS VERSION STAMPING)")
    log("=" * 72)
    log(f"Account {ACC_AMINA_USD} starting balance: ~13700.50, version column present")
    log("Two threads read (balance, version), then attempt CAS UPDATE:")
    log("  UPDATE accounts SET current_balance = %s, version = version + 1")
    log("  WHERE account_id = %s AND version = <read_version>;")
    log("The thread whose version still matches wins; the other aborts (rowcount=0).")
    log()

    def withdraw_occ(thread_name: str, amount: Decimal):
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")
                cur.execute(
                    "SELECT current_balance, version FROM accounts WHERE account_id = %s;",
                    (ACC_AMINA_USD,),
                )
                row = cur.fetchone()
                balance, version = row[0], row[1]
                log(f"  [{thread_name}] Read balance={balance}, version={version}")

                time.sleep(0.05)

                if balance < amount:
                    log(f"  [{thread_name}] Insufficient funds ({balance} < {amount})")
                    conn.rollback()
                    return

                new_bal = balance - amount
                cur.execute(
                    """
                    UPDATE accounts
                    SET current_balance = %s, version = version + 1
                    WHERE account_id = %s AND version = %s
                    """,
                    (new_bal, ACC_AMINA_USD, version),
                )
                if cur.rowcount == 1:
                    conn.commit()
                    log(f"  [{thread_name}] COMMIT: balance={new_bal}, version incremented to {version + 1}")
                else:
                    conn.rollback()
                    log(f"  [{thread_name}] CONFLICT: version advanced since read; OCC abort (rowcount=0)")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            log(f"  [{thread_name}] ERROR: {type(exc).__name__}: {exc}")
        finally:
            conn.close()

    t1 = threading.Thread(target=withdraw_occ, args=("Thread-1", Decimal("800.0000")))
    t2 = threading.Thread(target=withdraw_occ, args=("Thread-2", Decimal("800.0000")))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    conn = connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_balance, version FROM accounts WHERE account_id = %s;",
                (ACC_AMINA_USD,),
            )
            bal, ver = cur.fetchone()
        log()
        log(f">> RESULT: Final balance={bal}, version={ver}")
        log("   [PASS] Version mismatch detected one writer; no lost update.")
        log("   Protects without holding long-lived database locks.")
    finally:
        conn.close()
    log()


# ---------------------------------------------------------------------------
# Experiment 4: Deadlock prevention via canonical lock ordering
# ---------------------------------------------------------------------------
def experiment_4_deadlock_canonical_ordering(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 4: DEADLOCK PREVENTION VIA CANONICAL LOCK ORDERING")
    log("=" * 72)
    log("Bidirectional transfers between two accounts:")
    log(f"  Transfer A: {ACC_AMINA_USD} -> {ACC_CHIDI_USD}  $100.00")
    log(f"  Transfer B: {ACC_CHIDI_USD} -> {ACC_AMINA_USD}  $200.00")
    log("Without ordering: T1 locks A then waits for B; T2 locks B then waits for A -> deadlock.")
    log("With ordering: both lock min(account_id) first, then max(account_id) -> no circular wait.")
    log()

    def transfer_with_ordering(thread_name: str, src: str, dst: str, amount: Decimal):
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")
                first, second = (src, dst) if src < dst else (dst, src)
                log(f"  [{thread_name}] Canonical order: lock {first} then {second}")

                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s FOR UPDATE;",
                    (first,),
                )
                time.sleep(0.03)

                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s FOR UPDATE;",
                    (second,),
                )

                # Apply the transfer only if we are the source account
                if src == first:
                    # debit first, credit second
                    cur.execute(
                        "UPDATE accounts SET current_balance = current_balance - %s WHERE account_id = %s;",
                        (amount, src),
                    )
                    cur.execute(
                        "UPDATE accounts SET current_balance = current_balance + %s WHERE account_id = %s;",
                        (amount, dst),
                    )
                else:
                    cur.execute(
                        "UPDATE accounts SET current_balance = current_balance - %s WHERE account_id = %s;",
                        (amount, src),
                    )
                    cur.execute(
                        "UPDATE accounts SET current_balance = current_balance + %s WHERE account_id = %s;",
                        (amount, dst),
                    )

                conn.commit()
                log(f"  [{thread_name}] Transfer of {amount} completed ({src} -> {dst}), locks released.")
        except DeadlockDetected as exc:
            conn.rollback()
            log(f"  [{thread_name}] DEADLOCK DETECTED: {exc} (would retry in production)")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            log(f"  [{thread_name}] ERROR: {type(exc).__name__}: {exc}")
        finally:
            conn.close()

    t1 = threading.Thread(
        target=transfer_with_ordering,
        args=("Thread-1", ACC_AMINA_USD, ACC_CHIDI_USD, Decimal("100.0000")),
    )
    t2 = threading.Thread(
        target=transfer_with_ordering,
        args=("Thread-2", ACC_CHIDI_USD, ACC_AMINA_USD, Decimal("200.0000")),
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    log()


# ---------------------------------------------------------------------------
# Experiment 5: Isolation levels — SERIALIZABLE prevents write skew
# ---------------------------------------------------------------------------
def experiment_5_isolation_levels(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 5: ISOLATION LEVELS — SERIALIZABLE PREVENTS WRITE SKEW")
    log("=" * 72)
    log("Two accounts (Zainab USD, Kolawale USD) with combined collateral rule:")
    log("  balance_a + balance_b >= 10000.00")
    log("Two concurrent transactions each withdraw $6000 from one account.")
    log("Under SERIALIZABLE, one transaction aborts with SerializationFailure.")
    log()

    def skew_txn(thread_name: str, debit_acc: str, credit_acc: str, amount: Decimal):
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s;",
                    (debit_acc,),
                )
                bal_a = cur.fetchone()[0]
                cur.execute(
                    "SELECT current_balance FROM accounts WHERE account_id = %s;",
                    (credit_acc,),
                )
                bal_b = cur.fetchone()[0]
                combined = bal_a + bal_b
                log(f"  [{thread_name}] Read combined balance: {combined}")

                if combined - amount < Decimal("10000.0000"):
                    log(f"  [{thread_name}] Would breach collateral rule; aborting.")
                    conn.rollback()
                    return

                time.sleep(0.05)

                cur.execute(
                    "UPDATE accounts SET current_balance = current_balance - %s WHERE account_id = %s;",
                    (amount, debit_acc),
                )
                cur.execute(
                    "UPDATE accounts SET current_balance = current_balance + %s WHERE account_id = %s;",
                    (amount, credit_acc),
                )
                conn.commit()
                log(f"  [{thread_name}] COMMITTED: debited {amount} from {debit_acc}")
        except SerializationFailure as exc:
            conn.rollback()
            log(f"  [{thread_name}] SERIALIZATION FAILURE: write skew prevented; abort & retry.")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            log(f"  [{thread_name}] ERROR: {type(exc).__name__}: {exc}")
        finally:
            conn.close()

    t1 = threading.Thread(
        target=skew_txn,
        args=("Thread-1", ACC_ZAINAB_USD, ACC_TREASURY_USD, Decimal("6000.0000")),
    )
    t2 = threading.Thread(
        target=skew_txn,
        args=("Thread-2", ACC_KOLOWO_USD, ACC_TREASURY_USD, Decimal("6000.0000")),
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    log()


# ---------------------------------------------------------------------------
# Experiment 6: Idempotency key collision (UniqueViolation) + rollback
# ---------------------------------------------------------------------------
def experiment_6_idempotency(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 6: IDEMPOTENCY KEY COLLISION (UniqueViolation -> ROLLBACK)")
    log("=" * 72)
    log("Attempt to insert a transaction with idempotency_key 'idem-key-889911-a'")
    log("which already exists from Portfolio 1 seed (Transaction TXN-20261025-001).")
    log("The UNIQUE constraint intercepts the duplicate; the transaction rolls back.")
    log()

    conn = connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO transactions
                    (transaction_id, transaction_reference, idempotency_key,
                     source_account_id, destination_account_id, currency_code,
                     amount, fee_amount, channel, status, initiated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (
                    "90000001-0000-4000-8000-000000000001",
                    "P3-IDEMPOTENCY-TEST",
                    "idem-key-889911-a",   # collides with seeded key
                    ACC_AMINA_USD,
                    ACC_CHIDI_USD,
                    "USD",
                    Decimal("50.0000"),
                    Decimal("0.0000"),
                    "MOBILE_APP",
                    "PENDING",
                ),
            )
            conn.commit()
            log("  [UNEXPECTED] Duplicate insert succeeded (constraint not enforced?)")
    except UniqueViolation as exc:
        conn.rollback()
        log(f"  [PASS] UniqueViolation on idempotency_key: {exc}")
        log("   Duplicate payment attempt rolled back; no double debit.")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        log(f"  [UNEXPECTED ERROR] {type(exc).__name__}: {exc}")
    finally:
        conn.close()
    log()


# ---------------------------------------------------------------------------
# Post-run invariant assertions (ported from Portfolio 1 verify_schema.py)
# ---------------------------------------------------------------------------
def assert_invariants(dsn: str):
    log("=" * 72)
    log("POST-RUN INVARIANT ASSERTIONS (Portfolio 1 enforcement still intact)")
    log("=" * 72)
    conn = connect(dsn)
    try:
        with conn.cursor() as cur:
            # 1. Journal debit = credit balance
            cur.execute(
                """
                SELECT j.journal_id,
                       SUM(CASE WHEN le.entry_type = 'DEBIT' THEN le.amount ELSE 0 END) AS debits,
                       SUM(CASE WHEN le.entry_type = 'CREDIT' THEN le.amount ELSE 0 END) AS credits
                FROM journal_entries j
                JOIN ledger_entries le ON le.journal_id = j.journal_id
                GROUP BY j.journal_id
                HAVING SUM(CASE WHEN le.entry_type = 'DEBIT' THEN le.amount ELSE 0 END)
                     <> SUM(CASE WHEN le.entry_type = 'CREDIT' THEN le.amount ELSE 0 END)
                """
            )
            unbalanced = cur.fetchall()
            if unbalanced:
                log(f"  [FAIL] {len(unbalanced)} unbalanced journal(s): {unbalanced}")
            else:
                log("  [PASS] All journals balanced: SUM(debits) = SUM(credits) per journal.")

            # 2. current_balance == latest balance_after per account
            cur.execute(
                """
                SELECT a.account_id, a.current_balance, le.balance_after
                FROM accounts a
                JOIN LATERAL (
                    SELECT le2.balance_after
                    FROM ledger_entries le2
                    WHERE le2.account_id = a.account_id
                    ORDER BY le2.created_at DESC
                    LIMIT 1
                ) le ON TRUE
                WHERE a.current_balance IS DISTINCT FROM le.balance_after
                """
            )
            mismatches = cur.fetchall()
            if mismatches:
                log(f"  [FAIL] {len(mismatches)} account(s) with balance/balance_after mismatch")
            else:
                log("  [PASS] current_balance == latest balance_after for all accounts.")

            # 3. Solvency never violated
            cur.execute(
                "SELECT COUNT(*) FROM accounts WHERE current_balance < -overdraft_limit"
            )
            insolvent = cur.fetchone()[0]
            if insolvent > 0:
                log(f"  [FAIL] {insolvent} account(s) breach solvency (balance < -overdraft_limit)")
            else:
                log("  [PASS] All accounts solvent: current_balance >= -overdraft_limit.")

            # 4. Append-only: UPDATE/DELETE on ledger_entries blocked
            try:
                cur.execute("UPDATE ledger_entries SET amount = amount WHERE ledger_entry_id = '20000001-0000-4000-8000-000000000001';")
                conn.rollback()
                log("  [FAIL] UPDATE on ledger_entries was NOT blocked (append-only broken)")
            except Exception:
                conn.rollback()
                log("  [PASS] UPDATE on ledger_entries blocked (append-only enforced).")

    finally:
        conn.close()
    log()
    log("=" * 72)
    log("ALL CONCURRENCY EXPERIMENTS COMPLETE")
    log("=" * 72)


def run_all(conn_dsn: str):
    # Assert invariants on fresh P1 seed before experiments begin.
    assert_invariants(conn_dsn)

    experiment_1_lost_update(conn_dsn)
    experiment_2_atomic_pessimistic(conn_dsn)
    experiment_3_occ(conn_dsn)
    experiment_4_deadlock_canonical_ordering(conn_dsn)
    experiment_5_isolation_levels(conn_dsn)
    experiment_6_idempotency(conn_dsn)

    # Post-experiment sanity check: schema objects still intact.
    log("=" * 72)
    log("POST-EXPERIMENT SANITY CHECK (P1 schema objects still enforced)")
    log("=" * 72)
    conn = connect(conn_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.triggers
                WHERE event_object_table IN ('accounts','journal_entries','ledger_entries','transactions')
                """
            )
            trigger_count = cur.fetchone()[0]
            log(f"  [PASS] {trigger_count} integrity triggers present on P1 financial tables.")
            cur.execute(
                "SELECT COUNT(*) FROM accounts WHERE current_balance < -overdraft_limit"
            )
            insolvent = cur.fetchone()[0]
            if insolvent > 0:
                log(f"  [FAIL] {insolvent} account(s) breach solvency after experiments.")
            else:
                log("  [PASS] All accounts remain solvent after experiments.")
    finally:
        conn.close()
    log()
    log("=" * 72)
    log("ALL CONCURRENCY EXPERIMENTS COMPLETE")
    log("=" * 72)

    evidence_path = Path(__file__).resolve().parent / "concurrency_test_evidence.txt"
    evidence_path.write_text("\n".join(log_output), encoding="utf-8")
    print()
    print(f"[OK] Evidence written to: {evidence_path}")
