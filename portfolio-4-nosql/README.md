# Portfolio 4: NoSQL and Advanced Data Models
**Course:** MIT 8103 Advanced Database Systems  
**Case Study:** ApexBank Digital (Next-Generation Digital Banking & Fintech Platform)  
**Database Engine:** MongoDB 7.0 (Document Store)  
**Marks Allocated:** 7 Marks  
**Schema Source:** Portfolio 1 (`../portfolio-1-database-design/ddl_schema.sql`, `seed_data.sql`)

---

### Executive Summary

Portfolio 4 re-models the **ApexBank Digital** case study using **NoSQL advanced data models**, contrasting them with the Portfolio 1 relational (PostgreSQL) design. Four NoSQL paradigms are examined — document, key-value, column-family, and graph — with the document model (MongoDB 7.0) implemented end-to-end and the others specified as design models with suitability analysis.

MongoDB runs in a dedicated `mit8103-mongo` container on `localhost:27017`; Portfolio 1's PostgreSQL `apexbank` database is never modified.

---

### Directory Contents & Deliverables

| File | Description |
| :--- | :--- |
| [`nosql_model.md`](nosql_model.md) | NoSQL data model design: document schemas (MongoDB), key-value, column-family, and graph models with suitability analysis vs. relational. |
| [`nosql_runner.py`](nosql_runner.py) | MongoDB 7.0 implementation: connects to `mit8103-mongo`, creates collections, ingests ApexBank seed data as documents, runs document/KV queries, writes evidence. |
| [`nosql_test_evidence.txt`](nosql_test_evidence.txt) | Raw console output confirming collection creation, document ingestion, query results, and KV operations against MongoDB 7.0. |

---

### NoSQL Models Implemented

| NoSQL Paradigm | Technology | ApexBank Use Case | Status |
| :--- | :--- | :--- | :--- |
| **Document** | MongoDB 7.0 | Customer profiles, accounts (cards embedded), transactions (ledger lines embedded), KV store | ✅ Implemented |
| **Key-Value** | Redis concept (MongoDB `kv_store`) | Idempotency key cache, session tokens, rate-limiter counters, card locks | ✅ Implemented |
| **Column-Family** | Cassandra concept | Time-series transaction ledger by `account_id`, clustered by `initiated_at` | 📋 Design only |
| **Graph** | Neo4j concept | Account transfer network for AML/fraud cycle detection | 📋 Design only |

---

### Setup & Run

From the repository root:

```bash
# 1. Start MongoDB 7.0 (PostgreSQL is not required for Portfolio 4)
docker compose up -d mongo

# 2. Install Python dependencies (psycopg[binary]>=3.2, pymongo>=4.9)
pip install -r requirements.txt

# 3. Run Portfolio 4
python portfolio-4-nosql/nosql_runner.py
```

The runner connects via `NOSQL_DATABASE_URL` (default: `mongodb://apexbank:apexbank_dev@localhost:27017/apexbank?authSource=admin`). Override with:

```powershell
$env:NOSQL_DATABASE_URL="mongodb://apexbank:apexbank_dev@localhost:27017/apexbank?authSource=admin"
```

What the runner does:

1. Drops and recreates collections (re-runnable).
2. Inserts 8 customer documents (KYC embedded), 8 account documents (3 cards embedded), 2 transaction documents (6 ledger lines embedded), and 5 key-value documents; money is stored as BSON `Decimal128`.
3. Creates unique/secondary indexes (natural keys from P1, multikey `ledger_lines.account_id`, KV unique `_key` and TTL `expire_at`).
4. Runs document queries: single-document customer+KYC read, account+cards aggregate read, transaction+ledger-lines read, indexed status query (with `explain()` showing `IXSCAN`), aggregation over embedded `ledger_lines`.
5. Runs key-value operations: live idempotency key lookup, duplicate-key retry rejection (`DuplicateKeyError`), session get, atomic rate-limit `$inc`, card-lock toggle, key delete.
6. Runs sanity checks: document counts, account-to-customer references, PCI DSS masked-PAN and forbidden-field checks, `Decimal128` type check, debits = credits per transaction, ledger-lines embedding check.
7. Writes `nosql_test_evidence.txt` (the console output up to the end of the sanity checks).

The container is a **standalone** MongoDB server (no replica set), so the runner does not use multi-document transactions; see `nosql_model.md` section 4 for the consistency discussion.

---

### Relationship to Portfolio 1

- **Same case study:** ApexBank Digital, same entities (customers, accounts, cards, transactions).
- **Same data:** Document values mirror the P1 seeded UUIDs, customers, KYC records, cards and transactions. Account balances are the P1 *post-posting* balances (opening balances in `seed_data.sql` after `trg_ledger_apply_balance` applies the seeded ledger entries), so the two models are directly comparable.
- **PCI DSS preserved:** No CVV/CVC/PIN stored; only `masked_pan`, `card_token`, and `pan_hmac` — identical to P1.
- **Relational vs document:** P1's core tables become 3 document collections (`customers`, `accounts`, `transactions`) by embedding bounded related data (KYC inside customer, cards inside account, journal_id + ledger lines inside transaction; journal narrative not carried over), plus a `kv_store` collection for key-value data. Unbounded data (transactions per account) is referenced, not embedded. Lookup/reference tables (`currencies`, `account_types`), `merchants` (kept as `merchant_id` reference) and `audit_logs` are not modelled in the document store.

---

### File Links

Use relative links only:
- `nosql_model.md`
- `nosql_runner.py`
- `nosql_test_evidence.txt`
- `../portfolio-1-database-design/ddl_schema.sql`
- `../portfolio-1-database-design/seed_data.sql`
