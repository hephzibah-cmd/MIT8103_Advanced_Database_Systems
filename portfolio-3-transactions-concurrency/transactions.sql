-- ==============================================================================
-- MIT 8103 Advanced Database Systems - Practical Database Portfolio
-- Case Study: ApexBank Digital (Fintech & Core Banking Platform)
-- Portfolio 3: Transactions and Concurrency - ACID Transaction Scripts
-- Database Engine: PostgreSQL 16 (mit8103-postgres)
-- Schema source: ../portfolio-1-database-design/ddl_schema.sql
-- Seed source:     ../portfolio-1-database-design/seed_data.sql
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- TRANSACTION 1: Successful Atomic P2P Transfer with Double-Entry Bookkeeping
-- Business Scenario: Amina Bello (a0000001, USD) transfers $300.00 to
-- Chidi Okonkwo (a0000002, USD) with a $2.00 platform fee settled to
-- ApexBank Treasury (a0000008, USD).
--
-- ACID Properties Demonstrated:
--  - Atomicity: journal header + 3 ledger lines + transaction row commit
--                together or none do (single psycopg transaction block).
--  - Consistency: debits ($302.00) == credits ($300.00 + $2.00); the
--                deferred trg_ledger_balanced trigger enforces this at COMMIT.
--  - Isolation: intermediate balance states hidden from concurrent readers.
--  - Durability: committed changes survive via PostgreSQL WAL.
-- ------------------------------------------------------------------------------

BEGIN;

-- Step 1.1: Post double-entry journal header
INSERT INTO journal_entries (
    journal_id, entry_reference, narrative, event_type, posting_date, created_at
) VALUES (
    '50000001-0000-4000-8000-000000000001',
    'REF-P3-P2P-20261101-001',
    'P3 P2P Transfer Amina -> Chidi ($300.00 + $2.00 fee)',
    'P2P_TRANSFER',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);

-- Step 1.2: Post balanced double-entry ledger lines
--   DEBIT  Amina   $302.00  (balance_after = 14500.50 - 302.00 = 14198.50)
--   CREDIT Chidi   $300.00  (balance_after =  8250.00 + 300.00 =  8550.00)
--   CREDIT Treasury  $2.00  (balance_after = 18452.05 +   2.00 = 18454.05)
INSERT INTO ledger_entries (
    ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after, created_at
) VALUES
('60000001-0000-4000-8000-000000000001', '50000001-0000-4000-8000-000000000001', 'a0000001-0000-4000-8000-000000000001', 'DEBIT',  302.0000, 14198.5000, CURRENT_TIMESTAMP),
('60000002-0000-4000-8000-000000000002', '50000001-0000-4000-8000-000000000001', 'a0000002-0000-4000-8000-000000000002', 'CREDIT', 300.0000,  8550.0000, CURRENT_TIMESTAMP),
('60000003-0000-4000-8000-000000000003', '50000001-0000-4000-8000-000000000001', 'a0000008-0000-4000-8000-000000000008', 'CREDIT',   2.0000, 18454.0500, CURRENT_TIMESTAMP);

-- Step 1.3: Record customer-facing payment record with idempotency key
INSERT INTO transactions (
    transaction_id, transaction_reference, idempotency_key,
    source_account_id, destination_account_id, journal_id,
    currency_code, amount, fee_amount, channel, status, initiated_at, completed_at
) VALUES (
    '70000001-0000-4000-8000-000000000001',
    'P3-TXN-20261101-001',
    'idem-p3-p2p-001-success',
    'a0000001-0000-4000-8000-000000000001',
    'a0000002-0000-4000-8000-000000000002',
    '50000001-0000-4000-8000-000000000001',
    'USD',
    300.0000,
    2.0000,
    'MOBILE_APP',
    'SETTLED',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);

COMMIT;

-- Verification queries (run after COMMIT):
-- SELECT current_balance FROM accounts WHERE account_id IN (...);
-- SELECT journal_id, SUM(CASE WHEN entry_type='DEBIT' THEN amount ELSE -amount END) AS net
--   FROM ledger_entries WHERE journal_id = '50000001-...' GROUP BY journal_id;


-- ------------------------------------------------------------------------------
-- TRANSACTION 2: Insufficient Funds Failure Triggering Complete ROLLBACK
-- Business Scenario: David Kalu (a0000004, NGN) attempts to transfer
-- 150,000.00 NGN. His balance is 45,000.00 NGN with 0 overdraft limit.
-- The atomic solvency guard (WHERE current_balance + overdraft_limit >= amount)
-- matches 0 rows; the application detects rowcount=0 and issues an explicit,
-- application-initiated ROLLBACK (compare Transaction 4, where the engine
-- itself forces the rollback).
-- Verification: balance unchanged, no ledger rows written.
-- ------------------------------------------------------------------------------

BEGIN;

-- Step 2.1: Attempt atomic debit guarded by solvency (chk_account_solvency)
-- Expected: rowcount = 0 because 45000.00 + 0 < 150000.00
UPDATE accounts
SET current_balance = current_balance - 150000.0000
WHERE account_id = 'a0000004-0000-4000-8000-000000000004'
  AND (current_balance + overdraft_limit) >= 150000.0000;

-- Application detects 0 rows affected -> insufficient funds -> abort
ROLLBACK;

-- Verification query (run after ROLLBACK):
-- SELECT current_balance FROM accounts WHERE account_id = 'a0000004-...';
--   Expected: 45000.0000 (unchanged)


-- ------------------------------------------------------------------------------
-- TRANSACTION 3: Duplicate Request / Idempotency Collision with Abort
-- Business Scenario: A mobile app client retries a payment with the same
-- idempotency key 'idem-key-889911-a' (already committed by Portfolio 1 seed
-- transaction TXN-20261025-001). The UNIQUE constraint on
-- transactions.idempotency_key intercepts the duplicate insert, raising
-- UniqueViolation and rolling back the duplicate attempt.
-- ------------------------------------------------------------------------------

BEGIN;

INSERT INTO transactions (
    transaction_id, transaction_reference, idempotency_key,
    source_account_id, destination_account_id,
    currency_code, amount, fee_amount, channel, status, initiated_at
) VALUES (
    '70000002-0000-4000-8000-000000000002',
    'P3-TXN-DUPLICATE-002',
    'idem-key-889911-a',        -- Collides with seeded Transaction 1
    'a0000001-0000-4000-8000-000000000001',
    'a0000002-0000-4000-8000-000000000002',
    'USD',
    300.0000,
    2.0000,
    'MOBILE_APP',
    'PENDING',
    CURRENT_TIMESTAMP
);

-- Database engine throws: UniqueViolation on transactions.idempotency_key
-- Application handles exception:
ROLLBACK;

-- Verification query (run after ROLLBACK):
-- SELECT COUNT(*) FROM transactions WHERE idempotency_key = 'idem-key-889911-a';
--   Expected: 1 (only the original seeded payment)


-- ------------------------------------------------------------------------------
-- TRANSACTION 4: Constraint-Enforced ROLLBACK of a Partially Posted Journal
-- Business Scenario: David Kalu (a0000004, NGN, balance 45,000.00, overdraft 0)
-- attempts to pay 150,000.00 NGN to Grace (a0000003, NGN) through the proper
-- double-entry posting path. The journal header is inserted first; the DEBIT
-- ledger line then fires trg_ledger_apply_balance, whose UPDATE on accounts
-- would set current_balance to -105,000. That row breaks both chk_account_solvency
-- (balance >= -overdraft_limit) and chk_account_holds (hold_balance <= balance +
-- overdraft_limit); PostgreSQL 16 reports chk_account_holds. PostgreSQL aborts the
-- whole transaction: the already-inserted journal header is discarded too
-- (atomicity), so no orphan journal or half-applied posting survives.
-- ------------------------------------------------------------------------------

BEGIN;

INSERT INTO journal_entries (
    journal_id, entry_reference, narrative, event_type, posting_date, created_at
) VALUES (
    '50000004-0000-4000-8000-000000000004',
    'REF-P3-OVERDRAW-20261101-004',
    'P3 NGN transfer David -> Grace (exceeds solvency)',
    'P2P_TRANSFER',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);

-- Fails: CheckViolation (chk_account_holds / chk_account_solvency) raised inside trg_ledger_apply_balance
INSERT INTO ledger_entries (
    ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after, created_at
) VALUES
('60000041-0000-4000-8000-000000000041', '50000004-0000-4000-8000-000000000004', 'a0000004-0000-4000-8000-000000000004', 'DEBIT',  150000.0000, -105000.0000, CURRENT_TIMESTAMP),
('60000042-0000-4000-8000-000000000042', '50000004-0000-4000-8000-000000000004', 'a0000003-0000-4000-8000-000000000003', 'CREDIT', 150000.0000,  900000.0000, CURRENT_TIMESTAMP);

-- The transaction is now in the aborted state; only ROLLBACK is accepted.
ROLLBACK;

-- Verification queries (run after ROLLBACK):
-- SELECT COUNT(*) FROM journal_entries WHERE journal_id = '50000004-0000-4000-8000-000000000004';
--   Expected: 0 (header rolled back with the failed lines)
-- SELECT current_balance FROM accounts WHERE account_id = 'a0000004-...';
--   Expected: 45000.0000


-- ------------------------------------------------------------------------------
-- TRANSACTION 5: Partial Rollback with SAVEPOINT / ROLLBACK TO SAVEPOINT
-- Business Scenario: Chidi (a0000002) sends $50.00 to Amina (a0000001). Within
-- the same transaction the application tentatively posts a $10.00 promotional
-- cashback from Treasury (a0000008) to Chidi, then its eligibility check fails.
-- ROLLBACK TO SAVEPOINT undoes only the cashback journal (including the balance
-- changes made by trg_ledger_apply_balance and its queued deferred-constraint
-- checks); the main transfer is kept and COMMITs.
-- ------------------------------------------------------------------------------

BEGIN;

-- Step 5.1: Main transfer (kept)
--   DEBIT  Chidi  $50.00  (balance_after =  8550.00 - 50.00 =  8500.00)
--   CREDIT Amina  $50.00  (balance_after = 14198.50 + 50.00 = 14248.50)
INSERT INTO journal_entries (
    journal_id, entry_reference, narrative, event_type, posting_date, created_at
) VALUES (
    '50000005-0000-4000-8000-000000000005',
    'REF-P3-P2P-20261101-005',
    'P3 P2P Transfer Chidi -> Amina ($50.00)',
    'P2P_TRANSFER',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);
INSERT INTO ledger_entries (
    ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after, created_at
) VALUES
('60000051-0000-4000-8000-000000000051', '50000005-0000-4000-8000-000000000005', 'a0000002-0000-4000-8000-000000000002', 'DEBIT',  50.0000,  8500.0000, CURRENT_TIMESTAMP),
('60000052-0000-4000-8000-000000000052', '50000005-0000-4000-8000-000000000005', 'a0000001-0000-4000-8000-000000000001', 'CREDIT', 50.0000, 14248.5000, CURRENT_TIMESTAMP);

SAVEPOINT before_cashback;

-- Step 5.2: Tentative cashback (to be undone)
INSERT INTO journal_entries (
    journal_id, entry_reference, narrative, event_type, posting_date, created_at
) VALUES (
    '50000006-0000-4000-8000-000000000006',
    'REF-P3-CASHBACK-20261101-006',
    'P3 promotional cashback Treasury -> Chidi ($10.00)',
    'P2P_TRANSFER',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);
INSERT INTO ledger_entries (
    ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after, created_at
) VALUES
('60000061-0000-4000-8000-000000000061', '50000006-0000-4000-8000-000000000006', 'a0000008-0000-4000-8000-000000000008', 'DEBIT',  10.0000, 18444.0500, CURRENT_TIMESTAMP),
('60000062-0000-4000-8000-000000000062', '50000006-0000-4000-8000-000000000006', 'a0000002-0000-4000-8000-000000000002', 'CREDIT', 10.0000,  8510.0000, CURRENT_TIMESTAMP);

-- Step 5.3: Eligibility check fails -> undo only the cashback
ROLLBACK TO SAVEPOINT before_cashback;

COMMIT;

-- Verification queries (run after COMMIT):
-- SELECT journal_id FROM journal_entries WHERE journal_id IN
--   ('50000005-0000-4000-8000-000000000005', '50000006-0000-4000-8000-000000000006');
--   Expected: only 50000005-... (cashback journal discarded)
-- SELECT account_id, current_balance FROM accounts
--   WHERE account_id IN ('a0000001-...', 'a0000002-...', 'a0000008-...');
--   Expected: Amina 14248.5000, Chidi 8500.0000, Treasury 18454.0500 (unchanged)
