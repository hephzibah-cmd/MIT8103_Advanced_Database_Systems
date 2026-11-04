DROP INDEX IF EXISTS idx_transactions_source;
DROP INDEX IF EXISTS idx_transactions_status_date;
DROP INDEX IF EXISTS idx_transactions_initiated_at;
DROP INDEX IF EXISTS idx_txn_status_date;
DROP INDEX IF EXISTS idx_txn_status_date_cover;
DROP INDEX IF EXISTS idx_txn_source;
DROP INDEX IF EXISTS idx_txn_source_date_cover;

VACUUM (ANALYZE) transactions;

EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT transaction_id, amount, status, initiated_at
FROM transactions
WHERE status = 'SETTLED'
  AND initiated_at BETWEEN '2026-03-01' AND '2026-06-30';

CREATE INDEX idx_txn_status_date ON transactions (status, initiated_at);
VACUUM (ANALYZE) transactions;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT transaction_id, amount, status, initiated_at
FROM transactions
WHERE status = 'SETTLED'
  AND initiated_at BETWEEN '2026-03-01' AND '2026-06-30';

DROP INDEX IF EXISTS idx_txn_status_date;

CREATE INDEX idx_txn_status_date_cover
ON transactions (status, initiated_at) INCLUDE (transaction_id, amount);
VACUUM (ANALYZE) transactions;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT transaction_id, amount, status, initiated_at
FROM transactions
WHERE status = 'SETTLED'
  AND initiated_at BETWEEN '2026-03-01' AND '2026-06-30';

DROP INDEX IF EXISTS idx_txn_status_date_cover;
DROP INDEX IF EXISTS idx_txn_status_date;

VACUUM (ANALYZE) transactions;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT transaction_id, amount, currency_code, initiated_at
FROM transactions
WHERE source_account_id = 'fa91764d-3385-5037-bf44-84d8aba4d499'
ORDER BY initiated_at DESC;

CREATE INDEX idx_txn_source ON transactions (source_account_id);
VACUUM (ANALYZE) transactions;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT transaction_id, amount, currency_code, initiated_at
FROM transactions
WHERE source_account_id = 'fa91764d-3385-5037-bf44-84d8aba4d499'
ORDER BY initiated_at DESC;

DROP INDEX IF EXISTS idx_txn_source;

CREATE INDEX idx_txn_source_date_cover
ON transactions (source_account_id, initiated_at DESC)
INCLUDE (transaction_id, amount, currency_code);
VACUUM (ANALYZE) transactions;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT transaction_id, amount, currency_code, initiated_at
FROM transactions
WHERE source_account_id = 'fa91764d-3385-5037-bf44-84d8aba4d499'
ORDER BY initiated_at DESC;

DROP INDEX IF EXISTS idx_txn_source_date_cover;
DROP INDEX IF EXISTS idx_txn_source;

CREATE INDEX idx_txn_status_date_cover
ON transactions (status, initiated_at) INCLUDE (transaction_id, amount);
CREATE INDEX idx_txn_source_date_cover
ON transactions (source_account_id, initiated_at DESC)
INCLUDE (transaction_id, amount, currency_code);
VACUUM (ANALYZE) transactions;
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT
    c.customer_id,
    c.first_name || ' ' || c.last_name AS customer_name,
    c.email,
    c.tier_level,
    c.status AS customer_status,
    COUNT(DISTINCT a.account_id) AS total_active_accounts,
    COUNT(DISTINCT cd.card_id) AS total_linked_cards,
    COALESCE(SUM(a.current_balance) FILTER (WHERE a.currency_code = 'USD'), 0.0000) AS total_usd_balance,
    COALESCE(SUM(a.current_balance) FILTER (WHERE a.currency_code = 'NGN'), 0.0000) AS total_ngn_balance,
    COALESCE(SUM(a.current_balance) FILTER (WHERE a.currency_code = 'EUR'), 0.0000) AS total_eur_balance,
    COALESCE(SUM(a.current_balance) FILTER (WHERE a.currency_code = 'GBP'), 0.0000) AS total_gbp_balance,
    COALESCE(SUM(a.overdraft_limit) FILTER (WHERE a.currency_code = 'USD'), 0.0000) AS total_usd_overdraft_facility,
    COALESCE(SUM(a.hold_balance), 0.0000) AS total_hold_balance_nominal,
    CASE
        WHEN COALESCE(SUM(a.current_balance) FILTER (WHERE a.currency_code = 'USD'), 0) > 20000 THEN 'TIER_1_HIGH_USD_LIQUIDITY'
        WHEN COALESCE(SUM(a.current_balance) FILTER (WHERE a.currency_code = 'USD'), 0) BETWEEN 5000 AND 20000 THEN 'TIER_2_MASS_AFFLUENT'
        ELSE 'TIER_3_RETAIL_CORE'
    END AS usd_liquidity_segment
FROM customers c
LEFT JOIN accounts a
    ON a.customer_id = c.customer_id
   AND a.account_status = 'ACTIVE'
LEFT JOIN cards cd
    ON cd.account_id = a.account_id
   AND cd.card_status = 'ACTIVE'
GROUP BY c.customer_id, c.first_name, c.last_name, c.email, c.tier_level, c.status
ORDER BY total_usd_balance DESC;
