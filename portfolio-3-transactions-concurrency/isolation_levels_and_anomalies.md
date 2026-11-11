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
| Deferred `trg_journal_has_lines` constraint trigger | `ddl_schema.sql:348` | Atomicity (no empty journals at commit) |
| Deferred `trg_ledger_balanced` constraint trigger | `ddl_schema.sql:342` | Consistency (debits == credits per journal at commit) |
| `trg_ledger_apply_balance` AFTER INSERT trigger | `ddl_schema.sql:389` | Consistency (posting-maintained `current_balance` + `balance_after` validation) |
| `chk_account_solvency` CHECK constraint | `ddl_schema.sql:103` | Consistency (no unauthorized overdraft) |
| `chk_account_holds` CHECK constraint | `ddl_schema.sql:104` | Consistency (hold balance within available funds) |
| `UNIQUE (idempotency_key)` on `transactions` | `ddl_schema.sql:168` | Atomicity (no duplicate debits from retries) |
| `UNIQUE (journal_id)` on `transactions` | `ddl_schema.sql:167` | Atomicity (one transaction per journal) |
| Append-only `trg_journal_append_only` / `trg_ledger_append_only` | `ddl_schema.sql:290,294` | Durability (immutable financial history) |
| `accounts.version` column | `ddl_schema.sql:93` | Isolation (OCC compare-and-swap) |

---

### 2. Transaction Isolation Levels & Concurrency Anomalies

The ANSI SQL-92 standard and Berenson et al. (1995) formalize transaction isolation levels based on the phenomena (anomalies) they permit or prevent:

| Isolation Level | Dirty Read | Non-Repeatable Read | Phantom Read | Lost Update | Write Skew |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **READ UNCOMMITTED** | Allowed | Allowed | Allowed | Allowed | Allowed |
| **READ COMMITTED** | **Prevented** | Allowed | Allowed | Allowed | Allowed |
| **REPEATABLE READ** | **Prevented** | **Prevented** | Allowed / Prevented (MVCC) | **Prevented** | Allowed |
| **SERIALIZABLE** | **Prevented** | **Prevented** | **Prevented** | **Prevented** | **Prevented** |

#### 2.1 Anomaly Definitions in Banking Scenarios:

1. **Dirty Read ($G_1$):**
   - *Definition:* Transaction $T_1$ modifies an account balance. Transaction $T_2$ reads this modified balance before $T_1$ commits. $T_1$ subsequently aborts (`ROLLBACK`).
   - *Fintech Hazard:* A merchant POS terminal reads uncommitted funds, authorizes a physical withdrawal, and the customer's transfer aborts, leaving the bank short of funds.
   - *Prevention:* Prohibit uncommitted reads; enforce **READ COMMITTED** or higher via shared read locks or MVCC snapshots.

2. **Non-Repeatable (Fuzzy) Read ($G_{2a}$):**
   - *Definition:* Transaction $T_1$ reads an account balance. Transaction $T_2$ modifies and commits a new balance on that account. $T_1$ re-reads the account balance and observes a different value.
   - *Fintech Hazard:* An end-of-day interest accrual calculation reads balance $B$, prepares an interest credit, but in between, a debit commits, calculating interest on outdated capital.

3. **Phantom Read ($A_3$):**
   - *Definition:* Transaction $T_1$ executes a range query (e.g., `COUNT(*) FROM accounts WHERE customer_id = 'c001'`). Transaction $T_2$ inserts a new account for `c001` and commits. $T_1$ re-runs the range query and sees a new "phantom" row.
   - *Fintech Hazard:* A credit limit validator verifies that a customer has $\le 3$ active credit cards. Before the fourth card is issued, a concurrent session inserts another, violating credit risk caps.

4. **Lost Update ($P_4$):**
   - *Definition:* Both $T_1$ and $T_2$ read the same balance $X$. $T_1$ updates $X \leftarrow X - \Delta_1$. $T_2$ updates $X \leftarrow X - \Delta_2$ based on its original read, overwriting $T_1$'s modification.
   - *Fintech Hazard:* Empirically verified in our benchmark: two simultaneous withdrawals from the same account both read the pre-withdrawal balance, both deduct, and the second write erases the first deduction — the bank disburses double the intended amount.
   - *P1 Defense:* `chk_account_solvency` prevents overdrafts but does not prevent lost updates on valid debits. Applications must use atomic guarded updates (`UPDATE accounts SET current_balance = current_balance - :amount WHERE ... AND (current_balance + overdraft_limit) >= :amount`) or OCC with the `version` column.

5. **Write Skew (Snapshot Isolation Anomaly):**
   - *Definition:* Two transactions read overlapping data sets but write to disjoint rows, violating an inter-row invariant.
   - *Fintech Hazard:* Customer has Account A ($600) and Account B ($500) with a combined collateral requirement: `Bal_A + Bal_B >= $1,000`. $T_1$ reads both, sees $1,100, and withdraws $500 from Account A. Concurrently, $T_2$ reads both, sees $1,100, and withdraws $500 from Account B. Both commit under standard Snapshot Isolation, leaving combined balance at $100 (breaching the $1,000 collateral constraint).
   - *P1 Defense:* **SERIALIZABLE** isolation level detects the write skew and raises `SerializationFailure`, forcing a retry.

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
- PostgreSQL acquires an exclusive row lock (`X-Lock`) on the target `accounts` row prior to evaluating the `WHERE` clause.
- Because the condition and decrement occur within a single database atomic operation, concurrent threads serialize. The first thread decrements the balance and commits; subsequent threads re-evaluate the `WHERE` clause against the new committed balance and find the condition false (`rowcount = 0`), completely eliminating race conditions.
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

If another transaction committed between Step 1 and Step 2, `version` has advanced, causing the `UPDATE` to match 0 rows. The application detects the conflict (`rowcount = 0`), aborts the operation, and triggers a retry without any locks being held.

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

In PostgreSQL, `SELECT ... FOR UPDATE` acquires a row-level exclusive lock that is held until transaction commit, so the ordering must be established before any `SELECT ... FOR UPDATE` on the second account.

---

### 4. Empirical Validation

All mechanisms above are empirically validated in `concurrency_simulation.py`, which runs against the live Portfolio 1 PostgreSQL schema (`apexbank_concurrency` database) and exercises:

- **Lost Update** under READ COMMITTED (Experiment 1)
- **Atomic pessimistic guard** with solvency check (Experiment 2)
- **OCC with version stamping** (Experiment 3)
- **Deadlock prevention via canonical lock ordering** (Experiment 4)
- **SERIALIZABLE write-skew prevention** (Experiment 5)
- **Idempotency key uniqueness** (Experiment 6)
- **Portfolio 1 invariant assertions**: journal debit/credit balance, `current_balance == latest balance_after`, solvency, append-only enforcement (post-run assertions)

Evidence: `concurrency_test_evidence.txt`
