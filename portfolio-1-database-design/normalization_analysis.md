# Portfolio 1: Database Design and Modelling
## Rigorous Normalisation Analysis (UNF to BCNF)

---

### 1. Introduction to Normalisation in Core Banking

Normalisation is the formal mathematical process of decomposing complex relational structures into progressively smaller, well-structured relations. In the context of **ApexBank Digital**, normalisation is paramount to eliminate update, insertion, and deletion anomalies that could otherwise cause catastrophic financial discrepancies, ghost balances, or lost audit trails.

Below is the step-by-step transformation from an Unnormalised Form (UNF) through to Boyce-Codd Normal Form (BCNF).

---

### 2. Unnormalised Form (UNF)

In early prototyping, banking systems often start with a monolithic, denormalised master transaction sheet:

$$\begin{aligned}
\text{UNF\_BANK\_RECORD} = \{ & \text{CustomerID}, \text{CustomerName}, \text{Email}, \text{Phone}, \text{KYCDocType}, \text{KYCIdNumber}, \\
& (\text{AccountNumber}, \text{AccountType}, \text{AccountTypeName}, \text{MinBalance}, \text{CurrencyCode}, \\
& \text{CurrencyName}, \text{CurrentBalance}, \text{OverdraftLimit}), \\
& (\text{TransactionID}, \text{TxnRef}, \text{IdempotencyKey}, \text{TxnAmount}, \text{Fee}, \text{SourceAcc}, \text{DestAcc}, \\
& \text{MerchantID}, \text{MerchantName}, \text{MerchantMCC}, \text{TxnStatus}, \text{Timestamp}) \}
\end{aligned}$$

#### Anomalies Present in UNF:
- **Repeating Groups:** A single customer has multiple accounts and thousands of transactions embedded inside nested collections.
- **Redundancy:** Account type configurations (e.g., minimum balance, interest rate) and currency names are duplicated for every single transaction row.
- **Update Anomaly:** Modifying the minimum balance for "Savings" requires updating millions of historical rows; missing even one creates conflicting system states.
- **Insertion Anomaly:** A new currency (e.g., "GBP") or a new account type cannot be recorded until a customer opens an account in that currency.
- **Deletion Anomaly:** Deleting a customer's closed account purges historical transaction logs, violating banking regulatory audit compliance.

---

### 3. First Normal Form (1NF)

#### Definition:
A relation $R$ is in 1NF if and only if all underlying domains contain only **atomic (indivisible) values**, and each tuple contains exactly one value for each attribute (no repeating groups, arrays, or nested tables).

#### Transformation to 1NF:
1. Flatten repeating groups by creating distinct relations for Customer, KYC documents, Accounts, and Transactions. A customer can submit several identity documents over time (BVN, then National ID, then passport), so KYC data is a repeating group and cannot stay in the customer relation as single-valued columns.
2. Decompose composite names (e.g., `CustomerName` $\rightarrow$ `first_name`, `last_name`).
3. Define unambiguous primary keys for every decomposed relation.

#### Relations in 1NF:
- $R_1(\underline{\text{customer\_id}}, \text{first\_name}, \text{last\_name}, \text{email}, \text{phone}, \text{tier\_level}, \text{status})$
- $R_4(\underline{\text{kyc\_id}}, \text{customer\_id}, \text{document\_type}, \text{id\_number}, \text{verification\_status}, \text{verified\_by}, \text{verified\_at})$
- $R_2(\underline{\text{account\_id}}, \text{customer\_id}, \text{account\_number}, \text{account\_type\_id}, \text{account\_type\_name}, \text{min\_balance}, \text{interest\_rate}, \text{currency\_code}, \text{currency\_name}, \text{currency\_symbol}, \text{current\_balance}, \text{overdraft\_limit})$
- $R_3(\underline{\text{transaction\_id}}, \text{txn\_ref}, \text{idempotency\_key}, \text{source\_account\_id}, \text{dest\_account\_id}, \text{merchant\_id}, \text{merchant\_name}, \text{merchant\_mcc}, \text{amount}, \text{fee}, \text{channel}, \text{status}, \text{initiated\_at})$

---

### 4. Second Normal Form (2NF)

#### Definition:
A relation $R$ is in 2NF if and only if it is in 1NF and **every non-prime attribute is fully functionally dependent on the entire primary key** (i.e., no partial functional dependencies on composite candidate keys).

#### Analysis of Partial Dependencies:
Consider a composite relation associating cards with accounts and transaction limits:
$$\text{CARD\_LIMITS}(\underline{\text{account\_id}, \text{card\_id}}, \text{account\_number}, \text{current\_balance}, \text{card\_pan}, \text{card\_daily\_limit})$$

- $\text{account\_id} \rightarrow \text{account\_number}, \text{current\_balance}$ (Partial Dependency: depends only on $\text{account\_id}$, not $\text{card\_id}$).
- $\text{card\_id} \rightarrow \text{card\_pan}, \text{card\_daily\_limit}$ (Partial Dependency: depends only on $\text{card\_id}$).

#### Transformation to 2NF:
We decompose to eliminate partial dependencies: account attributes move to `ACCOUNTS` and card attributes to `CARDS` (which carries `account_id` as a foreign key). In the final schema every primary key is a single-attribute surrogate key (UUID / INT), so no partial dependency on the primary key can exist.

2NF must also hold for every *candidate* key, not only the primary key. The only composite candidate key in the schema is `KYC_VERIFICATIONS(document_type, id_number)`. Its non-prime attributes (`customer_id`, `verification_status`, `verified_by`, `verified_at`, `created_at`) depend on the full pair, not on either part alone: the same `id_number` string can occur for different document types, and one document type obviously identifies nothing. `KYC_VERIFICATIONS` therefore satisfies 2NF.

---

### 5. Third Normal Form (3NF)

#### Definition:
A relation $R$ is in 3NF if and only if it is in 2NF and **no non-prime attribute is transitively dependent on the primary key** ($X \rightarrow Y$ and $Y \rightarrow Z$, where $Y$ is not a candidate key).

#### Detection of Transitive Dependencies:

1. **In the KYC Relation ($R_4$):**
   - $\text{kyc\_id} \rightarrow \text{document\_type}, \text{id\_number}, \text{customer\_id}, \dots$ and $\{\text{document\_type}, \text{id\_number}\} \rightarrow \text{kyc\_id}, \text{customer\_id}, \dots$
   - Both determinants are candidate keys, so there is no transitive dependency. Customer details are *not* repeated here (only the `customer_id` foreign key), so a change of customer name or email never touches KYC rows.

2. **In the Account Relation ($R_2$):**
   - $\text{account\_id} \rightarrow \text{account\_type\_id} \rightarrow \text{type\_name}, \text{minimum\_balance}, \text{interest\_rate}$
   - $\text{account\_id} \rightarrow \text{currency\_code} \rightarrow \text{currency\_name}, \text{currency\_symbol}, \text{decimal\_places}$
   - *Transitive Dependencies:* Account configuration and currency metadata depend on their respective foreign master keys.
   - *Resolution:* Decompose into:
     - `ACCOUNT_TYPES(account_type_id, type_name, minimum_balance, interest_rate, default_overdraft_limit)`
     - `CURRENCIES(currency_code, currency_name, currency_symbol, decimal_places, is_active)`
     - `ACCOUNTS(account_id, customer_id, account_type_id, currency_code, account_number, current_balance, ...)`

3. **In the Transaction Relation ($R_3$):**
   - $\text{transaction\_id} \rightarrow \text{merchant\_id} \rightarrow \text{merchant\_name}, \text{merchant\_mcc}, \text{settlement\_account\_id}$
   - *Transitive Dependency:* Merchant metadata is transitively dependent on transaction ID.
   - *Resolution:* Extract `MERCHANTS(merchant_id, settlement_account_id, business_name, registration_number, merchant_category_code)`.

---

### 6. Boyce-Codd Normal Form (BCNF)

#### Definition:
A relation $R$ is in BCNF if and only if for every non-trivial functional dependency $X \rightarrow Y$, **$X$ is a superkey (candidate key)**.

#### Analysis of Candidate Keys in ApexBank:
Let us analyze the `CUSTOMERS` relation:
- Primary Key: `customer_id`
- Alternate Keys: `email`, `phone_number`

Functional Dependencies:
1. $\text{customer\_id} \rightarrow \text{first\_name}, \text{last\_name}, \text{email}, \text{phone\_number}, \text{tier\_level}, \text{status}$
2. $\text{email} \rightarrow \text{customer\_id}, \text{first\_name}, \text{last\_name}, \text{phone\_number}, \text{tier\_level}, \text{status}$
3. $\text{phone\_number} \rightarrow \text{customer\_id}, \text{first\_name}, \text{last\_name}, \text{email}, \text{tier\_level}, \text{status}$

In every dependency $X \rightarrow Y$, the determinant $X$ (`customer_id`, `email`, or `phone_number`) is an authentic candidate key with unique index enforcement. Therefore, `CUSTOMERS` is strictly in **BCNF**.

Similarly, for `TRANSACTIONS`:
- Functional Dependencies:
  - $\text{transaction\_id} \rightarrow \text{transaction\_reference}, \text{idempotency\_key}, \text{amount}, \dots$
  - $\text{transaction\_reference} \rightarrow \text{transaction\_id}, \text{idempotency\_key}, \text{amount}, \dots$
  - $\text{idempotency\_key} \rightarrow \text{transaction\_id}, \text{transaction\_reference}, \text{amount}, \dots$

Each of these left-hand determinants is a designated candidate key. The same argument applies to the other entity tables, whose only determinants are their primary key and declared `UNIQUE` keys (e.g. `CARDS`: `card_id`, `card_token`, `pan_hmac`; `KYC_VERIFICATIONS`: `kyc_id`, `(document_type, id_number)`).

#### 6.1 Residual Dependencies and Controlled Denormalisation
A rigorous BCNF claim must also account for the dependencies the physical design deliberately keeps. The schema contains four, each a conscious trade-off rather than an oversight:

1. **`TRANSACTIONS.currency_code`.** Because an account's currency does not change after opening (a business rule, not a database constraint), $\text{source\_account\_id} \rightarrow \text{currency\_code}$ (and likewise for `destination_account_id`) holds within `TRANSACTIONS`, and `source_account_id` is not a key. Strictly, this is a transitive dependency, so `TRANSACTIONS` is not in 3NF/BCNF on this attribute. It is kept because (a) either account may be NULL (cash deposits and withdrawals, merchant-only payments), so the currency is not always derivable; (b) the currency is part of the immutable payment instruction; and (c) Portfolio 2's reporting queries filter on it directly. The update anomaly is removed by `trg_transaction_currency_guard`, which rejects any row whose currency differs from a linked account.
2. **`ACCOUNTS.current_balance`.** This is a derived attribute: opening balance plus credits minus debits in `LEDGER_ENTRIES`. It is stored because balance checks happen on every authorisation and must not aggregate the full ledger. Postings cannot make it drift because `trg_ledger_apply_balance` applies every ledger line to it; direct `UPDATE`s are not blocked by the database (Portfolio 3 uses them to demonstrate anomalies) and would be revoked from application roles in production. (In the seed data, opening balances are loaded directly as migrated balances rather than posted as opening journals, so the ledger alone does not rebuild the full balance.)
3. **`LEDGER_ENTRIES.balance_after`.** A running-balance snapshot, derivable from earlier postings. It is kept as an audit and reconciliation aid (statements, point-in-time balances) and is checked against the real resulting balance at insert time; the table is append-only, so it cannot become stale.
4. **`TRANSACTIONS.amount` / `fee_amount`.** These duplicate amounts that also appear on the linked journal's ledger lines. They are kept because `TRANSACTIONS` records the customer instruction (which exists before posting and for `FAILED` payments that never post), while the ledger records the accounting effect.

With these four documented exceptions, the remaining relations are in BCNF.

---

### 7. Properties of Decomposed Relations

#### 7.1 Lossless-Join Decomposition (Heath's Theorem)
A decomposition of $R$ into $R_1$ and $R_2$ is lossless with respect to a set of functional dependencies $F$ if:
$$(R_1 \cap R_2) \rightarrow R_1 \quad \text{or} \quad (R_1 \cap R_2) \rightarrow R_2$$

In the decomposition of `ACCOUNTS` and `CUSTOMERS`:
- $R_{\text{ACCOUNTS}} \cap R_{\text{CUSTOMERS}} = \{\text{customer\_id}\}$
- Since $\text{customer\_id}$ is the primary key of `CUSTOMERS`, $\{\text{customer\_id}\} \rightarrow R_{\text{CUSTOMERS}}$.
- Hence, the natural join $R_{\text{ACCOUNTS}} \bowtie R_{\text{CUSTOMERS}}$ reconstructs the original relation with zero spurious tuples.

#### 7.2 Dependency Preservation
Every functional dependency identified in Sections 3 to 6 is preserved in the decomposition: each holds inside a single relation, where its determinant is a primary key or a declared `UNIQUE` constraint, so it can be enforced without inter-table joins. The decomposition is therefore **lossless** and **dependency-preserving** for those FDs.

Business rules that span relations are not functional dependencies of a single relation and are enforced by triggers instead: currency consistency between `TRANSACTIONS` and the linked accounts (`trg_transaction_currency_guard`), balanced single-currency journals (`trg_ledger_balanced`), and posting-maintained balances (`trg_ledger_apply_balance`).

