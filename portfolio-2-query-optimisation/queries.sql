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
WHERE t.initiated_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
GROUP BY t.channel, t.currency_code
HAVING COUNT(*) > 0
ORDER BY failure_rate_pct DESC;
