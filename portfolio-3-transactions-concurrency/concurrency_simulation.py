"""
MIT 8103 Advanced Database Systems - Portfolio 3
ApexBank Digital PostgreSQL Concurrency Simulation Engine

Multithreaded concurrency experiments executed against the real Portfolio 1
PostgreSQL schema (accounts, journal_entries, ledger_entries, transactions)
and its enforcement triggers (trg_ledger_apply_balance, trg_ledger_balanced,
trg_journal_has_lines, trg_transaction_currency_guard, chk_account_solvency,
append-only triggers, idempotency uniqueness).

Every thread opens its OWN psycopg connection (= its own PostgreSQL backend
session), so the interleavings below are real server-side concurrency, not
Python-level interleaving on a shared connection. A threading.Barrier is used
to force the interesting interleaving (e.g. "both transactions have read
before either writes") so the results are deterministic run after run rather
than depending on sleep() timing.

Experiments 1-5 deliberately write accounts.current_balance directly (outside
the P1 ledger posting path) to isolate one concurrency mechanism at a time.
Each such experiment snapshots the rows it touches and restores them
afterwards, so (a) every experiment starts from the same known state and (b)
the post-run P1 invariant "current_balance == latest ledger balance_after"
is re-checked honestly at the end.

Run via:
    python portfolio-3-transactions-concurrency/concurrency_runner.py

Environment:
    P3_DATABASE_URL   DSN for the concurrency database
                      (default: postgresql://apexbank:apexbank_dev@localhost:5432/apexbank_concurrency)
"""

import sys
import threading
import time
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.errors import DeadlockDetected, SerializationFailure, UniqueViolation

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Real Portfolio 1 seeded account UUIDs (see seed_data.sql). Balances shown are
# the values after the P1 seed postings AND the committed transactions.sql
# scripts (T1 and T5), i.e. the starting state of every experiment below.
ACC_AMINA_USD = "a0000001-0000-4000-8000-000000000001"   # balance 14248.50, overdraft 1000.00
ACC_CHIDI_USD = "a0000002-0000-4000-8000-000000000002"   # balance  8500.00, overdraft  500.00
ACC_ZAINAB_USD = "a0000005-0000-4000-8000-000000000005"  # balance 32000.75, overdraft 2000.00
ACC_KOLAWOLE_USD = "a0000006-0000-4000-8000-000000000006"  # balance 125400.00, overdraft 5000.00

MAX_ATTEMPTS = 3          # retry budget for 40001 / 40P01 and OCC conflicts
BARRIER_TIMEOUT = 15      # seconds; a broken barrier means the harness itself failed

log_output = []
_log_lock = threading.Lock()


def log(msg=""):
    with _log_lock:
        print(msg)
        log_output.append(msg)


def connect(dsn: str):
    return psycopg.connect(dsn, autocommit=False)


def read_balance(dsn: str, account_id: str):
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(
            "SELECT current_balance FROM accounts WHERE account_id = %s;", (account_id,)
        ).fetchone()[0]


def snapshot_accounts(dsn: str, account_ids):
    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT account_id::text, current_balance, version FROM accounts "
            "WHERE account_id = ANY(%s::uuid[]);",
            (list(account_ids),),
        ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def restore_accounts(dsn: str, snapshot):
    with psycopg.connect(dsn, autocommit=True) as conn:
        for account_id, (balance, version) in snapshot.items():
            conn.execute(
                "UPDATE accounts SET current_balance = %s, version = %s WHERE account_id = %s;",
                (balance, version, account_id),
            )
    log("   (touched accounts restored to their pre-experiment state)")


def run_threads(*targets):
    threads = [threading.Thread(target=fn, args=args) for fn, args in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ---------------------------------------------------------------------------
# Experiment 1: Lost Update under READ COMMITTED vs REPEATABLE READ
# ---------------------------------------------------------------------------
def experiment_1_lost_update(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 1: LOST UPDATE - READ COMMITTED vs REPEATABLE READ")
    log("=" * 72)
    amount = Decimal("800.0000")
    snap = snapshot_accounts(dsn, [ACC_AMINA_USD])
    start = snap[ACC_AMINA_USD][0]
    log(f"Account {ACC_AMINA_USD} (Amina USD) starting balance: {start}")
    log(f"Two concurrent sessions each withdraw {amount} via naive read-modify-write:")
    log("  SELECT current_balance ...;  -- application computes balance - amount")
    log("  UPDATE accounts SET current_balance = <computed value> ...;")
    log("A barrier guarantees both sessions READ before either WRITES.")
    log()

    def run(level: str):
        barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)

        def withdraw_naive(thread_name: str):
            for attempt in range(1, MAX_ATTEMPTS + 1):
                conn = connect(dsn)
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"SET TRANSACTION ISOLATION LEVEL {level};")
                        cur.execute(
                            "SELECT current_balance FROM accounts WHERE account_id = %s;",
                            (ACC_AMINA_USD,),
                        )
                        balance = cur.fetchone()[0]
                        log(f"  [{thread_name}] attempt {attempt}: read balance {balance}")
                        if attempt == 1:
                            barrier.wait()
                        new_bal = balance - amount
                        cur.execute(
                            "UPDATE accounts SET current_balance = %s WHERE account_id = %s;",
                            (new_bal, ACC_AMINA_USD),
                        )
                    conn.commit()
                    log(f"  [{thread_name}] attempt {attempt}: COMMIT, wrote balance {new_bal}")
                    return
                except SerializationFailure as exc:
                    conn.rollback()
                    log(f"  [{thread_name}] attempt {attempt}: SQLSTATE {exc.sqlstate} "
                        f"SerializationFailure ('{str(exc).splitlines()[0]}') -> ROLLBACK, retry")
                finally:
                    conn.close()
            log(f"  [{thread_name}] gave up after {MAX_ATTEMPTS} attempts")

        log(f"--- 1{'a' if level == 'READ COMMITTED' else 'b'}: {level} ---")
        run_threads((withdraw_naive, ("Thread-1",)), (withdraw_naive, ("Thread-2",)))
        final = read_balance(dsn, ACC_AMINA_USD)
        log(f">> RESULT ({level}): final balance = {final}")
        log(f"   Correct (both withdrawals applied): {start - 2 * amount}")
        if final == start - amount:
            log(f"   [ANOMALY CONFIRMED] Lost update: one {amount} debit was overwritten;")
            log(f"   {amount} was paid out but never deducted from the account.")
        elif final == start - 2 * amount:
            log("   [PASS] No lost update: the stale writer was aborted with SQLSTATE 40001")
            log("   (first-updater-wins under snapshot isolation) and its retry re-read")
            log("   the committed balance.")
        else:
            log("   [UNEXPECTED] final balance matches neither outcome")
        restore_accounts(dsn, snap)
        log()

    run("READ COMMITTED")
    run("REPEATABLE READ")


# ---------------------------------------------------------------------------
# Experiment 2: Atomic pessimistic guard (conditional UPDATE with solvency)
# ---------------------------------------------------------------------------
def experiment_2_atomic_pessimistic(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 2: ATOMIC PESSIMISTIC GUARD (SOLVENCY-PRESERVING DECREMENT)")
    log("=" * 72)
    amount = Decimal("9000.0000")
    snap = snapshot_accounts(dsn, [ACC_AMINA_USD])
    start = snap[ACC_AMINA_USD][0]
    log(f"Account {ACC_AMINA_USD} balance {start}, overdraft_limit 1000.00 "
        f"-> spendable {start + Decimal('1000')}")
    log(f"Two concurrent sessions (READ COMMITTED) each try to withdraw {amount};")
    log("one fits, two do not. Each runs a single guarded UPDATE:")
    log("  UPDATE accounts SET current_balance = current_balance - :amount")
    log("  WHERE account_id = :id AND (current_balance + overdraft_limit) >= :amount;")
    log("Each session holds its row lock ~0.3s before COMMIT so the other must wait.")
    log()

    barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)

    def withdraw_atomic(thread_name: str):
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")
                barrier.wait()
                t0 = time.perf_counter()
                cur.execute(
                    """
                    UPDATE accounts
                    SET current_balance = current_balance - %s
                    WHERE account_id = %s
                      AND (current_balance + overdraft_limit) >= %s
                    RETURNING current_balance
                    """,
                    (amount, ACC_AMINA_USD, amount),
                )
                waited_ms = (time.perf_counter() - t0) * 1000
                row = cur.fetchone()
                time.sleep(0.3)  # rest of the posting work, row lock still held
            conn.commit()
            if row:
                log(f"  [{thread_name}] SUCCESS: rowcount=1, new balance={row[0]} "
                    f"(UPDATE waited {waited_ms:.0f} ms)")
            else:
                log(f"  [{thread_name}] REJECTED: rowcount=0 - blocked {waited_ms:.0f} ms on the "
                    "row lock, then re-evaluated the guard against the committed row")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            log(f"  [{thread_name}] ERROR: {type(exc).__name__}: {exc}")
        finally:
            conn.close()

    run_threads((withdraw_atomic, ("Thread-1",)), (withdraw_atomic, ("Thread-2",)))
    final = read_balance(dsn, ACC_AMINA_USD)
    log()
    log(f">> RESULT: Final balance = {final} (expected {start - amount})")
    if final == start - amount:
        log("   [PASS] Exactly one debit applied; the second was rejected by the guard")
        log("   (READ COMMITTED re-checks the WHERE clause on the newest row version")
        log("   after the lock wait). No lost update, no overdraft breach.")
    else:
        log("   [FAIL] Unexpected final balance.")
    restore_accounts(dsn, snap)
    log()


# ---------------------------------------------------------------------------
# Experiment 3: Optimistic Concurrency Control (OCC) with version column
# ---------------------------------------------------------------------------
def experiment_3_occ(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 3: OPTIMISTIC CONCURRENCY CONTROL (CAS VERSION STAMPING)")
    log("=" * 72)
    amount = Decimal("800.0000")
    snap = snapshot_accounts(dsn, [ACC_AMINA_USD])
    start, start_ver = snap[ACC_AMINA_USD]
    log(f"Account {ACC_AMINA_USD} starting balance {start}, version {start_ver}")
    log("Two sessions read (balance, version), meet at a barrier, then CAS:")
    log("  UPDATE accounts SET current_balance = :new, version = version + 1")
    log("  WHERE account_id = :id AND version = :read_version;")
    log("rowcount=0 means the version moved: the loser re-reads and retries.")
    log()

    barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)

    def withdraw_occ(thread_name: str):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            conn = connect(dsn)
            try:
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")
                    cur.execute(
                        "SELECT current_balance, version FROM accounts WHERE account_id = %s;",
                        (ACC_AMINA_USD,),
                    )
                    balance, version = cur.fetchone()
                    log(f"  [{thread_name}] attempt {attempt}: read balance={balance}, version={version}")
                    if attempt == 1:
                        barrier.wait()
                    if balance < amount:
                        conn.rollback()
                        log(f"  [{thread_name}] insufficient funds")
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
                        log(f"  [{thread_name}] attempt {attempt}: COMMIT balance={new_bal}, "
                            f"version {version} -> {version + 1}")
                        return
                    conn.rollback()
                    log(f"  [{thread_name}] attempt {attempt}: CONFLICT (rowcount=0, version moved) "
                        "-> retry")
            finally:
                conn.close()
        log(f"  [{thread_name}] gave up after {MAX_ATTEMPTS} attempts")

    run_threads((withdraw_occ, ("Thread-1",)), (withdraw_occ, ("Thread-2",)))
    bal, ver = snapshot_accounts(dsn, [ACC_AMINA_USD])[ACC_AMINA_USD]
    log()
    log(f">> RESULT: Final balance={bal}, version={ver} "
        f"(expected {start - 2 * amount}, version {start_ver + 2})")
    if bal == start - 2 * amount and ver == start_ver + 2:
        log("   [PASS] Stale CAS rejected, retry applied on fresh state: both debits")
        log("   counted, no lost update, no lock held between read and write.")
    else:
        log("   [FAIL] Unexpected OCC outcome.")
    restore_accounts(dsn, snap)
    log()


# ---------------------------------------------------------------------------
# Experiment 4: Deadlock detection (unordered) vs prevention (canonical order)
# ---------------------------------------------------------------------------
def experiment_4_deadlock(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 4: DEADLOCK - DETECTION (40P01) vs PREVENTION (LOCK ORDERING)")
    log("=" * 72)
    log("Bidirectional transfers between two accounts:")
    log(f"  Transfer A: Amina {ACC_AMINA_USD} -> Chidi {ACC_CHIDI_USD}  $100.00")
    log(f"  Transfer B: Chidi {ACC_CHIDI_USD} -> Amina {ACC_AMINA_USD}  $200.00")
    log("Each transfer locks both rows with SELECT ... FOR UPDATE, then debits/credits.")
    log("A barrier makes both sessions hold their FIRST lock before requesting the second.")
    log()

    snap = snapshot_accounts(dsn, [ACC_AMINA_USD, ACC_CHIDI_USD])
    start_total = sum(v[0] for v in snap.values())

    def run(ordered: bool):
        barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)
        outcome = {"deadlocks": 0}

        def transfer(thread_name: str, src: str, dst: str, amount: Decimal):
            for attempt in range(1, MAX_ATTEMPTS + 1):
                conn = connect(dsn)
                try:
                    with conn.cursor() as cur:
                        cur.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED;")
                        first, second = sorted((src, dst)) if ordered else (src, dst)
                        cur.execute(
                            "SELECT 1 FROM accounts WHERE account_id = %s FOR UPDATE;", (first,)
                        )
                        log(f"  [{thread_name}] attempt {attempt}: locked {first[:8]}")
                        if attempt == 1:
                            # Unordered: barrier forces the hold-and-wait cycle.
                            # Ordered: the other session is blocked on `first`
                            # and cannot reach a barrier, so just hold the lock
                            # briefly to make it visibly queue.
                            if ordered:
                                time.sleep(0.2)
                            else:
                                barrier.wait()
                        cur.execute(
                            "SELECT 1 FROM accounts WHERE account_id = %s FOR UPDATE;", (second,)
                        )
                        log(f"  [{thread_name}] attempt {attempt}: locked {second[:8]}")
                        cur.execute(
                            "UPDATE accounts SET current_balance = current_balance - %s WHERE account_id = %s;",
                            (amount, src),
                        )
                        cur.execute(
                            "UPDATE accounts SET current_balance = current_balance + %s WHERE account_id = %s;",
                            (amount, dst),
                        )
                    conn.commit()
                    log(f"  [{thread_name}] attempt {attempt}: COMMIT transfer {amount} "
                        f"{src[:8]} -> {dst[:8]}, locks released")
                    return
                except DeadlockDetected as exc:
                    conn.rollback()
                    outcome["deadlocks"] += 1
                    log(f"  [{thread_name}] attempt {attempt}: SQLSTATE {exc.sqlstate} DeadlockDetected "
                        "- chosen as victim, ROLLBACK, retry")
                finally:
                    conn.close()
            log(f"  [{thread_name}] gave up after {MAX_ATTEMPTS} attempts")

        log(f"--- 4{'b' if ordered else 'a'}: {'CANONICAL ORDER (min id, then max id)' if ordered else 'UNORDERED (source first, then destination)'} ---")
        run_threads(
            (transfer, ("Thread-1", ACC_AMINA_USD, ACC_CHIDI_USD, Decimal("100.0000"))),
            (transfer, ("Thread-2", ACC_CHIDI_USD, ACC_AMINA_USD, Decimal("200.0000"))),
        )
        after = snapshot_accounts(dsn, [ACC_AMINA_USD, ACC_CHIDI_USD])
        total = sum(v[0] for v in after.values())
        net_amina = after[ACC_AMINA_USD][0] - snap[ACC_AMINA_USD][0]
        log(f">> RESULT: deadlocks={outcome['deadlocks']}, Amina net change {net_amina} "
            f"(expected +100.0000), combined balance {total} (expected {start_total})")
        if ordered:
            log("   [PASS] Canonical ordering removed the circular wait: zero deadlocks,"
                if outcome["deadlocks"] == 0 else "   [FAIL] Deadlock occurred despite ordering;")
            log("   the second session simply queued behind the first.")
        else:
            log("   [PASS] PostgreSQL's wait-for-graph check (after deadlock_timeout) aborted"
                if outcome["deadlocks"] == 1 else "   [UNEXPECTED] deadlock count != 1;")
            log("   one victim with 40P01; the survivor committed and the victim's retry")
            log("   succeeded. Detection resolves deadlocks, but costs ~1s and an abort.")
        restore_accounts(dsn, snap)
        log()

    run(ordered=False)
    run(ordered=True)


# ---------------------------------------------------------------------------
# Experiment 5: Write skew - REPEATABLE READ (allowed) vs SERIALIZABLE (SSI)
# ---------------------------------------------------------------------------
def experiment_5_write_skew(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 5: WRITE SKEW - REPEATABLE READ vs SERIALIZABLE (SSI)")
    log("=" * 72)
    rule = Decimal("150000.0000")
    amount = Decimal("6000.0000")
    snap = snapshot_accounts(dsn, [ACC_ZAINAB_USD, ACC_KOLAWOLE_USD])
    start_combined = sum(v[0] for v in snap.values())
    log("Zainab (a0000005) and Kolawole (a0000006) are a guarantor pair under a")
    log(f"combined-collateral rule: balance_zainab + balance_kolawole >= {rule}")
    log(f"Starting combined balance: {start_combined}")
    log(f"Each session reads BOTH balances, checks the rule for a {amount} withdrawal,")
    log("then debits ONLY its own account (disjoint write sets, so no row conflict).")
    log(f"One withdrawal is fine ({start_combined - amount}); both breach the rule "
        f"({start_combined - 2 * amount}).")
    log()

    def run(level: str):
        barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)

        def withdraw(thread_name: str, own_acc: str):
            for attempt in range(1, MAX_ATTEMPTS + 1):
                conn = connect(dsn)
                try:
                    with conn.cursor() as cur:
                        cur.execute(f"SET TRANSACTION ISOLATION LEVEL {level};")
                        cur.execute(
                            "SELECT SUM(current_balance) FROM accounts WHERE account_id IN (%s, %s);",
                            (ACC_ZAINAB_USD, ACC_KOLAWOLE_USD),
                        )
                        combined = cur.fetchone()[0]
                        log(f"  [{thread_name}] attempt {attempt}: read combined balance {combined}")
                        if attempt == 1:
                            barrier.wait()
                        if combined - amount < rule:
                            conn.rollback()
                            log(f"  [{thread_name}] attempt {attempt}: rule would be breached "
                                "-> withdrawal declined")
                            return
                        cur.execute(
                            "UPDATE accounts SET current_balance = current_balance - %s WHERE account_id = %s;",
                            (amount, own_acc),
                        )
                    conn.commit()
                    log(f"  [{thread_name}] attempt {attempt}: COMMIT, debited {amount} from {own_acc[:8]}")
                    return
                except SerializationFailure as exc:
                    conn.rollback()
                    log(f"  [{thread_name}] attempt {attempt}: SQLSTATE {exc.sqlstate} SerializationFailure "
                        f"('{str(exc).splitlines()[0]}') -> ROLLBACK, retry")
                finally:
                    conn.close()
            log(f"  [{thread_name}] gave up after {MAX_ATTEMPTS} attempts")

        log(f"--- 5{'a' if level == 'REPEATABLE READ' else 'b'}: {level} ---")
        run_threads(
            (withdraw, ("Thread-1", ACC_ZAINAB_USD)),
            (withdraw, ("Thread-2", ACC_KOLAWOLE_USD)),
        )
        combined = sum(v[0] for v in snapshot_accounts(dsn, [ACC_ZAINAB_USD, ACC_KOLAWOLE_USD]).values())
        log(f">> RESULT ({level}): combined balance = {combined} (rule >= {rule})")
        if combined < rule:
            log("   [ANOMALY CONFIRMED] Write skew: each snapshot saw a valid state, both")
            log("   committed, and the combined-collateral rule is now violated.")
        else:
            log("   [PASS] Rule preserved: SSI detected the rw-dependency cycle, aborted one")
            log("   session with 40001, and its retry saw the other's debit and declined.")
        restore_accounts(dsn, snap)
        log()

    run("REPEATABLE READ")
    run("SERIALIZABLE")


# ---------------------------------------------------------------------------
# Experiment 6: Idempotency key - concurrent duplicate submission + replay
# ---------------------------------------------------------------------------
def experiment_6_idempotency(dsn: str):
    log("=" * 72)
    log("EXPERIMENT 6: IDEMPOTENCY KEY (UNIQUE INDEX AS A CONCURRENCY CONTROL)")
    log("=" * 72)
    key = "idem-p3-concurrent-001"
    log(f"6a: two sessions submit the SAME payment request (idempotency_key '{key}')")
    log("    at the same instant, e.g. a mobile client double-tap. Each holds its")
    log("    INSERT open ~0.3s before COMMIT.")
    log()

    barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)
    insert_sql = """
        INSERT INTO transactions
            (transaction_id, transaction_reference, idempotency_key,
             source_account_id, destination_account_id, currency_code,
             amount, fee_amount, channel, status, initiated_at)
        VALUES (%s, %s, %s, %s, %s, 'USD', 50.0000, 0.0000, 'MOBILE_APP', 'PENDING', CURRENT_TIMESTAMP)
    """

    def submit(thread_name: str, txn_id: str, reference: str):
        conn = connect(dsn)
        try:
            with conn.cursor() as cur:
                barrier.wait()
                t0 = time.perf_counter()
                cur.execute(insert_sql, (txn_id, reference, key, ACC_AMINA_USD, ACC_CHIDI_USD))
                time.sleep(0.3)
            conn.commit()
            log(f"  [{thread_name}] COMMIT: payment {reference} accepted")
        except UniqueViolation:
            waited_ms = (time.perf_counter() - t0) * 1000
            conn.rollback()
            log(f"  [{thread_name}] UniqueViolation after waiting {waited_ms:.0f} ms on the "
                "uncommitted duplicate -> ROLLBACK (duplicate rejected)")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            log(f"  [{thread_name}] ERROR: {type(exc).__name__}: {exc}")
        finally:
            conn.close()

    run_threads(
        (submit, ("Thread-1", "90000001-0000-4000-8000-000000000001", "P3-IDEM-CONCURRENT-A")),
        (submit, ("Thread-2", "90000002-0000-4000-8000-000000000002", "P3-IDEM-CONCURRENT-B")),
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE idempotency_key = %s;", (key,)
        ).fetchone()[0]
    log(f">> RESULT: rows with key '{key}' = {n} (expected 1)")
    log("   [PASS] The unique index serialised the two inserts: the second waited for"
        if n == 1 else "   [FAIL] duplicate payment recorded")
    log("   the first to commit, then failed - exactly one payment exists.")
    log()

    log("6b: client replays an already-settled request (key 'idem-key-889911-a',")
    log("    seeded P1 transaction TXN-20261025-001).")
    conn = connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                insert_sql,
                ("90000003-0000-4000-8000-000000000003", "P3-IDEMPOTENCY-REPLAY",
                 "idem-key-889911-a", ACC_AMINA_USD, ACC_CHIDI_USD),
            )
        conn.commit()
        log("  [FAIL] Duplicate insert succeeded (constraint not enforced?)")
    except UniqueViolation as exc:
        conn.rollback()
        log(f"  [PASS] UniqueViolation (SQLSTATE {exc.sqlstate}): {str(exc).splitlines()[0]}")
        log("   Replay rolled back; the application returns the original result instead.")
    finally:
        conn.close()
    log()


# ---------------------------------------------------------------------------
# Invariant assertions (ported from Portfolio 1 verify_schema.py)
# ---------------------------------------------------------------------------
def assert_invariants(dsn: str, phase: str) -> int:
    log("=" * 72)
    log(f"{phase} INVARIANT ASSERTIONS (Portfolio 1 enforcement)")
    log("=" * 72)
    failures = 0
    conn = connect(dsn)
    try:
        with conn.cursor() as cur:
            # 1. Journal debit = credit balance
            cur.execute(
                """
                SELECT j.journal_id
                FROM journal_entries j
                JOIN ledger_entries le ON le.journal_id = j.journal_id
                GROUP BY j.journal_id
                HAVING SUM(CASE WHEN le.entry_type = 'DEBIT' THEN le.amount ELSE 0 END)
                     <> SUM(CASE WHEN le.entry_type = 'CREDIT' THEN le.amount ELSE 0 END)
                """
            )
            unbalanced = cur.fetchall()
            if unbalanced:
                failures += 1
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
                failures += 1
                log(f"  [FAIL] {len(mismatches)} account(s) with balance/balance_after mismatch: {mismatches}")
            else:
                log("  [PASS] current_balance == latest balance_after for all posted accounts.")

            # 3. Solvency never violated
            cur.execute("SELECT COUNT(*) FROM accounts WHERE current_balance < -overdraft_limit")
            insolvent = cur.fetchone()[0]
            if insolvent > 0:
                failures += 1
                log(f"  [FAIL] {insolvent} account(s) breach solvency (balance < -overdraft_limit)")
            else:
                log("  [PASS] All accounts solvent: current_balance >= -overdraft_limit.")

            # 4. Append-only: UPDATE on ledger_entries blocked
            try:
                cur.execute(
                    "UPDATE ledger_entries SET amount = amount "
                    "WHERE ledger_entry_id = '20000001-0000-4000-8000-000000000001';"
                )
                conn.rollback()
                failures += 1
                log("  [FAIL] UPDATE on ledger_entries was NOT blocked (append-only broken)")
            except psycopg.Error:
                conn.rollback()
                log("  [PASS] UPDATE on ledger_entries blocked (append-only enforced).")

            # 5. Integrity triggers still installed
            cur.execute(
                """
                SELECT COUNT(DISTINCT trigger_name) FROM information_schema.triggers
                WHERE event_object_table IN ('accounts','journal_entries','ledger_entries','transactions')
                """
            )
            log(f"  [INFO] {cur.fetchone()[0]} distinct integrity triggers on P1 financial tables.")
    finally:
        conn.close()
    log()
    return failures


def run_all(conn_dsn: str) -> int:
    failures = assert_invariants(conn_dsn, "PRE-RUN")

    experiment_1_lost_update(conn_dsn)
    experiment_2_atomic_pessimistic(conn_dsn)
    experiment_3_occ(conn_dsn)
    experiment_4_deadlock(conn_dsn)
    experiment_5_write_skew(conn_dsn)
    experiment_6_idempotency(conn_dsn)

    failures += assert_invariants(conn_dsn, "POST-RUN")
    log("=" * 72)
    log("ALL CONCURRENCY EXPERIMENTS COMPLETE"
        + ("" if failures == 0 else f" - {failures} INVARIANT FAILURE(S)"))
    log("=" * 72)

    evidence_path = Path(__file__).resolve().parent / "concurrency_test_evidence.txt"
    evidence_path.write_text("\n".join(log_output) + "\n", encoding="utf-8")
    print()
    print(f"[OK] Evidence written to: {evidence_path}")
    return failures
