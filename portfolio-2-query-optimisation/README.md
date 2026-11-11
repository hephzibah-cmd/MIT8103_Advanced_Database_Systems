# Portfolio 2: Query Processing and Optimisation

ApexBank Digital benchmark built on Portfolio 1 schema and seed data.
Uses a separate PostgreSQL benchmark database so Portfolio 1 remains unchanged.

## Relationship to Portfolio 1
- Schema source: `../portfolio-1-database-design/ddl_schema.sql`
- Seed source: `../portfolio-1-database-design/seed_data.sql`
- Benchmark database: `apexbank_benchmark` on PostgreSQL 16 via Docker Compose.
- Portfolio 1 database `apexbank` is not modified.

## Prerequisites
- PostgreSQL 16 container `mit8103-postgres` running on `localhost:5432`.
- Python dependencies: `psycopg[binary]>=3.2` from `../requirements.txt`.
- Default DSN: `postgresql://apexbank:apexbank_dev@localhost:5432/apexbank_benchmark`
- Override with `BENCHMARK_DATABASE_URL` if needed.

## Run benchmark
From repository root:

```powershell
python portfolio-2-query-optimisation\benchmark_runner.py
```

A full run takes several minutes, because rows are inserted one at a time so that the Portfolio 1 ledger triggers fire for every posting.

The runner:
1. Creates/reuses `apexbank_benchmark`.
2. Loads Portfolio 1 DDL and seed.
3. Generates deterministic benchmark data: 100 customers, 100 accounts, 100 cards, 3 merchants, 50,000 transactions (1,175 heap pages, about 9.4 MB), then runs `VACUUM (ANALYZE)`.
4. For each index scenario: one warm-up run, then `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)`, the median of 5 server-side `EXPLAIN (ANALYZE, TIMING OFF)` executor times, and 5 timed client round-trips. Index sizes are recorded with `pg_relation_size`.
5. Captures plans for all four production queries under the final index set.
6. Writes evidence files.

## Evidence files
- `queries.sql`: PostgreSQL production queries, currency-safe.
- `indexing_experiments.sql`: index baseline, composite, covering, and ordered covering experiments (run only on `apexbank_benchmark`).
- `benchmark_results.txt`: measured plans, server execution times, round-trip latencies, index sizes, and speedups.
- `query_results.txt`: first 20 rows for each production query.
- `execution_plans_and_results.md`: summarised execution plans and plan interpretation.
- `performance_analysis.md`: methodology, findings, trade-offs, and limitations.

## Measured results summary
Dataset: 100 customers, 100 accounts, 100 cards, 3 merchants, 50,000 transactions. Figures below are from the run recorded in `benchmark_results.txt`; timings vary between runs, so treat `benchmark_results.txt` as authoritative after re-running.

| Scenario | Index | Plan | Server execution (median) | Server speedup | Index size |
|---|---|---|---:|---:|---:|
| 1A | None (status/date scan) | Seq Scan | 4.367 ms | 1.00x | - |
| 1B | Composite `(status, initiated_at)` | Bitmap Heap Scan | 2.162 ms | 2.02x | 1592 kB |
| 1C | Covering `(status, initiated_at) INCLUDE (transaction_id, amount)` | Index Only Scan | 1.148 ms | 3.80x | 3008 kB |
| 2A | None (account statement) | Seq Scan + Sort | 2.146 ms | 1.00x | - |
| 2B | Single-column `source_account_id` | Bitmap Heap Scan + Sort | 0.334 ms | 6.43x | 376 kB |
| 2C | Ordered covering `(source_account_id, initiated_at DESC) INCLUDE (...)` | Index Only Scan, no Sort | 0.055 ms | 39.02x | 3784 kB |
| 3 | 360-degree rollup (master tables only) | HashAggregate over Nested Loop | 1.033 ms | N/A | - |

Client round-trip latencies (Python `execute()` + `fetchall()`) are also in `benchmark_results.txt`. They are dominated by transferring and decoding rows (about 14,700 rows for Scenario 1), so they understate the index effect and are noisier than server time.

## Currency safety
- No FX table exists in Portfolio 1, so cross-currency sums are avoided.
- AML velocity query is USD-only with a 24-hour `RANGE` window.
- Customer 360 query reports per-currency balances separately.
- Merchant settlement query joins transactions only to the settlement account's currency.
- The 30-day channel query is anchored to `MAX(initiated_at)`, so results are reproducible on the fixed dataset. Production would use `CURRENT_TIMESTAMP`.
- The customer 360 query pre-aggregates cards per account, so an account with several cards is not double-counted in balance sums.
- Generated data respects P1 constraints: `PENDING` transactions have `completed_at IS NULL`; terminal statuses have `completed_at` set; transaction currency matches linked accounts.

## File links
Use relative links only:
- `queries.sql`
- `indexing_experiments.sql`
- `benchmark_results.txt`
- `query_results.txt`
- `execution_plans_and_results.md`
- `performance_analysis.md`
- `../portfolio-1-database-design/ddl_schema.sql`
- `../portfolio-1-database-design/seed_data.sql`
