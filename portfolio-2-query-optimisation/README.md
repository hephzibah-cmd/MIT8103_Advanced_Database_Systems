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

The runner:
1. Creates/reuses `apexbank_benchmark`.
2. Loads Portfolio 1 DDL and seed.
3. Generates deterministic benchmark data: 100 customers, 100 accounts, 100 cards, 3 merchants, 50,000 transactions.
4. Captures `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)` plans.
5. Measures latency over 5 timed runs after one warm-up run.
6. Writes evidence files.

## Evidence files
- `queries.sql`: PostgreSQL production queries, currency-safe.
- `indexing_experiments.sql`: index baseline, composite, covering, and ordered covering experiments.
- `benchmark_results.txt`: measured plans, latencies, and speedups.
- `query_results.txt`: first 20 rows for each production query.
- `execution_plans_and_results.md`: summarised execution plans and results.
- `performance_analysis.md`: measured performance findings.

## Measured results summary
Dataset: 100 customers, 100 accounts, 100 cards, 3 merchants, 50,000 transactions.

| Scenario | Index | Average latency | Minimum latency | Speedup vs baseline |
|---|---|---:|---:|---:|
| 1A | Unindexed status/date scan | 88.658 ms | 79.535 ms | 1.00x |
| 1B | Composite `(status, initiated_at)` | 83.311 ms | 78.001 ms | 1.06x |
| 1C | Covering `INCLUDE` index | 80.982 ms | 76.472 ms | 1.09x |
| 2A | Unindexed account statement scan | 10.053 ms | 8.961 ms | 1.00x |
| 2B | Single-column `source_account_id` | 5.378 ms | 4.895 ms | 1.87x |
| 2C | Ordered covering index | 5.196 ms | 4.569 ms | 1.93x |
| 3 | 360-degree rollup | 2.900 ms | 2.376 ms | N/A |

Latencies include Python round-trip and row fetch; `EXPLAIN ANALYZE` execution times are in `benchmark_results.txt`.

## Currency safety
- No FX table exists in Portfolio 1, so cross-currency sums are avoided.
- AML velocity query is USD-only with a 24-hour `RANGE` window.
- Customer 360 query reports per-currency balances separately.
- Merchant settlement query joins transactions only to the settlement account's currency.
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
