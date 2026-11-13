# Portfolio 4: NoSQL and Advanced Data Models
## Case Study: ApexBank Digital (Next-Generation Digital Banking & Fintech Platform)

**Course:** MIT 8103 Advanced Database Systems  
**Database Engine:** MongoDB 7.0 (Document Store)  
**Marks Allocated:** 7 Marks  
**Schema Source:** Portfolio 1 (`../portfolio-1-database-design/ddl_schema.sql`, `seed_data.sql`)

---

### 1. Executive Summary

Portfolio 4 re-models the **ApexBank Digital** case study using **NoSQL advanced data models**, contrasting them with the Portfolio 1 relational (PostgreSQL) design. Four NoSQL paradigms are examined:

| NoSQL Paradigm | Technology | ApexBank Use Case | Implemented |
| :--- | :--- | :--- | :--- |
| **Document** | MongoDB | Customer profiles, account details, transaction history, card records | ✅ Yes (`nosql_runner.py`) |
| **Key-Value** | Redis concept | Idempotency key cache, session tokens, rate-limiter counters | ✅ Yes (MongoDB KV collection) |
| **Column-Family** | Cassandra concept | Time-series transaction ledger by account | 📋 Design only |
| **Graph** | Neo4j concept | Account transfer network for AML/fraud detection | 📋 Design only |

The document model is the primary implementation because customer accounts, cards, and transactions are naturally hierarchical and are typically read together as a single aggregate — a sweet spot for document stores.

---

### 2. Directory Contents & Deliverables

| File | Description |
| :--- | :--- |
| [`nosql_model.md`](nosql_model.md) | NoSQL data model design: document schemas (MongoDB), key-value, column-family, and graph models with suitability analysis. |
| [`nosql_runner.py`](nosql_runner.py) | MongoDB 7.0 implementation: connects to `mit8103-mongo`, creates collections, ingests ApexBank seed data as documents, runs document/KV queries, writes evidence. |
| [`nosql_test_evidence.txt`](nosql_test_evidence.txt) | Raw console output confirming collection creation, document ingestion, query results, and KV operations against MongoDB 7.0. |

---

### 3. NoSQL Data Model Design

#### 3.1 Document Model (MongoDB) — Primary Implementation

Relational normalization (P1) splits customer, KYC, account, card, and transaction data across 11 tables requiring joins. In the document model, data that is bounded and read together is **embedded** (KYC inside the customer, cards inside the account, ledger lines inside the transaction), so each of those aggregates is read in **one query, zero joins**. Data that grows without bound is **referenced** instead: transactions are their own collection (keyed by `source_account_id`/`ledger_lines.account_id`) rather than an array inside the account, because an ever-growing array would eventually hit MongoDB's 16 MB document limit and make every account update rewrite a large document. A full "profile + accounts + cards + recent transactions" screen therefore needs three indexed reads (or one `$lookup` pipeline), still far fewer than the P1 join plan.

Monetary fields are stored as BSON **Decimal128** (shown below as plain numbers for readability), matching P1's `NUMERIC(18,4)`; binary `double` is avoided because it cannot represent values such as 0.1 exactly. Balances are the **post-posting** values (P1 opening balance minus/plus the seeded ledger entries applied by `trg_ledger_apply_balance`), e.g. 15003.0000 - 502.5000 = 14500.5000 for account `a0000001`.

##### `customers` collection
```json
{
  "_id": ObjectId(...),
  "customer_id": "c0000001-0000-4000-8000-000000000001",
  "first_name": "Amina",
  "last_name": "Bello",
  "email": "amina.bello@example.com",
  "phone_number": "+2348031112233",
  "tier_level": "TIER_3",
  "status": "ACTIVE",
  "kyc": {
    "kyc_id": "d0000001-...",
    "document_type": "NATIONAL_ID",
    "id_number": "NIN-1092837465",
    "verification_status": "VERIFIED",
    "verified_at": "2026-01-15T09:30:00+01"
  },
  "created_at": "2026-01-10T08:00:00+01",
  "updated_at": "2026-01-15T09:30:00+01"
}
```

##### `accounts` collection
```json
{
  "_id": ObjectId(...),
  "account_id": "a0000001-0000-4000-8000-000000000001",
  "customer_id": "c0000001-0000-4000-8000-000000000001",
  "account_number": "1000100101",
  "currency_code": "USD",
  "current_balance": 14500.5000,
  "hold_balance": 0.0000,
  "overdraft_limit": 1000.0000,
  "account_status": "ACTIVE",
  "opened_at": "2026-01-10T08:00:00+01",
  "cards": [
    {
      "card_id": "f0000001-...",
      "masked_pan": "411111XXXXXX1122",
      "card_token": "tok_vault_6b1f0c2a9d4e8f7b",
      "pan_hmac": "2cd4bde7...",
      "expiry_date": "2028-12-31",
      "card_type": "DEBIT",
      "daily_spend_limit": 5000.0000,
      "card_status": "ACTIVE"
    }
  ]
}
```

##### `transactions` collection (ledger lines embedded)
```json
{
  "_id": ObjectId(...),
  "transaction_id": "30000001-0000-4000-8000-000000000001",
  "transaction_reference": "TXN-20261025-001",
  "idempotency_key": "idem-key-889911-a",
  "source_account_id": "a0000001-0000-4000-8000-000000000001",
  "destination_account_id": "a0000002-0000-4000-8000-000000000002",
  "merchant_id": null,
  "journal_id": "10000001-0000-4000-8000-000000000001",
  "currency_code": "USD",
  "amount": 500.0000,
  "fee_amount": 2.5000,
  "channel": "MOBILE_APP",
  "status": "SETTLED",
  "initiated_at": "2026-10-25T10:13:58+01",
  "completed_at": "2026-10-25T10:14:01+01",
  "ledger_lines": [
    {"account_id": "a0000001-...", "entry_type": "DEBIT",  "amount": 502.5000, "balance_after": 14500.5000},
    {"account_id": "a0000002-...", "entry_type": "CREDIT", "amount": 500.0000, "balance_after":  8250.0000},
    {"account_id": "a0000008-...", "entry_type": "CREDIT", "amount":   2.5000, "balance_after": 18450.2500}
  ]
}
```

**Embedding rationale:** A transaction is almost always read together with its ledger lines (for balance-after display). The array is small and bounded (2-3 lines per journal) and immutable once posted, so embedding avoids a join without any document-growth risk. A multikey index on `ledger_lines.account_id` supports per-account statement queries.

**Indexes created by the runner:** unique `customer_id`, `email`, `account_id`, `account_number`, `transaction_id`, `idempotency_key` (mirroring P1's natural-key UNIQUE constraints); `accounts.customer_id`; compound `(source_account_id, initiated_at DESC)`; multikey `ledger_lines.account_id`; `status` (demonstrated with `explain()` showing `IXSCAN`; in production this low-cardinality field would be better as the suffix of a compound index); `kv_store._key` unique and a TTL index on `kv_store.expire_at`.

##### Alternative: separate `cards` collection (referenced design, not implemented)

The runner embeds cards in `accounts` (an account has few cards, and they are read with it). If cards needed independent lifecycle queries (e.g. "all cards expiring this month" across all accounts) a referenced `cards` collection would be used instead:
```json
{
  "_id": ObjectId(...),
  "card_id": "f0000001-...",
  "account_id": "a0000001-0000-4000-8000-000000000001",
  "masked_pan": "411111XXXXXX1122",
  "card_token": "tok_vault_6b1f0c2a9d4e8f7b",
  "pan_hmac": "2cd4bde77ae262c960a8643c57c18048bcad51885f144496dd51ae36cb0b8169",
  "expiry_date": "2028-12-31",
  "card_type": "DEBIT",
  "daily_spend_limit": 5000.0000,
  "card_status": "ACTIVE"
}
```

**PCI DSS compliance:** No CVV/CVC or PIN fields are stored. Only `masked_pan` (<=10 digits), `card_token` (opaque vault token), and `pan_hmac` (keyed HMAC-SHA-256) are persisted — identical to Portfolio 1. Embedding these card fields in the account document is acceptable precisely because none of them is cardholder data in clear; the full PAN lives only in the external token vault. The runner verifies the P1 rule (total digit count of `masked_pan` <= 10) and the absence of `cvv`/`cvc`/`pin`/`pan` fields. Unlike P1's CHECK constraint this is not enforced by the database; a `$jsonSchema` collection validator would be the MongoDB equivalent.

#### 3.2 Key-Value Model (Redis concept)

Used for short-lived, high-throughput lookup patterns where the value is opaque and accessed by a single key:

| Key Pattern | Value | TTL | Use Case |
| :--- | :--- | :--- | :--- |
| `idem:{idempotency_key}` | `transaction_id` | 24h | Idempotency: reject duplicate payment retries |
| `sess:{session_token}` | JSON customer/session profile | 30m | Mobile app session authentication |
| `ratelimit:{customer_id}` | Integer request count | 60s | API rate limiting per customer |
| `card_lock:{card_id}` | `"locked"`/`"unlocked"` | indefinite | Card freeze/unfreeze toggle |

**Implementation:** The runner creates a MongoDB `kv_store` collection with a unique index on `_key` and a TTL index (`expireAfterSeconds: 0`) on `expire_at`, demonstrating key-value semantics (get/set/delete by key, set-if-absent, atomic `$inc`, automatic expiry). `expire_at` is a BSON date computed relative to the write time (now + 24h / 30m / 60s); entries with a null `expire_at` (card locks) are never expired. MongoDB's TTL monitor runs only about every 60 seconds, so expired keys can still be visible briefly; reads therefore also filter on `expire_at > now`, and a 60-second rate-limit window is approximate (Redis `EXPIRE` is exact). Idempotency is enforced by the unique `_key` index: a retried payment with the same key raises `DuplicateKeyError` and is rejected (the transactions collection also has a unique index on `idempotency_key`, mirroring P1).

#### 3.3 Column-Family Model (Cassandra concept) — Design Only

For write-heavy, time-ordered transaction analytics where queries are always filtered by `account_id` and ordered by `initiated_at`:

- **Partition key:** `(account_id, year_month)` — a composite key that buckets each account by month, so a very active account (e.g. the treasury/fee account `a0000008`) does not grow one unbounded partition
- **Clustering columns:** `initiated_at DESC`, `transaction_id` (the UUID makes rows with the same timestamp unique)
- **Columns:** `entry_type`, `amount`, `balance_after`, `currency_code`, `status`, `counterparty_account_id`

```sql
-- CQL (Cassandra), one row per ledger line, query-first denormalised table
CREATE TABLE apexbank.ledger_by_account_month (
    account_id              uuid,
    year_month              text,        -- e.g. '2026-10'
    initiated_at            timestamp,
    transaction_id          uuid,
    entry_type              text,        -- DEBIT / CREDIT
    amount                  decimal,
    balance_after           decimal,
    currency_code           text,
    status                  text,
    counterparty_account_id uuid,
    PRIMARY KEY ((account_id, year_month), initiated_at, transaction_id)
) WITH CLUSTERING ORDER BY (initiated_at DESC, transaction_id ASC);

-- Statement: last 50 lines for Amina's USD account in October 2026
SELECT initiated_at, entry_type, amount, balance_after
FROM apexbank.ledger_by_account_month
WHERE account_id = a0000001-0000-4000-8000-000000000001 AND year_month = '2026-10'
LIMIT 50;
```

Suitable for: account statement generation ("last 50 transactions for account X this month"), time-range scans within a partition, and very high write throughput across nodes. Not suitable as the system of record for balances: Cassandra has no multi-partition ACID transactions, so the debit and credit rows of one journal (different partitions) cannot be written atomically; it is fed from the relational ledger as a read model.

#### 3.4 Graph Model (Neo4j concept) — Design Only

For AML/fraud detection over the account transfer network:

- **Nodes:** `Account` (account_id, account_number, currency_code), `Customer` (customer_id, name, tier_level), `Merchant` (merchant_id, business_name)
- **Relationships:** `(:Customer)-[:OWNS]->(:Account)`, `(:Account)-[:TRANSFERRED_TO {transaction_id, amount, at, channel}]->(:Account)` (one relationship per transaction), `(:Merchant)-[:SETTLES_TO]->(:Account)`

```cypher
// Load the two seeded P1 transactions
MERGE (a1:Account {account_id:'a0000001-0000-4000-8000-000000000001'})
MERGE (a2:Account {account_id:'a0000002-0000-4000-8000-000000000002'})
MERGE (a5:Account {account_id:'a0000005-0000-4000-8000-000000000005'})
MERGE (a6:Account {account_id:'a0000006-0000-4000-8000-000000000006'})
CREATE (a1)-[:TRANSFERRED_TO {transaction_id:'30000001-0000-4000-8000-000000000001', amount:500.00,
        at:datetime('2026-10-25T10:13:58+01:00'), channel:'MOBILE_APP'}]->(a2)
CREATE (a5)-[:TRANSFERRED_TO {transaction_id:'30000002-0000-4000-8000-000000000002', amount:120.00,
        at:datetime('2026-10-26T14:29:55+01:00'), channel:'POS_TERMINAL'}]->(a6);

// 1-hop: accounts that received funds from A within 24 hours of a given time
MATCH (a:Account {account_id:$acct})-[t:TRANSFERRED_TO]->(b:Account)
WHERE t.at >= $since AND t.at < $since + duration('PT24H')
RETURN b.account_id, t.amount, t.at;

// Cycle detection (round-tripping): money leaves A and returns to A in 2-5 hops,
// each hop later in time than the previous one
MATCH p = (a:Account)-[:TRANSFERRED_TO*2..5]->(a)
WHERE all(i IN range(0, size(relationships(p)) - 2)
          WHERE relationships(p)[i].at < relationships(p)[i+1].at)
RETURN p LIMIT 25;

// Fund-flow path between two accounts
MATCH p = shortestPath((x:Account {account_id:$from})-[:TRANSFERRED_TO*..6]->(y:Account {account_id:$to}))
RETURN p;
```

Variable-length traversals are bounded (`*2..5`, `*..6`) because unbounded path expansion is exponential on a dense transfer graph. The equivalent in P1 is a recursive CTE with a cycle check over `transactions`, whose cost grows with join depth; a graph database follows stored adjacency pointers ("index-free adjacency"), so cost depends on the neighbourhood visited rather than total table size.

---

### 4. Suitability Analysis

| Workload | Relational (P1, PostgreSQL) | Document (P4, MongoDB) | Why NoSQL fits |
| :--- | :--- | :--- | :--- |
| Customer profile + KYC read | `customers` ⋈ `kyc_verifications` | 1 document read | Embedded sub-document eliminates the join |
| Account + cards read | `accounts` ⋈ `cards` | 1 document read | Embedded bounded array eliminates the join |
| Profile + accounts + cards screen | 3-4 table joins | 2 indexed reads (customer, accounts) or one `$lookup` | Fewer round trips; unbounded data (transactions) deliberately kept out of the aggregate |
| Transaction history pagination | Join `transactions` → `ledger_entries` | Embedded ledger lines in 1 doc | Read-optimized, no join |
| Account statement time-series (column-family) | Index range scan on `ledger_entries` | Single-partition clustered scan | Pre-sorted by time within `(account_id, month)` partition; linear write scale-out |
| Idempotency key lookup | Unique constraint + index | Key-value get by `idem:{key}` | Single-key lookup (O(1) hash in Redis; B-tree index in the MongoDB demo), native TTL expiry |
| AML circular transfer detection | Recursive CTE over `transactions` | Graph traversal | Native graph traversal |
| Double-entry ledger integrity | Deferred triggers, CHECK constraints | Application-enforced only | Relational still stronger for financial invariants |

**Consistency and transactions:** A single-document write in MongoDB is atomic, so a transaction document together with its embedded ledger lines is written all-or-nothing, and the runner verifies that debits equal credits for every transaction. Updating the *account balances* in other documents at the same time, however, would need a multi-document ACID transaction (`session.with_transaction()`), which MongoDB only supports on a replica set or sharded cluster. The `mit8103-mongo` container used here is a **standalone** server, so the runner does **not** use multi-document transactions and balances are not updated atomically with the ledger; this is exactly the invariant P1 enforces declaratively. In production a replica set with `writeConcern: "majority"` and `readConcern: "majority"` would be required for durable, non-rollback-able financial writes (in CAP terms MongoDB is then CP for a partitioned minority, while Cassandra with tunable consistency, e.g. `QUORUM`, and Redis replication lean towards availability and BASE-style eventual consistency).

**Key finding:** Document/key-value models excel at customer-facing read workloads (profile, transaction history, session/idempotency lookups). The relational model (P1) remains superior for the double-entry ledger where declarative constraints (deferred triggers, CHECK solvency) enforce financial correctness that NoSQL must implement in application code. A polyglot persistence architecture — relational for the ledger, document for customer profiles, key-value for sessions/idempotency — is the most suitable production design.

---

### 5. Implementation Evidence

The runner (`nosql_runner.py`) connects to MongoDB 7.0 (`mit8103-mongo` on `localhost:27017`), creates collections and indexes, ingests ApexBank seed data as documents (8 customers, 8 accounts with 3 embedded cards, 2 transactions with 6 embedded ledger lines, 5 key-value entries), runs document and key-value queries, runs sanity checks, and writes `nosql_test_evidence.txt`. The column-family and graph models are design-only (CQL and Cypher above are not executed).

Run:
```bash
docker compose up -d mongo
pip install -r requirements.txt
python portfolio-4-nosql/nosql_runner.py
```

Default DSN: `mongodb://apexbank:apexbank_dev@localhost:27017/apexbank?authSource=admin` (overridable via `NOSQL_DATABASE_URL`).
