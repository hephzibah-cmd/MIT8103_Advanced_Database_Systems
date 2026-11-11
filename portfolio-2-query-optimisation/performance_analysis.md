# Performance Analysis

## Methodology
- **Data:** a deterministic dataset (`random.seed(42)`) of 100 customers, 100 accounts, 100 cards, 3 merchants and 50,000 transactions in `apexbank_benchmark`. `VACUUM (ANALYZE)` runs after loading and after every index change, so planner statistics and the visibility map are current.
- **Fair comparison:** each scenario starts by dropping all non-constraint transaction indexes, including the P1 baseline indexes. Only the index under test then exists. Every scenario runs one warm-up execution before measurement, so baseline and indexed runs start from the same cache state.
- **Server execution time:** the median of 5 `EXPLAIN (ANALYZE, TIMING OFF)` executor times. This is the primary metric, because it isolates the access path.
- **Round-trip latency:** the mean and minimum of 5 timed `execute()` + `fetchall()` calls from Python. These include network transfer and Python decoding of UUID, Decimal and timestamp values.
- **Plans:** captured with `EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)` after the warm-up run. Index sizes come from `pg_relation_size`.
- **Evidence:** full plans and all figures are in `benchmark_results.txt`. The numbers below are from the run recorded there.

## Results

| Scenario | Index strategy | Server time | Server speedup | Round-trip avg | Index size |
|---|---|---:|---:|---:|---:|
| 1A: AML status/date scan | None | 4.367 ms | 1.00x | 50.145 ms | - |
| 1B: Composite B-tree `(status, initiated_at)` | Composite | 2.162 ms | 2.02x | 48.686 ms | 1592 kB |
| 1C: Covering index with `INCLUDE` | Covering | 1.148 ms | 3.80x | 51.294 ms | 3008 kB |
| 2A: Account statement scan | None | 2.146 ms | 1.00x | 4.521 ms | - |
| 2B: Single-column `source_account_id` | Single-column | 0.334 ms | 6.43x | 2.036 ms | 376 kB |
| 2C: Ordered covering `(source_account_id, initiated_at DESC)` | Ordered covering | 0.055 ms | 39.02x | 2.133 ms | 3784 kB |
| 3: 360-degree rollup | Master-table join only | 1.033 ms | N/A | 2.235 ms | - |

## Findings
- **Query 1 returns about 29% of the table (14,672 rows), so indexes give only moderate gains.** The composite index roughly halves executor time (2.0x) through a bitmap heap scan of 492 of 1,175 pages. The covering index allows an index-only scan with zero heap fetches, about 3.8x faster than the sequential scan. Round-trip latency barely moves: transferring and decoding 14,672 rows costs far more than the scan itself. In the recorded run all three round-trip averages fall within about 3 ms of each other (48.7-51.3 ms), and 1C's is slightly slower than 1A's despite a 3.8x faster executor, which shows that transfer cost and noise exceed the index effect at that level.
- **Query 2 is selective (743 rows, about 1.5%), so indexes help much more.** A single-column index cuts executor time about 6.4x. The ordered covering index matches `WHERE source_account_id = ... ORDER BY initiated_at DESC` exactly, removing both the Sort node and heap access and reading 11 buffers instead of 1,175. That is the textbook case for a composite index whose key order matches the predicate and the sort.
- **Query 3 does not read the transaction table, so transaction indexes do not affect it.** It is a small rollup over customers, accounts and cards, and the planner uses the P1 index `idx_accounts_customer`.
- **The planner's choices match the selectivity:** a sequential scan when no index exists, a bitmap scan for medium selectivity (Query 1), and an index-only scan when every column is covered and the visibility map is all-visible.

## Trade-offs (write amplification and storage)
- **Storage:** the covering indexes are larger than their non-covering versions. In the recorded run, `idx_txn_status_date_cover` was 3008 kB against 1592 kB for the composite, and `idx_txn_source_date_cover` was 3784 kB against 376 kB for the single-column index. Together they are about 70% of the 9.4 MB heap.
- **Writes:** every `INSERT` into `transactions` must update every index on the table. ApexBank's transaction table is write-heavy, so each extra index adds latency and WAL volume to the payment path. Write cost was not measured in this benchmark.
- **HOT updates:** indexing `status` blocks heap-only tuple (HOT) updates for the `PENDING` to `SETTLED` transition. Because `status` is an indexed column, each settlement update writes new entries into every index. A partial index such as `ON transactions (initiated_at) WHERE status = 'SETTLED'` would be smaller, but it only serves queries on settled rows.
- **Index-only scans need maintenance:** they rely on autovacuum keeping the visibility map current. On recently updated pages, PostgreSQL falls back to heap fetches.

## Limitations
- **The working set fits in memory.** The heap is about 9.4 MB, and every plan shows `shared hit` only, so these are in-memory results. Disk-bound tables at production scale would favour the index plans more strongly, because random I/O dominates.
- **Each scenario has five runs on a shared Docker host.** Treat differences below about 10% as noise.
- **Data distribution:** transaction timestamps rise steadily with insertion order, which gives `initiated_at` near-perfect physical correlation and helps range scans. Real data would be less ordered.

## Constraints respected
- `PENDING` transactions have `completed_at IS NULL`.
- Non-`PENDING` transactions have `completed_at` populated.
- Transaction currency matches source and destination account currencies.
- Merchant transactions are limited to the settlement account's currency.

## Recommendations
- Use `idx_txn_status_date_cover` for AML status/date scans when index-only scans are acceptable, and weigh it against the write and HOT-update cost on `status`.
- Use `idx_txn_source_date_cover` for account statement queries filtered by source account and ordered by time. This is the strongest result in the benchmark.
- Keep the Portfolio 1 baseline indexes for operational queries. Benchmark indexes were created and dropped only in the separate benchmark database.
