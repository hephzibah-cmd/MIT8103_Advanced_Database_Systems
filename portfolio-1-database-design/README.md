# Portfolio 1: Database Design and Modelling
**Course:** MIT 8103 Advanced Database Systems  
**Case Study:** ApexBank Digital (Next-Generation Digital Banking & Fintech Platform)  
**Database Engine:** PostgreSQL 16  
**Marks Allocated:** 7 Marks  

---

### Executive Summary

Portfolio 1 establishes the conceptual, logical, and physical database architecture for **ApexBank Digital**, an enterprise fintech platform handling multi-currency wallets, high-concurrency P2P payments, debit card processing, and immutable double-entry ledger bookkeeping.

The physical implementation targets **PostgreSQL 16**, using native `UUID`, `NUMERIC(18,4)`, `TIMESTAMPTZ`, `JSONB`, deferred constraint triggers, and PL/pgSQL integrity functions.

---

### Directory Contents & Deliverables

| File | Description |
| :--- | :--- |
| [`case_study_description.md`](case_study_description.md) | Business context, user personas, stored entities, and business rules. |
| [`er_diagram.md`](er_diagram.md) | Crow's foot ER diagram, data dictionary, and cardinality analysis. |
| [`er_diagram.png`](er_diagram.png) / [`er_diagram.svg`](er_diagram.svg) | Image exports of the ER diagram rendered from the Mermaid source. |
| [`relational_schema.md`](relational_schema.md) | Relational notation, candidate keys, constraints, and trigger definitions. |
| [`normalization_analysis.md`](normalization_analysis.md) | Normalisation analysis from UNF through 1NF, 2NF, 3NF to BCNF. |
| [`ddl_schema.sql`](ddl_schema.sql) | PostgreSQL DDL creating all 11 tables, constraints, indexes, and triggers. |
| [`seed_data.sql`](seed_data.sql) | Realistic seed dataset with reconciled balances and balanced ledger postings. |
| [`verify_schema.py`](verify_schema.py) | Automated PostgreSQL schema, invariant, append-only, and PCI DSS verification runner. |
| [`test_execution_evidence.txt`](test_execution_evidence.txt) | Raw console output confirming all checks pass. |

---

### Database Setup

From the repository root:

```bash
docker compose up -d
pip install -r requirements.txt
python portfolio-1-database-design/verify_schema.py
```

The verifier connects to:

```text
postgresql://apexbank:apexbank_dev@localhost:5432/apexbank
```

Override this with the `DATABASE_URL` environment variable if required.

### What the Verification Covers

1. Re-runnable PostgreSQL DDL and seed loading.
2. Row-count audit for all 11 relations.
3. Per-journal and whole-book debit/credit balance invariants.
4. Account balances reconciled to the latest ledger snapshot and updated by postings.
5. PCI DSS card-data checks (no CVV/PIN, tokenised PAN, masked PAN, keyed HMAC, separated PAN rejection).
6. Constraint tests: overdraft, orphan records, duplicate idempotency keys, self-transfer, full PAN, status/timestamp consistency, settled-without-journal, closed-with-balance.
7. Append-only enforcement on `journal_entries`, `ledger_entries`, and `audit_logs` (including the permitted `ON DELETE SET NULL` path for audit rows).
8. Deferred double-entry enforcement: unbalanced, empty, and mixed-currency journals are rejected at commit.
9. Posting-time `balance_after` validation and transaction-currency consistency.
10. Schema-object audit for the required integrity triggers and audit actor snapshots.

### Database-Level Integrity Design

| Invariant | Enforcement |
| :--- | :--- |
| Every journal balances in a single currency | Deferred PostgreSQL constraint trigger (validated at commit). |
| Every journal has at least two lines | Deferred constraint trigger. |
| Ledger, journal, and audit history is append-only | `BEFORE UPDATE OR DELETE` PL/pgSQL triggers. |
| No unauthorised overdraft | `CHECK (current_balance >= -overdraft_limit)`. |
| Idempotent payments | `UNIQUE (idempotency_key)`. |
| No self-transfer | `CHECK (source_account_id <> destination_account_id)`. |
| No CVV/PIN stored | Column removed; PCI DSS aligned card model. |
| No full PAN stored | Masked PAN (≤10 digits after stripping separators), vault token, and keyed HMAC fingerprint. |
| Account balances reflect postings | `trg_ledger_apply_balance` updates the account and validates `balance_after`. |
| Transaction currency consistency | `trg_transaction_currency_guard` checks source, destination, and merchant settlement currencies. |
| Status/timestamp consistency | Conditional `CHECK` constraints on KYC, accounts, and transactions. |
| Settled/reversed transactions are posted | `CHECK (status NOT IN ('SETTLED','REVERSED') OR journal_id IS NOT NULL)`. |
| Closed accounts hold no funds | `CHECK (account_status <> 'CLOSED' OR (current_balance = 0 AND hold_balance = 0))`. |
| Audit actor survives deletion | Immutable `actor_reference` snapshot in `audit_logs`. |

> **Posting rule:** A journal header and all of its ledger lines must be inserted in the **same database transaction**. `trg_journal_has_lines` rejects a journal that is committed without lines.

### PCI DSS Note

The previous draft stored `encrypted_cvv`. PCI DSS v4.0 Requirement 3.3.1 **prohibits storing card verification values and PINs after authorisation, even when encrypted**. The schema now stores only:

- `masked_pan` — truncated PAN (first 6 and last 4 digits; the check strips separators before counting),
- `card_token` — opaque token from the PCI-scoped vault,
- `pan_hmac` — keyed HMAC-SHA-256 fingerprint using a KMS/HSM-held key.

CVV, CVV2, and PIN blocks are never stored.
