"""
MIT 8103 Advanced Database Systems - Portfolio 2
ApexBank Digital PostgreSQL Query Optimisation Benchmark

This runner builds a dedicated PostgreSQL benchmark database from the
Portfolio 1 DDL and seed, generates a deterministic high-volume dataset,
captures PostgreSQL execution plans, measures latency, and writes evidence
files for the portfolio.
"""

import hashlib
import os
import random
import statistics
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

BASE_DIR = Path(__file__).resolve().parent
P1_DIR = BASE_DIR.parent / "portfolio-1-database-design"
DDL_FILE = P1_DIR / "ddl_schema.sql"
SEED_FILE = P1_DIR / "seed_data.sql"

DEFAULT_DSN = "postgresql://apexbank:apexbank_dev@localhost:5432/apexbank_benchmark"
BENCHMARK_DSN = os.getenv("BENCHMARK_DATABASE_URL", DEFAULT_DSN)
BENCHMARK_DB = conninfo_to_dict(BENCHMARK_DSN).get("dbname", "apexbank_benchmark")
MAINTENANCE_DSN = make_conninfo(**{**conninfo_to_dict(BENCHMARK_DSN), "dbname": "postgres"})

TARGET_CUSTOMERS = 100
TARGET_ACCOUNTS = 100
TARGET_TRANSACTIONS = 50_000
SOURCE_ACCOUNT_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "apexbank-bench-account-9")
DATASET_START = datetime(2026, 1, 1, tzinfo=timezone.utc)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AML_QUERY = """
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
"""

CUSTOMER_360_QUERY = """
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
"""

MERCHANT_SETTLEMENT_QUERY = """
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
"""

CHANNEL_ANOMALY_QUERY = """
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
"""

BENCHMARK_QUERY_1 = """
SELECT transaction_id, amount, status, initiated_at
FROM transactions
WHERE status = 'SETTLED'
  AND initiated_at BETWEEN '2026-03-01' AND '2026-06-30';
"""

BENCHMARK_QUERY_2 = f"""
SELECT transaction_id, amount, currency_code, initiated_at
FROM transactions
WHERE source_account_id = '{SOURCE_ACCOUNT_ID}'
ORDER BY initiated_at DESC;
"""

BENCHMARK_QUERY_3 = CUSTOMER_360_QUERY

PRODUCTION_QUERIES = [
    ("AML 24-hour USD velocity and structuring detection", AML_QUERY),
    ("360-degree customer financial position", CUSTOMER_360_QUERY),
    ("Merchant daily settlement reconciliation", MERCHANT_SETTLEMENT_QUERY),
    ("30-day channel anomaly diagnostics", CHANNEL_ANOMALY_QUERY),
]


def execute_script(conn, path):
    text = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(text)


def ensure_benchmark_database():
    with psycopg.connect(MAINTENANCE_DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (BENCHMARK_DB,))
            if cur.fetchone() is None:
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(BENCHMARK_DB))
                )
                print(f"[OK] Created PostgreSQL benchmark database: {BENCHMARK_DB}")
            else:
                print(f"[OK] Reusing PostgreSQL benchmark database: {BENCHMARK_DB}")


def load_p1_schema_and_seed(conn):
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    execute_script(conn, DDL_FILE)
    execute_script(conn, SEED_FILE)
    print("[OK] Loaded Portfolio 1 DDL and seed into benchmark database")


def generate_dataset(conn):
    random.seed(42)

    first_names = ["Amina", "Chidi", "Folake", "David", "Zainab", "Kolawole", "Ngozi", "Emeka", "Fatima", "Tunde"]
    last_names = ["Bello", "Okonkwo", "Adeyemi", "Kalu", "Mohammed", "Balogun", "Eze", "Nwosu", "Aliyu", "Suleiman"]
    account_currencies = ["USD", "NGN", "EUR", "GBP"]

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM customers;")
            existing_customers = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM accounts;")
            existing_accounts = cur.fetchone()[0]

            customer_rows = []
            account_rows = []

            for i in range(existing_customers + 1, TARGET_CUSTOMERS + 1):
                customer_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-customer-{i}")
                customer_rows.append((
                    customer_id,
                    random.choice(first_names),
                    random.choice(last_names),
                    f"bench.user{i:03d}@apexbank.test",
                    f"+2349{i:09d}",
                    f"benchmark_hash_{i:03d}",
                    random.choice(["TIER_1", "TIER_2", "TIER_3"]),
                    "ACTIVE",
                ))

            cur.executemany(
                """
                INSERT INTO customers
                    (customer_id, first_name, last_name, email, phone_number,
                     password_hash, tier_level, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                customer_rows,
            )

            for i in range(existing_accounts + 1, TARGET_ACCOUNTS + 1):
                account_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-account-{i}")
                customer_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-customer-{i}")
                currency = account_currencies[(i - existing_accounts - 1) % len(account_currencies)]
                account_rows.append((
                    account_id,
                    customer_id,
                    random.choice([1, 2, 3]),
                    currency,
                    f"9000{i:06d}",
                    Decimal(str(round(random.uniform(500, 150000), 4))),
                    Decimal("0.0000"),
                    Decimal("1000.0000"),
                    "ACTIVE",
                ))

            cur.executemany(
                """
                INSERT INTO accounts
                    (account_id, customer_id, account_type_id, currency_code,
                     account_number, current_balance, hold_balance, overdraft_limit,
                     account_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                account_rows,
            )

            cur.execute("SELECT account_id, currency_code FROM accounts;")
            all_accounts = cur.fetchall()
            accounts_by_currency = {}
            for account_id, currency in all_accounts:
                accounts_by_currency.setdefault(currency, []).append(account_id)

            cur.execute("SELECT account_id FROM cards;")
            carded_accounts = {row[0] for row in cur.fetchall()}
            card_rows = []
            for account_id, currency in all_accounts:
                if account_id in carded_accounts:
                    continue
                card_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-card-{account_id}")
                token = f"tok_bench_{account_id}"
                hmac_hex = hashlib.sha256(token.encode("utf-8")).hexdigest()
                card_rows.append((
                    card_id,
                    account_id,
                    f"411111XXXXXX{str(account_id.int)[-4:]}",
                    token,
                    hmac_hex,
                    date(2028, 12, 31),
                    "DEBIT",
                    Decimal("5000.0000"),
                    "ACTIVE",
                ))

            if len(card_rows) > TARGET_ACCOUNTS:
                card_rows = card_rows[:TARGET_ACCOUNTS - len(carded_accounts)]

            cur.executemany(
                """
                INSERT INTO cards
                    (card_id, account_id, masked_pan, card_token, pan_hmac,
                     expiry_date, card_type, daily_spend_limit, card_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                card_rows,
            )

            merchant_rows = []
            for currency, name, code, commission in [
                ("NGN", "Lagos Retail Network", "5411", Decimal("0.0150")),
                ("EUR", "EuroPay Clearing", "7372", Decimal("0.0200")),
            ]:
                settlement_account = accounts_by_currency[currency][0]
                merchant_rows.append((
                    uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-merchant-{currency}"),
                    settlement_account,
                    name,
                    f"RC-BENCH-{currency}",
                    code,
                    commission,
                    "ACTIVE",
                ))
            cur.executemany(
                """
                INSERT INTO merchants
                    (merchant_id, settlement_account_id, business_name,
                     registration_number, merchant_category_code, commission_rate, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                merchant_rows,
            )

            cur.execute("SELECT merchant_id, m.settlement_account_id, a.currency_code "
                        "FROM merchants m JOIN accounts a ON a.account_id = m.settlement_account_id;")
            merchants_by_currency = {}
            for merchant_id, settlement_account_id, currency in cur.fetchall():
                merchants_by_currency.setdefault(currency, []).append(merchant_id)

            cur.execute("SELECT COUNT(*) FROM transactions;")
            existing_transactions = cur.fetchone()[0]
            cur.execute("SELECT account_id, current_balance, overdraft_limit, hold_balance FROM accounts;")
            balances = {}
            overdraft_limits = {}
            hold_balances = {}
            for row in cur.fetchall():
                balances[row[0]] = row[1]
                overdraft_limits[row[0]] = row[2]
                hold_balances[row[0]] = row[3]
            statuses = ["SETTLED"] * 70 + ["PENDING"] * 10 + ["FAILED"] * 10 + ["REVERSED"] * 10
            channels = ["MOBILE_APP", "POS_TERMINAL", "WEB_PORTAL", "API_INTEGRATION"]
            transaction_rows = []
            journal_rows = []
            ledger_rows = []

            i = 1
            max_attempts = (TARGET_TRANSACTIONS - existing_transactions) * 10
            attempts = 0
            while i <= TARGET_TRANSACTIONS - existing_transactions and attempts < max_attempts:
                attempts += 1
                currency = random.choice(["USD", "USD", "USD", "NGN", "NGN", "EUR", "GBP"])
                available_accounts = accounts_by_currency[currency]
                source = random.choice(available_accounts)
                destination_candidates = [a for a in available_accounts if a != source]
                if not destination_candidates:
                    continue
                destination = random.choice(destination_candidates)
                merchant = None
                settlement_account = None
                if i % 4 == 0 and currency in merchants_by_currency:
                    merchant = random.choice(merchants_by_currency[currency])
                    cur.execute("SELECT settlement_account_id FROM merchants WHERE merchant_id = %s;", (merchant,))
                    settlement_account = cur.fetchone()[0]

                amount = Decimal(str(round(random.uniform(10.0, 12500.0), 4)))
                if settlement_account is not None:
                    fee = (amount * Decimal("0.0050")).quantize(Decimal("0.0001"))
                else:
                    fee = Decimal("0.0000")

                # Enforce solvency: after debit, current_balance + overdraft_limit
                # must still cover hold_balance (chk_account_holds).
                max_debit = balances[source] + overdraft_limits[source] - hold_balances[source]
                if amount + fee > max_debit:
                    amount = max_debit - fee
                    if amount <= Decimal("0.0000"):
                        continue

                status = random.choice(statuses)
                initiated_at = DATASET_START + timedelta(seconds=i * 500)
                completed_at = None if status == "PENDING" else initiated_at + timedelta(seconds=random.randint(1, 120))

                journal_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-journal-{i}")
                entry_reference = f"JRN-BNCH-{i:08d}"
                narrative = f"Benchmark transaction BNCH-{i:08d}"
                event_type = "MERCHANT_SETTLEMENT" if merchant is not None else "P2P_TRANSFER"

                # Compute running balances sequentially so that overlapping
                # accounts (e.g. destination == settlement_account) are handled
                # correctly: each ledger line sees the balance produced by the
                # previous line for the same account.
                src_bal = balances[source]
                dst_bal = balances[destination]
                stl_bal = balances[settlement_account] if settlement_account is not None else None

                # DEBIT source: amount + fee
                src_bal_after = src_bal - amount - fee

                # CREDIT destination: amount
                dst_bal_after = dst_bal + amount

                # CREDIT settlement: fee (use updated balance if account overlaps)
                if settlement_account is not None:
                    if settlement_account == destination:
                        stl_bal_after = dst_bal_after + fee
                    elif settlement_account == source:
                        stl_bal_after = src_bal_after + fee
                    else:
                        stl_bal_after = stl_bal + fee
                else:
                    stl_bal_after = None

                journal_rows.append((
                    journal_id,
                    entry_reference,
                    narrative,
                    event_type,
                    initiated_at,
                    initiated_at,
                ))

                ledger_rows.append((
                    uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-ledger-{i}-src"),
                    journal_id,
                    source,
                    "DEBIT",
                    amount + fee,
                    src_bal_after,
                    initiated_at,
                ))
                ledger_rows.append((
                    uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-ledger-{i}-dst"),
                    journal_id,
                    destination,
                    "CREDIT",
                    amount,
                    dst_bal_after,
                    initiated_at,
                ))
                if settlement_account is not None:
                    ledger_rows.append((
                        uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-ledger-{i}-fee"),
                        journal_id,
                        settlement_account,
                        "CREDIT",
                        fee,
                        stl_bal_after,
                        initiated_at,
                    ))

                balances[source] = src_bal_after
                balances[destination] = dst_bal_after
                if settlement_account is not None:
                    balances[settlement_account] = stl_bal_after

                transaction_rows.append((
                    uuid.uuid5(uuid.NAMESPACE_DNS, f"apexbank-bench-txn-{i}"),
                    f"BNCH-{i:08d}",
                    f"bnch-idem-{i:08d}",
                    source,
                    destination,
                    merchant,
                    journal_id,
                    currency,
                    amount,
                    fee,
                    random.choice(channels),
                    status,
                    initiated_at,
                    completed_at,
                ))
                i += 1

            for row in journal_rows:
                cur.execute(
                    """
                    INSERT INTO journal_entries
                        (journal_id, entry_reference, narrative, event_type, posting_date, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s);
                    """,
                    row,
                )
            for row in ledger_rows:
                cur.execute(
                    """
                    INSERT INTO ledger_entries
                        (ledger_entry_id, journal_id, account_id, entry_type, amount, balance_after, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    row,
                )
            for row in transaction_rows:
                cur.execute(
                    """
                    INSERT INTO transactions
                        (transaction_id, transaction_reference, idempotency_key,
                         source_account_id, destination_account_id, merchant_id,
                         journal_id, currency_code, amount, fee_amount, channel,
                         status, initiated_at, completed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    row,
                )

    print(f"[OK] Dataset generated: {TARGET_CUSTOMERS} customers, "
          f"{TARGET_ACCOUNTS} accounts, {TARGET_TRANSACTIONS} transactions")


def table_counts(conn):
    tables = [
        "customers", "accounts", "merchants", "cards", "transactions",
        "journal_entries", "ledger_entries", "audit_logs",
    ]
    counts = {}
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            counts[table] = cur.fetchone()[0]
    return counts


def drop_transaction_indexes(cur):
    for name in [
        "idx_txn_status_date",
        "idx_txn_status_date_cover",
        "idx_txn_source",
        "idx_txn_source_date_cover",
        "idx_transactions_source",
        "idx_transactions_status_date",
        "idx_transactions_initiated_at",
    ]:
        cur.execute(sql.SQL("DROP INDEX IF EXISTS {};").format(sql.Identifier(name)))


def capture_plan(cur, query):
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + query)
    return "\n".join(row[0] for row in cur.fetchall())


def time_query(cur, query, iterations=5):
    cur.execute(query)
    cur.fetchall()
    times = []
    for _ in range(iterations):
        started = time.perf_counter()
        cur.execute(query)
        cur.fetchall()
        times.append((time.perf_counter() - started) * 1000.0)
    return statistics.mean(times), min(times)


def benchmark(cur, name, query):
    plan = capture_plan(cur, query)
    average_ms, minimum_ms = time_query(cur, query)
    return {
        "name": name,
        "query": query.strip(),
        "plan": plan,
        "average_ms": average_ms,
        "minimum_ms": minimum_ms,
    }


def run_benchmarks(conn):
    results = []
    with conn.cursor() as cur:
        drop_transaction_indexes(cur)
        cur.execute("VACUUM (ANALYZE) transactions;")
        results.append(benchmark(cur, "1A: Unindexed status/date scan", BENCHMARK_QUERY_1))

        cur.execute("CREATE INDEX idx_txn_status_date ON transactions (status, initiated_at);")
        cur.execute("VACUUM (ANALYZE) transactions;")
        results.append(benchmark(cur, "1B: Composite B-tree (status, initiated_at)", BENCHMARK_QUERY_1))

        cur.execute("DROP INDEX IF EXISTS idx_txn_status_date;")
        cur.execute(
            "CREATE INDEX idx_txn_status_date_cover "
            "ON transactions (status, initiated_at) INCLUDE (transaction_id, amount);"
        )
        cur.execute("VACUUM (ANALYZE) transactions;")
        results.append(benchmark(cur, "1C: Covering index with INCLUDE", BENCHMARK_QUERY_1))

        drop_transaction_indexes(cur)
        cur.execute("VACUUM (ANALYZE) transactions;")
        results.append(benchmark(cur, "2A: Unindexed account statement scan", BENCHMARK_QUERY_2))

        cur.execute("CREATE INDEX idx_txn_source ON transactions (source_account_id);")
        cur.execute("VACUUM (ANALYZE) transactions;")
        results.append(benchmark(cur, "2B: Single-column source account index", BENCHMARK_QUERY_2))

        cur.execute("DROP INDEX IF EXISTS idx_txn_source;")
        cur.execute(
            "CREATE INDEX idx_txn_source_date_cover "
            "ON transactions (source_account_id, initiated_at DESC) "
            "INCLUDE (transaction_id, amount, currency_code);"
        )
        cur.execute("VACUUM (ANALYZE) transactions;")
        results.append(benchmark(cur, "2C: Ordered covering index", BENCHMARK_QUERY_2))

        drop_transaction_indexes(cur)
        cur.execute(
            "CREATE INDEX idx_txn_status_date_cover "
            "ON transactions (status, initiated_at) INCLUDE (transaction_id, amount);"
        )
        cur.execute(
            "CREATE INDEX idx_txn_source_date_cover "
            "ON transactions (source_account_id, initiated_at DESC) "
            "INCLUDE (transaction_id, amount, currency_code);"
        )
        cur.execute("VACUUM (ANALYZE) transactions;")
        results.append(benchmark(cur, "3: 360-degree analytical rollup", BENCHMARK_QUERY_3))
    return results


def format_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)


def write_query_results(conn):
    lines = []
    lines.append("=" * 80)
    lines.append("PORTFOLIO 2: PRODUCTION QUERY RESULTS (first 20 rows per query)")
    lines.append("=" * 80)
    lines.append("")
    with conn.cursor() as cur:
        for name, query in PRODUCTION_QUERIES:
            cur.execute(query)
            headers = [description.name for description in cur.description]
            rows = cur.fetchmany(20)
            lines.append("-" * 80)
            lines.append(name)
            lines.append("-" * 80)
            lines.append(" | ".join(headers))
            for row in rows:
                lines.append(" | ".join(format_value(value) for value in row))
            lines.append(f"({len(rows)} rows shown; full result available by running queries.sql)")
            lines.append("")
    (BASE_DIR / "query_results.txt").write_text("\n".join(lines), encoding="utf-8")


def build_report(conn, results, counts):
    with conn.cursor() as cur:
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]

    lines = []
    lines.append("=" * 80)
    lines.append("PORTFOLIO 2: POSTGRESQL QUERY PROCESSING AND OPTIMISATION REPORT")
    lines.append("=" * 80)
    lines.append(f"Database Engine: {version}")
    lines.append(f"Benchmark Database: {BENCHMARK_DB}")
    lines.append(f"Dataset: {counts['customers']} customers, {counts['accounts']} accounts, "
                 f"{counts['cards']} cards, {counts['merchants']} merchants, "
                 f"{counts['transactions']} transactions")
    lines.append("Portfolio 1 schema: portfolio-1-database-design/ddl_schema.sql")
    lines.append("Portfolio 1 seed: portfolio-1-database-design/seed_data.sql")
    lines.append("Iterations: 5 timed runs after one warm-up run")
    lines.append("Plans: EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)")
    lines.append("")

    baseline_1 = results[0]["average_ms"]
    baseline_2 = results[3]["average_ms"]
    for result in results:
        lines.append("-" * 80)
        lines.append(result["name"])
        lines.append("-" * 80)
        lines.append(f"Average latency: {result['average_ms']:.3f} ms")
        lines.append(f"Minimum latency: {result['minimum_ms']:.3f} ms")
        if result["name"].startswith("1"):
            lines.append(f"Speedup vs 1A: {baseline_1 / result['average_ms']:.2f}x")
        elif result["name"].startswith("2"):
            lines.append(f"Speedup vs 2A: {baseline_2 / result['average_ms']:.2f}x")
        lines.append("Execution plan:")
        lines.append(result["plan"])
        lines.append("")

    return "\n".join(lines)


def main():
    ensure_benchmark_database()
    with psycopg.connect(BENCHMARK_DSN) as conn:
        conn.autocommit = True
        load_p1_schema_and_seed(conn)
        generate_dataset(conn)
        cur = conn.cursor()
        cur.execute("VACUUM (ANALYZE);")
        counts = table_counts(conn)

        results = run_benchmarks(conn)
        write_query_results(conn)
        report = build_report(conn, results, counts)
        (BASE_DIR / "benchmark_results.txt").write_text(report, encoding="utf-8")
        print(report)
        print(f"[OK] Wrote {BASE_DIR / 'benchmark_results.txt'}")
        print(f"[OK] Wrote {BASE_DIR / 'query_results.txt'}")


if __name__ == "__main__":
    main()
