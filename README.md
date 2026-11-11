# MIT8103 Advanced Database Systems Portfolio

**Student portfolio case study:** ApexBank Digital — a next-generation digital banking and fintech platform.

This repository contains the practical portfolio activities for MIT8103. All activities use the same ApexBank Digital case study and target **PostgreSQL 16**.

---

## Repository Structure

| Folder | Status | Focus |
| :--- | :--- | :--- |
| [`portfolio-1-database-design/`](portfolio-1-database-design/) | Complete | ER model, relational schema, normalisation, PostgreSQL DDL, seed data, integrity and PCI DSS verification. |
| [`portfolio-2-query-optimisation/`](portfolio-2-query-optimisation/) | Pending | SQL queries, execution plans, indexing, and performance analysis. |
| [`portfolio-3-transactions-concurrency/`](portfolio-3-transactions-concurrency/) | Complete | ACID transaction scripts, multithreaded concurrency experiments (lost update, atomic pessimistic guard, OCC, deadlock prevention, SERIALIZABLE write-skew, idempotency), P1 invariant assertions, PostgreSQL 16 evidence. |
| [`portfolio-4-nosql/`](portfolio-4-nosql/) | Complete | NoSQL model (MongoDB document store): customer profiles, accounts with embedded cards, transactions with embedded ledger lines, key-value idempotency/session/rate-limit store; column-family and graph designs documented. |
| [`portfolio-5-distributed-cloud/`](portfolio-5-distributed-cloud/) | Pending | Replication, sharding, availability, consistency, and deployment. |

---

## Getting Started

### 1. Start PostgreSQL

```bash
docker compose up -d
```

This starts PostgreSQL 16 on `localhost:5432` with:

- database: `apexbank`
- user: `apexbank`
- password: `apexbank_dev`

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the Portfolio 1 verification

```bash
python portfolio-1-database-design/verify_schema.py
```

The verification is re-runnable: it drops and recreates the schema, loads seed data, and then runs integrity, ledger, append-only, and PCI DSS checks.

### Optional `DATABASE_URL`

Override the default connection string if needed:

```bash
set DATABASE_URL=postgresql://apexbank:apexbank_dev@localhost:5432/apexbank
```

PowerShell equivalent: `$env:DATABASE_URL="postgresql://apexbank:apexbank_dev@localhost:5432/apexbank"`

---

## Portfolio 1 Highlights

- 11 normalised relations in BCNF with primary, alternate, and foreign keys.
- Deferred PL/pgSQL constraint triggers enforce double-entry balance at commit.
- Append-only triggers prevent updates or deletes on financial history.
- Ledger postings maintain account balances and validate `balance_after`.
- Transaction currency and status/timestamp consistency are enforced.
- PCI DSS aligned card model: no CVV/CVC or PIN storage; masked PAN, vault token, and keyed HMAC fingerprint only.
- Automated evidence in [`portfolio-1-database-design/test_execution_evidence.txt`](portfolio-1-database-design/test_execution_evidence.txt).

Portfolio 1 documentation: [`portfolio-1-database-design/README.md`](portfolio-1-database-design/README.md)

---

## Academic Integrity and AI Use

AI tools were used as learning and drafting aids. All generated code, SQL, and documentation must be reviewed, tested, and understood by the student before submission. A full AI-use declaration and technical reflection will be included in the final documentation.
