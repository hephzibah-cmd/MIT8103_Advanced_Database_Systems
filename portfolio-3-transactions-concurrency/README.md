# Portfolio 3: Transactions and Concurrency
**Course:** MIT 8103 Advanced Database Systems  
**Case Study:** ApexBank Digital (Next-Generation Digital Banking & Fintech Platform)  
**Database Engine:** PostgreSQL 16  
**Schema:** Portfolio 1 (`../portfolio-1-database-design/ddl_schema.sql`)

---

### Executive Summary

Portfolio 3 presents practical implementations, architectural explanations, and empirical simulation logs demonstrating ACID transaction processing, rollback mechanisms, isolation level guarantees, and concurrency control in **ApexBank Digital**. All experiments execute against the **live Portfolio 1 PostgreSQL schema** (tables, triggers, deferred constraints, `chk_account_solvency`, idempotency uniqueness, append-only ledger/journal) in a dedicated `apexbank_concurrency` database — Portfolio 1's `apexbank` database is never modified.

---

### Directory Contents & Deliverables

| File | Description |
| :--- | :--- |
| [`transactions.sql`](transactions.sql) | Three ACID transaction scripts against real P1 seeded data: (1) atomic double-entry P2P transfer with `COMMIT`, (2) insufficient-funds guarded debit with `ROLLBACK`, (3) idempotency-key collision `UniqueViolation` with `ROLLBACK`. |
| [`concurrency_runner.py`](concurrency_runner.py) | Orchestrates the full P3 run: creates `apexbank_concurrency` DB, loads P1 DDL + seed, executes `transactions.sql`, then runs `concurrency_simulation.py`. Follows the same env-var DSN + separate-DB pattern as Portfolio 2's `benchmark_runner.py`. |
| [`concurrency_simulation.py`](concurrency_simulation.py) | Multithreaded Python simulation engine (psycopg, PostgreSQL 16) demonstrating: Lost Update, Atomic Pessimistic Guard, Optimistic Concurrency Control (OCC), Deadlock Prevention via Canonical Lock Ordering, SERIALIZABLE Write-Skew prevention, Idempotency Uniqueness. Asserts P1 invariants post-run. |
| [`concurrency_test_evidence.txt`](concurrency_test_evidence.txt) | Raw console log evidence documenting the execution of all concurrency experiments and invariant assertions, generated against PostgreSQL 16. |
| [`isolation_levels_and_anomalies.md`](isolation_levels_and_anomalies.md) | Academic and technical analysis of the 4 ANSI SQL isolation levels, Dirty/Non-repeatable/Phantom/Lost-Update/Write-Skew anomalies, Coffman's deadlock conditions, and the P1 enforcement mechanisms (deferred triggers, CHECK constraints, `version` column) that defend against them. |

---

### Setup & Run

From the repository root:

```bash
# 1. Start PostgreSQL 16 (once)
docker compose up -d

# 2. Install Python dependencies (psycopg[binary]>=3.2)
pip install -r requirements.txt

# 3. Run Portfolio 3
python portfolio-3-transactions-concurrency/concurrency_runner.py
```

The runner connects via `P3_DATABASE_URL` (default: `postgresql://apexbank:apexbank_dev@localhost:5432/apexbank_concurrency`). Override with:

```powershell
$env:P3_DATABASE_URL="postgresql://apexbank:apexbank_dev@localhost:5432/apexbank_concurrency"
```

What the runner does:

1. Creates/reuses the `apexbank_concurrency` database (P1's `apexbank` database is untouched).
2. Loads Portfolio 1 DDL and seed data into the concurrency database.
3. Executes the three ACID transaction scripts from `transactions.sql`.
4. Runs six multithreaded concurrency experiments via `concurrency_simulation.py`.
5. Asserts Portfolio 1 invariants (journal balance, `current_balance == latest balance_after`, solvency, append-only).
6. Writes `concurrency_test_evidence.txt`.

---

### Key Concurrency Experiments & Findings

1. **Lost Update & Double-Spending Race Condition:**
   - Two simultaneous withdrawals against the same account under READ COMMITTED with naive read-modify-write. Both threads read the same balance and both write the same post-withdrawal balance — the second write erases the first deduction. Confirmed anomaly.

2. **Pessimistic Atomic Invariant Enforcement:**
   - `UPDATE accounts SET current_balance = current_balance - :amount WHERE account_id = :id AND (current_balance + overdraft_limit) >= :amount`. The solvency guard is evaluated atomically inside the UPDATE; concurrent threads serialize on the row lock. Debits that would keep the account solvent succeed; debits that would breach overdraft are rejected (`rowcount = 0`).

3. **Optimistic Concurrency Control (OCC):**
   - Compare-And-Swap on the `accounts.version` column. Threads read `(balance, version)`, then `UPDATE ... SET version = version + 1 WHERE version = :read_version`. The thread whose version still matches commits; the other aborts (`rowcount = 0`) and retries. No long-lived locks.

4. **Deadlock Prevention via Canonical Lock Ordering:**
   - Bidirectional transfers between two accounts. Both threads acquire `SELECT ... FOR UPDATE` locks in lexicographic order (`min(account_id)` first, then `max(account_id)`). Circular wait is impossible; both transfers serialize and complete with zero deadlocks.

5. **SERIALIZABLE Write-Skew Prevention:**
   - Two concurrent transactions withdraw from different accounts while checking a combined collateral invariant. Under SERIALIZABLE, PostgreSQL detects the dangerous read/write pattern and raises `SerializationFailure` on one transaction, forcing abort and retry.

6. **Idempotency Key Collision:**
   - Retrying a payment with an already-committed `idempotency_key` raises `UniqueViolation` on `transactions.idempotency_key`; the transaction rolls back, preventing double debit.

---

### Relationship to Portfolio 1

- **Schema:** Portfolio 3 reuses `../portfolio-1-database-design/ddl_schema.sql` and `../portfolio-1-database-design/seed_data.sql` verbatim (loaded into `apexbank_concurrency`, not `apexbank`).
- **The `version` column:** A `version INTEGER NOT NULL DEFAULT 1` column was added to P1's `accounts` table (`ddl_schema.sql:93`) to give OCC a physical compare-and-swap target. This is purely additive — existing seed data and P1 verification are unaffected (re-verified with `verify_schema.py`).
- **Triggers exercised:** `trg_ledger_apply_balance`, `trg_ledger_balanced`, `trg_journal_has_lines`, `trg_transaction_currency_guard`, `trg_*_append_only`, `chk_account_solvency`, `chk_account_holds`, `UNIQUE (idempotency_key)`.

---

### File Links

Use relative links only:
- `transactions.sql`
- `concurrency_runner.py`
- `concurrency_simulation.py`
- `concurrency_test_evidence.txt`
- `isolation_levels_and_anomalies.md`
- `../portfolio-1-database-design/ddl_schema.sql`
- `../portfolio-1-database-design/seed_data.sql`
- `../portfolio-1-database-design/verify_schema.py`
