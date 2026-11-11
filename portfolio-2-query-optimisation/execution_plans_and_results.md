# Execution Plans and Results

PostgreSQL 16.15. Benchmark database: `apexbank_benchmark`. Dataset: 100 customers, 100 accounts, 100 cards, 3 merchants, 50,000 transactions. The `transactions` heap is 1,175 pages of 8 kB (about 9.4 MB). Full plans: `benchmark_results.txt`. Numbers below are from the run recorded there; re-running changes the timings slightly but not the plan shapes.

"Server time" is the median PostgreSQL executor time over 5 runs of `EXPLAIN (ANALYZE, TIMING OFF)`. The plans shown were captured with `EXPLAIN (ANALYZE, BUFFERS)` after a warm-up run.

## Reading the cost model
PostgreSQL costs are in arbitrary units, not milliseconds. The defaults are `seq_page_cost = 1.0`, `random_page_cost = 4.0`, `cpu_tuple_cost = 0.01` and `cpu_operator_cost = 0.0025`. The Scenario 1A estimate can be checked by hand:

```
1,175 pages x 1.0                 = 1,175
50,000 tuples x 0.01              =   500
50,000 tuples x 3 quals x 0.0025  =   375
Total Seq Scan cost               = 2,050   (plan: cost=0.00..2050.00)
```

Scenario 2A has a single qual, so its cost is 1,175 + 500 + 125 = 1,800. Row estimates come from `ANALYZE` statistics and are close to the actual counts: 14,714 estimated vs 14,672 actual in 1A, and 757 vs 743 in 2A.

## Scenario 1: AML status/date scan
Query: settled transactions between 2026-03-01 and 2026-06-30. This returns 14,672 rows, about 29% of the table.

| Index | Server time | Plan shape | Buffers |
|---|---:|---|---|
| None | 4.367 ms | Seq Scan, 35,328 rows removed by filter | 1,175 heap pages |
| `(status, initiated_at)` | 2.162 ms | Bitmap Index Scan, then Bitmap Heap Scan | 59 index + 492 heap pages |
| Covering `INCLUDE (transaction_id, amount)` | 1.148 ms | Index Only Scan, Heap Fetches: 0 | 112 index pages |

Why the planner chooses each plan:
- **1B uses a bitmap scan, not a plain index scan.** About 29% of rows match, so the planner collects matching TIDs into a bitmap and reads each heap page once, in physical order. Rows were inserted in `initiated_at` order, so the matching rows sit in 492 contiguous pages rather than across all 1,175.
- **The column order is equality first, then range.** `status` is compared with `=` and `initiated_at` with a range, so the matching entries form one contiguous range of the B-tree. With `(initiated_at, status)`, the scan would walk the whole date range and filter on status.
- **1C is an index-only scan.** All selected columns are in the index: `status` and `initiated_at` as keys, `transaction_id` and `amount` as `INCLUDE` payload. `Heap Fetches: 0` depends on the visibility map, which the runner's `VACUUM` sets. On a table under heavy update load, some heap fetches would come back.

Key plan for covering index:

```
Index Only Scan using idx_txn_status_date_cover on transactions  (cost=0.41..768.69 rows=14590 width=38) (actual time=0.023..1.503 rows=14672 loops=1)
  Index Cond: ((status = 'SETTLED'::text) AND (initiated_at >= '2026-03-01 ...') AND (initiated_at <= '2026-06-30 ...'))
  Heap Fetches: 0
  Buffers: shared hit=112
```

## Scenario 2: Account statement scan
Query: one source account ordered by `initiated_at DESC`. This returns 743 rows, about 1.5% of the table.

| Index | Server time | Plan shape | Buffers |
|---|---:|---|---|
| None | 2.146 ms | Seq Scan (49,257 rows removed), then Sort | 1,175 |
| `source_account_id` | 0.334 ms | Bitmap Heap Scan, then quicksort | 3 index + 575 heap pages |
| Ordered covering `(source_account_id, initiated_at DESC) INCLUDE (transaction_id, amount, currency_code)` | 0.055 ms | Index Only Scan, no Sort node, Heap Fetches: 0 | 11 |

- **2B still sorts and touches 575 heap pages.** One account's transactions are spread across the heap, because rows were generated in time order and the source account is chosen at random.
- **2C needs no Sort node.** The B-tree already returns rows in `initiated_at DESC` order for each account, so the planner removes the Sort. A plain ascending `(source_account_id, initiated_at)` index would also work, using a backward scan. The `INCLUDE` columns remove heap access.
- **2C changes two things at once relative to 2B:** the ordering and the covering columns. The benchmark does not separate their individual contributions.

Key plan for ordered covering index:

```
Index Only Scan using idx_txn_source_date_cover on transactions  (cost=0.41..45.94 rows=773 width=35) (actual time=0.006..0.054 rows=743 loops=1)
  Index Cond: (source_account_id = 'fa91764d-3385-5037-bf44-84d8aba4d499'::uuid)
  Heap Fetches: 0
  Buffers: shared hit=11
```

## Scenario 3: 360-degree analytical rollup
Query: aggregates 100 customers with their active accounts and pre-aggregated active cards.

| Server time | Plan shape |
|---:|---|
| 1.033 ms | Sort over HashAggregate over a Nested Loop Left Join. The outer side is a Seq Scan on customers. The inner side is a Hash Right Join of the pre-aggregated cards with accounts, which are probed via a Bitmap Index Scan on `idx_accounts_customer`. |

Transaction indexes play no part here, because the rollup does not read the transaction table. The P1 foreign-key index `idx_accounts_customer` drives the per-customer account lookup.

## Production query plans
`benchmark_results.txt` also records plans for the other three production queries in `queries.sql`, captured under the final index set (both covering indexes):
- **AML velocity:** Seq Scan on transactions (about 34% of rows match USD + SETTLED/PENDING), then Memoize + `accounts_pkey` lookups, a Hash Join to customers, and a Sort on `(source_account_id, initiated_at)` for the `WindowAgg`. `idx_txn_source_date_cover` does not help. It does not contain `status`, and at this selectivity a sequential scan followed by a sort is cheaper.
- **Merchant settlement:** Hash Right Join over a full Seq Scan of transactions. The query aggregates every period, so every row must be read.
- **30-day channel diagnostics:** an InitPlan computes `MAX(initiated_at)`, followed by a Seq Scan. The planner estimates 16,667 rows, its default one-third selectivity for a comparison with a value unknown at plan time, against 3,593 actual. An `initiated_at` index (P1's `idx_transactions_initiated_at`, dropped in this benchmark) would serve both the MAX and the range filter.

## Query results
First 20 rows per production query are in `query_results.txt`. All queries are currency-safe: USD-only AML 24-hour velocity, per-currency customer balances, and merchant settlement in the settlement account's currency.
