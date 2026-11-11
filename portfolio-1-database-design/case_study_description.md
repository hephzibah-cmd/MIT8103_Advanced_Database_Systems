# Portfolio 1: Database Design and Modelling
## Case Study: ApexBank Digital (Next-Generation Digital Banking & Fintech Platform)

---

### 1. Organisation Background & System Scenario

**Organisation Name:** ApexBank Digital  
**Industry:** Financial Technology (Fintech) / Digital Retail Banking  
**Platform Scope:** Core Banking, Multi-Currency Wallets, Real-Time Interbank Payments, and Merchant Settlement Engine  

#### 1.1 Business Context
ApexBank Digital is a high-growth neo-bank operating in the modern financial services ecosystem. Unlike legacy banks burdened by monolithic mainframe architectures, ApexBank provides purely digital, API-driven financial services to over 2.5 million retail customers, micro-enterprises, and e-commerce merchants.

The core banking engine is responsible for maintaining the financial state of all user accounts with zero tolerance for financial discrepancies, data loss, or race conditions. To meet stringent central banking and financial regulatory compliance standards (e.g., Basel III, PCI-DSS, AML/CFT regulations, and Central Bank prudential guidelines), the database architecture must strictly enforce:
1. **Mathematical Accuracy & Balance Invariants:** Every posting must keep the books balanced (total debits equal total credits, which is what keeps assets equal to liabilities plus equity in the bank's general ledger). Individual account balances must never breach overdraft limits or become illegally negative.
2. **Double-Entry Bookkeeping:** Every monetary movement is recorded as balanced debit and credit entries in an immutable general ledger.
3. **High Concurrency & Low Latency:** Real-time point-of-sale (POS) authorizations, peer-to-peer (P2P) transfers, and payment gateway webhooks must execute within 200 milliseconds while preventing double-spending and lost updates.
4. **Idempotency & Auditability:** Every financial request is tagged with unique idempotency keys and logged in a tamper-resistant audit trail.

---

### 2. Database Users and Personas

The database serves several distinct user personas, each interacting through secure application layers with specific access patterns and security clearances:

| User Persona | Access Mechanism | Database Role & Key Operations |
| :--- | :--- | :--- |
| **Retail Mobile Customer** | Mobile App / API Gateway | Query personal balances, view paginated transaction histories, initiate P2P transfers, manage debit card limits, freeze/unfreeze cards. Read-heavy with burst atomic writes during transfers. |
| **Merchant / Business Client** | Merchant Portal & Webhook API | Generate merchant payment links, process customer checkouts, initiate batch payroll transfers, download daily settlement reconciliations. |
| **Core Banking System (Engine)** | Automated Background Daemons & Microservices | Execute atomic double-entry ledger postings, calculate end-of-day (EOD) interest accruals, process automated clearing house (ACH) settlements, execute card network settlements. |
| **Compliance & AML Officers** | Internal Back-office Dashboard | Execute complex analytical audit queries: detect suspicious transaction patterns exceeding \$10,000 threshold (AML flags), trace fund lineage across accounts, generate regulatory reports. |
| **Database Administrator (DBA)** | Administrative Bastion & CLI | Monitor connection pools, analyze execution plans (`EXPLAIN ANALYZE`), manage index maintenance, partition historical transaction tables, coordinate disaster recovery and replication. |

---

### 3. Major Data Entities to be Stored

The database stores the entire lifecycle of retail banking and fintech operations:

1. **Customers (`customers`):** Core demographic, contact, authentication hashes, and account tier information for retail and business clients.
2. **KYC Verifications (`kyc_verifications`):** Tiered Know-Your-Customer compliance records, government identity document types, verification statuses, the reviewing officer or service, and verification timestamps.
3. **Account Types (`account_types`):** Master configuration of account classes (e.g., Retail Tier 1 Savings, Retail Premier Checking, SME Business High-Yield, Institutional Settlement) including minimum balance rules, interest rates, and default overdraft limits.
4. **Currencies (`currencies`):** ISO-4217 currency definitions (e.g., USD, EUR, GBP, NGN), decimal precision units, and active trading status.
5. **Accounts (`accounts`):** Customer financial ledger accounts, account numbers (10-digit NUBAN-style), posting-maintained balances, hold balances (reserved for pending authorizations), status (ACTIVE, FROZEN, CLOSED), and overdraft limits.
6. **Journal Entries (`journal_entries`):** Financial transaction header grouping double-entry movements, storing transaction reference, posting timestamp, and business event type.
7. **Ledger Entries (`ledger_entries`):** Individual atomic double-entry bookkeeping lines (DEBIT or CREDIT) linked to specific accounts, ensuring balance conservation ($\sum \text{Debits} = \sum \text{Credits}$).
8. **Transactions (`transactions`):** User-facing payment records detailing sender, receiver, transaction channel (`MOBILE_APP`, `WEB_PORTAL`, `POS_TERMINAL`, `API_INTEGRATION`), fees, external transaction reference, idempotency keys, payment status, and the journal that posted it.
9. **Cards (`cards`):** Physical and virtual debit cards, tokenised card reference, masked Primary Account Number (PAN), keyed PAN fingerprint (HMAC), card expiration, daily spend limit, and security locks. CVV/CVC and PIN values are never stored, in line with PCI DSS.
10. **Merchants (`merchants`):** Registered business vendors, dedicated settlement account, merchant category code (MCC), and platform commission fee agreements.
11. **Audit Logs (`audit_logs`):** Append-only operational audit trail (UPDATE/DELETE rejected by trigger) recording an immutable actor reference snapshot, linked customer ID, IP address, changed table/record, old state, new state, and timestamp. The actor snapshot survives customer deletion.

---

### 4. Key Business Rules & Transactional Invariants

To guarantee data integrity and regulatory compliance, the relational design enforces the following explicit domain rules:

1. **Zero-Balance Invariant:** Every settled or reversed transaction must be backed by a journal entry whose lines are in a single currency and where the sum of all debits exactly equals the sum of all credits.
2. **Overdraft-Bounded Balance Rule:** Standard savings and checking accounts must have `current_balance >= -overdraft_limit`. Unauthorized overdrafts are rejected at the database constraint level.
3. **Idempotency Enforcement:** All transaction requests require a unique client-generated `idempotency_key`. Subsequent requests with the same key must return the original transaction without re-executing debits.
4. **Immutable Financial History:** Rows in `ledger_entries` and `journal_entries` are strictly **append-only**. Adjustments or refunds must be executed via compensatory reversal transactions, never via `UPDATE` or `DELETE` on past ledger rows.
5. **Referential & Cascade Integrity:** Customers cannot be deleted if any accounts or KYC records exist (`RESTRICT`). An account can only be marked `CLOSED` once its current and hold balances are zero.
6. **PCI DSS Card-Data Minimisation:** Card verification values (CVV/CVC) and PIN blocks must never be persisted. The full PAN is held only in the PCI-scoped token vault; the database stores a token, a masked PAN, and a keyed HMAC fingerprint.
7. **Ledger-Driven Balances:** `accounts.current_balance` is maintained by ledger postings. Every posting must supply a `balance_after` value equal to the resulting account balance, or the database rejects the posting.
8. **Currency Consistency:** A transaction's currency must match the currency of its source account, destination account, and merchant settlement account where applicable.
9. **Audit Identity Preservation:** Audit rows retain an immutable `actor_reference` snapshot so that the responsible actor remains identifiable even if the linked customer record is later deleted.

