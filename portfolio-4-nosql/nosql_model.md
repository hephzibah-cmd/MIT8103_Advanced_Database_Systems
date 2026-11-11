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

Relational normalization (P1) splits customer, KYC, account, card, and transaction data across 11 tables requiring joins. In the document model, related data is **embedded** into single documents so a typical retail customer read (profile + accounts + cards + recent transactions) requires **one query, zero joins**.

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
  "current_balance": 15003.0000,
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

**Embedding rationale:** A transaction is almost always read together with its ledger lines (for balance-after display). Embedding ledger lines avoids a join and matches the append-only, read-heavy access pattern of transaction history.

##### `cards` collection
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

**PCI DSS compliance:** No CVV/CVC or PIN fields are stored. Only `masked_pan` (<=10 digits), `card_token` (opaque vault token), and `pan_hmac` (keyed HMAC-SHA-256) are persisted — identical to Portfolio 1.

#### 3.2 Key-Value Model (Redis concept)

Used for short-lived, high-throughput lookup patterns where the value is opaque and accessed by a single key:

| Key Pattern | Value | TTL | Use Case |
| :--- | :--- | :--- | :--- |
| `idem:{idempotency_key}` | `transaction_id` | 24h | Idempotency: reject duplicate payment retries |
| `sess:{session_token}` | JSON customer/session profile | 30m | Mobile app session authentication |
| `ratelimit:{customer_id}` | Integer request count | 60s | API rate limiting per customer |
| `card_lock:{card_id}` | `"locked"`/`"unlocked"` | indefinite | Card freeze/unfreeze toggle |

**Implementation:** The runner creates a MongoDB `kv_store` collection with a TTL index on `expire_at`, demonstrating key-value semantics (get/set/delete by key, automatic expiry).

#### 3.3 Column-Family Model (Cassandra concept) — Design Only

For write-heavy, time-ordered transaction analytics where queries are always filtered by `account_id` and ordered by `initiated_at`:

- **Partition key:** `account_id`
- **Clustering columns:** `initiated_at DESC`, `transaction_id`
- **Columns:** `amount`, `currency_code`, `status`, `counterparty_account_id`

Suitable for: account statement generation ("last 50 transactions for account X"), time-range aggregations, and partitioning historical transaction data by month.

#### 3.4 Graph Model (Neo4j concept) — Design Only

For AML/fraud detection over the account transfer network:

- **Nodes:** `Account` (account_id, customer_id, balance), `Customer` (customer_id, name)
- **Relationships:** `TRANSFERRED_TO` (amount, timestamp, channel) between accounts

Queries:
- "Find all accounts that received funds from Account A within 24 hours" (1-hop)
- "Detect circular money-laundering patterns: A→B→C→A" (cycle detection)
- "Shortest path of fund flow between two accounts" (pathfinding)

---

### 4. Suitability Analysis

| Workload | Relational (P1, PostgreSQL) | Document (P4, MongoDB) | Why NoSQL fits |
| :--- | :--- | :--- | :--- |
| Customer profile + accounts + cards read | 4-5 table joins | 1 document read | Embedded aggregates eliminate joins |
| Transaction history pagination | Join `transactions` → `ledger_entries` | Embedded ledger lines in 1 doc | Read-optimized, no join |
| Idempotency key lookup | Unique constraint + index | Key-value get by `idem:{key}` | O(1) key lookup, TTL expiry |
| AML circular transfer detection | Recursive CTE over `transactions` | Graph traversal | Native graph traversal |
| Double-entry ledger integrity | Deferred triggers, CHECK constraints | Application-enforced (transactions) | Relational still stronger for financial invariants |

**Key finding:** Document/key-value models excel at customer-facing read workloads (profile, transaction history, session/idempotency lookups). The relational model (P1) remains superior for the double-entry ledger where declarative constraints (deferred triggers, CHECK solvency) enforce financial correctness that NoSQL must implement in application code. A polyglot persistence architecture — relational for the ledger, document for customer profiles, key-value for sessions/idempotency — is the most suitable production design.

---

### 5. Implementation Evidence

The runner (`nosql_runner.py`) connects to MongoDB 7.0 (`mit8103-mongo` on `localhost:27017`), creates collections, ingests ApexBank seed data as documents, runs document and key-value queries, and writes `nosql_test_evidence.txt`.

Run:
```bash
docker compose up -d mongo
pip install -r requirements.txt
python portfolio-4-nosql/nosql_runner.py
```

Default DSN: `mongodb://apexbank:apexbank_dev@localhost:27017/apexbank?authSource=admin` (overridable via `NOSQL_DATABASE_URL`).
