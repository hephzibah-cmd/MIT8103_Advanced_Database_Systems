# Portfolio 3: Transactions and Concurrency
## Transaction Isolation Levels, Concurrency Anomalies, and Control Mechanisms
**Course:** MIT 8103 Advanced Database Systems  
**Case Study:** ApexBank Digital (Next-Generation Digital Banking & Fintech Platform)  
**Database Engine:** PostgreSQL 16  
**Schema:** Portfolio 1 (`../portfolio-1-database-design/ddl_schema.sql`)

---

### 1. Introduction: ACID Guarantees in Financial Ledgers

In digital core banking architectures like **ApexBank Digital**, transaction management is the ultimate defense against financial insolvency. Transactions must strictly satisfy the ACID criteria:

- **Atomicity:** All debits, credits, and audit journal lines commit as an indivisible unit; any failure causes a complete rollback.
- **Consistency:** Database invariants (`SUM(debits) = SUM(credits)` per journal and `current_balance >= -overdraft_limit`) are satisfied at the beginning and end of every transaction.
- **Isolation:** Concurrently executing transactions must not observe or corrupt each other's intermediate uncommitted states.
- **Durability:** Once committed, transactions survive system crashes, power outages, and media failure via PostgreSQL write-ahead logging (WAL).

Portfolio 1 enforces these invariants at the database level through:

| P1 Enforcement Mechanism | DDL Reference | ACID Property |
|--------------------------|---------------|---------------|
| Deferred `trg_journal_has_lines` constraint trigger | `ddl_schema.sql:349` | Atomicity (no empty journals at commit) |
| Deferred `trg_ledger_balanced` constraint trigger | `ddl_schema.sql:343` | Consistency (debits == credits per journal at commit) |
| `trg_ledger_apply_balance` AFTER INSERT trigger | `ddl_schema.sql:390` | Consistency + Isolation (posting-maintained `current_balance` via a relative `current_balance = current_balance ± amount` update, and `balance_after` validation that rejects postings computed from a stale read) |
| `chk_account_solvency` CHECK constraint | `ddl_schema.sql:104` | Consistency (no unauthorized overdraft) |
| `chk_account_holds` CHECK constraint | `ddl_schema.sql:105` | Consistency (hold balance within available funds) |
| `UNIQUE (idempotency_key)` on `transactions` | `ddl_schema.sql:169` | Consistency + Isolation (no duplicate payments from retries or concurrent double-submits) |
| `UNIQUE (journal_id)` on `transactions` | `ddl_schema.sql:173` | Consistency (one payment per journal) |
| Append-only `trg_journal_append_only` / `trg_ledger_append_only` | `ddl_schema.sql:291,295` | Integrity / auditability (immutable financial history; durability itself comes from WAL) |
| `accounts.version` column | `ddl_schema.sql:93` | Isolation (OCC compare-and-swap) |

---

### 2. Transaction Isolation Levels & Concurrency Anomalies

The ANSI SQL-92 standard defines isolation levels by the phenomena they must prevent (dirty read, non-repeatable read, phantom). Berenson et al. (1995) showed these definitions are ambiguous and added further phenomena, notably **Lost Update (P4)** and **Write Skew (A5B)**. Two views are therefore needed: what the standard (lock-based reading) permits, and what PostgreSQL 16 actually does, because PostgreSQL implements isolation with MVCC snapshots rather than read locks.

**Table 2a - ANSI SQL-92 / Berenson et al. (lock-based interpretation):**

| Isolation Level | Dirty Read (P1) | Non-Repeatable Read (P2) | Phantom (P3) | Lost Update (P4) | Write Skew (A5B) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **READ UNCOMMITTED** | Possible | Possible | Possible | Possible | Possible |
| **READ COMMITTED** | Prevented | Possible | Possible | Possible | Possible |
| **REPEATABLE READ** | Prevented | Prevented | Possible | Prevented | Prevented |
| **SERIALIZABLE** | Prevented | Prevented | Prevented | Prevented | Prevented |

**Table 2b - PostgreSQL 16 actual behaviour (MVCC):**

| Isolation Level (PostgreSQL 16) | Dirty Read | Non-Repeatable Read | Phantom | Lost Update (read-modify-write) | Write Skew |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **READ UNCOMMITTED** (behaves exactly as READ COMMITTED) | **Prevented** | Possible | Possible | Possible | Possible |
| **READ COMMITTED** (new snapshot per statement) | **Prevented** | Possible | Possible | Possible (Exp. 1a) | Possible |
| **REPEATABLE READ** (snapshot isolation, one snapshot per transaction) | **Prevented** | **Prevented** | **Prevented** | **Prevented** - stale writer aborted with `40001` (Exp. 1b) | Possible (Exp. 5a) |
| **SERIALIZABLE** (Serializable Snapshot Isolation, SSI) | **Prevented** | **Prevented** | **Prevented** | **Prevented** (`40001`) | **Prevented** - `40001` (Exp. 5b) |

Key differences from the ANSI table: PostgreSQL never exposes uncommitted data, even at READ UNCOMMITTED; its REPEATABLE READ is *stronger* than ANSI on phantoms (the snapshot hides newly inserted rows) but *weaker* than lock-based REPEATABLE READ on write skew, because snapshot isolation only detects write-write conflicts on the same row. At REPEATABLE READ and SERIALIZABLE, prevention works by **aborting** a transaction (SQLSTATE `40001`), so applications must retry; at READ COMMITTED a concurrent `UPDATE` instead waits for the row lock and then re-evaluates its `WHERE` clause against the newest committed row version.

#### 2.1 Anomaly Definitions in Banking Scenarios:

1. **Dirty Read (P1):**
   - *Definition:* Transaction $T_1$ modifies an account balance. Transaction $T_2$ reads this modified balance before $T_1$ commits. $T_1$ subsequently aborts (`ROLLBACK`).
   - *Fintech Hazard:* A merchant POS terminal reads uncommitted funds, authorizes a physical withdrawal, and the customer's transfer aborts, leaving the bank short of funds.
   - *Prevention:* Prohibit uncommitted reads; enforce **READ COMMITTED** or higher via shared read locks or MVCC snapshots. In PostgreSQL this is unconditional: MVCC snapshots only ever contain committed row versions, so a dirty read cannot be produced at any level (hence no dirty-read experiment).

2. **Non-Repeatable (Fuzzy) Read (P2):**
   - *Definition:* Transaction $T_1$ reads an account balance. Transaction $T_2$ modifies and commits a new balance on that account. $T_1$ re-reads the account balance and observes a different value.
   - *Fintech Hazard:* An end-of-day interest accrual calculation reads balance $B$, prepares an interest credit, but in between, a debit commits, calculating interest on outdated capital.

3. **Phantom Read (P3):**
   - *Definition:* Transaction $T_1$ executes a range query (e.g., `COUNT(*) FROM accounts WHERE customer_id = 'c001'`). Transaction $T_2$ inserts a new account for `c001` and commits. $T_1$ re-runs the range query and sees a new "phantom" row.
   - *Fintech Hazard:* A credit limit validator verifies that a customer has $\le 3$ active credit cards. Before the fourth card is issued, a concurrent session inserts another, violating credit risk caps.

4. **Lost Update (P4):**
   - *Definition:* Both $T_1$ and $T_2$ read the same balance $X$. $T_1$ updates $X \leftarrow X - \Delta_1$. $T_2$ updates $X \leftarrow X - \Delta_2$ based on its original read, overwriting $T_1$'s modification.
   - *Fintech Hazard:* Empirically verified in Experiment 1a: two simultaneous $800 withdrawals from the same account both read the pre-withdrawal balance and each write `balance - 800`; the second write erases the first deduction, so $1,600 is paid out but only $800 is deducted.
   - *Defenses:* `chk_account_solvency` prevents overdrafts but does not prevent lost updates on valid debits. Options: (i) atomic relative updates (`SET current_balance = current_balance - :amount`, optionally guarded, Experiment 2) - this is exactly how P1's `trg_ledger_apply_balance` posts, and its `balance_after` check rejects a posting computed from a stale balance, so the proper ledger path is not exposed to this anomaly; (ii) `SELECT ... FOR UPDATE` before the read (pessimistic); (iii) OCC with the `version` column (Experiment 3); or (iv) REPEATABLE READ / SERIALIZABLE, where PostgreSQL aborts the stale writer with `40001` and the application retries (Experiment 1b).

5. **Write Skew (A5B, Snapshot Isolation Anomaly):**
   - *Definition:* Two transactions read overlapping data sets but write to disjoint rows, violating an inter-row invariant.
   - *Fintech Hazard:* Customer has Account A ($600) and Account B ($500) with a combined collateral requirement: `Bal_A + Bal_B >= $1,000`. $T_1$ reads both, sees $1,100, and withdraws $500 from Account A. Concurrently, $T_2$ reads both, sees $1,100, and withdraws $500 from Account B. Both commit under standard Snapshot Isolation, leaving combined balance at $100 (breaching the $1,000 collateral constraint).
   - *Defense:* PostgreSQL's **SERIALIZABLE** level (SSI, Cahill et al. 2008; Ports & Grittner 2012) tracks read/write (rw-) antidependencies via predicate (SIRead) locks; when two concurrent transactions form a dangerous structure it aborts one with `SerializationFailure` (`40001`), forcing a retry. Experiment 5 reproduces the anomaly at REPEATABLE READ (both commit, rule broken) and its prevention at SERIALIZABLE. An alternative without SERIALIZABLE is to materialise the conflict, e.g. `SELECT ... FOR UPDATE` on *both* accounts before checking the rule.

---

### 3. Concurrency Control Mechanisms in ApexBank Digital

To eliminate race conditions while preserving high transaction throughput, the following three core control patterns are deployed against the Portfolio 1 schema:

#### 3.1 Mechanism 1: Atomic Invariant Guards (Pessimistic Decrements)

Instead of executing multi-step application logic (`SELECT` then `UPDATE`), the database executes an atomic predicate-guarded write:

```sql
UPDATE accounts
SET current_balance = current_balance - :amount
WHERE account_id = :account_id
  AND (current_balance + overdraft_limit) >= :amount;
```

**Underlying Engine Mechanics:**
- The `UPDATE` evaluates its `WHERE` clause against its snapshot, then takes a row-level write lock on each qualifying tuple; the lock is held until `COMMIT`/`ROLLBACK`.
- If another transaction has already updated (and still locks) the row, the second `UPDATE` waits. Under READ COMMITTED, once the first commits, PostgreSQL re-fetches the newest row version and re-evaluates the `WHERE` clause against it (the "EvalPlanQual" recheck). If the guard no longer holds, the row is skipped (`rowcount = 0`); otherwise the decrement is applied to the *new* balance. Either way no update is lost and the guard is never evaluated on stale data. (Under REPEATABLE READ the waiting `UPDATE` would instead fail with `40001`.)
- Experiment 2 shows this directly: of two concurrent $9,000 debits on a $15,248.50 spendable balance, one succeeds and the other waits ~300 ms on the row lock and then matches 0 rows.
- The `chk_account_solvency` CHECK constraint provides a second line of defense, rejecting any row update that would push `current_balance` below `-overdraft_limit`.

#### 3.2 Mechanism 2: Optimistic Concurrency Control (OCC) with Version Stamping

For multi-screen web workflows or checkout approvals where holding database locks across HTTP calls is unacceptable, **Optimistic Concurrency Control (OCC)** is implemented using the `accounts.version` column (added to P1 DDL specifically for this pattern):

```sql
-- Step 1: Read state
SELECT current_balance, version FROM accounts WHERE account_id = :id;

-- Step 2: Compare-And-Swap (CAS) write
UPDATE accounts
SET current_balance = :new_balance,
    version = version + 1
WHERE account_id = :id
  AND version = :read_version;
```

If another transaction committed between Step 1 and Step 2, `version` has advanced, causing the `UPDATE` to match 0 rows. The application detects the conflict (`rowcount = 0`), aborts the operation, re-reads and retries (bounded retries). No lock is held between the read and the write; the CAS `UPDATE` itself still takes a brief row lock, and if it collides with an uncommitted writer it waits and then re-checks `version` (READ COMMITTED recheck), so the conflict is still detected. Experiment 3 shows one CAS rejected and the retry succeeding, with both debits applied and `version` advanced by 2.

#### 3.3 Mechanism 3: Deadlock Prevention via Canonical Resource Ordering

A deadlock occurs when two or more transactions hold locks that the other requires to proceed, forming a circular wait. According to **Coffman's Conditions**, a deadlock requires four simultaneous conditions:

1. Mutual Exclusion
2. Hold and Wait
3. No Preemption
4. **Circular Wait**

```mermaid
graph LR
    subgraph Circular Wait Deadlock
        T1[Transaction 1: Amina -> Chidi] -->|Holds Lock| LA[Account A]
        LA -.->|Waits For| T2[Transaction 2: Chidi -> Amina]
        T2 -->|Holds Lock| LB[Account B]
        LB -.->|Waits For| T1
    end

    subgraph Canonical Lock Ordering Fix
        T3[Transaction 1] -->|Step 1: Locks min(A,B)| L1[Lock Account A]
        T4[Transaction 2] -->|Step 1: Waits for min(A,B)| L1
        L1 -->|Step 2: Locks max(A,B)| L2[Lock Account B]
    end
```

**The Canonical Ordering Protocol:**
To break Coffman's fourth condition (Circular Wait), ApexBank enforces a strict total ordering over resource acquisitions:

$$\text{Account}_{\text{First}} = \min(\text{from\_id}, \text{to\_id}), \quad \text{Account}_{\text{Second}} = \max(\text{from\_id}, \text{to\_id})$$

Both concurrent transactions are mandated to acquire row locks in lexicographic order using `SELECT ... FOR UPDATE`. Because Thread 1 and Thread 2 both compete for the lower `account_id` first, one wins and proceeds while the other waits, completely eliminating the circular dependency graph.

In PostgreSQL, `SELECT ... FOR UPDATE` acquires a row-level lock (the strongest row lock mode, conflicting with other `FOR UPDATE`/`UPDATE`/`DELETE` on that row, but not with plain `SELECT`, which reads an MVCC snapshot) that is held until transaction end. The ordering must therefore be applied to every lock a transaction takes, from the first one.

**Deadlock detection (the fallback):** prevention is a coding discipline, so PostgreSQL also *detects* deadlocks. A session that has waited for a lock longer than `deadlock_timeout` (default 1s) checks the wait-for graph; if it finds a cycle, it aborts one transaction with `DeadlockDetected` (SQLSTATE `40P01`), releasing its locks so the others continue. Experiment 4a reproduces this with unordered locking (one victim, retried successfully); Experiment 4b shows canonical ordering yields zero deadlocks and no ~1s detection stall.

**Retry policy:** `40001` (serialization failure) and `40P01` (deadlock) mean "nothing was committed, safe to retry the whole transaction". The experiments retry up to 3 times; production code should add jittered back-off and, for payments, combine retries with the idempotency key so a retried request cannot post twice.

---

### 4. Empirical Validation

All mechanisms above are empirically validated in `concurrency_simulation.py`, which runs against the live Portfolio 1 PostgreSQL schema (`apexbank_concurrency` database) and exercises:

- **Lost Update** under READ COMMITTED (anomaly) vs REPEATABLE READ (`40001` + retry) (Experiment 1)
- **Atomic pessimistic guard** with solvency check and lock-wait recheck (Experiment 2)
- **OCC with version stamping** and retry (Experiment 3)
- **Deadlock detection (`40P01`) vs prevention via canonical lock ordering** (Experiment 4)
- **Write skew** at REPEATABLE READ (anomaly) vs SERIALIZABLE (SSI `40001` + retry) (Experiment 5)
- **Idempotency key uniqueness** under concurrent duplicate submission and replay (Experiment 6)
- **Portfolio 1 invariant assertions** before and after the run: journal debit/credit balance, `current_balance == latest balance_after`, solvency, append-only enforcement

Each thread uses its own database connection, and a `threading.Barrier` forces the interleaving under test, so outcomes are deterministic across runs. Experiments 1-5 write `accounts.current_balance` directly to isolate one mechanism at a time and restore the touched rows afterwards. COMMIT, ROLLBACK (application- and constraint-initiated) and SAVEPOINT behaviour is demonstrated separately in `transactions.sql`, whose outcomes are also verified in the evidence file.

Evidence: `concurrency_test_evidence.txt`
