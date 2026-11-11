-- Portfolio 2 production queries (ApexBank Digital, PostgreSQL 16).
-- Run against apexbank_benchmark after benchmark_runner.py has loaded data.

-- Q1. AML 24-hour USD velocity and structuring detection.
--     Rolling 24-hour RANGE window per source account; USD only (no FX table).
WITH usd_stream AS (
    SELECT
        t.transaction_id,
        t.transaction_reference,
        t.source_account_id,
        c.customer_id,
        c.first_name || ' ' || c.last_name AS customer_name,
        c.tier_level,
        t.currency_code,
        t.amount,
        t.initiated_at
    FROM transactions t
    INNER JOIN accounts a ON a.account_id = t.source_account_id
    INNER JOIN customers c ON c.customer_id = a.customer_id
    WHERE t.currency_code = 'USD'
      AND t.status IN ('SETTLED', 'PENDING')
),
rolling AS (
    SELECT
        *,
        SUM(amount) OVER (
            PARTITION BY source_account_id
            ORDER BY initiated_at
            RANGE BETWEEN INTERVAL '24 hours' PRECEDING AND CURRENT ROW
        ) AS rolling_24h_amount
    FROM usd_stream
)
SELECT
    transaction_reference,
    customer_name,
    tier_level,
    amount,
    currency_code,
    rolling_24h_amount,
    initiated_at,
    CASE
        WHEN rolling_24h_amount >= 10000.00 THEN 'HIGH_RISK_AML_ALERT'
        WHEN amount >= 5000.00 THEN 'MODERATE_SURVEILLANCE'
        ELSE 'STANDARD_COMPLIANT'
    END AS compliance_risk_flag
FROM rolling
WHERE rolling_24h_amount >= 5000.00 OR amount >= 5000.00
ORDER BY initiated_at DESC;

-- Q2. 360-degree customer financial position (per-currency balances).
SELECT
    c.customer_id,
    c.first_name || ' ' || c.last_name AS customer_name,
    c.email,
    c.tier_level,
    c.status AS customer_status,
    COUNT(a.account_id) AS total_active_accounts,
    COALESCE(SUM(cd.active_cards), 0) AS total_linked_cards,
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
LEFT JOIN (
    -- Pre-aggregate cards per account so an account with several cards
    -- is not repeated in the join and its balance is not double-counted.
    SELECT account_id, COUNT(*) AS active_cards
    FROM cards
    WHERE card_status = 'ACTIVE'
    GROUP BY account_id
) cd ON cd.account_id = a.account_id
GROUP BY c.customer_id, c.first_name, c.last_name, c.email, c.tier_level, c.status
ORDER BY total_usd_balance DESC;

-- Q3. Merchant settlement reconciliation (all periods), in the settlement
--     account's currency.
SELECT
    m.merchant_id,
    m.business_name,
    m.merchant_category_code,
    m.commission_rate * 100.0 AS commission_rate_pct,
    t.currency_code,
    COUNT(t.transaction_id) AS total_transactions_processed,
    COALESCE(SUM(CASE WHEN t.status = 'SETTLED' THEN 1 ELSE 0 END), 0) AS successful_transactions,
    COALESCE(SUM(CASE WHEN t.status = 'FAILED' THEN 1 ELSE 0 END), 0) AS failed_transactions,
    COALESCE(ROUND(SUM(CASE WHEN t.status = 'SETTLED' THEN t.amount ELSE 0 END), 2), 0) AS gross_processing_volume,
    COALESCE(ROUND(SUM(CASE WHEN t.status = 'SETTLED' THEN t.fee_amount ELSE 0 END), 2), 0) AS total_platform_fees,
    COALESCE(ROUND(SUM(CASE WHEN t.status = 'SETTLED' THEN (t.amount - t.fee_amount) ELSE 0 END), 2), 0) AS net_merchant_payable
FROM merchants m
INNER JOIN accounts a ON a.account_id = m.settlement_account_id
LEFT JOIN transactions t
    ON t.merchant_id = m.merchant_id
   AND t.currency_code = a.currency_code
GROUP BY m.merchant_id, m.business_name, m.merchant_category_code, m.commission_rate, t.currency_code
ORDER BY gross_processing_volume DESC;

-- Q4. 30-day channel failure-rate diagnostics.
SELECT
    t.channel,
    t.currency_code,
    COUNT(*) AS total_attempts,
    COUNT(*) FILTER (WHERE t.status = 'SETTLED') AS settled_count,
    COUNT(*) FILTER (WHERE t.status = 'FAILED') AS failed_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE t.status = 'FAILED') / COUNT(*), 2) AS failure_rate_pct,
    ROUND(AVG(t.amount), 2) AS average_ticket_size,
    ROUND(MAX(t.amount), 2) AS peak_ticket_size
FROM transactions t
-- Anchored to the latest transaction rather than CURRENT_TIMESTAMP so the
-- result is reproducible on the fixed benchmark dataset. In production use
-- CURRENT_TIMESTAMP - INTERVAL '30 days'.
WHERE t.initiated_at >= (SELECT MAX(initiated_at) FROM transactions) - INTERVAL '30 days'
GROUP BY t.channel, t.currency_code
HAVING COUNT(*) > 0
ORDER BY failure_rate_pct DESC;
